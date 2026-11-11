# Gufo 加载 27B / 35B-A3B 与 NPU 单独加载 35B-A3B：收益预测

日期：2026-11-08 19:05 GMT+8
对象：AMD Ryzen AI MAX+ 395 / Strix Halo / gfx1151 / XDNA2 / 128 GiB 统一内存主机
上承：`2026-11-08-NPU与GPU共存可行性及收益预测.md`、`2026-11-07-Halogen与Gufo-本机适配性对比判定.md`、`2026-11-06-Gufo方案-本地部署可行性分析.md`

---

## 一、两问结论

| 问题 | 判定 |
|---|---|
| **Gufo 加载 Qwen3.8-27B** | 三个 Flash-Next 场景里**最接近可行**的一条（GTT 只差 8.67–9.73 GiB），但仍装不下、仍需改 BIOS、权重零重叠。改 BIOS 后 decode **0.55–1.20×（中位 ≈1.0×，持平）**，prefill 有限提升、8 并发 +27%、冷加载 +272%。为 22.4 t/s 的次要模型摧毁 90.14 t/s 主链路 → **净负** |
| **Gufo 加载 Qwen3.6-35B-A3B** | 官方 **无 35B**，只有两个第三方 fork。改 BIOS 后真实混合负载 decode **0.65–1.35×（中位 ≈0.8×，更慢）**；只有 code/JSON 结构化输出达 1.2–1.8×。净收益由输出类型决定：prose 主导必负，结构化主导才可能正 → **总体净负** |
| **NPU 单独加载 35B-A3B** | **官方支持、有现成 .q4nx 权重**，但本机 host 仅 30.47 GiB，**必然 OOM**（本机历史实测 SIGKILL 137）。同芯片实测 decode **8.11–16 t/s** = 本机 iGPU 90.14 t/s 的 **0.09–0.18×**；32K TTFT **126.3 s**。且为扩内存改 BIOS 会用 `amd_iommu=off` 把 NPU 一起关掉 → **逻辑自相矛盾，净负 5–11 倍** |

**一句话**：换「小一点的同一个模型」没有绕开内存池零和；NPU 跑 35B 是「能跑但没意义」——`decode 由激活参数决定`，NPU 跑 4B 是 12.4 t/s，跑 35B-A3B 还是 8–16 t/s，却要多付 5× 权重、9× 内存、100× 首字延迟。

---

## 二、本机基线与口径（2026-11-08 18:57 实测）

| 项 | 值 | 来源 |
|---|---:|---|
| 27B dense decode | **22.4 t/s**（已是最优，物理上限 ~23，带宽墙） | `~/.workbuddy/MEMORY.md` |
| 35B-A3B decode | **90.14 t/s** | `2026-10-03-35B速度复测.md` |
| 35B-A3B 89K 长 prefill | **≈520 t/s** | 同上 |
| MTP 接受率 / 同会话 LCP 复用 | 77.4% / **18–202×** | 同上、项目 `MEMORY.md` 第三节 |
| host MemTotal / **MemAvailable** | 30.47 GiB / **18.41 GiB** | `/proc/meminfo` 18:57:24 |
| VRAM carve-out total / used | 96.00 GiB / 36.71 GiB | sysfs `mem_info_vram_*` |
| GTT total / used | **30.47 GiB** / 0.15 GiB | sysfs `mem_info_gtt_*` |
| 8080 / 8219 / 18090 | 8080 未监听、8219 未监听、18090 在听 | `ss -ltnp` |
| SoC 功耗墙 / 有效带宽 | 120 W / ≈144 GB/s | 项目 `MEMORY.md` 第四节、2026-10-30 实测 |

**沿用两条铁律**：① `decode 由激活参数决定，与总参数无关`；② 净收益模型 `T_new/T_old = p/S_p + (1−p)/S_d`，`p` 为长 prefill 占端到端耗时比例，本机因 LCP 复用 `p` 远低于 0.642（上一份报告盈亏平衡点）。

---

## 三、问 1a：Gufo 加载 Qwen3.8-27B

### 3.1 硬阻塞（当前配置装不下）

