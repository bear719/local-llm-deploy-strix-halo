# 收益预测（订正后口径）与 NPU + iGPU 共存可行性判定

日期：2026-11-08 18:30 GMT+8
对象：AMD Ryzen AI MAX+ 395 / Strix Halo / gfx1151 / XDNA2 / 128 GiB 统一内存主机
上承：`2026-11-07-Halogen与Gufo-本机适配性对比判定.md`、`2026-11-06-Strata方案-社区经验收益预测.md`、`2026-11-06-Gufo方案-本地部署可行性分析.md`

---

## 一、两问的结论

**问 1「预测收益怎么样」**：按上一轮两处订正后的口径，**换任何 Flash-Next 专用引擎（Gufo / Halogen / Strata）在本机都是净负收益**，盈亏平衡要求长 prefill 占端到端耗时 > 64.2%，而本机同会话 LCP 前缀复用 18–202× 使稳态 prefill 占比远低于该阈值。唯一低风险正收益仍是零 BIOS 改动的单点调优，确定部分约 combined **+5.9%**（新 RADV），其余降为 [UNVERIFIED] 待 A/B。

**问 2「NPU 闲置，能否 NPU+GPU 同时加速或共存，不抢资源，多一个干活的」**：

| 形态 | 判定 |
|---|---|
| **同一个请求拆给 NPU + iGPU 协同**（hybrid / 算子拆分 / NPU 草稿投机） | **不可行，且实测是负收益**。见第四节 |
| **各干各的、任务级并存**（NPU 跑旁路小模型，iGPU 跑主模型与视频） | **可行，今天就能做，是唯一正确形态**。见第七节 |
| **完全不抢对方资源** | **不成立**。计算单元 / 显存 / 设备节点 / 驱动隔离；**UMA 带宽、120 W 功耗墙、host RAM 三者共享**。见第五节 |

**一句话**：能多一个干活的，但不是同一个活两个人干；而且这个新工人要和老工人分同一条内存总线和同一份 120 W 电。

---

## 二、问 1：订正后口径的收益预测

### 2.1 基线（本机一手）

| 项 | 值 | 来源 |
|---|---:|---|
| 35B-A3B decode | **90.14 t/s** | `2026-10-03-35B速度复测.md` |
| 89K 长 prefill | **≈520 t/s** | 同上 |
| MTP 接受率 | 77.4% | 同上 |
| 同会话 LCP 前缀复用 | **18–202×** | 项目 `MEMORY.md` 第三节 |
| SoC 功耗墙 | **120 W**（`amdgpu_pm_info` 平均=瞬时=120.01 W） | `~/.workbuddy/MEMORY.md`、项目 2026-10-30 实测 |
| 有效带宽 | ≈144 GB/s | 项目 `MEMORY.md` 第四节 |

### 2.2 四场景预测表

| 场景 | decode | prefill | 容量 | 净判定 | 置信度 |
|---|---:|---:|---|---|---|
| **A 现状直上 Flash-Next 引擎** | **0.31–0.64×**（28–58 t/s，腰斩） | 2.4–3.1× | 现有 Vulkan 栈全灭 | **净负** | 高 |
| **B 改 BIOS 做 Gufo 隔离 PoC** | 0.31–0.64× | 2.4–3.1× | GTT 30.47 → ≈124 GiB | 容量正 / 速度负 | 中 |
| **C 永久切大 GTT（Halogen/Gufo 常驻）** | 0.31–0.64× | 2.4–3.1× | carve-out 96 → 0.5 GiB | **−80%~−100%** | 高 |
| **D 维持现状 + 单点调优** | 0～+8% | +15~35%（理论）/ **实测确定 +5.9%** | 不变 | **唯一低风险正收益** | 中高 |

来源：上一轮报告第六节订正 A（decode 跨模型不可折算）、`2026-11-06-Strata方案-社区经验收益预测.md` 四场景矩阵。

### 2.3 净收益模型（为什么 prefill 2.7× 救不回来）

设 `p` = 长 prefill 占端到端耗时比例，`S_p` = prefill 加速比，`S_d` = decode 加速比：

