# 渐进式披露（Progressive Disclosure）文档喂料方案

> 目标：把大文档问答的输入从数万 token 压到数千 token，绕开本机 ~322 t/s 的
> prefill 墙。实测载体：Qwen3.8-Flash-Next（llama.cpp build-vk4，:8080），
> 代理实现 `tools/docproxy.py`（:18090）。

## 一、实测结论（同一问题：113 KB / 34,911 token 的文档问"第一个标题"）

| 路径 | prompt tokens | 耗时 | 备注 |
|---|---|---|---|
| 全文塞进上下文 | **34,911** | **110.3 s** | prefill 实测 322.3 t/s |
| 目录（元数据+轮廓+2KB 预览） | **3,342** | **10.6 s** | -90.4% token，-90.4% 耗时 |
| 目录 + 检索（深层问题） | 13,979（3 轮累计） | 27.3 s | search→search→peek 自主完成 |

- 简单问题（标题/结构类）：目录里就有答案，**0 次工具调用**。
- 细节问题：模型自己 `search_file` 定位行号 → `peek_file` 精读 23 行，
  单轮增量只有几百 token。
- 收益与文档大小成正比：1 MB 文档全文 ≈ 30 万 token ≈ 15 分钟，目录法不变。

## 二、机制

prefill 是 O(n) 开销：34,911 token ÷ 322 t/s ≈ 108 s，每次请求都要重新付这笔钱
（llama-server 的 prompt cache 只救重复前缀，问题措辞一变就失效）。
渐进式披露把「每请求固定成本」变成「按需检索成本」：

```
旧：question + FULL TEXT(34911 tok) ──────── 110 s
新：question + CATALOG(~3300 tok) ── 10 s
        └─ 需要细节时才 peek_file(id, 138, 160) ── 每段 +几百 tok
```

## 三、`tools/docproxy.py` 设计

OpenAI 兼容反代（:18090 → :8080），任何客户端把 base_url 指过来即可用上工具。

- **注册**：`docproxy.py add <文件>` 抽取全文入索引（`docindex.json`，只存元数据+预览，
  正文每次从源文件读，不占内存不复制）。支持 md/txt/csv/log/pdf/docx/xlsx；
  图片等二进制只登记元数据。
- **目录注入**：system prompt = 每个文件的 id、名称、大小、行数 + 标题树轮廓（≤40 条）
  + 开头预览（文本 2 KB / PDF·DOCX 500 字 / 图片 0）。
- **五个工具**（TOOLS_SPEC，OpenAI function-calling 格式）：
  | 工具 | 作用 | 返回预算 |
  |---|---|---|
  | `list_files()` | 列出已注册文件 | 极小 |
  | `search_file(id, query)` | 关键词定位，命中行 ±2 行 | ≤8 处 |
  | `peek_file(id, start, stop)` | 按行区间读取 | ≤8000 字符 |
  | `extract_file(id)` | 标题树/结构摘要 | ≤1200 字符 |
  | `load_file(id, max_chars)` | 全文兜底 | 默认截 8000 |
- **tool 循环**：代理端最多 8 轮；system prompt 明确"目录够答就别调工具、
  peek 一次 ≤150 行、检索可并行"。

## 四、预加载量怎么选

| 类型 | 进目录的内容 | 依据 |
|---|---|---|
| 纯文本 md/txt | 前 2 KB + 标题树 | 标题树让模型知道"去哪找" |
| PDF | 首页文本 500 字 + 页目录 | pymupdf 逐页 get_text |
| DOCX | 前 500 字（含表格轮廓） | python-docx |
| 图片 | 仅文件名/大小 | 视觉 token 太贵 |

预加载可以设 0（把 `PREVIEW_LIMITS` 清零）——标题树仍在，模型可用
`peek_file(id,1,50)` 自取开头；实测保留 2 KB 预览能让约半数问题免检索一轮。

## 五、使用方式

```bash
PY=$HOME/.workbuddy/binaries/python/envs/default/bin/python
$PY tools/docproxy.py add 文件1.md 大文件.pdf ...   # 注册
$PY tools/docproxy.py ls                            # 查看
$PY tools/docproxy.py serve --port 18090            # 起代理（默认 upstream :8080）
$PY tools/docproxy.py ask "问题"                    # 快速自测（带工具统计）
```

接入方式（任何 OpenAI 兼容客户端）：
- base_url 改 `http://127.0.0.1:18090/v1`；
- 或 MCP/agent 工具面直接复用 `tool_call(name, args)`（docproxy.py 可直接 import）。

## 六、边界与注意

- 检索是**关键词级**，同义改写会漏；可升级为 BM25/向量检索（本机可加 ollama bge-m3）。
- 跨文档综合类问题（"对比这两个文件"）仍需要多次 peek，token 优势随问题复杂度衰减；
  极端全量比对场景（如 diff）不适用，直接 load_file 或本地工具做。
- 目录本身有固定 ~3.3K token（两个文件时）。文件注册多了要按相关性过滤注入。
- tool-calling 依赖模型的指令跟随能力；Qwen3.8 实测稳定，其他模型接入需先跑 `ask` 自测。
- 端口坑：本机 8081/8089 已被其他服务占用（8089 返回 host_validation_failed），
  代理默认用 **18090**。

## 七、与既有调优的关系

投机解码（n-max=2，35.59 t/s）优化的是 **decode**；渐进式披露优化的是 **prefill**
（322 t/s × 35K token = 110 s 的固定税）。两者正交，叠加后长文档场景整体提速
一个数量级。prefill 数值提醒：短 prompt 的 60 t/s 是冷启动假象，
长上下文稳态 prefill 约 322 t/s——评估 prefill 必须用 ≥2700 token 的输入。
