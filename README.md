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
│   └── 2026-11-*.md                     # 每日增量专题（NPU 重定位 / FLM / ASR / 引擎评估），见「近期同步」
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
│   └── 05-quality-topics-vs-community.md# 五个质量专题的社区对比
├── tools/
│   ├── docproxy/                        # 渐进式披露推理代理
│   ├── openwebui/  sdcpp-video/         # 前端与视频生成启动脚本
│   ├── gguf_probe.py                    # 判定 PLE 布局后再定参数
│   ├── bench-*.py  spec-grid*.sh        # 测速与投机解码网格
│   ├── test-npu.py  test-sampling.py    # NPU 与采样验证
│   ├── analyze_prompt_dump.py           # 请求快照分析：稳定公共前缀 token 数与预加载判定
│   ├── kv_cache_probe.py                # 逐槽 KV / cache-ram 占用探针
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