```
T_new / T_old = p / S_p + (1 - p) / S_d
```

代入 Flash-Next 引擎实测区间中位（`S_p = 1400 / 520 = 2.69`，`S_d = 42 / 90.14 = 0.47`）：

```
T_new / T_old = 0.372p + 2.128(1-p) = 2.128 − 1.756p
盈亏平衡 p* = (2.128 − 1) / 1.756 = 0.642
```

| 实际 p | T_new/T_old | 结果 |
|---:|---:|---|
| 0.15（典型对话 / 代码） | 1.865 | **慢 87%** |
| 0.30（长文档较多） | 1.601 | **慢 60%** |
| 0.642 | 1.000 | 打平 |
| 0.65+ | <1 | 需 prefill 占 2/3 时间，本机不成立 |

**本机 `p` 低的原因不是 prompt 短，是 LCP 复用**：WorkBuddy 注入 40K+ tokens，但同会话前缀命中后 prefill <1 s（项目 `MEMORY.md` 第三节、`2026-10-03-35B速度复测.md` 冷启动 84K≈149 s / 复用后 <1 s）。只有全新会话、随机 uuid 前缀的冷启动才吃满 prefill——而那正是测速场景，不是日常负载。

**结论**：换引擎拿到的 2.4–3.1× prefill 收益被 LCP 复用稀释，付出的 decode 腰斩却是每轮都吃，净负。

### 2.4 场景 D 重排（承接上一轮订正 B）

| 单项 | 原预测 | 订正后 | 依据 |
|---|---|---|---|
| 新 RADV | PP +18.4% / combined +5.9% | **不变，唯一有实测的确定项** | 收益预测报告社区证据 |
| `amd_iommu=off` | prefill +13~16%，列为优先项 | **[UNVERIFIED]，须 off / pt / translated 三臂 A/B** | `noamsto/nix-amd-ai/docs/halogen-flash-teardown.md` 原始对照是 off vs `iommu=pt`，逐字 `Translated mode was never measured, and Translated is what our hosts run` |
| Flash Attention / no-mmap / headless / CPU 限频 | 各 +若干 | **[UNVERIFIED]**，逐项 A/B | 收益预测报告 |
| decode 硬上限 | 无法 2× | **不变** | 120 W 墙 + ≈144 GB/s 有效带宽 |

**可执行确定收益 = combined ≈ +5.9%**，零 BIOS 改动、逐项可回滚。其余须先测再定，不得外推。

---

## 三、NPU 与 iGPU 当前状态（2026-11-08 18:29:34 CST，一手）

| 项 | 读数 | 判定 |
|---|---|---|
| 内核 | `7.0.0-42-generic` | — |
| host MemTotal / **MemAvailable** | 30.47 GiB / **18.43 GiB** | 比 11-07 的 3.57 GiB 大幅好转（Firefox 关闭、sd-cli RSS 从 6.1 GiB 降到 824 MiB） |
| VRAM carve-out total / used | 96.00 GiB / **37.87 GiB** | `sd-cli` 在跑 |
| GTT total / used | 30.47 GiB / **0.16 GiB** | HIP 侧几乎零占用 |
| 8080 / 8219 / 18090 / 23333 | 8080 **未监听**、8219 **未监听**、18090 与 23333 在听 | **iGPU 主模型未启动、NPU 服务未启动** |
| `sd-cli` | `-M vid_gen MiniMax-H3`（PID 1587520，RSS 824 MiB） | 视频生成占 carve-out |
| XDNA 设备 | `/dev/accel0`（`root:render`，261:0，Nov 8 13:40）存在 | 驱动就绪 |
| 内核模块 | `amdxdna` 已加载，`amd_pmf` 依赖它；`amdgpu` 独立 | 两套驱动分离 |
| `flm` | v0.9.45 已装 | — |
| `flm list --filter installed` | **`No models found for the specified filter`** | **[UNVERIFIED]** 已装模型不可用或路径未接上 |
| `model_list.json` | `model_path: "models"`（相对路径）；`$HOME/models` 下无 NPU 目录 | 需核实 `FLM_MODEL_PATH`（项目 `MEMORY.md` 第六节：其下多一层 `models/`） |
| `xrt-smi` | 不存在 | flm 自带 runtime，非阻塞 |

