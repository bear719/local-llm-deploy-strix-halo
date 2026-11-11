# Qwen3.8-27B（dense 基座）

27B dense 基座，ROCmFP4 量化；decode 22.4 t/s，是本机 dense 路线的性能下限参照。
当前 8080 主力已由 `Qwen3.8-Flash-Next-imatrix-v2` 接替，本档保留作**低显存备选**与对照基线。

## 模型侧关键点

| 项 | 值 |
|---|---|
| 权重 | `Qwen3.8-27B-ROCmFP4-FAST.gguf` |
| 量化 | ROCmFP4（fork 私有 ggml type 101）→ **只能由 `vulkan/qwen4exp-rocmfpx` 分支二进制加载** |
| mmproj | `mmproj-F32.gguf` 或 `mmproj-Qwen3.8-27B-BF16.gguf` |
| 草稿模型 | 配套 MTP 草稿（`nextn_predict_layers=1`） |

> **mmproj 必须与主模型 embedding 维度匹配**；用 35B 的 mmproj 会直接
> `mismatch between text model and mmproj` 启动失败。

## 实测

| 指标 | 值 | 口径 |
|---|---|---|
| decode | **22.4 t/s** | 2026-09-14，3 次 × 400 token，MTP 开启 |
| 物理上限 | ~23 t/s | dense 27B 需读全部权重，受统一内存带宽墙限制 |

对比：35B-A3B（MoE，每 token 只读 1.6 GB 激活权重）57–92 t/s，两者差约 2.6–4 倍。
**decode 由激活参数量决定，与总参数量无关** —— 这是选 MoE 而非 dense 的核心依据。

## 与 Flash-Next 的关系

同一 27B dense 基座的两个部署变体：

| | 本档（27B 基座） | Flash-Next-imatrix-v2 |
|---|---|---|
| 量化 | ROCmFP4-FAST | imatrix-v2 + PLE n-gram 表（+22.4 GB） |
| 显存 | 约 14 GB 级 | 86–90 GB |
| decode | 22.4 t/s | 32–40 t/s |
| 额外依赖 | 无 | 必须 `--ngram-on-disk` |

## 启动参数（模板，**未在本机单独验证**）

> 当前磁盘无该 gguf，以下按 imatrix-v2 脚本裁剪，仅作参考；实际以 `start-qwen38-imatrix-v2.sh` 为准。

```bash
$HOME/llama-qwen4exp-rocmfpx/build-vk4/bin/llama-server \
  -m "$HOME/models/Qwen3.8-27B-ROCmFP4-FAST.gguf" \
  -md "$HOME/models/Qwen3.8-Flash-Next-MTP-ROCmFP4-FAST.gguf" \
  --spec-type draft-mtp -ngl 999 \
  -c 131072 -np 1 -b 4096 -ub 1024 \
  -ctk q8_0 -ctv q8_0 --spec-draft-n-max 2 \
  --reasoning off --metrics --host 0.0.0.0 --port 8080
```

调优结论（n-max 越小越快、`-ctk/-ctv q8_0` 省显存不降速、`--reasoning off` +16%）来自
Flash-Next 实测，**27B 基座未做独立网格**，套用前请自行 A/B。

来源：2026-09-14 本机实测记录；mmproj 匹配规则见 `docs/00`。
