# 本地大模型部署实战 · AMD Strix Halo (Ryzen AI MAX+ 395)

单台 mini 主机（AMD Ryzen AI MAX+ 395 / Radeon 8060S，96 GiB 统一显存）上，用 llama.cpp + sd.cpp（Vulkan）跑四类模型的完整部署经验：启动脚本、调优实测、踩坑记录、运维工具。

在此基础上还包含两套**上层应用**的完整经验：自建导播台（出片工作台）与短剧制作方法论。

> 全部内容以 **CC0-1.0** 公共领域贡献发布，无任何使用限制。
> 后端：llama.cpp fork 分支 `vulkan/qwen4exp-rocmfpx`（Vulkan）。上游 master 不识别本项目用到的私有量化类型（ggml type 101/104）。

## 四个模型 / 四条分支

| 模型 | 分支（点击直达） | 类型 | 显存 | decode | 主要用途 |
|---|---|---|---|---|---|
| **Qwen3.6-35B-A3B** | [`model/qwen3.6-35b-a3b`](https://github.com/bear719/local-llm-deploy-strix-halo/tree/model/qwen3.6-35b-a3b) | MoE 35B / 激活 3B | 23.4 GB(Q4_K_P) / 28 GB(Q5_K_P) | **83–92 t/s** | 主力对话、长思考、多模态（mmproj） |
| **Qwen3.8-27B** | [`model/qwen3.8-27b`](https://github.com/bear719/local-llm-deploy-strix-halo/tree/model/qwen3.8-27b) | dense 27B | 4bit 量化 | 22.4 t/s | dense 基座 / 低显存备选 |
| **Qwen3.8-Flash-Next** | [`model/qwen3.8-flash-next`](https://github.com/bear719/local-llm-deploy-strix-halo/tree/model/qwen3.8-flash-next) | dense 27B + PLE n-gram 表 | ~86–90 GB | 32–40 t/s | imatrix-v2 / n-gram 加速 |
| **MiniMax-H3** | [`model/minimax-h3`](https://github.com/bear719/local-llm-deploy-strix-halo/tree/model/minimax-h3) | 视频+立体声联合生成 | 40.85 GB 权重 / 峰值 75 GB | 56 帧 @ 8 步 + LoRA ≈ 356 s | 文生视频（含音轨） |

`main` 分支保留**合并视图**（四个模型目录 + docs + tools），便于整体检索；各 `model/*` 分支只放该模型的完整资料，便于聚焦。

- **Qwen3.8-27B 与 Qwen3.8-Flash-Next 的关系**：同一 27B dense 基座的两个部署变体。前者是基础 ROCmFP4 量化（22.4 t/s），后者叠加 imatrix-v2 + 22.4 GB PLE n-gram 表并启用 `--ngram-on-disk`（32–40 t/s）。当前主力是 Flash-Next。

## 两条创作分支：自建导播台与短剧制作

模型跑通之后，真正难的是一集能看的东西怎么产出。这两条分支记录全部现场经验。

| 分支 | 内容 | 目录 |
|---|---|---|
| **自建导播台** | React 19 + Vite 8 + FastAPI + sd-cli 的单机出片工作台：GPU 独占仲裁器（96 GiB 单池记账）、出片规格与耗时实测、A/B/C 三级优化清单、六起事故复盘、四单元 systemd 部署、SSE 同源代理 | [`director-console/`](director-console/README.md) |
| **短剧制作** | 创作方法论：一集成片的九类缺陷诊断、六条系统性根因与三轮修复、台词时长安全模型、分段重演与 seed=42 陷阱、五个质量专题的社区对比 | [`drama/`](drama/README.md) |

对应远端分支：[`drama/director-console`](https://github.com/bear719/local-llm-deploy-strix-halo/tree/drama/director-console) ·
[`drama/production`](https://github.com/bear719/local-llm-deploy-strix-halo/tree/drama/production)

**这两条分支最核心的三条结论**：

1. 96 GiB 单池下**并发必须 = 1**；显存越线不报 OOM，只报 `vk::Queue::submit: ErrorDeviceLost` + `context is lost. This context is innocent.`（radv 会虚报可用显存，日志报过 `free 145964 MB`）
2. 出片成本是**分钟/秒成片**（12 步档 ≈ 12.3、20 步档 ≈ 20.5），最大的浪费是**段数**而不是分辨率 —— 每段都要重载约 40 GiB 权重
3. 「画质差」里 **70% 其实是镜头语法问题**：镜内跳切、无运镜、无正反打、背景脸崩、道具三样，根因都在分镜与提示词，不在模型

## 目录结构

```
.
├── README.md
├── docs/
│   ├── 00-hardware-and-environment.md   # 硬件 / Vulkan vs HIP / 双池记账 / ICD / 上下文上限
│   ├── 01-common-pitfalls.md            # 反代 SSE、cache-ram、cross-slot、私有量化
│   ├── 02-panel-and-ops.md              # MCSManager 面板化、孤儿进程、日志、分时复用
│   ├── 03-npu-8219.md                   # AMD XDNA2 NPU（FLM）测试与接入
│   ├── 04-openwebui.md                  # Open WebUI 双端点接入
│   ├── 05-model-catalog.md              # 社区量化模型清单与选型
│   ├── 06-video-pipeline.md             # 视频模型方案（sd.cpp / GTT 池隔离）
│   ├── 07-strata-halo-evaluation.md     # Strata（125B MoE 专家分层）可行性与对比分析
│   ├── 08-gufo-halo-evaluation.md       # Gufo（gfx1151 原生 HIP 引擎）可行性与 BIOS 零和代价
│   ├── 09-strata-community-benchmark-forecast.md # 社区倍数折算 + 四场景收益矩阵 + 场景 D 调优清单
│   ├── 10-local-llm-daily-baseline.md   # 运行基线快照、参数漂移核查、优化候选、社区数字采纳原则
│   ├── 2026-11-23-NPU充分利用方案.md     # NPU 非推理用途盘点 + P0/P1/P2 优先级
│   ├── 2026-11-23-NPU非推理用途.md       # 翻译/embed/ASR 旁路落地与判断力边界
│   ├── 2026-11-23-文档库审计报告.md      # 索引重复块审计与去备份定
│   ├── 2026-11-23-P0P1P2执行记录.md      # 向量检索底座与可观测性落地
│   ├── 2026-11-23-Inkling-2-Mini-对比与可替换性判定.md # 新 looped 模型 vs 本机 35B 的可替换性
│   ├── 2026-11-23-C类工程侧执行记录.md   # 全量 RAG 混合重排、工具接入、结构化输出
│   └── 2026-11-*.md                     # 每日增量专题与运行快照（最新 2026-11-23-daily-report.md），见「近期同步」
├── models/
│   ├── qwen3.6-35b-a3b-moe/             # start.sh + benchmarks + legacy-params
│   ├── qwen3.8-27b/                     # 基座说明 + 调优结论
│   ├── qwen3.8-flash-next-imatrix-v2/   # start.sh + ngram-on-disk + benchmarks
│   └── minimax-h3/                      # start.sh + 组件与实测
├── director-console/                    # ★ 自建导播台（工程侧）
│   ├── README.md                        # 总览 + 一页结论
│   ├── 01-architecture-and-services.md  # 八个组件、数据流、四单元 systemd、SSE 同源代理
│   ├── 02-gpu-arbiter.md                # 96 GiB 单池记账、崩溃边界、仲裁器五条策略
│   ├── 03-render-profile-and-cadence.md # 出片规格、耗时实测、三角约束、A/B/C 优化
│   └── 04-incidents-and-pitfalls.md     # 六起事故复盘 + 踩坑速查表
├── drama/                               # ★ 短剧制作（创作侧）
│   ├── README.md                        # 十条最贵经验 + 铁律
│   ├── 01-ep001-diagnosis.md            # 九类缺陷与七条硬事实
│   ├── 02-ep002-root-causes.md          # 六条系统性根因与三轮修复
│   ├── 03-dialogue-timing-model.md      # 台词时长安全模型
│   ├── 04-segment-repetition-and-seed.md# 分段重演、MAD 判重、seed=42
│   ├── 05-quality-topics-vs-community.md# 五个质量专题的社区对比
│   ├── 2026-11-15-ep006-acceptance.md   # 开片验收单实测：长镜原生音频丢字率、路线与音色锚互斥
│   ├── 2026-11-22-ep007-acceptance.md   # 同日三次重跑的评分口径、关键帧残留盲区、经验→检查项
│   └── 2026-11-22-pipeline-optimize-report.md # 出片流程自检：采集字段、本地模型诊断的边界
├── tools/
│   ├── docproxy/                        # 渐进式披露推理代理
│   ├── ui-zh/                           # ★ llama.cpp WebUI 汉化流水线（整串替换 + UTF-16 切片）
│   ├── openwebui/  sdcpp-video/         # 前端与视频生成启动脚本
│   ├── gguf_probe.py                    # 判定 PLE 布局后再定参数
│   ├── bench-*.py  spec-grid*.sh        # 测速与投机解码网格
│   ├── bench-ab.py                      # 交错 A/B 压测（uuid 避缓存 + 中位数）
│   ├── test-npu.py  test-sampling.py    # NPU 与采样验证
│   ├── analyze_prompt_dump.py           # 请求快照分析：稳定公共前缀 token 数与预加载判定
│   ├── kv_cache_probe.py                # 逐槽 KV / cache-ram 占用探针
│   ├── npu-*.py  npu-reindex.sh         # NPU 侧车/索引/去重/审计/健康/门控/混合检索工具集
│   ├── medcalc.py                       # ★ 临床评分规则引擎（21 项，参数带单位 + 文献标注）
│   ├── mcp-local.py  structured.py      # 本地 MCP 5 工具 + 结构化输出封装
│   ├── who-connects.py                  # 只读连接监控（frp 穿透来源判定）
│   ├── frps-audit.sh  frps-audit-revert.sh # frps 侧真实 IP 审计与回滚
│   ├── ask-local.sh                     # 一条命令查本地文档库
│   └── compare-quant-speed-v3.sh        # 量化档位对比
└── scripts/
    └── switch-model.sh                  # 两档一键切换
```

## 快速开始

1. 编译 fork 分支 `vulkan/qwen4exp-rocmfpx`（上游 master 不识别私有量化 type 101/104）。
2. 下载对应 GGUF（见各模型 README 的「模型侧关键点」）。
3. 编辑 `start.sh` 顶部 `BIN_DIR` / `MODEL` 等路径为本机值。
4. `./start.sh long`，用 `./start.sh status` 看健康。

## 每日自动同步

仓库每天 01:00 扫描工作区新增/变更的经验文档与脚本，按模型归入对应目录，提交并推送到 `main` 与相关 `model/*` 分支。
导播台与短剧经验分别归入 `director-console/` 与 `drama/`，并同步到 `drama/director-console` 与 `drama/production` 两条分支。

## 近期同步（2026-11-07 ~ 11-09）：NPU 重定位、KV cache 落显存、ASR 纠错

这一批是三个方向的连贯实验，结论已互相咬合，建议按顺序读。

### 一、NPU 从「什么都能跑」收缩到「只接批量无生成任务」

| 文档 | 一句话结论 |
|---|---|
| `docs/2026-11-08-npu-gpu-coexistence.md` | NPU 与 GPU **可共存**，但 NPU 严格串行且吃 host RAM（memlock 2.9 GB）；低频占空比仅 −1.5% decode |
| `docs/2026-11-08-npu-task-allocation.md` | 现状下的任务分配表：embedding ✅ / ASR ⚠️ / chat 仅兜底 |
| `docs/2026-11-08-npu-bypass-model-selection.md` | 旁路模型选型：1.2B 级够用，4B 换不来判断力 |
| `docs/2026-11-08-npu-repositioning.md` | **judge 不迁 NPU**（1.2B 判定 11/20 vs 35B 20/20 @0.63 s）——格式可强制，判断力不可强制 |
| `docs/2026-11-08-four-apps-npu-judge.md` | 四应用接入实测 + judge 必须经 18090（直连 8080 时 12.5 s/合法率 2/3） |
| `docs/2026-11-08-flm-upgrade-and-flash.md` | FLM v1.0.x 各版本行为差异与「Flash」模型判定口径 |
| `docs/2026-11-08-flm-v1012-lfm25-bypass.md` | v1.0.12 落地：三模型常驻（chat/embed/asr）的启动姿势与面板托管约束 |
| `docs/2026-11-08-asr-accuracy.md` | ASR 中文纠错：拼音层确定性纠错把 CER 从 **23.06% → 4.11%** |

### 二、KV / prompt cache 落到 GPU carve-out（35B 运行时）

| 文档 | 一句话结论 |
|---|---|
| `models/qwen3.6-35b-a3b-moe/2026-11-09-kv-slot-snapshot-feasibility.md` | KV 槽快照的收益测算与三个本机特有否决点 |
| `models/qwen3.6-35b-a3b-moe/2026-11-09-kv-slot-snapshot-rejected.md` | `--slot-save-path` 路径**否决**：快照不含 checkpoints，restore 后 `cache_n=0` |
| `models/qwen3.6-35b-a3b-moe/2026-11-09-prompt-cache-to-vram.md` | 改造落点后：27.5K 三应用轮转 VmRSS 8.40→0.42 GB、命中 29.4 s→0.68 s；**全局改 DEVICE_LOCAL 会让 decode 掉 46%** |
| `models/qwen3.6-35b-a3b-moe/2026-11-09-cache-ram-100k.md` | `--cache-ram` 语义反直觉：`-1` 比正数 MiB **更严格**；100K 上下文冷 prefill 216 s（463 t/s），切走再回 14.3 s |

### 三、引擎与项目评估

| 文档 | 一句话结论 |
|---|---|
| `docs/2026-11-07-halogen-vs-gufo.md` | Halogen 与 Gufo 在本机的适配性判定（同属 HIP host-mapped 类，装不下） |
| `docs/2026-11-08-gufo-host-27b-35b-forecast.md` | Gufo 加载 27B/35B 的可行性分档与收益预测 |
| `docs/2026-11-08-colibri-analysis.md` | colibri 引擎对照评估（Vulkan 构建 vs llama.cpp） |
| `docs/2026-11-09-llama-modchip-radar.md` | `llama-modchip` 项目雷达：12 项技术逐条判定 + 明确不要抄的部分 |
| `docs/2026-11-08-daily-report.md` / `docs/2026-11-09-daily-report.md` | 当日运行快照（端口、显存、命中率、异常） |

### 新增工具

| 工具 | 用途 |
|---|---|
| `tools/pyfix.py` | 中文 ASR 拼音层确定性纠错（模糊音归一化 + 医学词表） |
| `tools/asr-bench.py` | ASR 纠错前后 CER 对照测速 |
| `tools/preload_system_prompt.py` | 预置 system prompt 以命中 slot 前缀复用 |
| `tools/bench-npu-models.py` / `bench-judge-*.py` | NPU 旁路模型与 judge schema 压测 |
| `tools/apply-npu-route.py` / `verify-npu-route.py` | 应用侧 NPU 路由写入与验证 |
| `tools/start-flm-npu.sh` | FLM NPU 三模型常驻启动脚本（须面板托管） |
| `tools/docproxy/` | 渐进式披露代理（更新版：chunked 上传解码 + SSE 心跳修复） |

## 近期同步（2026-11-10 ~ 11-11）：prompt 前缀复用定案、Gufo NPU 卖点证伪、Flash-Next 案例对账

这一批是同一台机器上「长会话首请求到底慢在哪」的收尾实验，加上两份外部案例的逐条对账。

### 一、prompt 前缀复用的最终判定（35B 运行时）

| 文档 | 一句话结论 |
|---|---|
| `models/qwen3.6-35b-a3b-moe/2026-11-11-preload-v2-verdict.md` | 预加载 cron 是**负优化**并已停用：docproxy 是 passthrough，预热内容与真实请求 LCP=0，收益 0，代价是每分钟把用户槽踢一次 |
| `models/qwen3.6-35b-a3b-moe/2026-11-11-prompt-version-drift.md` | tools 顺序与 `sort_keys` **对 token 无影响**（归一化在 `common/chat.cpp`）；真正的断点是 tools 集合/内容漂移 → 结论改为**多版本共存 + 一次 `--warm-all`** |

三条可直接复用的数字（同机实测）：40K 稳定前缀冷 prefill **52.7 s**、槽内命中 **0.81 s**、cache-ram 恢复 **9.93 s**；覆盖一个 100K 活跃槽要 `prompt_save` **80.4 s**。

### 二、外部案例对账（不采信二手转述）

| 文档 | 一句话结论 |
|---|---|
| `docs/2026-11-11-gufo-npu-prefill-verdict.md` | 「GPU+NPU 分摊 prefill」在 `gufo serve llm` 里**结构上不可达**（offload 要求 `n_tokens % 4096 == 0`，server 分块永不满足），只有 `gufo bench` 能触发 |
| `models/qwen3.8-flash-next-imatrix-v2/2026-11-11-douyin-case-verdict.md` | 视频里 40 t/s 的差距主因是 **PLE n-gram 表放 GTT 内存**而不是 `--ngram-on-disk` 逐 token 随机 pread（≈20–30× 放大） |

### 三、当日运行快照

`docs/2026-11-10-daily-report.md`、`docs/2026-11-11-daily-report.md` —— 端口/显存/命中率/异常项，以及当天的参数漂移核查结果。

### 四、新增与更新工具

| 工具 | 用途 |
|---|---|
| `tools/analyze_prompt_dump.py` | 读 docproxy 的 `DUMP_PROMPT` 快照，输出稳定公共前缀 token 数与「该不该预加载」的判定 |
| `tools/kv_cache_probe.py` | 逐槽探 KV / cache-ram 占用与 `cache_n`，用于验收复用是否真的生效 |
| `tools/preload_system_prompt.py`（v2） | 快照重放 + 严格槽守卫（槽忙或有真实会话一律跳过），**不挂 cron** |
| `tools/docproxy/docproxy.py` | `DUMP_PROMPT=1` 请求取证；转义与错误路径修正 |

## 近期同步（2026-11-12 ~ 11-13）：NPU 翻译模型定稿、WebUI 汉化流水线入库

### 一、NPU 翻译任务改用专用 MT 小模型

`hy-mt2-flash:1.8b` 在 5 例专业术语语料上 **5/5 合格、合计 3.74 s**；通用对话模型 `lfm2.5-it:1.2b` 只有 1/5（4 例术语意译成错），GPU 35B 质量同级但要 9.48 s。结论：翻译这类「术语映射」任务，**专用小模型 > 通用小模型 > 大模型**，且完全不占 VRAM。详见 `docs/03-npu-8219.md` 第八节，实现见 `tools/docproxy/start.sh`。

### 二、llama.cpp WebUI 汉化流水线

`tools/ui-zh/` 是 8080 内置 WebUI（SvelteKit 打包产物，无 i18n）的汉化工具链。核心不是「全文替换」，而是三条硬约束：

| 约束 | 原因 |
|---|---|
| **只做整串替换 + 文本段替换，绝不子串替换** | 子串替换会把 `"Set the API Key if ..."` 换成中英混排，也会改坏 `GET/POST/Bearer/Enter/Tab` 这类兼作协议名/按键名的串 |
| **切片必须按 `utf-16-le` 字节偏移** | acorn 的偏移是 UTF-16 码元，Python 字符下标与之不等价（bundle 含 emoji 代理对），按下标切会把 `console.error("No wrapper found")` 切成语法错误 |
| **验证前清 Service Worker** | 否则浏览器一直吃旧缓存，看着像替换没生效 |

`apply4.py` 是主构建脚本，`dict.json`（整串词表）+ `segments.json`（段级词表）为其输入。产物挂载用 `llama-server --path <目录>`，回滚 `UI_PATH=` 重启。

### 三、当日运行快照

`docs/2026-11-12-daily-report.md`、`docs/2026-11-13-daily-report.md` —— 端口/显存/MTP 接受率/参数漂移核查，以及 minimax-h3 专项逐条结论。

## 近期同步（2026-11-14 ~ 11-16）：两条结论被实测推翻

本轮的价值不在新增功能，而在**把旧文档里两个"看起来对"的结论当场作废**。

### 一、`--moe-cache-mib` 不是万能提速开关（A1 候选作废）

缓存只服务于**留在主机内存**的专家权重，必须配合 `-cmoe` / `-ncmoe` / `-ot` 让部分专家层不上显存，
且只对 **≤32 token batch（decode）**生效。本机 `-ngl 999` 全 offload → 没有任何层的专家留在主机内存 →
llama.cpp **警告并自动禁用缓存**，加了 flag 也零效果。

作者在 RTX 5090 报 2.2×（命中率 89%），双卡测试者反而变慢 —— **跨硬件不可外推**。
要验证收益必须先搭 A/B：A 组全 offload 基线 / B 组用 `-ncmoe` 留层后再开缓存。

### 二、并发渲染会让 decode 掉 76%，测速必须先查进程

| 指标 | 空闲态 | 渲染并发窗口内 |
|---|---|---|
| decode | 72.41 t/s | **17.28 t/s（-76%）** |
| prefill | ~400 t/s | 621 t/s（数值反而更高，同样作废） |

`gpu_arbiter` 对 image 档（800×448 / 20 步）判定在预算内、**不会暂停 llama**，
端口层面无冲突但负载层面硬争抢。铁律：**测速前 `pgrep -c sd-cli`，非 0 则数字全部作废**；
prefill 在争用下会"显得更快"，单次测量不足信。

### 三、离线排障要分清三种"不通"

| 现象 | 判定 | 处置 |
|---|---|---|
| 8080 不通 + 有渲染进程 + 显存占用高 | 仲裁器**按设计**暂停 | 等 `auto_resume`，别重启 |
| 8080 不通 + 无渲染进程 + **显存 0%** | **实例没被拉起**（非崩溃） | 经面板 API 拉起，别翻崩溃栈 |
| 8080 通、18090 报 unreachable | 两者是独立进程 | 先修 8080 |

另：`/props` 的 `params.speculative.types="none"` 是 fork 已知不可信字段，
MTP 是否生效只认 `ps` + `/metrics`；且**累计接受率跨重启不可比**（重启即归零）。

### 四、短剧侧：长镜原生音频的丢字规律

跨集实测：**≤9.9 s 命中 100%，>10 s 命中 61–92%**，失败形态是**模型摘写前段**而非截断。
加提示词无效、压台词字数也无效（压字数会把富余撑过 1.5 s，转而触发自由续写，更糟）。
要保节奏四档的长镜就得接受 8–39% 丢字，否则只能在剧本层拆成两个机位。

详见 `docs/2026-11-14-daily-report.md`、`docs/2026-11-15-daily-report.md`、`docs/2026-11-16-daily-report.md`、
`drama/2026-11-15-ep006-acceptance.md`。

## 近期同步（2026-11-17 ~ 11-18）：decode 基线恢复 82.5 t/s、huge pages 候选、MTP 判据

两篇快照：`docs/2026-11-17-daily-report.md`、`docs/2026-11-18-daily-report.md`。

### 一、怎么证明 MTP 真的在跑（`/props` 在说谎）

`/props` 的 `params.speculative.types` 返回 `"none"` 时，MTP 可能正在满速工作 —— 这是 fork 的已知不可信字段。
**只查它必然得出错误结论。** 可信判据是三条并列：

| 判据 | 期望 |
|---|---|
| `/slots[0].speculative` 与 `params."speculative.types"` | `true` / `none,draft-mtp` |
| `ps` 命令行 | 含 `--spec-type draft-mtp --spec-draft-n-max N -md ...MTP-ONLY...gguf` |
| `/metrics` 的 `spec_decode_num_draft_tokens_total` / `_accepted_tokens_total` | 计数器在增长（非静态回显） |

第三条还能顺带算出接受率。注意**累计值跨重启归零**，别把归零当性能回归。

### 二、基线恢复：82.50 t/s，但 prefill 仍空着

11-15 的 17.28 t/s 是并发渲染污染、11-16 是离线，两天的数据都已作废。
本轮空闲态实测 **82.50 t/s**（Q5_K_P + MTP n=2，接受率 81.11%），这条才是当前可引用基线。

**prefill 不要引用 89 t/s** —— 那是 `prompt_n=5` 的短样本，没有 pp512 意义。标准复核要 `llama-bench -p 512`。

测速纪律：发布任何 decode 数字前先 `pgrep -c sd-cli`，非 0 则整组作废；且 prefill 在争用下会"显得更快"。

### 三、`GLIBC_TUNABLES=glibc.malloc.hugetlb=1`：本机唯一零成本的提速候选

社区实测（H100 +21% RPS / 首 token +22%；L4 +6.5%；8B plain chat 无增益），机制是 malloc 走 hugetlb、把页错误从 ~124,000 降到 ~1,850 次/请求。
本机前置已满足：glibc 2.43 + THP=`madvise`。验证生效：`grep AnonHugePages /proc/$(pidof -s llama-server)/smaps_rollup` 应 > 0。

**必须 A/B**：预热 2 次丢弃 → 加/不加交错各 3 轮 → 读 `timings.predicted_per_second`。分组跑会被温升污染。

### 四、「MoE 投机陷阱」不适用于内嵌 MTP

社区流传的「35B-A3B 加 speculative 反而 -60%」针对的是**独立 1.5B draft 模型**（另一套权重、另一份内存，verify 会触发全部专家加载）。
本机是 **MTP heads 内嵌主模型**，`-md` 只是 heads 头，实测 82.50 t/s。**机制不同，结论不可套用**。
真正的风险在另一侧（#27950）：采样器与 drafter 不对齐时接受率会从 59.6% 掉到 45.7% 且墙钟慢 2.8× —— **接受率高 ≠ 质量无损**，改 `n-max` 必须人工比对输出。

社区 n-max 曲线（M2 Ultra / Metal）：n=2 → 73.04 t/s(86.2%)、n=3 → 76.00(78.3%)、n=4 → 77.68(76.7%)、n=5 → 74.68(68.0%)。拐点在 3~4，且 MTP 会让 prefill 掉约 17%。

### 五、导播台侧：无新增漂移，仍是老账

`config.json` 自 11-12 未变。唯一实质变化是 B1 关注点闭环（8080 恢复在线，应用链路可用）。
未决项照旧：`steps 12` 低于共识、画布 800×448 非竖屏、`comfyui_url` 指向无监听的 8188、`--host 0.0.0.0` 未收窄。

## 近期同步（2026-11-19 ~ 11-23）：MTP 口径修正、长上下文吃掉 MTP 收益、验收单评分纪律

五篇运行快照（`docs/2026-11-19` ~ `2026-11-23-daily-report.md`）+ 两篇短剧文档。

### 一、基线：68–88 t/s 区间，不是某个单值

| 日期 | decode | MTP 接受率 |
|---|---|---|
| 11-18 | 82.50 | 81.11% |
| 11-19 | 81.88 | 81.24% |
| 11-20 | 82.33 | 81.55% |
| 11-22 | 81.69 | 80.91% |
| 11-23 | **87.75** | 80.65%（进程已重启，重累计） |

配置全程未变，单值波动全靠短样本抖动。**区间上修到 68–88 t/s，单次数字一律不定论。**

### 二、两个「看起来是回归，其实是误读」的坑

1. **计数器归零 ≠ 性能回归**：`/metrics` 的 `spec_decode_*_total` 是进程级累计，11-22 16:12 重启后清零。比较接受率前先看 `lstart`。
2. **验收单分数下降 ≠ 质量下降**：EP007 同日三次重跑，评分 68 → 65 → 64，检查项 33/32/31 全绿、⛔ 始终 0。是**检查覆盖面在扩大**，不是作品在退步。**分数只能横向比同一口径，不能纵向跨轮次比。**

### 三、长上下文会吃掉 MTP 收益（新量化）

社区多源实测：27B 上空窗 3.1×，到 256K 只剩 **1.15×**。本机满配 `-c 262144`，**若要判断长会话下 MTP 是否还值钱，必须在 ≥100K 输入上单独 A/B，不能拿短样本结论外推**。

同批旁证：Q8_0 草稿头比 Q4 头稳（+27.9%，接受率 75.59%），本机 35B 的 head 是 Q4_K_M —— 接受率若持续下滑，优先试换 Q8 头。

### 四、方法修正：判断「上游 PR 是否已在本机」

不能用 `git merge-base --is-ancestor <PR号> HEAD` —— PR 号不是 git 对象，报 `Not a valid object name` 且失败分支会被 `if` 静默吞掉。

```bash
git log --oneline --all --grep='<PR号>' -i
```

用对之后重核：某「零温度链改 greedy 选择」的采样 PR 实际**早已在 HEAD 里**。

### 五、`--host 0.0.0.0` 已 46 日未收窄

应用侧全走回环，局域网没有任何消费方。这不是优化项，是暴露面。改一行、面板重启 27 秒生效、零回滚成本。

### 六、短剧侧两篇

- `drama/2026-11-22-ep007-acceptance.md`：37 条经验编译成检查项（26 auto + 11 manual，**manual 不假装自动通过**）；关键帧根目录残留同名旧图属人工核查盲区；4 镜 14 s 长镜丢字风险照旧。
- `drama/2026-11-22-pipeline-optimize-report.md`：把「诊断」做成流水线一环 —— 固定采集字段（git/参数/事件/日志/服务）+ 本地模型只做归纳。实测 4 条建议里**有 1 条必须人工否决**（提并发），因为模型看不到「96 GiB 单池、并发必须 = 1」的现场约束。

## 近期同步（2026-11-23 下午批）：能力提升方案逐项判定 + 文档库混合检索落地

上午批（5 篇运行快照 + 2 篇短剧文档）已记于上一节；本批是同日 **09:57–21:42** 新增的 28 个文件，主线是「推理层已见底，增量转向模型选型与工程侧」。

### 一、B1/B2/B3/V1 四项候选逐项判定：全部否决或已生效

| 项 | 结论 | 证据 |
|---|---|---|
| B1 限 CPU 频率 | **无效**（66.00→66.68 t/s，+1.0% 噪声内） | 交错双向 A/B，解码期 CPU 只做 tokenize/HTTP，无真实功耗竞争 |
| B2 `-fa on` | **已开启**，无需改 | V 量化 + FA 关会在 `llama-context.cpp:480` 抛异常 |
| B3 核 KV q8_0 | **已生效**（KV 2720 MiB 精确吻合） | 10 层 attention 各 10880 B/token + 66.3 MB SSM |
| V1 升级上游 | **否决**（收益 <5%，损失 118 私有提交） | 新版 coopmat2 提交依赖 NVIDIA 扩展，RDNA3.5 零收益 |

同批订正：`76.3 t/s` 是模板化短样本乐观口径，通用长文实测 **66.5 t/s（−13%）**；文档里引用速度必须带口径。

### 二、Inkling 2 Mini（新 looped 模型）可替换性判定：否决替换、可试并行

官方架构 `inkling2_loop`（24 物理层，中间 12 层跑 3 次 → 48 层应用），本机 fork 的 121 个架构里**没有** `LLM_ARCH_INKLING2_LOOP`，需另编上游 ≥ b12641。中文与多轮多约束指令是硬伤（官方自认落后 Qwen3.8-27B），判定为**不能替换 8080 主力**；VRAM 余量够，可作 agentic coding / 图像输入 / 1M 文档的并行副实例。

### 三、文档库从双库手工联合升级为单库混合检索

旧架构两库重复块 **544 个（28.7%）**，漏加 `--extra` 会安静错命中。新架构：`npu-index.py` 全文 md5 去重 → 单库 `idx/all.json`（116 文件 / 1977 块）；`npu-search.py` 向量 + BM25(CJK bigram) 双路召回 → RRF(k=60) → MMR(λ=0.75)，实测 **MRR 0.838 / Hit@5 100%**（单塔 0.504、BM25 0.473）。

### 四、工具接入与结构化输出（C2/C3）

- `medcalc.py`：21 项临床评分规则引擎，参数名带单位后缀避免 mg/dL 与 µmol/L 混用，每项标注原始文献；确定性计算交给规则，不交给 LLM。
- `mcp-local.py` / `structured.py`：stdio MCP 5 工具 + 结构化输出封装；三条铁律（enum 不进 required、同字段不混 number/string、否定表述须显式声明）。

### 五、公网暴露面处置（P1）

8080 加 `--api-key-file`（key 存 600 权限文件，轮换只改文件+重启）；docproxy/anthropic 桥改为代理侧自动补 Bearer，客户端无感；18090 从 frp 撤除；frps 侧部署真实 IP 审计链（`tools/frps-audit.sh`）。日志已见 Nmap/HNAP1 扫描 32 次。

### 六、新增/更新文件清单

- 文档：`docs/` 6 篇（NPU 充分利用 / 非推理用途 / 文档库审计 / P0P1P2 / Inkling 判定 / C 类工程侧）；`models/qwen3.6-35b-a3b-moe/` 3 篇（能力提升清单 / 中层循环移植 / B1B2B3V1 执行）。
- 工具：`tools/` 新增 15 个（NPU 工具集、bench-ab、medcalc、mcp-local、structured、who-connects、frps 审计、ask-local），更新 `models/qwen3.6-35b-a3b-moe/start.sh`（+ 上游鉴权）与 `tools/docproxy/docproxy.py`（+ Bearer 注入）。

## 通用前置（必读）

- `VK_ICD_FILENAMES` 必须指向真实存在的 ICD 文件，否则 Vulkan 枚举不到设备 → 静默退化 CPU 推理（速度掉 2 倍+ 且不报错）。
- 任何「莫名慢但没报错」先查 Vulkan 设备枚举（见 `docs/00`）。

## 换引擎前先算清的一件事：BIOS 内存分法是零和的

本机把 **96 GiB** 划给 BIOS UMA carve-out（iGPU 可见，OS 不可见），OS 只剩 **30.47 GiB**（GTT 池上限 = host MemTotal）。这条分法决定了两类引擎的命运：

| 引擎类型 | 内存后盾 | 本机可用 | 结论 |
|---|---|---|---|
| Vulkan（llama.cpp / sd.cpp） | carve-out 96 GiB | 充足 | 现有生产栈 |
| HIP `hipMalloc` 类（PyTorch / ComfyUI / Strata） | GTT，实际受 host RAM 约束 | 约 8–10 GiB | 必退化到 SSD 分层 |
| HIP host-mapped 类（Gufo / Halogen，mmap + `hsa_amd_register_*`） | OS 可见页 | 30 GiB，连最小 27B Q4 的 39 GiB 都装不下 | 装不上，直接 `bad_alloc` |

**关键教训**：看到「某引擎在 Strix Halo 上很快」先问它的权重落在哪一池。同一块硅、不同的切法，结果互斥。改 BIOS 到小 carve-out 能解锁 HIP 系引擎，代价是现有 Vulkan 栈（35B Q4_K_P / Q5_K_P / MiniMax-H3 / sd.cpp）全部无法加载，且 `amd_iommu=off` 会连带禁用 NPU。详见 `docs/08`、`docs/09`。

## License

**CC0-1.0 公共领域贡献** —— 见 [`LICENSE`](LICENSE) 与 [`LICENSE-CC0.md`](LICENSE-CC0.md)。

全部文档、实测数据、脚本、配置片段**无条件释放到公共领域**：
可自由复制、修改、分发、商用、二次发布，**无需署名、无需许可、无版权限制**。

本仓库不分发任何模型权重；模型本身的许可请查阅各自发布页。
（历史版本曾以 MIT 发布，该文本保留在 [`LICENSE-MIT.txt`](LICENSE-MIT.txt)。）