**NPU 确实闲置，硬件与驱动就绪，零占用；`MemAvailable 18.43 GiB` 足够容纳记忆里 NPU 模型的 RSS 6.5 GB。**

---

## 四、为什么「同一个请求 NPU + GPU 协同」不可行

### 4.1 一手实测：hybrid 当前是 measured loss

`1bit-MONSTER/engine/docs/hybrid.md`（Strix Halo 同款芯片，2026-10-30 pin）：

> `No real NPU prefill provider exists in this tree or in this build`
> `58.14 s for a 5-token batched chunk on the 27B` —— 比 backend 自己 prefill 慢约四个数量级
> `restore 6-7 ms for 307 tokens`；backend 自己 prefill 307 tokens 约 `95 ms`
> `on this box the hybrid row is a measured loss, not a route waiting for a benchmark`

即便未来实现真正的并发拆分，按该文档算术上限 **`1.035×` end-to-end prefill（约 +3.5%，且 `before the pipeline cost`）**；`M<=2048` 时答案是 `1.00×`（`no`）。

hybrid 还**明确拒绝** `--parallel > 1`、`--mtp`、`--dflash`、`--mmproj`、`--moe-slots`、`--embedding` / `--reranking` role、`--pm`，且**只用单 slot `-np 1`**、GGUF 自带 MTP head 不使用。→ 与本机 `-c 262144` + MTP n-max=2 + mmproj + 投机解码的生产配置**正面冲突**。

### 4.2 一手实测：NPU 草稿模型投机解码零收益

`OllamaAMDNPU` 项目（自研 llama.cpp backend 把 `GGML_OP_MUL_MAT` 派发到 XDNA2）：

> `Speculative decoding with Llama-3.2-1B draft: 44% accept rate, 212 t/s draft, but zero effective gain`
> `The lack of improvement ... indicates the bottleneck is LPDDR5 bandwidth, not compute`
> `No software technique can overcome a bandwidth-bound memory wall`

**该项目核心数字已自我订正**：`The 43.7 t/s "NPU decode" baseline ... was later found to be Vulkan decode (see Phase 7 correction)` → 其 `Vulkan prefill + NPU decode 930 t/s / 43.7 t/s / 41.5 W / 0.947 J/tok` 一栏的 decode 归属存疑，**不作为 NPU 性能依据**（见第十节剔除表）。

### 4.3 格式与栈的硬门槛

| 来源 | 原文 |
|---|---|
| runaihome Lemonade 指南 | `GGUF (via llama.cpp) / FLM (q4nx, for NPU) / ONNX (via OnnxRuntime GenAI, for NPU+iGPU hybrid)`；`Not every model is available in FLM or ONNX format — the NPU path has a narrower model library than GGUF` |
| AI-Radar | `GGUF models can't simply be turned into ONNX; a dedicated adaptation process is needed` |
| OJAI / MTP 分析 | FastFlowLM `Speculative decoding: ❌ not yet (single-stream NPU)`；`curated whitelist` |
| InfoWorld | Linux 上 NPU 支持**只经 FastFlowLM**；自动后端选择，GUI 几乎无调优项 |

→ 本机主力 `Qwen3.8-Flash-Next-ROCmFP4-FAST-imatrix-v2.gguf` 是私有 ggml type 101，只有 `llama-qwen4exp-rocmfpx` fork 能读；**任何 hybrid 路径都不认它**。要走 hybrid 必须换模型、换引擎、换量化，且放弃 LCP 复用与 MTP。

---

## 五、「不抢资源」逐项判定

