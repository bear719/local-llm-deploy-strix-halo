# Qwen3.8-Flash-Next-ROCmFP4-FAST-imatrix-v2 (dense 27B 生产档)

27B dense 基座 + imatrix-v2 + PLE n-gram 表；decode 32–40 t/s。当前 8080 主力档之一。

## 模型侧关键点

1. **`--ngram-on-disk` 是必选项**：joined 布局，PLE 表 22.4 GB
   （`per_layer_token_embd.weight`，Q3_0_ROCMFPX type 104，320001536 行 × 70 B）。
   不开 → 表常驻 host 内存 → 本机 30 GB host 直接进 swap（fork 文档实测 21.1 GiB swapped、156 major faults/s）。
2. 只有 fork 分支 `vulkan/qwen4exp-rocmfpx` 二进制能跑（私有 type 104）。
3. `-np > 1` 时 draft-mtp 有 cross-slot 串扰风险（PR #28123），long 档强制 `-np 1`。

## 参数档

| 档 | 参数 | 说明 |
|---|---|---|
| `long`（默认） | `-c 131072 -np 2 -b 4096 -ub 1024` | 90.6 GB，35–39 t/s |
| `multi` | `-c 65536 -np 4 -b 2048 -ub 512` | 79.2 GB，26–33 t/s |

## 调优固化（含 2026-10-08 host RAM 治理）

```
--spec-type draft-mtp,ngram-map-k -ctk q8_0 -ctv q8_0 --spec-draft-n-max 2
--cache-reuse 256 --cache-idle-slots --cache-ram 1024
--ngram-on-disk --ngram-cache 512 --ngram-io-threads 64
--reasoning off
```

- **`--cache-ram 1024`**：prompt cache host RAM 上限，默认 8192 MiB；本档同源机制、同样吃默认值。
  降到 1024 MiB 省约 7 GiB host RAM，槽内 LCP 复用不受影响。
  完全禁用走 `--cache-ram 0`，但 `--cache-idle-slots` 要求 cache-ram > 0，须一并去掉。
- `--reasoning off`：+16.3% decode（34.94 → 40.65 t/s，A/B 实测）。
- n-max 网格：1→34.22 / 2→34.75（最优）/ 3→33.08 / 8→11.51 / 16→8.64 t/s；
  ≥8 崩塌 65–74%（串行 draft 循环 + 接受率暴跌）。`p-min` 在噪声内，不设。

## 实测

| 指标 | 值 |
|---|---|
| decode | 32–40 t/s（n-max=2 固化 35.59，较无调优 +11.4%） |
| 显存 | 86–90 GiB |
| MTP 接受率 | ~43%（n-gram 也在贡献 draft） |
| 加载 | ~55 s（93 GB） |

详见 `ngram-on-disk.md`、`benchmarks.md`。
