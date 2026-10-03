# Qwen3.8-imatrix-v2 + `--ngram-on-disk` 上线验证记录

验证时间：2026-09-27 19:34–19:42 CST
被验实例：PID 209345，17:52:32 启动（root，经 MCSManager 面板）
验证方式：`/health` `/v1/models` `/props` `/slots` `/metrics` + 3 组真实推理 + `ps` + `rocm-smi` + `gguf_probe.py`
被验文档：`Qwen3.8-imatrix-v2-ngram-on-disk-方案.md`

---

## 一、结论

**方案已按文档正确启用，且已实测生效。** 但发现 **1 处与方案文档的实质性冲突**和 **2 处环境偏差**，见第四、五节。

---

## 二、参数核对：与方案完全一致

实际进程命令行（`ps -o args -p 209345`）：

```
$HOME/llama-qwen4exp-rocmfpx/build-vk4/bin/llama-server \
  -m $HOME/models/Qwen3.8-Flash-Next-ROCmFP4-FAST-imatrix-v2.gguf \
  -md $HOME/models/Qwen3.8-Flash-Next-MTP-ROCmFP4-FAST.gguf \
  --spec-type draft-mtp \
  --ngram-on-disk --ngram-cache 512 --ngram-io-threads 64 \
  -ngl 999 -c 262144 -np 1 -b 4096 -ub 1024 \
  --spec-type draft-mtp,ngram-map-k -ctk q8_0 -ctv q8_0 \
  --metrics --host 0.0.0.0 --port 8080
```

| 方案项 | 实际 | 判定 |
|---|---|---|
| 模型文件 | `Qwen3.8-Flash-Next-ROCmFP4-FAST-imatrix-v2.gguf` | ✅ |
| draft 模型 | `Qwen3.8-Flash-Next-MTP-ROCmFP4-FAST.gguf` | ✅ |
| `--ngram-on-disk` | 在命令行中 | ✅ |
| `--ngram-cache 512` / `--ngram-io-threads 64` | 一致 | ✅ |
| `-ngl 999 -c 262144 -np 1 -b 4096 -ub 1024` | 一致 | ✅ |
| 调优档 TUNING（`draft-mtp,ngram-map-k` + `-ctk q8_0 -ctv q8_0`） | 已固化进命令行 | ✅ |
| `--metrics` | 有 | ✅ |
| `rocm-smi --setperflevel high` | `Performance Level: high` | ✅ |

> 注：`--spec-type` 在命令行中出现了两次（`draft-mtp` 与 `draft-mtp,ngram-map-k`）。
> llama.cpp 对重复参数取**最后一个**，实际生效为 `draft-mtp,ngram-map-k`，与方案 E 档意图一致。
> 建议后续清理脚本，只保留一次，避免歧义。

---

## 三、生效性验证：`--ngram-on-disk` 确实工作

| 证据 | 实测值 | 判定 |
|---|---|---|
| **PLE 表布局** | `[joined] per_layer_token_embd.weight dims=(160, 320001536) type=104`，offset=524994560 | ✅ joined，支持 on-disk |
| 表体积（按 3.5 bpw 推算） | 160 × 320,001,536 × 3.5 / 8 = **22,400,107,520 B = 20.87 GiB** | 与方案一致 |
| **进程 RSS** | **7.53 GiB** | ✅ 远小于 20.87 GiB → 表**未**常驻内存 |
| 进程 VSZ | 98.11 GiB | 整个文件被 mmap（含表），但只有访问到的页进 RSS |
| 显存 Used | **86.34 GB / 96 GiB** | 与方案 E 档 86.84 GB 吻合（差 0.5 GB） |
| GTT Used | 3.08 GB / 104.8 GB | 远未触限，无 `ErrorDeviceLost` 风险 |
| draft 模型 | 日志 `common_speculative_init_result: loading draft model ...` | ✅ |
| slot speculative | `/slots` 返回 `"speculative": true` | ✅ |

> 补充：本次**未能**用 `/proc/<pid>/io` 的 `read_bytes` 复核（进程属 root，lc 用户无权限，
> 且 `sudo -n` 需交互密码）。RSS 7.53 GiB 已足以证明表未进内存。

### 关于 `/props` 里 `speculative.types = none`

这是**已知假象**，不是 MTP 未生效。llama.cpp 的 `/props` 返回的是
`default_generation_settings.params`，该字段**恒为 `none`**，不可信。
正确判据是 `/slots[0].speculative`（本次为 `true`）与进程命令行里的 `-md` / `--spec-type`。

---

## 四、⚠️ 与方案文档的实质性冲突：「每步最多 draft 1 个 token」不成立

方案第六之二节称：

> **MTP 草稿模型只有 1 层** → 每个验证步**最多只能 draft 1 个 token**。
> 所以 `--spec-draft-n-max` / `--spec-draft-n-min` 设成什么都一樣，调了没用。

**实测推翻：**

| 来源 | 指标 | 实测值 |
|---|---|---|
| `/metrics` 累计（17:52 起） | `spec_decode_num_draft_tokens_total` / `spec_decode_num_drafts_total` | **每次 draft 平均 3.06 个 token** |
| `/metrics` 按位置分布 | `spec_decode_num_accepted_tokens_per_pos_total{position="0..2"}` | position 0: **840**、1: **546**、2: **337** → **三个位置都有接受** |
| 启动日志 task 0 | `draft acceptance = 0.57143 (60 accepted / 105 generated), mean len = 2.71` | mean len **2.71** |
| 启动日志 task 39 | `draft acceptance = 0.55556 (20 accepted / 36 generated), mean len = 2.67` | mean len **2.67** |

