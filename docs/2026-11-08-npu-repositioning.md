# NPU 重新定位：judge 分流否决 + embedding/ASR 落地

日期：2026-11-08
结论一句话：**judge 这类语义定档任务不该给 NPU（1.2B 是又慢又错，35B 修完思考链后只要 0.63s），NPU 应承接「批量、无生成、可延迟」的 embedding 与 ASR。**

---

## 一、judge 分流：三条路全部实测否决

### 1.1 前提已经消失

2026-11-08 早前修掉了 `jev-local/judge.py` 的两个坑（ENDPOINT 指向 18090 注入关思考、MAX_TOKENS 1024→128），
judge 单次从 **12.5 s 降到 0.63 s**、合法率 2/3→3/3。

**当时想做 NPU 分流的唯一动机是「35B judge 要 12.5 秒」。动机已不存在。**

### 1.2 1.2B 的实测：不是慢，是判错

20 条 A/B 交错（预热 2 条丢弃、顺序奇偶对调、两侧都强制 `response_format=json_schema`）：

| 指标 | 35B @18090 | 1.2B @8219 |
|---|---:|---:|
| 判对率 | **20/20 = 100%** | **11/20 = 55%** |
| 中位延迟 | **0.63 s** | 0.68 s |
| 格式非法 | 0 | 0（约束解码生效） |

混淆矩阵：10 条 reasoning 里 **9 条被判成 cheap**，只有「证明根号 2」判对；它 20 条里 19 条输出 cheap。

复现：`python tools/bench-judge-schema.py --gpu 18090`

### 1.3 约束解码解决了格式，救不了语义

关键发现：**flm v1.0.12 二进制完整编进了 xgrammar**（`GrammarCompiler` / `SchemaSpec` / `JSONFormat` / `StructuralTag` 全在），
`response_format={"type":"json_schema",...}` 真正生效——会 mask 掉非法 token，模型**物理上不可能**再吐「简单问答」。

| 约束 | 输出 | 耗时 |
|---|---|---:|
| 无 | `{"cheap":"日常对话…","reasoning":"复杂推理…"}`（复述定义） | 1.26 s |
| `json_object` | 同上 | 1.26 s |
| **`json_schema` 枚举** | **`{"choice":"cheap"}`** | **0.67 s** |

所以旧结论「choice 非法」只是表象。**格式可以强制，判断力不能强制。**

### 1.4 prompt 调优无效：它没在读内容

5 个变体 × 6 条已知答案样本：

| 变体 | 正确 | 中位延迟 | 偏向 |
|---|---:|---:|---|
| V1 中文长描述（现行） | 3/6 | 0.53 s | 全偏 cheap |
| V2 极简中文 | 4/6 | 0.52 s | 全偏 cheap |
| V3 极简英文 | 2/6 | 0.51 s | 全偏 cheap |
| V4 无 system | 3/6 | 0.46 s | **全偏 reasoning** |
| V5 few-shot | 2/6 | 0.51 s | 全偏 cheap |

二分类随机水平就是 50%，全部落在 2/6~4/6 区间，且**偏向随 prompt 措辞整体翻转**。
说明它响应的是 prompt 里 `cheap`/`reasoning` 两个词的分布，不是在读题目内容。**这是能力问题。**

### 1.5 d3 决策模型：架构层面不匹配

`flm serve --decision d3:edge`，走 `POST /v1/systemone`。7 个档位都可拉：

| 档位 | 名称 | 体积 | 平台 | 要求 |
|---|---|---:|---|---|
| edge | D3-Edge-NPU2 | 595.7 MB | aie2p | 1.0.12 |
| lite | D3-Lite-NPU2 | 762.9 MB | aie2p | 1.0.11 |
| nano | D3-Nano-NPU2 | 1926.4 MB | aie2p | 1.0.11 |
| mini | D3-Mini-NPU2 | 3271.1 MB | aie2p | 1.0.11 |
| flash | D3-Flash-NPU2 | 5858.5 MB | aie2p | 1.0.12 |
| turbo / ultra | — | 15789.2 MB | aie2p | 1.0.11 |

但读出 `decision_config.json` 后真相是：