| 项 | 事实 | 来源 |
|---|---|---|
| 权重零重叠 | 本机 `Qwen3.8-27B-ROCmFP4-FAST.gguf` 是**私有 ggml type 101**，只有本机 fork 能读；Gufo 只吃 Unsloth `Qwen3.8-27B-UD-Q4_K_XL.gguf`（16.35 GiB）+ `z-lab DFlash2 Q4_K_M` | `2026-11-06-Gufo方案-本地部署可行性分析.md` 第五节；官方 `docs/models/qwen3.8-27b.md` |
| Gufo 27B Q4 峰值内存 | **40.20 GiB**（pp2048+tg128）；16K prefix **50.27 GiB**；`--cache-ram-bytes 1073741824` 下限 **39.14 GiB** | 官方 `docs/internal/models/qwen3.8-27b/BENCHMARKS.md`「Memory occupation」 |
| 本机 GTT | 30.47 GiB | 本次实测 |
| 缺口 | **−8.67 ~ −9.73 GiB** | 计算 |
| 关 vision projector / 缩 context 能否压到 30.47 以下 | 官方无数据 | 待核（沿用 Gufo 报告待核 1） |

→ **仍无降级验证路径**：连官方最小文本模型都装不下，必须改 BIOS UMA 96 GiB → 512 MiB。

### 3.2 官方一手同机数据（Strix Halo 128 GB，Q4_K_XL，vs llama.cpp b11069）

来源：`docs/internal/models/qwen3.8-27b/BENCHMARKS.md`，HTTP / greedy / thinking off，2026-10-19 刷新。

| 场景 | Gufo | llama.cpp 参考 | 增益 |
|---|---:|---:|---:|
| AR pp @depth 0 | 648.89 t/s | 357.54 | +81.5% |
| AR pp @131,072 | 259.73 | 135.95 | +91.0% |
| **AR tg @depth 0** | **12.37** | 12.06 | **+2.6%** |
| AR tg @131,072 | 8.51 | 8.46 | +0.6% |
| DFlash2 tg mixed @0 | 26.91 | 23.40 | +15.0% |
| DFlash2 tg mixed @32,768 | 19.77 | 18.88 | +4.7% |
| DFlash2 tg mixed @131,072 | 15.30 | 14.58 | +4.9% |
| DFlash2 tg repetitive @0 | 64.74 | 35.86 | +80.5% |
| 8 并发 DFlash2 mixed 聚合 | 91.27 | 71.71 | +27.3% |
| 冷加载 Q4 → HTTP ready | **6.27 s** | 23.33 s | +272.1% |

官方模型卡摘要 `up to 71.55 tok/s tg` / `128.42 aggregated`，均标注 `Peak measured workloads ... Peaks include repetitive output`。

**关键读数**：AR decode 只 +2.6% —— **dense 27B 的带宽墙在任何引擎上都一样**。Gufo 的全部 decode 收益来自 DFlash2 投机，且随上下文深度从 +15.0% 衰减到 +4.9%。

### 3.3 三方交叉验证

| 来源 | 27B decode | 说明 |
|---|---:|---|
| 中文同机横评（AMD MAX+ 395 128GB） | 中文长文 **17.3** vs llama.cpp 19.1 → **0.91×（更慢）**；降 AI 改写 38.4 vs 32.8 → 1.12–1.17× | `2026-11-06-Gufo方案…` 7.2 节 |
| `mikealanni/gufo` fork（UD-Q4_K_XL，同芯片） | plain 12.3；DFlash2 code 47.6 / **prose 24.8** / JSON 62.2；auto 43 / 24 / 53 | 该 fork README，`gufo serve` greedy chat |
| 本机 | **22.4** | `~/.workbuddy/MEMORY.md` |

### 3.4 折算到本机 22.4 t/s

| 对照 | t/s | 相对本机 |
|---|---:|---:|
| Gufo AR @0 | 12.37 | **0.55×** |
| Gufo DFlash2 mixed @0 | 26.91 | **1.20×** |
| Gufo DFlash2 mixed @32K | 19.77 | 0.88× |
| Gufo DFlash2 mixed @131K | 15.30 | 0.68× |
| 中文长文 | 17.3 | 0.77× |
| fork DFlash2 prose | 24.8 | 1.11× |
| fork DFlash2 code / JSON | 47.6 / 62.2 | 2.13× / 2.78× |