| 资源 | 隔离? | 依据 |
|---|---|---|
| 计算单元（AIE tile vs RDNA3.5 CU） | **独立** | OJAI：`they will not contend for compute` |
| 设备节点 / 驱动 | **独立** | 本机实测 `/dev/accel0` + `amdxdna` vs `/dev/kfd` + `amdgpu`；OJAI：`It does not use ROCm, does not go through HIP` |
| iGPU carve-out / GTT 显存 | **独立** | 项目 `MEMORY.md` 第六节：flm `RSS 6.5 GB / 不占 iGPU 显存`；本次 GTT used 0.16 GiB |
| **host RAM** | **共享** | flm RSS 6.5 GB 全在 host RAM；本机 MemTotal 仅 30.47 GiB，`MemAvailable` 在 3.57–18.43 GiB 间波动 |
| **UMA / LPDDR5X 带宽** | **共享** | CPU/GPU/NPU 同 die，256-bit LPDDR5X-8000，理论 256 GB/s / 社区实测 ~215 GB/s（bestllmfor / spawningpoint / willitrunai）；本机有效带宽 ≈144 GB/s（项目实测口径） |
| **120 W 功耗墙** | **共享** | 本机 `amdgpu_pm_info` 120.01 W 锁定；同机制证据：IOMMU 翻译功耗 122–127 W 时 shader 从 2549–2713 MHz 降到 2357–2409 MHz，prefill 460→385 t/s |
| NPU 设备并发 | **串行** | 项目 `MEMORY.md`：`NPU busy, request queued (N/10)`；OJAI：`single-stream NPU` |

### 唯一量化到的争用代价

`1bit-MONSTER/engine/docs/hybrid.md` 在 Strix Halo 上做 4 cell × 2 pass 实测：

> `a GPU-busy NPU stream keeps ~87 % of its bandwidth, 7.40 GB/s against 8.2-8.5 idle`；`per launch 10.5-10.9 ms -> 12.0 ms`；`Budget the provider at ~13 % below its solo figure while the decoder is working`
> `160 byte-exact checks, all PASS`；`zero` `GPU reset / MODE2 / ring-timeout`

**并发稳定性好，但带宽折损 ~13% 是真实代价**。重要边界：该实测硬件/固件为 `Kernel 7.3.0-rc4-1bit-perfopt+ / SMU 100.7.0 / BIOS 1.09 / device 0x1586`，原文自己强调 `That is the hardware/firmware pair this verdict is for`。本机内核 `7.0.0-42-generic`、固件未核 → **13% 标 [UNVERIFIED]，且原文未给「NPU busy 时 GPU decode 掉多少」的数字**，必须本机 A/B。

---

## 六、一手资料对「任务级共存」的正面结论

`ojitha.github.io《Multi-Token Prediction on OJAI》` 逐字（最直接回答少爷的设想）：

> `the iGPU and NPU run in parallel, not in series. A Lemonade-orchestrated deployment can route a long-context coding task to the iGPU (with MTP) and an ambient assistant or transcription task to the NPU (FastFlowLM) at the same time, and they will not contend for compute. They will contend for UMA bandwidth, which is the real bottleneck.`

`AMD Lemonade Server`（Apache-2.0，端口 13305，OpenAI 兼容 `/v1`，`/stats` 显示 backend）正是这种编排层：Linux NPU 支持自 10.0（2026-03）经 **FastFlowLM** 提供，而 FastFlowLM 就是本机已装的 `flm`。nilo.io 与 InfoWorld 列出其支持的旁路模态：**Embedding / Reranking / Transcription / Image**。

**关键**：本机缺的不是硬件、不是驱动、不是 runtime，而是 ① NPU 模型文件（`flm list --filter installed` 为空）② 编排/路由层。

---

## 七、可执行方案（零 BIOS 改动，可回滚）

