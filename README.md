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
│   └── 07-strata-halo-evaluation.md     # Strata（125B MoE 专家分层）可行性与对比分析
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

仓库每天 23:30 扫描工作区新增/变更的经验文档与脚本，按模型归入对应目录，提交并推送到 `main` 与相关 `model/*` 分支。
导播台与短剧经验分别归入 `director-console/` 与 `drama/`，并同步到 `drama/director-console` 与 `drama/production` 两条分支。

## 通用前置（必读）

- `VK_ICD_FILENAMES` 必须指向真实存在的 ICD 文件，否则 Vulkan 枚举不到设备 → 静默退化 CPU 推理（速度掉 2 倍+ 且不报错）。
- 任何「莫名慢但没报错」先查 Vulkan 设备枚举（见 `docs/00`）。

## License

**CC0-1.0 公共领域贡献** —— 见 [`LICENSE`](LICENSE) 与 [`LICENSE-CC0.md`](LICENSE-CC0.md)。

全部文档、实测数据、脚本、配置片段**无条件释放到公共领域**：
可自由复制、修改、分发、商用、二次发布，**无需署名、无需许可、无版权限制**。

本仓库不分发任何模型权重；模型本身的许可请查阅各自发布页。
（历史版本曾以 MIT 发布，该文本保留在 [`LICENSE-MIT.txt`](LICENSE-MIT.txt)。）