**本机 22.4 t/s 已是 ROCmFP4-FAST（更轻量化）+ 调优 fork 的带宽墙结果**；Gufo 换更重的 `UD-Q4_K_XL`（16.35 GiB）后 AR 只有 12.37 t/s，全靠投机拉回 26.91。→ **真实混合负载 decode 0.77–1.20×，中位 ≈1.0×（持平）**；只有 code/JSON 结构化输出能到 2×。

| 维度 | 预测（改 BIOS 且隔离 PoC 后） | 置信度 |
|---|---|---|
| decode | **0.55–1.20×**（混合负载中位 ≈1.0×） | 高（官方同机 + 中文同机 + fork 三方） |
| prefill | **1.0–1.5×** | **中低 [UNVERIFIED]**：官方 +67~91% 是相对未调优 llama.cpp b11069；本机 27B prefill 未单独测 |
| 8 并发聚合 | **≈1.27×**（唯一结构性收益） | 中高 |
| 冷加载 | **≈3.7×** | 中（本机 27B 冷加载未测） |
| 容量 | GTT 30.47 → ≈124 GiB，可装 | 高 |

**净判定**：`S_d ≈1.0`、`S_p ≈1.0–1.5` → `T_new/T_old ≈1`，性能打平；代价是 carve-out 96 → 0.5 GiB（35B 90.14 t/s 主链路、MiniMax-H3 / sd.cpp 视频栈全灭）、NPU 可能失效、重下 16.35 GiB + DFlash2 权重、docproxy 适配。**净负，置信高**。

---

## 四、问 1b：Gufo 加载 Qwen3.6-35B-A3B

### 4.1 官方无 35B，只有两个第三方 fork

`https://api.github.com/repos/gufo-org/gufo/contents/docs/models` 实测：仅 `qwen3.8-27b.md`、`qwen3.8-flash-next.md`、`deepseek-v4-flash.md`、`minimax-h3.md`、`embeddinggemma-2.md`、`qwen3-asr.md`、`qwen3-tts.md`、`qwen-image-2.1.md` — **无 35B**。

| fork | 权重 | 一手数字 |
|---|---|---|
| `NinjaPear/gufo-Qwen3.6-35B-A3B-Q6dense` | **Q6dense 特制权重 + native MTP** | `3,095.44 tok/s pp @4,096 depth`；`up to 190.67 tok/s tg` 单用户；`334.35` 8 并发 |
| `mikealanni/gufo`（GPU + XDNA2 NPU） | `UD-Q4_K_XL` | GPU-only prefill `-p2048 3,034 / -p4096 3,013 / -p8192 2,862`；decode plain 60.6（gufo bench -n 128）、MTP code 111 / prose 72 / JSON 122、DFlash2 code 140 / prose 59 / JSON 159、auto 138 / 68 / 156 |

NinjaPear README 逐字 `Peak measured workloads; ... Peaks include repetitive output` → **190.67 t/s 是 peak + repetitive + 特制权重，剔除，不作持续吞吐**。两 fork 均需重下权重，本机 `Q4_K_P.gguf`（22 GiB）/ `MTP-ONLY-Q4_K_M.gguf` 都不兼容。

### 4.2 折算到本机 90.14 t/s

| 模式 | code | prose | JSON | 相对本机 |
|---|---:|---:|---:|---|
| plain | 60.6 | 60.6 | 60.6 | **0.67×** |
| MTP | 111 | 72 | 122 | 1.23 / **0.80** / 1.35× |
| DFlash2 | 140 | 59 | 159 | 1.55 / **0.65** / 1.76× |
| auto | 138 | 68 | 156 | 1.53 / **0.75** / 1.73× |

交叉校验：`llamaperf.com/report/891` 同芯片 llama.cpp b11009 + `UD-Q4_K_XL` + MTP **77.92 t/s**（无 MTP 53.83）→ 本机 90.14 处于同档，说明折算口径一致。