| 步 | 操作 | 备注 |
|---|---|---|
| 0 快照 | 备份 `tools/docproxy.py`；导出 MCSManager `InstanceConfig/*.json` | 可回滚 |
| 1 修阻塞 | 核实 `FLM_MODEL_PATH`（其下多一层 `models/`）；重新拉取 NPU 模型到 **`$HOME/models`**（少爷永久约定），`HF_ENDPOINT=https://hf-mirror.com`，`hf` CLI 未装走 `curl`；验证 `flm list --filter installed` 非空 | 当前唯一硬阻塞 |
| 2 启动 | `unset ROCM_PATH HIP_PATH LD_LIBRARY_PATH` → `flm serve <模型> --port 8219 --host 0.0.0.0`；**经 MCSManager 面板新建实例、前台 `exec`**，禁止裸跑 | 沿用面板托管纪律 |
| 3 路由 | 在 docproxy 18090 加最小分流：按 `model` 名或 `X-Backend: npu` 头转发到 8219，其余仍走 8080；先在本机 18091 测试实例验证再上 18090 | 保留 `enable_thinking=false` 注入、chunked 上传、`select` SSE 心跳 |
| 4 任务白名单 | NPU 侧只跑：embedding / rerank / 意图分类与路由 / 安全 guard / 轻量摘要 / ASR；**不跑主对话、不跑长文档** | 对应设备串行、单流限制 |
| 5 A/B 验证 | 同口径测「GPU 单独 decode」vs「GPU + NPU 并发 decode」：记 t/s、`amdgpu_pm_info` 功耗、`pp_dpm_sclk`、`MemAvailable`；prompt 带**随机 uuid 前缀**规避 LCP 复用 | 这是本机唯一缺失的关键实测 |
| 6 回滚 | 停 NPU 面板实例 → docproxy 路由回退到全走 8080 → 删实例；模型文件保留 | 无 BIOS / 内核改动 |

**验收门槛**：NPU 旁路请求 200 且 content 非空；GPU 主模型 decode 在并发下降幅 ≤3%；`MemAvailable` 全程 ≥4 GiB；无 `amdgpu` reset / MODE2 / ring-timeout。任一不达标即回滚。

**不建议**引入 Lemonade Server 作为编排层：其内置 llama.cpp 是通用 Vulkan 版，**不认本机私有 ROCmFP4 type 101 / QWEN4EXP**，且会与现有 8080 / 18090 / docproxy 链路形成第二套模型管理与缓存；本机已有 docproxy，加一个路由分支是最小改动（简单优先）。

---

## 八、定量收益与代价

### 8.1 NPU 共存的收益（不是主模型变快）

| 收益 | 量化 | 来源 |
|---|---|---|
| 旁路任务从「占用主模型」变成「独立工人」 | 释放 GPU 的 KV slot / prompt cache / carve-out / prefill 时间 | 架构推论 |
| NPU 侧吞吐 | 4B NPU2 模型 **12.4 t/s**、TTFT 1.19 s | 项目 `MEMORY.md` 第六节 2026-10-07 本机实测 |
| GPU 主模型 | 90.14 t/s decode **理论不变**，待 A/B 证实 | 基线 |
| 能效 | NPU 侧 TPS/W 显著优于同模型 iGPU（社区称 prefill 67× / decode 223×） | OJAI，**[UNVERIFIED]** 数量级过大且非绝对速度，仅作定性 |

**收益性质**：多一个低并发、常驻、不占显存的工人；**主链路速度不提升**。若少爷的期待是「主模型更快」，答案是不会——本机主模型 decode 已顶在 120 W 墙 + 带宽墙上。

### 8.2 代价

| 代价 | 量化 |
|---|---|
| host RAM | flm RSS 6.5 GB；本机 MemAvailable 18.43 GiB 够，但 11-07 曾降到 3.57 GiB（sd-cli + Firefox 满载）→ 需错峰或设限 |
| NPU 侧带宽折损 | GPU busy 时 ~13%（1bit 实测，本机固件未验证） |
| GPU 侧降幅 | **原文未给数字**，必须本机 A/B |
| 120 W 功耗墙 | NPU 满载挤占 shader 功耗预算（同 IOMMU 翻译功耗机制推论，非实测） |
| NPU 并发 | 设备独占，串行排队 `NPU busy, request queued (N/10)` |

### 8.3 ★ 与前面所有引擎方案的交叉约束（决定性）

`amd_iommu=off`（改 BIOS 上 Gufo / Halogen / Strata 大 GTT 的标准项）**会禁用 NPU**（offsite.guru 原文 `takes the NPU with it`）。

→ **「启用 NPU 共存」与「改 BIOS 上大 GTT 引擎」是本机架构上的又一组二选一，不可兼得。**
当前决策「维持 96 GiB UMA + Vulkan 现状」恰好保留 NPU，因此 NPU 共存方案与既有结论**方向一致、无冲突**。

