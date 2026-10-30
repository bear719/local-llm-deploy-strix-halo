# Qwen3.6-35B-A3B-Uncensored (MoE 主力档)

本机**主力档**：MoE 架构，每 token 只激活 ~3B，decode 83–92 t/s。

## 模型侧关键点

1. **标准 Q4_K_P**（gguf file_type 15），不含 fork 私有 ggml type → 任意 build 可加载；
   本机统一用 build-vk4（Vulkan，比 HIP 快约 51%）。另有 **Q5_K_P 变体**（28.0 GB，2026-10-07 加入），质量更高、显存约 +4 GB。
2. arch=qwen35moe，40 层，embedding 2048，expert 256 取 8；`context_length = 262144`。
3. 草稿模型 41 层、`nextn_predict_layers=1`、embedding 2048 → 维度匹配，MTP 可用。
4. **不要加 `--ngram-on-disk` / `--spec-type ...ngram-map-k`**：本模型无 PLE n-gram 表，那是 Flash-Next 专用。
5. `-np > 1` 时 draft-mtp 有 cross-slot 串扰风险（上游 PR #28123），long/fast 档强制 `-np 1`。
6. **mmproj 必须匹配**：用 `mmproj-Qwen3.6-35B-A3B-Uncensored-f16.gguf`（27B 用 `mmproj-F32.gguf`，用错启动失败）。

## 参数档（2026-10-23 更正）

| 档 | 参数 | 说明 |
|---|---|---|
| `long`（默认） | `-c 262144 -np 1 -b 4096 -ub 1024` | **262K 真实可用** |
| `fast` | long + `--reasoning off` | 日常待办/结构化抽取，直出答案 |
| `multi` | `-c 65536 -np 2 -b 2048 -ub 1024` | 并发优先（有串扰风险） |

**★ 撤销 2026-10-03 的「131072 clamp」误判**：当时 `-c 131072` 是脚本自己设的，
日志 `exceeds ... 131072` 指请求超过该设定值；源码 `llama-context.cpp:131` 为
`n_ctx = params.n_ctx==0 ? n_ctx_train : params.n_ctx`，`:325` 仅在 `n_ctx>n_ctx_train` 时 WARN，**不截断**。
GGUF `qwen35moe.context_length = 262144`。故恢复 `-c 262144`；KV(q8_0) 由 1.33 → 2.66 GiB，96 GiB carve-out 充裕。

## 调优固化（2026-10-08 加入 host RAM 治理）

```
--spec-draft-n-max 2 -ctk q8_0 -ctv q8_0
--context-shift --cache-idle-slots -cms 512 --cache-ram 1024
```

- **`--cache-ram 1024`**：server prompt cache 的 **host RAM 上限，默认 8192 MiB**。
  `--cache-idle-slots` 在新任务到达时把空闲 slot 的 KV 序列化进 host RAM 再清 device KV
  —— 本质「用 host RAM 换显存」。本机 carve-out 余 52 GiB、host RAM 仅 30 GiB，方向相反。
  实测 `RssAnon = 8.37 GiB ≈ 8192 MiB + 基础开销`，日志 61 次
  `making room for prompt cache entry ... (size = 126.169 MiB)`（缓存满循环淘汰）。
  降到 1024 MiB 省约 **7 GiB host RAM**，`-np 1` 下槽内 LCP 前缀复用不受影响。
- `--context-shift`：上下文满 CTX 时丢最旧 token 继续（100% 触发）；
  要 75% 即压缩，把 `-c` 设 196608（=0.75×262144）。
- `--cache-reuse` 在 mmproj 下被自动禁用（已移除）；多轮加速靠 `--cache-idle-slots` + LCP。

## 实测

| 指标 | 值 |
|---|---|
| decode | **83–92 t/s**（中位 90.14） |
| 长 prefill | **~520 t/s**（89K tok / ~171s） |
| 显存 | ~31 GiB（Q4_K_P）/ ~35 GiB（Q5_K_P） |
| MTP（n-max=2） | 接受率 77–80%，每步 1.55–1.99 token |
| 对比 Flash-Next（dense 27B） | 快约 2.2 倍 |

详见同目录 `benchmarks.md`、`legacy-params.md`。