```
base_model      Qwen/Qwen3.5-0.8B
format_id       d3-code-readout-v1
attention_mode  noncausal_full_attention     ← encoder，不是生成
pooling         last
codes           255 个（A..AZ）
readout.safetensors                          ← 线性分类头
```

**d3 = Qwen3.5-0.8B 编码器 + 255 类「动作码」readout**（System 1 快决策，给 agent 选下一步动作用）。
它的 255 个 code 没有公开语义，**不含「cheap/reasoning 难度」这个维度**。硬套等于自己重新训 readout，成本远超收益。

`flm serve d3:edge` 已下载并留盘（624 MB），未启用。

### 1.6 4B 未测（已下载备用）

`qwen3-it:4b`（3.29 GB，`think=False`，footprint 3.1 GB）已下载。
用户判断「35B 0.63s 已很快，分流没意义」后**未做 20 条验证**。
若将来仍想试：停 8219 → 以 qwen3-it:4b 起临时实例 → 复用 `bench-judge-schema.py --npu-model qwen3-it:4b`。
注意 NPU 全局串行，测完必须恢复 `MODEL_TAG=lfm2.5-it:1.2b`。

---

## 二、NPU 新定位：embedding + ASR

判据：GPU 被 35B 主 slot 占用，价值在长上下文 prefill 与高质量生成；
NPU 应承接**批量、无生成、短时、可延迟**的工作。flm 原生提供两类。

### 2.1 三模型常驻同一实例

`flm serve lfm2.5-it:1.2b --embed embed-gemma:300m --asr whisper-v3:turbo`

```
[FLM] ASR mode enabled: reserving additional 1GB of memory
[FLM] Embedding mode enabled: reserving additional 300MB of memory
[FLM] Loading model: Whisper-V3-Turbo-NPU2
[FLM] Loading model: Embedding-Gemma-300M-NPU2
[FLM] Loading model: LFM2.5-1.2B-NPU2
[Linux] Memlock Limit: raised to 2896 MB
```

合计约 2.9 GB，启动到就绪约 4 s。`--embed/--asr` 与主 chat **常驻共存**，只有 chat↔chat 才换模。

### 2.2 Embedding：可用，质量好

| 项 | 实测 |
|---|---|
| 维度 | 768，**768/768 分量非零**，L2 范数 0.9971 |
| 单条查询 | **0.17 s** |
| 批量吞吐 | **5.3 条/s**（batch=1/16/50 完全一致 → NPU 逐条串行，合并请求无效） |
| 语义检索 | **Top-1 命中 6/6**（病案场景，非字面匹配） |

检索样例（6 条病案段落）：

| 查询 | Top-1 | 是否正确 |
|---|---|---|
| 出血是怎么处理的 | EVL 套扎那条 | 命中 |
| 用了什么口服药 | 普萘洛尔那条 | 命中 |
| 有没有输血 | 血红蛋白 82→95 那条 | 命中 |
| 肝功能分级如何 | Child-Pugh B 那条 | 命中 |
| 体重下降和发热 | 家属诉体重下降那条 | 命中 |
| 有没有发现肿瘤 | 肝右叶结节警惕 HCC 那条 | 命中 |

**768/768 非零这点很重要**——顺带实证了 v1.0.12 修好了 `embed-gemma` 自 v0.9.45 起「坏向量」的历史问题。

### 2.3 ASR：英文优秀，中文医学术语不可用

| 音频 | 耗时 | 结果 |
|---|---:|---|
| JFK 英文 11 s | 3.35 s（3.3× 实时） | **一字不差** |
| 中文电话录音 35 s | 6.54 s（5.4× 实时） | 可读，「牡丹江」→「木丹江」 |
| 中文医学 TTS 2.4 s | 1.24 s | **「胃肠镜」→「未尝静简查」** |

**`language=zh` 与 `prompt` 都无效，且有害**：

| 变体 | 医学 TTS 耗时 | 效果 |
|---|---:|---|
| 自动语种（基线） | 1.25 s | 未尝静简查 |
| `language=zh` | 1.25 s | 完全相同（参数被忽略） |
| `zh` + 医学术语 prompt | **3.45 s** | 仍错，且出现重复幻觉「好的。好的。好的。」 |

**定位必须钉死：可用于会议记录、口语备忘、字幕草稿；不可用于口述病历、医嘱录入。**

### 2.4 NPU 全局串行的代价