---

## 九、风险清单

1. **固件外推**：1bit 的 160 次 byte-exact 全 PASS 与 0 次 reset 是在 `Kernel 7.3.0-rc4 / SMU 100.7.0 / BIOS 1.09` 上取得；本机 `7.0.0-42-generic` 未核 → 并发安全性须本机复现，不得直接引用。
2. **GPU 负载类型不匹配**：1bit 的 GPU busy 用的是 `weight-streaming pp512`（prefill），不是 decode loop 也不是视频渲染；本机 `sd-cli` 是扩散模型渲染，干扰特征不同。
3. **host RAM 波动**：3.57 ↔ 18.43 GiB 之间，NPU 6.5 GB 在低水位时会触发 swap / OOM（11-07 曾全局 OOM）。
4. **NPU 模型格式**：`q4nx` / `.hnpw` 等专有格式，不能被 llama.cpp 复用；本机 `flm` 白名单模型有限（Gemma3 / Llama3.2 / Qwen3 / GPT-OSS-20B）。
5. **flm 调用三坑**：`FLM_MODEL_PATH` 多一层 `models/`；调用前 `unset ROCM_PATH HIP_PATH LD_LIBRARY_PATH`；`export HF_ENDPOINT=https://hf-mirror.com`。
6. **主模型当前未启动**：8080 未监听，A/B 前须先经面板拉起 35B 实例；`sd-cli` 正在占 37.87 GiB carve-out，需注意显存余量。

---

## 十、数据校验与剔除（怀疑一切）

| 数据 | 校验结果 | 处置 |
|---|---|---|
| `OllamaAMDNPU`：`Vulkan prefill + NPU decode 930 t/s / 43.7 t/s / 41.5 W / 0.947 J/tok` | 项目自有 Phase 7 订正：`43.7 t/s ... was later found to be Vulkan decode`；decode 归属错误 | **剔除**，不作 NPU 性能依据；其「投机解码零收益」的带宽墙结论保留（方法学独立于该误判） |
| aifoss.dev / runaihome 把 `GPT-OSS 120B ~50 t/s`、`Qwen3.5-35B-A3B 55 t/s` 列在 "NPU + GPU Hybrid" 标题下 | 同一批数字在 runaihome 被列为普通 `Community benchmarks`（Vulkan/ROCm），未给 hybrid 与纯 GPU 的对照 | **[UNVERIFIED]**，不作 hybrid 收益证据 |
| Lemonade「NPU prefill + iGPU decode」 | 多篇二手文章一致描述，但 1bit 同芯片一手实测为 `measured loss`、无 real NPU provider | 标为**产品设计意图**，非本机可用能力 |
| OJAI `67× prefill / 223× decode TPS/W` | 能效比（TPS/W）非绝对吞吐；单机自测，数量级异常大 | **[UNVERIFIED]**，仅定性参考 |
| 社区带宽 `256 GB/s 理论 / ~215 GB/s 实测` vs 本机 `≈144 GB/s 有效带宽` | 口径不同（理论 / 峰值实测 / 本机 decode 反推有效值） | **禁止混用**；本报告的争用判定只用「共享同一总线」这一定性事实 + 1bit 的 ~13% 相对折损 |
| `flm list --filter installed` 空 | 可能是 filter 语义、路径未接或模型确已清除，三者未区分 | **[UNVERIFIED]**，列待核第 1 条，不写死结论 |

---

## 十一、待核项

1. `FLM_MODEL_PATH` 实际指向与已装 NPU 模型是否仍在磁盘；若已清除，需重下哪个模型到 `$HOME/models`。
2. 本机固件/SMU 版本，与 1bit 实测的 `7.3.0-rc4 / SMU 100.7.0 / BIOS 1.09` 差异。
3. **「NPU busy 时 GPU 35B-A3B decode 掉多少」——所有来源都未给，必须本机 A/B**（第七节第 5 步）。
4. `sd-cli` 扩散渲染负载下 NPU 并发是否触发 `amdgpu` reset / MODE2（1bit 只测了 pp512 prefill）。
5. 35B 长 prefill 旧记录「308 KB → 26 s」与 89K / 171 s / ≈520 t/s 口径差异（沿用前报告待核）。
6. `amd_iommu` 三臂（off / pt / translated）A/B 与 NPU 可用性对照。
7. Lemonade 11.5 smart router 是否能只作路由、不接管模型管理（若可以，第七节第 3 步可换成官方实现）。