→ **真实混合负载（prose 主导）0.65–0.80×，更慢；只有 code/JSON 结构化输出 1.23–1.76×，更快**。`mikealanni` 自注 `The 35B-A3B runs MTP at three draft tokens`、`DFlash2 wins on code and JSON, MTP on prose`。

### 4.3 净收益模型：胜负完全取决于输出类型

沿用 `T_new/T_old = p/S_p + (1−p)/S_d`，取 `S_p = 2.69`（长 prefill 2.4–3.1× 中位），解 `T=1` 所需 `S_d* = (1−p)/(1−p/S_p)`：

| p（长 prefill 占比） | 打平所需 `S_d*` | Gufo 35B prose `S_d=0.65–0.80` | Gufo 35B code/JSON `S_d=1.23–1.76` |
|---:|---:|---|---|
| 0.15（典型对话） | **0.900** | 亏（T≈1.33–1.51） | **赚**（T≈0.72–0.79） |
| 0.30（长文档较多） | 0.788 | 亏（T≈1.30–1.43） | **赚** |
| 0.50 | 0.614 | 亏（T≈1.22–1.31） | **赚** |

**结论**：本机是「对话 + 代码 + 文档处理」混合负载，prose 与结构化输出各占一部分；但同会话 LCP 复用把 `p` 压到远低于 0.15，而 decode 是每轮都吃。综合 **净负**，置信中高。若少爷的负载是纯 code/JSON 批量生成，该分支可能转正 —— 这是唯一值得单列 A/B 的细分场景（前提仍是改 BIOS + 第三方 fork）。

### 4.4 容量与链路

- 35B 权重 ~22 GiB，按 27B 的「权重→峰值」倍率 16.35→40.20（2.46×）外推，Gufo 35B GTT 需求 **≈45–55 GiB [UNVERIFIED]**（无官方数据）> 本机 30.47 GiB → **仍需改 BIOS**。
- 链路冲突沿用 Gufo 报告第六节：8080 端口、MCSManager 面板托管、`enable_thinking` 注入、`model` 字段匹配、`maxRequestBytes`、`--cache-ram-bytes`、podman 未装。
- 第三方 fork 无官方 CI / 逐模型质量报告，v0.29.0 后上游有 BREAKING CHANGES → 可维护性风险高。

---

## 五、问 2：NPU 单独加载 Qwen3.6-35B-A3B

### 5.1 可行性：**官方支持，但不是 GGUF**

本机 `flm v0.9.45` 的 `/opt/fastflowlm/share/flm/model_list.json` 实测有 `qwen3.6-moe:35b-a3b` 条目（`flm list` 全量清单第 33 行）：

```json
"name": "Qwen3.6-35B-A3B-NPU2",
"flm_min_version": "0.9.45",          // 本机版本正好满足
"details": { "format": "NPU2", "parameter_size": "35B",
             "quantization_level": "Q4_K_S" },
"default_context_length": 32768,
"max_prefill_len": 4096,
"vlm": true,
"footprint": 24.3
```

`halobench clm-0013` 交叉验证：`23.2 GB` 权重 + `1.0 GB` vision encoder（= footprint 24.3，单位为十进制 GB）。`1bit-MONSTER/Qwen3.6-35B-A3B-NPU` 模型卡逐字：`Q4NX packing: FastFlowLM/Qwen3.6-35B-A3B-NPU2, unchanged (model.q4nx is byte-identical at 0cad628)`。

**订正 1**：项目 `2026-10-07-NPU-8219-测试与使用手册.md` 第七节「不能加速 35B/27B GGUF」在 2026-10-07 时点正确（指 GGUF 不兼容），但**不能外推为「NPU 跑不了 35B」**——官方已发布 `.q4nx` 转换版。

### 5.2 本机硬阻塞：必然 OOM

