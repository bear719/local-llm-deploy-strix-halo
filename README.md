# 本地大模型部署实战 · AMD Strix Halo (Ryzen AI MAX+ 395)

在单台 mini 主机（AMD Ryzen AI MAX+ 395 / Radeon 8060S，96 GiB 统一内存）上用 llama.cpp 跑大模型的完整经验沉淀。**按模型分类**：每个模型一个目录，含启动脚本、调优实测、踩坑记录；通用工具与运维经验集中在 `tools/`、`scripts/`、`docs/`。

> 适用后端：llama.cpp fork 分支 `vulkan/qwen4exp-rocmfpx`（Vulkan）。上游 master 不识别本项目用到的私有量化类型，请勿混用。

## 硬件基线

- **CPU/GPU**：AMD Ryzen AI MAX+ 395（Strix Halo），16C/32T，Radeon 8060S（集显即 GPU，无独显）
- **物理统一内存** ≈ 128 GiB：host `MemTotal` ~30.5 GiB + BIOS UMA 分配给 iGPU 的 **96 GiB**
- **GTT 上限 104.8 GB**（Vulkan 严格受限，超了报 `ErrorDeviceLost` 而非 OOM）
- **推理后端 Vulkan 优于 HIP ~51%**（同模型 decode 27.5 vs 18.15 t/s、prefill 86–117 vs 62–68 t/s）

## 两个模型怎么选

| 维度 | Qwen3.6-35B-A3B (MoE) | Qwen3.8-Flash-Next-imatrix-v2 (dense 27B) |
|---|---|---|
| 架构 | qwen35moe，40 层，每 token 激活 ~3B | qwen4exp，48 层；fork 私有量化 type 104 |
| 权重 / 显存 | 23.4 GB / ~31 GiB | 93 GB / ~86–90 GiB |
| decode | **83–92 t/s** | 32–40 t/s |
| 长 prefill | ~520 t/s（89K tok） | 38–80 t/s |
| 多模态 | ✅ mmproj（视觉） | ❌ |
| 必选项 | — | `--ngram-on-disk`（PLE 表 20.87 GiB，否则吃光 host 内存进 swap） |
| 适用 | 长思考 / 日常待办 / 批量抽取 / 视觉 | 需要 imatrix-v2 n-gram 表能力的场景 |
| 共存 | ❌ 两档分时复用同一张卡（96 GiB 装不下两个） | ❌ |

> 两档切换见 `scripts/switch-model.sh`；模型专属细节见各子目录 `README.md`。

## 目录结构

```
.
├── README.md
├── docs/
│   ├── 00-hardware-and-environment.md   # 硬件 / Vulkan vs HIP / GTT / ICD / rocm-smi
│   ├── 01-common-pitfalls.md             # 反代 SSE、cache-reuse、cross-slot、私有量化等踩坑
│   └── 02-panel-and-ops.md               # MCSManager 面板化、孤儿进程、日志、分时复用
├── models/
│   ├── qwen3.6-35b-a3b-moe/              # MoE 档：start.sh + benchmarks + legacy-params
│   └── qwen3.8-flash-next-imatrix-v2/    # dense 档：start.sh + ngram-on-disk + benchmarks
├── tools/
│   ├── docproxy/                         # 渐进式披露推理代理（绕开 prefill 墙）
│   ├── gguf_probe.py                     # 判定 PLE 布局（joined/per-head）再决定参数
│   ├── bench-*.py / spec-grid.sh         # 测速与投机解码网格工具
└── scripts/
    └── switch-model.sh                   # 两档一键切换
```

## 快速开始

1. 编译 fork 分支 `vulkan/qwen4exp-rocmfpx`（上游 master 不识别私有量化 type 101/104）。
2. 下载对应 GGUF 到 `~/models/`（见各模型 README 的「模型侧关键点」）。
3. 编辑 `models/<x>/start.sh` 顶部的 `BIN_DIR` / `MODEL` 路径为你本机值。
4. 运行 `./start.sh long`，用 `./start.sh status` 看健康。

## 通用前置（必读）

- `VK_ICD_FILENAMES` 必须指向真实存在的 ICD 文件，否则 Vulkan 枚举不到设备 → 静默退化 CPU 推理（速度掉 2 倍+ 且不报错）。排错口诀见 `docs/00`。
- 任何「莫名慢但没报错」先查 Vulkan 设备枚举。

## License

MIT —— 见 `LICENSE`。