---

## 十二、来源清单

**本机一手（2026-11-08 18:29:34 CST）**
- `/proc/meminfo`、`/sys/class/drm/card1/device/mem_info_{vram,gtt}_{total,used}`、`ss -ltnp`、`ps -eo pid,user,rss,args --sort=-rss`
- `ls -l /dev/accel0`、`lsmod | grep -iE 'amdxdna|xrt|amdgpu'`、`/sys/class/accel/`
- `flm --version`（v0.9.45）、`flm list --filter installed`、`/opt/fastflowlm/share/flm/model_list.json`
- 项目 `MEMORY.md`、`~/.workbuddy/MEMORY.md`、`2026-10-03-35B速度复测.md`、`2026-10-07-NPU-8219-测试与使用手册.md`、`2026-11-07-Halogen与Gufo-本机适配性对比判定.md`

**NPU + GPU 并发一手**
- `https://github.com/1bit-MONSTER/engine/blob/main/docs/hybrid.md`（160 byte-exact、~87% 带宽、~13% 折损、measured loss、1.035× 上限、拒绝 flags、固件限定）
- `https://github.com/1bit-MONSTER/engine`（Apache-2.0 仓库 README：`the NPU and the GPU are measured running at the same time`、私有 NPU runtime / HIP kernels）
- `https://ojitha.github.io/ai/rocm/2026/05/15/MTP-on-OJAI.html`（iGPU/NPU 并行不串行、不争 compute 争 UMA 带宽、FastFlowLM 不支援投机解码、XRT + `/dev/accel0` + amdxdna）
- `https://coryebert.com/OllamaAMDNPU/xdna-npu/phase8.html`、`https://www.openclawradar.com/article/custom-llama-cpp-backend-amd-xdna2-npu-offload-ryzen-ai-max-385`（Phase 7 订正、投机解码零收益、LPDDR5 带宽墙）
- `https://github.com/noamsto/nix-amd-ai/blob/main/docs/halogen-flash-teardown.md`（IOMMU 翻译功耗挤占 shader 预算）

**Lemonade / 生态**
- `https://dev.to/jovan_chan_9500711396d4e6/amd-lemonade-review-2026-gpu-npu-and-multi-modal-3gd9`（v10.6、prefill→NPU / decode→iGPU 设计、Linux 经 FastFlowLM）
- `http://runaihome.com/blog/amd-lemonade-local-llm-server-npu-gpu-guide-2026`（GGUF / FLM / ONNX 格式与 hybrid 门槛）
- `https://www.nilo.io/articles/lemonade-ai-features`（Embedding / Reranking / Transcription / Image 模态，v11.5 smart router）
- `https://infoworld.com/article/4169474/first-look-lemonade-serves-up-local-ai-with-limitations.html`（Linux NPU 只经 FastFlowLM、自动后端选择限制）
- `https://ai-radar.it/article/amd-strix-halo-lnpu-ora-funziona-con-rocm-ibrido-gpu-npu-per-llm-locali?lang=en`（GGUF 不能直转 ONNX）

**硬件资源共享**
- `https://bestllmfor.com/guide/strix-halo-vs-dgx-spark-128gb-comparatif`、`https://spawningpoint.com/article/amd-strix-halo-review-2026-...`、`https://willitrunai.com/gpus/ryzen-ai-max-plus-395-96gb`、`https://mefmobile.org/amd-ryzen-ai-max-395-technical-overview-zen-5-radeon-8060s-and-xdna-2`（同 die 共享 256-bit LPDDR5X、256 GB/s 理论、~215 GB/s 实测、45–120 W TDP）
- `https://modelscope.cn/learn/437077`（医药文献筛查落地：128GB 统一内存、~215 GB/s 实测、45–120 W）

---

> 许可：CC0-1.0，公共领域贡献，无任何限制。