| 项 | 事实 | 来源 |
|---|---|---|
| 历史一手 | 本机曾实际尝试 flm 加载 35B-A3B，**OOM-killer SIGKILL（exit 137）**；dmesg `anon-rss 34.5 GB + shmem-rss 22.2 GB ≈ 58.6 GB`，加其他进程 ~33 GB 共 ~92 GB > 当时系统总内存 91 GB | `$HOME/.openclaw/workspace/memory/flm_qwen3.6_moe_35b_a3b.md` |
| 当前 host RAM | MemTotal **30.47 GiB** / MemAvailable **18.41 GiB** | 本次 `/proc/meminfo` |
| 35B 权重 | 24.3 GB 未下载；`flm list --filter installed` 空 | 本次实测 |
| 结论 | 连 24.3 GB 权重 + 运行时都放不下，**30.47 GiB 下必然 OOM**，无从谈速度 | 计算 |

> 该历史记录写「系统总内存 91 GB」，与当前 30.47 GiB host 分法不同，时点存疑 **[UNVERIFIED]**；但「flm 35B 峰值约 58.6 GB / 触发 OOM」这一事实有效。

**订正 2（闭环上一份报告待核 1）**：11-08 报告称「`flm list --filter installed` 返回 `No models found` 是唯一硬阻塞」——本次定位为**环境变量未注入**，不是模型丢失：

```bash
export FLM_MODEL_PATH=$HOME/.config/flm/models
flm list --filter installed
# [FLM] Fetching models from: /opt/fastflowlm/share/flm/model_list.json
# Models:
#   - qwen3.5:4b ✅
```

真路径 `$HOME/.config/flm/models/models/Qwen3.5-4B-NPU2/` 下有 `model.q4nx 4.1G` + `vision_weight.q4nx 637M`（共 4.7 GB），另两个目录为空。**NPU 4B 链路今天就能用**，35B 权重需另下。

### 5.3 同芯片一手速度（Strix Halo / XDNA2）

`halobench clm-0013`（Framework Desktop, gfx1151, LMDE 7 / xanmod 7.1.3，verified 2026-08-05，「CORRECTED with measured Strix Halo data」）：

| ctx | NPU decode | NPU prefill | NPU TTFT |
|---:|---:|---:|---:|
| 1k | **12.11 t/s** | 90.7 t/s | 10.8 s |
| 8k | **10.94** | 209.9 | 36.9 s |
| 32k | **8.11** | 245.2 | **126.3 s** |

同机同模型更高量化（Q8_0, 35.21 GiB）在 iGPU：`pp4096 709–840 t/s ROCm / 964–1039 t/s Vulkan`；`tg128 43 t/s ROCm / 53 t/s Vulkan`。原文结论逐字：`the iGPU is roughly 4x faster at decode AND 4-6x faster at prefill, while running a heavier quantisation`。

第二独立来源 `1bit-MONSTER/Qwen3.6-35B-A3B-NPU` 模型卡（Lemonade + `1bit serve`，full ELFs）：`ready in 30 s; about 16 tok/s decode`。

### 5.4 折算到本机

| 指标 | NPU 35B | 本机 iGPU 35B | 倍数 |
|---|---:|---:|---:|
| decode | 8.11–16 t/s | **90.14 t/s** | **0.09–0.18×（慢 5.6–11 倍）** |
| prefill | 90.7–245.2 t/s | ≈520 t/s（89K 长窗口） | 0.17–0.47× **[UNVERIFIED]**（窗口口径不同） |
| TTFT @32K | **126.3 s** | 同会话 LCP 复用 <1 s / 冷启动 84K ≈149 s | 交互场景直接出局 |
| 权重 / 运行时内存 | 24.3 GB / ≈58.6 GB | 22 GiB 落 carve-out | — |
| 上下文 | 32768（单次 prefill ≤4096） | **262144** | 1/8 |
| 并发 | 设备独占、串行排队 | `-np 1`（可扩） | — |

### 5.5 核心洞察：换大模型只提质量，不提速度

`decode 由激活参数决定` 在 NPU 上再次成立：