若每步只能 draft 1 个 token，position 1、2 必然恒为 0，mean len 必为 1.00。实测 **2.67~3.06**。

**推论：提高 `--spec-draft-n-max` 是有效调节项，方案「调了没用」的结论需要重新实验。**
当前命令行**未**指定 `--spec-draft-n-max`，用的是默认值（实测等效 3）。

### 建议的下一次实验（需重启服务，需少爷授权）

```bash
# 在现有 TUNING 基础上追加，把 draft 长度从默认 3 提到 8
--spec-draft-n-max 8 --spec-draft-n-min 2

# 对照：n-max 5
--spec-draft-n-max 5
```

判据：每次 draft 平均 token 数是否上升、接受率是否维持在 40% 以上、decode t/s 是否提升。
若 draft 变长但接受率跌破 30%，说明多出的草稿位无效，回退。

> 风险提示：`ngram-map-k` 也在贡献草稿 token，draft 长度 3.06 可能是「MTP 1 + n-gram 2」的合成结果。
> 因此 n-max 是否线性有效需实测，不能直接推断。

---

## 五、环境偏差（不影响方案成立，但需处理）

| 项 | 方案文档 | 实测 | 处理 |
|---|---|---|---|
| **Swap** | 「实测 used 14 GB，无换页压力」 | **已用 7.95 GB / 8 GB（95%）**，`SwapFree` 仅 205,756 kB | **P1**。llama-server RSS 仅 7.53 GB，swap 应是 09-26 磁盘写满崩溃期的历史遗留（当日早报记录 swap 已连续多日上升）。建议排查占用者后再 `swapoff -a && swapon -a`；**内存 available 仅 8 GB，直接 swapoff 有 OOM 风险，不要贸然执行** |
| **主机内存** | used 14 GB | used **21 GB**，available **8 GB** | 同上。主要占用：llama-server 24.7%、WorkBuddy 4.6%、3 个 java（MCSM）约 11% |
| **磁盘** | 93% 剩 38G | **77% 剩 124G**（548G/397G） | 已改善（期间有清理）。仍不建议再下载第二个 93 GB 文件 |
| 启动日志中 `unused tensor per_layer_token_embd.weight` 行 | 方案第三节引用为该判据 | **本实例日志中未出现**（只有 4 条 `blk.48.indexer.*` ignoring） | 该行非必现，不影响判定（RSS 已足够作证据）。方案文档此判据需改为「参考项，非必现」 |

> 另：17:26 有过一次启动失败 `couldn't bind HTTP server socket, port: 8080`（端口被占并退出），
> 17:52 的实例正常。日志 `/tmp/qwen38-imatrix-v2-server.log` 属 17:26 那一轮。

---

## 六、性能实测（本次，temperature 0.7）

### 即时推理（`/v1/chat/completions`，`timings` 字段）

| prompt | prompt tok | gen tok | prefill t/s | **decode t/s** | draft 接受 |
|---|---|---|---|---|---|
| 量化必要性（中文问答） | 64 | 131 | 84.72 | **32.19** | 73 / 174 = 42.0% |
| 写快速排序（代码） | 61 | 200 | 54.04 | **43.95** | 135 / 191 = 70.7% |
| Strix Halo Vulkan vs HIP | 65 | 200 | 58.72 | **33.20** | 114 / 254 = 44.9% |

### 累计（`/metrics`，17:52 起全量）

| 指标 | 值 |
|---|---|
| 累计 decode | **32.81 t/s** |
| 累计 draft 接受率 | **43.5%**（1,723 / 3,962） |
| 每次 draft 平均接受 | 1.332 token |
| prompt tokens | 17,928（其中 15,160 命中缓存，命中率 84.6%） |
| `n_tokens_max` | 14,569 |
| 并发 | `n_busy_slots_per_decode = 1`、`requests_deferred = 0` |

### 启动日志实测

| task | prefill | **decode** | draft 接受率 | mean len |
|---|---|---|---|---|
| 0 | 250.42 t/s（372 tok） | **36.37 t/s** | 57.14% | 2.71 |
| 39 | 76.32 t/s（55 tok） | **34.61 t/s** | 55.56% | 2.67 |

**判定：32~36 t/s，与方案文档「33~35 t/s 是这台机器的正常水位」一致，方案已达标。**

---

## 七、下一步（按优先级）

- **P0 无**：方案本身无问题。
- **P1 — Swap 95%**：排查占用者，安全时机下清理。命令（**执行前确认 available 内存充足**）：
  ```bash
  # 先看谁在用 swap（需 root）
  for p in /proc/[0-9]*; do s=$(grep VmSwap "$p/status" 2>/dev/null | awk '{print $2}'); \
    [ "${s:-0}" -gt 1024 ] && echo "$(basename $p) $((s/1024))MB $(cat $p/comm)"; done | sort -k2 -nr | head
  ```
- **P2 — `--spec-draft-n-max` 实验**：见第四节，需重启服务，需授权。
- **P2 — 脚本清理**：`--spec-type` 重复出现两次，建议只保留 `draft-mtp,ngram-map-k` 一次。
- **P2 — 安全**：`--host 0.0.0.0` 且无 API key（启动日志已打 CORS 警告）。跨网使用需加 `--api-key`。
