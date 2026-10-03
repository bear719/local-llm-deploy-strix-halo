# Qwen3.8-Flash-Next-ROCmFP4-FAST-imatrix-v2 (dense 27B 档)

本机**能力档**：dense 27B，imatrix-v2 带 PLE n-gram 表；受带宽墙限制 decode 32–40 t/s。

## 模型侧关键点（勿删）

1. **`--ngram-on-disk` 是必选项不是可选项**：imatrix-v2 用 joined 布局，
   PLE n-gram 表 22.4 GB（`per_layer_token_embd.weight`，Q3_0_ROCMFPX type 104，320001536 行 × 70 B）。
   不开 → 表常驻 host 内存 → 本机 30 GB host 直接进 swap（fork 文档实测 21.1 GiB swapped、156 major faults/s），整机卡顿
2. 只有 fork 分支 `vulkan/qwen4exp-rocmfpx` 编出的二进制能跑：表量化类型是 fork 私有 ggml type 104，
   上游二进制不识别（启动即 `invalid ggml type`）
3. `-np > 1` 时 draft-mtp 存在 cross-slot 串扰风险（上游 PR #28123 作者声明），
   故 long 档强制 `-np 1`；multi 档如需严格正确请改回 `-np 1`

## 用法

```
./start.sh            # 自动：有终端→后台，无终端(面板/守护)→前台
./start.sh long       # 262K 单槽（默认档，速度优先）
./start.sh multi      # 64K × 4 槽，并发优先
./start.sh fg|bg|stop|status|check
```

- long 档：`-c 131072 -np 2`（本 build 上限 131072，`-c 262144` 被 clamp）
- 已固化 `--reasoning off`（A/B 实测 +16.3% decode：34.94 → 40.65 t/s）

## 实测

| 指标 | 值 |
|---|---|
| decode | 32–40 t/s（n-max=2 固化 **35.59 t/s**，较无调优 +11.4%） |
| 显存 | 86–90 GiB |
| MTP 接受率 | ~43%（n-gram 也在贡献 draft token） |
| 加载 | ~55s（93 GB） |

## 调优固化

```
--spec-type draft-mtp,ngram-map-k -ctk q8_0 -ctv q8_0 \
--spec-draft-n-max 2 --cache-reuse 256 --cache-idle-slots \
--ngram-on-disk --ngram-cache 512 --ngram-io-threads 64
```

- `--ngram-cache 512`：行缓存 512 MiB ≈ 7.3M 行（占表 2.3%），成本极低
- `--ngram-io-threads 64`：O_DIRECT 随机读靠队列深度换吞吐（本机 NVMe qd16/64/128 = 62k/130k/160k IOPS），**不要调小**
- **`--spec-draft-n-max` 网格结论（三轮共 15 组）**：1→34.22 / 2→34.75（最优）/ 3→33.08 / 8→11.51 / 16→8.64 t/s；
  ≥8 直接崩塌 65~74%。机制见 `ngram-on-disk.md` 第六节
- `--spec-draft-p-min` 在噪声内，保持默认不设；`--spec-draft-adaptive` 只是大 n-max 的补救，不是加速手段

详见同目录 `ngram-on-disk.md`（方案 + 三重生效验证 + 网格实验）、`benchmarks.md`（上线验证性能数据）。