| NPU 上跑 | 激活参数 | 每 token 读 | 实测 decode |
|---|---:|---:|---:|
| Qwen3.5-4B-NPU2 | 4B dense | ~2.5 GB | **12.4 t/s**（本机 2026-10-07 实测） |
| Qwen3.6-35B-A3B-NPU2 | **3B**（8 routed + 1 shared / 256 experts） | ~2 GB（halobench 原文） | **8.11–16 t/s** |

→ **速度几乎相同**（同受 XDNA2 侧内存带宽墙），但代价是权重 4.7 GB → 24.3 GB（**5.2×**）、运行时 6.5 GB → ≈58.6 GB（**9×**）、TTFT 1.19 s → 126.3 s @32K（**106×**）、上下文 262144 → 32768。换来的只有模型能力（35B vs 4B），且 35B 占着 NPU 时所有旁路任务排队。

### 5.6 致命交叉约束：为跑 NPU 而改 BIOS，会把 NPU 一起关掉

1. 要让 flm 装下 35B（需 ~58.6 GB host RAM），必须把 BIOS UMA 从 96 GiB 改到 512 MiB → carve-out 塌到 0.5 GiB，**iGPU 90.14 t/s 主链路 + 视频栈全灭**。
2. 大 GTT 标准配置含 `amd_iommu=off`；offsite.guru 原文 `It also disables DMA translation machine-wide and takes the NPU with it`，halobench 亦记 `mutually exclusive with amd_iommu=off (+5-12%)` → **NPU 同时失效**。
3. → 结果是「为了用 NPU，把 iGPU 和 NPU 都弄没了」。**该路径逻辑上自我否定**。
4. 理论上「只改 BIOS UMA、不加 `amd_iommu=off`」可同时保留大 host RAM 与 NPU（默认 GTT 上限约 92 GiB 足够 58.6 GB），但 **[UNVERIFIED]**，且 carve-out 全灭的代价不变。

**判定**：NPU 单独跑 35B-A3B 速度 **8–16 t/s decode / 90–245 t/s prefill / TTFT 10.8–126.3 s**；当前配置必 OOM；改 BIOS 跑起来也是「用 90 t/s 换 12 t/s」，净负 5–11 倍。**NPU 的正确用途仍是旁路 4B**（12.4 t / <2 W / 6.5 GB / 零显存 / TTFT 1.19 s），即 11-08 报告第七节方案，不变。

---

## 六、三处口径订正（覆盖前报告）

| # | 原记载 | 订正后 | 依据 |
|---|---|---|---|
| 1 | 11-08 报告第九节风险 4「flm 白名单模型有限（Gemma3 / Llama3.2 / Qwen3 / GPT-OSS-20B）」 | **过时不完整**：v0.9.45 清单 **27 族 / 37 变体**，含 `qwen3.6-moe:35b-a3b`、`gpt-oss:20b`、`qwen3.5:9b`、`gemma4-it:e2b/e4b`。NPU **能跑 35B-A3B MoE**，只是不吃 GGUF | 本机 `model_list.json` + `flm list` |
| 2 | 11-08 报告第三节「`flm list --filter installed` 空 = 唯一硬阻塞 [UNVERIFIED]」 | **已定位闭环**：`FLM_MODEL_PATH` 未注入；设为 `$HOME/.config/flm/models` 后 `qwen3.5:4b ✅` 可见，4.7 GB 权重在盘。35B 权重确实未下载 | 本次实测 |
| 3 | 11-08 报告第四节「同一个请求 NPU+GPU 协同不可行、实测负收益」 | **收窄**：1bit engine 的 hybrid 确为 `measured loss`、`No real NPU prefill provider exists`；但 `mikealanni/gufo` fork 实现了「同一 projection 分列 offload」（NPU 跑前导输出列的 block-float 8-bit GEMM，GPU 算剩余列并直接读 NPU 结果），同机实测 prefill **27B +9.3~28.2% / 35B +1.1~9.5% / Flash-Next +17.3~19.9%**。机制不同，不矛盾 | `github.com/mikealanni/gufo` README |