二进制里明确写着 `NPU Locked!` / `NPU busy, request queued`。实测并发：

| 场景 | chat | embed |
|---|---:|---:|
| 单独 | 0.47 s | 0.25 s |
| 并发 | **1.12 s** | **0.58 s** |

并发总墙钟 1.12 s ≈ 两者相加。**NPU 是严格串行，不是并行。**

使用纪律：
- 批量建索引挑 GPU 空闲时段（100 条 = 18.8 s，1000 页病案约 4000 块 ≈ 12.5 分钟）
- 不要在 chat 正忙时跑大批量
- 沿用既有结论：NPU 满载会把 GPU decode 拖到 −12.7%，低频 17% 占空比只 −1.5%

---

## 三、上生产变更

| 项 | 变更 | 可逆性 |
|---|---|---|
| `flm-npu.conf`（新建） | `EMBED=embed-gemma:300m` / `ASR=whisper-v3:turbo` | 删行 + 重启实例 |
| `start-flm-npu.sh` | 增加白名单配置文件读取（备份 `.bak.20261108-embed`） | 恢复备份 |
| 面板 8219 | 因 conf 生效，启动参数变为带 `--embed --asr` | 同上 |
| `start-docproxy.sh` | 新增 `NPU_SIDECAR="${NPU_SIDECAR-1}"` 并 export | 设空串 + 重启 |

**为什么用 conf 文件而不是直接改面板**：面板 `startCommand` 属主是 `root:root`（`-rw-r--r--`），lc 改不动。
conf 文件属主 lc，改完只需面板重启实例。优先级严格为「面板显式 env > conf > 脚本默认值」，已三情形实测。

### 3.1 回归矩阵 8/8 通过

| # | 用例 | 结果 |
|---|---|---|
| 1 | 默认 chat 走 8080，回包 model 是 `Q5_K_P` | OK 0.27 s |
| 2 | `/v1/embeddings` 经 18090 自动走 NPU，返回 768 维 | OK 0.17 s |
| 3 | `/v1/audio/transcriptions` 经 18090 自动走 NPU | OK 1.20 s |
| 4 | `X-Backend: npu` 显式分流仍生效 | OK 0.38 s |
| 5 | 未知路径仍 404 | OK |

**客户端调用方式（无需任何特殊头）**：

```bash
# 向量化
curl -s http://127.0.0.1:18090/v1/embeddings \
  -H "Content-Type: application/json" \
  -d '{"model":"embed-gemma:300m","input":["患者呕血黑便，急诊胃镜示食管胃底静脉曲张"]}'

# 语音转写
curl -s http://127.0.0.1:18090/v1/audio/transcriptions \
  -F model=whisper-v3:turbo -F file=@录音.wav
```

### 3.2 回滚阶梯

| 层级 | 操作 | 影响 |
|---|---|---|
| L1 关 sidecar | `NPU_SIDECAR=` 设空 + 重启 18090 | 回「仅按头/别名分流」，embedding 请求改走 8080 |
| L2 关 embed/asr | 注释 `flm-npu.conf` 两行 + 面板重启 8219 | 回单模型，省 1.2 GB |
| L3 停旁路 | 面板停 `flm-npu-8219` | 秒级 |
| L4 清模型 | 删 `D3-Edge-NPU2` / `Qwen3-4B-Instruct-2507-NPU2` / `Embedding-Gemma-300M-NPU2` / `Whisper-V3-Turbo-NPU2` | 释放约 5.2 GB 磁盘 |

---

## 四、未做与已知限制

| 项 | 状态 |
|---|---|
| 4B（`qwen3-it:4b`）判定能力 | 已下载未测；NPU 全局串行，测它要停生产 8219 |
| 病案检索端到端 PoC（分块→索引→检索→喂 35B） | 未做；价值明确但需要真实病案，未动用户数据 |
| ASR 中文医学术语准确率 | 不达标，`prompt` 注入无效；要改善需换 ASR 方案（非 flm） |
| 8219 仍绑 `0.0.0.0` | 局域网可直调且 flm 无认证，未收敛（怕断掉潜在局域网客户端） |
| d3 的 255 个 code 语义 | 未逆向，`/v1/systemone` 未实测调用 |

---

> 许可：CC0-1.0，公共领域贡献，无任何限制。