**订正 3 不改变「不建议」的结论**，但理由从「物理不可行」改为「有可行实现，硬前置不适配本机混合生产机」：`mikealanni/gufo` 要求 ① `-DGUFO_ENABLE_NPU=ON` 源码构建（本机无 podman/nix）② **必须锁 GPU fabric clock 到 2000 MHz**，原文 `This is required: without it the GPU and the NPU together can hang the machine`、`It is not a guarantee`、`A hang needs a power cycle` ③ 每次 boot 重设 `xrt-smi configure --pmode performance`（本机 `xrt-smi` 不存在）④ 禁止 NPU runtime suspend ⑤ 测量须 `With nothing else running`。→ 与本机「桌面 + WorkBuddy + docproxy + 视频生成」混合生产直接冲突，且有整机 hang 风险。

---

## 七、数据校验与剔除（怀疑一切）

| 数据 | 校验 | 处置 |
|---|---|---|
| NinjaPear `190.67 t/s tg` / `3,095.44 pp` | README 自注 `Peak measured workloads ... Peaks include repetitive output`；Q6dense 特制权重、第三方 fork、无质量报告 | **剔除**，不作持续吞吐，仅列上界 |
| 官方 27B `up to 71.55 t/s tg` / `128.42 聚合` | 同注 `Peaks include repetitive output`；`71.55` 对应 1 用户 repetitive 档 | 仅列上界；折算用 `tg mixed` 列 |
| Gufo 官方 `AR tg +2.6%` | 与「dense 带宽墙」物理一致，且 Q8 AR 增益 ≈0%（−0.1~+0.3%）互证 | **保留**，作为 decode 无结构性收益的铁证 |
| `mikealanni` 的 `+28.2%` NPU prefill | 是 `-p8192` 短窗口；本机 89K 长窗口未测；fork 自述无独立复现；与 1bit `measured loss` 机制不同 | **[UNVERIFIED]**，不外推到本机长上下文 |
| halobench「iGPU 快 4× decode / 4–6× prefill」 | 同机同模型、iGPU 用更重 Q8_0 量化，方法学完整（含自我订正 `CORRECTED 2026-08-05`） | **保留**，作为 NPU 35B 的主要依据 |
| 本机历史 OOM 记录「系统总内存 91 GB」 | 与当前 30.47 GiB host 分法不符，时点存疑 | **[UNVERIFIED]**，但 OOM 事实与 58.6 GB 峰值有效 |
| 本机 27B prefill 基线 | 从未单独测过 | **[UNVERIFIED]**，所有 27B prefill 折算标注中低置信 |
| Gufo 35B GTT 需求 ≈45–55 GiB | 按 27B 权重→峰值倍率外推，无官方数据 | **[UNVERIFIED]**，仅用于判定「>30.47 GiB」这一方向 |

---

## 八、决策建议

1. **维持现状**（96 GiB UMA + Vulkan + MTP），四条路径全部不进生产：Gufo 27B / Gufo 35B / NPU 35B / Flash-Next 引擎，净收益均为负或被 LCP 复用稀释。
2. **NPU 侧立即可以做的零风险动作**（不改 BIOS、可回滚）：按 11-08 报告第七节，`export FLM_MODEL_PATH=$HOME/.config/flm/models` 后经面板起 8219（`qwen3.5:4b` 已在盘），跑 embedding / rerank / 分类 / guard 旁路；docproxy 加最小分流。**本次已验证该阻塞只是环境变量**。
3. **唯一值得单列 A/B 的细分场景**：Gufo 35B 第三方 fork 在**纯 code / JSON 批量生成**下 decode 1.23–1.76×，是全书唯一可能转正的点。但前提是改 BIOS + 重下 `UD-Q4_K_XL` 权重 + 第三方 fork 可维护性风险 → 只在隔离 PoC 且少爷授权后做。
4. **不要为跑 NPU 35B 改 BIOS**：与 `amd_iommu=off` 互斥，逻辑自我否定。
5. **修正长期知识**：把第六节三处订正写入项目 `MEMORY.md`；NPU 手册第七节「不能加速 35B/27B」加注时点说明。

---

## 九、来源清单

**本机一手（2026-11-08 18:57:24 CST）**
- `/proc/meminfo`、`/sys/class/drm/card1/device/mem_info_{vram,gtt}_{total,used}`、`ss -ltnp`
- `/opt/fastflowlm/share/flm/model_list.json`（27 族 / 37 变体，`qwen3.6-moe:35b-a3b` 全字段）
- `flm --version`（v0.9.45）、`flm list`、`flm list --filter installed`（含 `FLM_MODEL_PATH` 注入前后对照）
- `$HOME/.config/flm/models/models/Qwen3.5-4B-NPU2/`（4.7 GB）
- `$HOME/.openclaw/workspace/memory/flm_qwen3.6_moe_35b_a3b.md`（OOM 137 / 58.6 GB 峰值）
- `$HOME/models` 顶层 GGUF 清单
- 项目 `2026-10-07-NPU-8219-测试与使用手册.md`、`2026-10-03-35B速度复测.md`、`MEMORY.md`、`~/.workbuddy/MEMORY.md`

**Gufo 官方 / fork**
- `https://api.github.com/repos/gufo-org/gufo/contents/docs/models`（确认无 35B）
- `https://raw.githubusercontent.com/gufo-org/gufo/main/docs/models/qwen3.8-27b.md`（模型卡 + 648.89 / up to 71.55 / 128.42 / 16.35 GiB）
- `https://raw.githubusercontent.com/gufo-org/gufo/main/docs/internal/models/qwen3.8-27b/BENCHMARKS.md`（完整 AR/DFlash2/多用户/内存/冷加载表）
- `https://raw.githubusercontent.com/NinjaPear/gufo-Qwen3.6-35B-A3B-Q6dense/main/README.md`（3,095.44 / 190.67 / 334.35 + peak 标注）
- `https://github.com/mikealanni/gufo`（35B / 27B 完整 prefill + decode 表、NPU projection offload 机制、Try it 硬前置、稳定性风险）

**NPU 35B 同芯片实测**
- `https://www.halobench.com/records/clm-0013`（12.11 / 10.94 / 8.11 t/s；90.7 / 209.9 / 245.2 pp；TTFT 10.8 / 36.9 / 126.3 s；iGPU Q8_0 对照；与 amd_iommu=off 互斥；NPU 并发使 iGPU decode −14%）
- `https://huggingface.co/1bit-MONSTER/Qwen3.6-35B-A3B-NPU`（ready 30 s / about 16 tok/s / Q4NX byte-identical at 0cad628）
- `https://hf-mirror.com/FastFlowLM/Qwen3.6-35B-A3B-NPU2/resolve/main/README.md` + `/api/models/...`（35B 总参 / 3B 激活 / 256 experts / 8 routed + 1 shared / 40 层 / 原生 262144 / MTP trained）
- `https://www.llamaperf.com/report/891`（同芯片 llama.cpp b11009 + UD-Q4_K_XL + MTP 77.92 / 无 MTP 53.83，交叉校验）

---

## 十、待核项

1. 本机 27B prefill 基线未测 → 所有 27B prefill 折算置信中低，需补一次带随机 uuid 前缀的短/长窗口测速。
2. Gufo 27B 关闭 vision projector + 更小 context 后能否压到 30.47 GiB 以下（官方无数据）。
3. Gufo 35B 的官方/第三方 GTT 峰值无数据，≈45–55 GiB 为倍率外推。
4. 本机历史 OOM 记录「系统总内存 91 GB」的时点与当时 BIOS UMA 分法。
5. 「只改 BIOS UMA、不加 `amd_iommu=off`」能否同时保留大 host RAM 与 NPU（默认 GTT 上限 ~92 GiB 是否足够）。
6. `mikealanni/gufo` 的 NPU prefill 正收益在 ≥32K 长窗口是否成立（其只测到 `-p8192`）。
7. 11-08 报告遗留：本机固件/SMU 版本、「NPU busy 时 GPU 35B decode 掉多少」A/B（halobench 给出旁证约 −14%，仍非本机实测）。
8. 35B 长 prefill 旧记录「308 KB → 26 s」与 89K / 171 s / ≈520 t/s 口径差异（沿用前报告待核）。

---

> 许可：CC0-1.0，公共领域贡献，无任何限制。
