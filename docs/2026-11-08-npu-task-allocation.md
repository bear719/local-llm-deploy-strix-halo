# 维持 96 GiB UMA + Vulkan + MTP 现状下的 NPU 任务分配推荐方案

> 生成时间：2026-11-08 19:38–20:05 CST
> 状态：**方案已定，未执行任何生产变更**（未改 BIOS、未改内核参数、未改服务、未改进程、未改 `docproxy.py`、未重启 18090）
> 口径：只读实测 + 官方文档 + 社区一手数据；推断项统一标 `[UNVERIFIED]`
> 适用主机：AMD Ryzen AI MAX+ 395 / Radeon 8060S / XDNA2 NPU / 内核 `7.0.0-42-generic`

---

## 0. 一句话结论

**在完全不动现有 96 GiB UMA + Vulkan + MTP 主链路的前提下，给 NPU 分配「任务级旁路杂活」是唯一正收益形态：起一个由 MCSManager 面板托管的 `flm serve` 实例（8219），在 docproxy 18090 上用 `X-Backend: npu` 显式分流，把分类/路由/guard/格式化/摘要/embedding/ASR/视觉预处理从 35B 的 `-np 1` 主 slot 挪走。**

- 主模型 **90.14 t/s 不会变快**（120 W SoC 功耗墙 + ≈144 GB/s 有效带宽，来源：项目 `MEMORY.md` 第四节）。
- 真实收益是**保护主 slot 的 LCP 前缀缓存不被杂活冲掉**，以及释放 8080 的排队。
- 「完全不抢资源」**不成立**：UMA 带宽、120 W 功耗墙、30.47 GiB host RAM 三者共享（来源：`2026-11-08-NPU与GPU共存可行性及收益预测.md` 第五节）。
- 分流由 `NPU_UPSTREAM` 环境变量控制，**不设即完全等于现状**，天然可回滚。

---

## 1. 决策边界

### 1.1 维持（一个字节都不动）

| 项 | 当前值 | 来源 |
|---|---|---|
| BIOS UMA carve-out | 96.00 GiB（`mem_info_vram_total=103079215104`） | 本机 sysfs，19:38 实测 |
| 主引擎 | `$HOME/llama-qwen4exp-rocmfpx/build-vk4/bin/llama-server`（Vulkan） | `ps -eo pid,args`，19:38 |
| 主权重 | `Qwen3.6-35B-A3B-Uncensored-Q5_K_P.gguf` + `MTP-ONLY-Q4_K_M` 草稿 | `ps -eo pid,args`，19:38 |
| MTP / 投机解码 | `--spec-type draft-mtp`，接受率 77.4% | 项目 `MEMORY.md` 第四节 |
| 上游 / 代理 | 8080 真模型、18090 docproxy、23333 MCSManager | `ss -ltnp`，19:38 |
| 应用侧端点 | 一律 18090 | 用户级 `~/.workbuddy/MEMORY.md`（2026-10-14 定策） |
| 托管方式 | 一律 MCSManager 面板，禁止裸跑 | 用户级 `~/.workbuddy/MEMORY.md`（2026-11-04 铁律） |

> 注：19:38 实测主权重是 **Q5_K_P**，不是长期笔记里记的 Q4_K_P；VRAM used 35.38 GiB。这不改变任何结论，仅记录本次状态。

### 1.2 新增（本方案要加的）

1. 一个 MCSManager 面板托管的 `flm serve` 实例，端口 **8219**，`--host 0.0.0.0`。
2. `tools/docproxy.py` 的**可选**分流补丁（12 处精确替换，默认关闭）。
3. 应用层在杂活请求上加 `X-Backend: npu` 头。
4. 一套 A/B 验收与回滚流程。

### 1.3 明确不做

| 不做 | 理由 |
|---|---|
| 同请求 NPU+GPU 协同 / 算子拆分 / NPU 草稿投机 | `1bit-MONSTER/engine/docs/hybrid.md`：`on this box the hybrid row is a measured loss`；NPU 草稿投机 `zero effective gain`；来源 `2026-11-08-NPU与GPU共存可行性及收益预测.md` 第三节 |
| NPU 跑 35B-A3B | 同芯片 decode 8.11–16 t/s = iGPU 的 0.09–0.18×，且本机 host RAM 30.47 GiB 下必 SIGKILL 137（峰值 ≈58.6 GB）；来源 `2026-11-08-Gufo加载27B与35B及NPU单独加载35B-收益预测.md` |
| NPU 跑主对话 / 代码 / 长文 / 多模态主链路 | 质量与上下文（4B NPU2 32768、`max_prefill_len 4096`）都不够 |
| 改 BIOS 到 512 MiB UMA + large GTT | 会摧毁 Vulkan carve-out，且 `amd_iommu=off` 会**禁用 NPU**（`takes the NPU with it`）→ 逻辑自我否定 |
| 引入 Lemonade Server | 内置 llama.cpp 不认本机私有 ROCmFP4 `ggml type 101`；且 Linux NPU 后端本就是已装的 flm，会形成第二套模型管理 |
| 内容自动分类路由（按 prompt 猜） | 误判会把重要请求送进 4B；只接受**显式头**分流 |
| NPU 故障时静默回落到 8080 | 会让杂活突然用 35B 跑，掩盖故障并反过来抢占主 slot；**显式 502/503** |

---

## 2. 本机复核实测（2026-11-08 19:38:42 CST）

| 项 | 读数 | 判定 |
|---|---|---|
| `MemTotal / MemAvailable` | 30.47 GiB / **17.88 GiB** | 足够容纳 flm 4B（历史 RSS 6.5 GB） |
| `SwapTotal / SwapFree` | 16.0 / 12.15 GiB | 有缓冲但不可依赖 |
| VRAM total / used | 96.00 / **32.95 GiB** | 主模型在跑 |
| GTT total / used | 30.47 / **1.98 GiB** | 与 host RAM 同源，见 `MEMORY.md` 第二节 |
| 端口 | 8080 LISTEN、18090 LISTEN、23333 LISTEN、**8219 未监听** | NPU 零占用，可用 |
| 进程 | `llama-server`(root, Q5_K_P+MTP)、`docproxy.py`(root, PID 13256) | 无 flm、无 sd-cli |
| `/dev/accel0` | `crw-rw---- root:render`；`lc` 在 `render` 组 | 权限具备 |
| `amdxdna` | 已加载，refcount **0** | NPU 空闲 |
| `flm validate` | `[Linux] NPU: /dev/accel/accel0 with 8 columns` / `NPU FW Version: 1.1.2.65` / `amdxdna version: 0.7` / `Memlock Limit: infinity` | **NPU 栈健康，可直接起服务** |
| `flm --version` | **v0.9.45** | 满足 `qwen3.5:4b` 的 `flm_min_version 0.9.45` |
| `flm list --filter installed` | `qwen3.5:4b ✅`（注入 `FLM_MODEL_PATH` 后） | 4.7 GB 权重在盘 |
| 已装权重 | `$HOME/.config/flm/models/models/Qwen3.5-4B-NPU2/`：`model.q4nx 4.1G` + `vision_weight.q4nx 637M` + tokenizer/template | **自带视觉能力，零下载可做 OCR/图片描述** |
| 空目录 | `Embedding-Gemma-300M-NPU2/`、`Llama-3.2-1B-NPU2/` 均 4.0K（空壳） | 需 `flm pull` 才能用 embedding |

来源：本机 `/proc/meminfo`、`/sys/class/drm/card1/device/mem_info_*`、`ss -ltnp`、`ps -eo pid,user,rss,args`、`lsmod`、`id`、`flm validate`、`flm --help`、`flm list`、`/opt/fastflowlm/share/flm/model_list.json`。

---

## 3. 为什么是「任务级并存」而不是「同请求协同」

| 形态 | 判定 | 一手依据 |
|---|---|---|
| 同请求协同（hybrid / 算子拆分 / NPU 草稿投机） | **负收益，不做** | `1bit-MONSTER/engine/docs/hybrid.md`：`No real NPU prefill provider exists`、`58.14 s for a 5-token batched chunk on the 27B`、`on this box the hybrid row is a measured loss`；NPU 草稿投机 `44% accept rate, 212 t/s draft, but zero effective gain` |
| **任务级并存（各干各的）** | **可行，本方案采用** | OJAI 逐字：`the iGPU and NPU run in parallel, not in series ... they will not contend for compute. They will contend for UMA bandwidth, which is the real bottleneck.` |
| 完全不抢资源 | **不成立** | 见 §8 |

另有一处需要修正的边界：`mikealanni/gufo` 的分列 offload 确实有 +1~28% prefill 实测（不是 `measured loss`），但它要求**锁 FCLK 2000 MHz 否则整机 hang**、每次 boot 设 XRT pmode、**独占整机** → 不适配本机混合生产机。来源：`2026-11-08-Gufo加载27B与35B及NPU单独加载35B-收益预测.md` 第四节订正 3。

---

## 4. 收益到底在哪：保护主 slot 的 LCP 前缀缓存

这是本方案最核心、也最容易被忽略的一点。

**机制链**（来源：项目 `MEMORY.md` 第三节、`2026-10-03-35B速度复测.md`）：

```
fast 档 -np 1  →  只有 1 个 slot
--cache-idle-slots  →  空闲 slot 保留 KV
同会话 LCP 前缀复用  →  18~202× 加速
冷启动 84K tokens ≈ 149 s   →   同 slot 复用 < 1 s
```

**任何挤进这个 slot 的杂活请求**（automations 摘要、连接器状态整理、memory 压缩、其他 agent 的分类调用），只要前缀不同，就会：

1. 触发一次全新的 prefill；
2. 覆盖 / 逐出主会话的 KV 前缀；
3. 使主会话下一轮从「< 1 s」退化到「≈ 149 s」冷启动。

**量级估算**（`[UNVERIFIED]`，机制推断，需 A/B）：

- 单次杂活成本：约 2K tokens prefill @ ≈520 t/s ≈ **3.8 s** + 少量 decode。
- 若打断一次主会话 LCP：损失约 **148 s**。
- 即使只有 10% 概率打断，期望损失 ≈ **14.8 s / 次杂活**。
- 把杂活挪到 8219，主 slot 不再被污染 → **这部分损失直接归零**。

**结论**：NPU 的价值不是「多一个 12.4 t/s 的工人」，而是**让 90.14 t/s 的主工人不被打断**。衡量收益的指标应当是「主会话 TTFT / 首字延迟的稳定性」和「8080 排队长度」，不是「总 t/s 相加」。

`docproxy` 已有的 `X-Trim-Prompt` 头（connectors / automations / memory / all，分别省 ~56% / ~81%）与分流是互补关系：前者减少单请求的 prompt 体量，后者减少请求数量本身。

---

## 5. NPU 能力清单（本次核实，纠正旧认知）

### 5.1 官方支持的 OpenAI 端点

来源：`https://fastflowlm.com/docs/instructions/server/openapi/`、`https://deepwiki.com/FastFlowLM/FastFlowLM/4.1-openai-api-compatibility`

| 端点 | 用途 |
|---|---|
| `GET /v1/models` | 列出本地模型 |
| `POST /v1/chat/completions` | 多轮对话、VLM（content 数组内 `image_url` base64）、流式 SSE |
| `POST /v1/completions` | 旧式补全 |
| `POST /v1/embeddings` | 向量化 |
| `POST /v1/audio/transcriptions` | Whisper ASR（multipart） |
| `/v1/systemone` 或 `/v1/decisions` | System One 快速决策/分类（**本机 v0.9.45 是否支持 [UNVERIFIED]**） |
| `/api/*` | Ollama 兼容端点 |

### 5.2 启动参数（`flm --help` 本机实测）

```
--host (默认 127.0.0.1)     -p/--port (默认 52625，本机用 8219)
--pmode powersaver|balanced|performance|turbo (默认 performance)
-a/--asr 0|1|<tag>          -e/--embed 0|1|<tag>
-c/--ctx-len                 --prefill-chunk-len
-s/--socket (默认 10)        -q/--q-len (默认 10)
--preemption 0|1             --cors 0|1
```

- 官方文档：`flm serve gemma3:4b --embed embed-gemma:300m` 可同时挂 LLM + embedding；`flm serve -e embed-gemma:300m` 可独立跑 embedding；`flm serve --asr 1` 可独立跑 ASR。
- `--embed` / `--asr` 的 `1` = 选默认模型，也可直接给 tag；**给错类型会直接报错退出**。来源：`https://fastflowlm.com/docs/models/embeddinggemma/`、`http://fastflowlm.com/docs/models/whisper`。
- 官方 README：`The model tag sets the initial model, which is optional. If another model is requested, FastFlowLM will automatically switch to it.` → **按 `model` 字段自动热切换**。代价是首次切换要重新载入权重，且 DeepWiki 明确 `NPUAccessManager` 全局互斥、**一次一个请求**。
  → 因此本方案**固定初始模型 tag，不依赖自动切换**。
- 默认端口是 `52625`（`flm port` 实测），不是 8219；8219 是本机自定义。
- 官方 README 注明 2026-08-11 项目已归入 AMD ROCm 组织并发布 v1.0.0；本机 v0.9.45 属旧版，端点以本机 `--help` + 官方文档交叉确认。

### 5.3 模型清单（本机 `model_list.json`，27 族）

| tag | footprint | 关键字段 | 本机状态 |
|---|---:|---|---|
| `qwen3.5:4b` | 4.7 GB | `vlm=true`、`think=true`、ctx 32768、`max_prefill_len 4096`、label `vision/reasoning/tool-calling` | **已装** ✅ |
| `qwen3.5:2b` | 3.2 GB | vlm、tool-calling | 未装 |
| `qwen3.5:0.8b` | 1.4 GB | vlm、reasoning | 未装 |
| `embed-gemma:300m` | **0.62 GB** | label `embeddings`、Q4_1、ctx 2048 | 目录空壳，需 pull |
| `whisper-v3:turbo` | **0.62 GB** | `asr=true`、label `audio/transcription` | 需 pull |
| `qwen3vl-it:4b` | 3.9 GB | VLM、`think=false`、tool-calling | 未装 |
| `translategemma:4b` | 4.5 GB | 翻译、vlm、ctx 65536 | 未装 |
| `medgemma1.5:4b` | 4.5 GB | 医疗 VLM | 未装（少爷专业方向可选） |
| `lfm2.5-tk:1.2b` | 0.96 GB | 纯 reasoning | 未装 |
| `qwen3.6-moe:35b-a3b` | 24.3 GB | MoE、Q4_K_S | **不用**（见 §1.3） |

**NPU2 4B 性能基线**（项目 `MEMORY.md` 第六节、`2026-10-07-NPU-8219-测试与使用手册.md`）：TTFT 1.19 s / decode 12.4 t/s / prefill 24.7 t/s / RSS 6.5 GB / **< 2 W** / **不占 iGPU 显存**。

### 5.4 flm 特有指标（可直接用于验收）

`tools/test-npu.py` 已验证 flm 在 `usage` 中上报：`decoding_speed_tps`、`prefill_duration_ttft`、`prefill_speed_tps`、`kv_token_occupancy_rate_percentage`。iGPU 侧用 `timings.predicted_per_second`（`tools/bench-35b-20261003.py`）。

---

## 6. 任务选型与优先级

打分维度：是否**低并发 / 短输出 / 不需 35B 质量 / 不占主 slot / 不要求长上下文**。

| 优先级 | 任务 | 端点 | 权重/下载 | 分流键 | 说明 |
|---|---|---|---|---|---|
| **P0** | 意图识别、路由判定、guard/合规初筛、结构化 JSON 抽取、字段格式化、标题与一句话摘要、query 改写 | `/v1/chat/completions` | `qwen3.5:4b` 已装 | `X-Backend: npu` | **零下载、今天可验证**；输出短，NPU 12.4 t/s 完全够 |
| **P0** | 后台批处理：automations 结果整理、memory 压缩、日志归类、定时任务文案 | `/v1/chat/completions` | 同上 | `X-Backend: npu` | 低价值且高频，是抢占主 slot 的主要来源；允许排队 |
| **P0** | 图片 OCR / 图片描述 / 简单视觉问答 | `/v1/chat/completions` + `image_url` | `vision_weight.q4nx` **637 MB 已在盘** | `X-Backend: npu` | `qwen3.5:4b` 的 `vlm=true`，零下载；注意 `max_prefill_len 4096` |
| **P1** | embeddings：RAG 向量化、去重、语义检索、文档聚类 | `/v1/embeddings` | `embed-gemma:300m` **0.62 GB** | `X-Backend: npu` 或 `NPU_SIDECAR=1` 自动 | 300M / Q4_1 / chunk 2048；不占 iGPU 显存，是本方案性价比最高的一项 |
| **P1** | ASR：语音转写、会议/查房录音转文字 | `/v1/audio/transcriptions` | `whisper-v3:turbo` **0.62 GB** | `X-Backend: npu` | **需 docproxy 补丁支持 multipart**（已含在补丁中）；Whisper 完全跑在 NPU |
| **P2** | 中英翻译 | `/v1/chat/completions` | `translategemma:4b` 4.5 GB | `X-Backend: npu` | 需额外下载与换模，收益不确定 |
| **P2** | 医疗图文初筛 | `/v1/chat/completions` | `medgemma1.5:4b` 4.5 GB | `X-Backend: npu` | 与少爷专业方向相关，但需单独评估准确性 |
| — | 主对话 / 代码 / 长文 / 复杂推理 / 35B 多模态主链路 | — | — | **默认走 8080** | 一律不分流 |

**推荐组合（第一阶段）**：只上 P0 三项 + `qwen3.5:4b`，**零下载、零 BIOS 改动、零生产重启即可在 18091 验证**。P1 的 embedding / ASR 待 A/B 通过后再 `flm pull`（合计仅 1.24 GB）。

---

## 7. 架构与分流设计

### 7.1 链路

```
应用 / WorkBuddy / automations
        │  http://127.0.0.1:18090  （应用侧端点不变）
        ▼
  docproxy-18090（MCSManager 托管，passthrough）
        │
        ├─ 默认（无标记） ──────────────► 8080  llama-server / Vulkan / 35B-A3B + MTP
        │                                  carve-out 96 GiB
        │
        └─ X-Backend: npu ─────────────► 8219  flm serve / XDNA2 NPU
           或 model ∈ NPU 别名集                host RAM 30.47 GiB
           或 (NPU_SIDECAR=1 且 /v1/embeddings、/v1/audio/*)
```

### 7.2 分流规则（唯一、显式、不做内容猜测）

1. `NPU_UPSTREAM` 为空 → **所有请求走 8080**，代码路径与补丁前完全一致。
2. `X-Backend: npu` → 走 8219（推荐，最明确）。
3. `body.model` 在 `NPU_MODEL_ALIASES` → 走 8219。
4. `NPU_SIDECAR=1` 且路径为 `/v1/embeddings` 或 `/v1/audio/*` → 走 8219。
5. 走 NPU 时，若 `body.model` 不是合法 NPU tag，**自动改写为 `NPU_MODEL_TAG`**（默认 `qwen3.5:4b`），避免 flm 收到 35B 别名后触发一次昂贵换模或直接报错。
6. 走 NPU 时**跳过 `chat_template_kwargs.enable_thinking=false` 注入**（该字段是 llama.cpp 特有，flm 官方文档未列；flm 自带 `<think>` 分离）。
7. 走 NPU 时**强制 passthrough**（跳过 disclosure 工具循环）。
8. 内存水位线不足 → **503 显式拒绝，不回落**（见 §8.2）。
9. 8219 不可达 → `forward_to_upstream` 已有统一 `502 upstream unreachable`，不改。

### 7.3 环境变量（全部可选，默认关闭）

| 变量 | 默认 | 作用 |
|---|---|---|
| `NPU_UPSTREAM` | **空** | 设为 `http://127.0.0.1:8219` 启用分流；清空即回滚 |
| `NPU_MODEL_TAG` | `qwen3.5:4b` | model 字段改写目标 |
| `NPU_MODEL_ALIASES` | `qwen3.5:4b,qwen3.5:2b,qwen3.5:0.8b,embed-gemma:300m,whisper-v3:turbo` | 按 model 自动分流的白名单 |
| `NPU_SIDECAR` | `0` | 置 `1` 才让 embeddings/audio 自动分流 |
| `NPU_MIN_MEMAVAIL_MIB` | `4096` | host RAM 水位线，低于则拒绝分流 |

### 7.4 为什么补丁必须改 `forward_to_upstream`

现状 `forward_to_upstream()` 把 `UPSTREAM` 写死在 `urlparse()` 里，且 `Content-Type` 硬编码 `application/json`（`tools/docproxy.py:405,415`）。分流需要：

- 增加 `base_url=None` 参数（`base_url or UPSTREAM`）——1 行；
- 增加 `content_type=None` 参数——1 行，用于把 multipart 的 `boundary` 原样带给 `/v1/audio/transcriptions`；
- **保留**现有 chunked 上传解码、SSE `select` 心跳、`STREAM_READ_TIMEOUT=600`、非 2xx 原样回传等所有既有修复（项目 `MEMORY.md` 第八节），不动其逻辑。

---

## 8. 资源共享边界与防护

### 8.1 隔离 vs 共享

| 隔离（不抢） | 共享（会抢） |
|---|---|
| 计算单元：`/dev/accel/accel0` + `amdxdna` vs `/dev/kfd` + `amdgpu` | **UMA 带宽**：256-bit LPDDR5X，理论 256 / 社区实测 ~215 GB/s，本机有效 ≈144 GB/s |
| carve-out 显存：NPU 不占 96 GiB VRAM | **120 W SoC 功耗墙**：`amdgpu_pm_info` 平均=瞬时=120.01 W |
| 进程地址空间、模型权重 | **host RAM 30.47 GiB**（flm 4B RSS 6.5 GB 从这里出） |

唯一量化的争用代价（`1bit-MONSTER` 同芯片 4 cell × 2 pass）：GPU busy 时 NPU stream 保留 **~87% 带宽**（7.40 vs 8.2–8.5 GB/s，约 −13%），`160 byte-exact all PASS`、`zero reset/MODE2`。**但该固件限定 `Kernel 7.3.0-rc4 / SMU 100.7.0 / BIOS 1.09`，本机 `7.0.0-42 / FW 1.1.2.65` 不同 → `[UNVERIFIED]`；且原文未给「NPU busy 时 GPU decode 掉多少」，这正是 §11 的 A/B 要测的。**

### 8.2 四道防护

1. **内存水位线**：`MemAvailable < 4096 MiB` 时分流返回 503。依据：2026-10-08 实测 HIP 分配 20 GiB 时 host avail 仅 494 M → 全局 OOM（项目 `MEMORY.md` 第二节）；11-07 03:43 曾降到 3.57 GiB，11-08 19:38 为 17.88 GiB，波动极大，必须有动态闸门。
2. **功耗档位**：`--pmode balanced`（而非默认 `performance`），把 NPU 功耗预算让给 iGPU。是否真有收益需 A/B，`[UNVERIFIED]`。
3. **并发闸门**：`-q 4 -s 8`（默认 10/10）。NPU 是全局互斥串行资源，队列过长只会堆积内存、拉长尾延迟，不会提高吞吐。
4. **不自动回落**（见 §1.3）。

### 8.3 交叉约束（务必记住）

`amd_iommu=off`（改 BIOS 上大 GTT 引擎的标准项）**会禁用 NPU**。本方案维持 96 GiB UMA，恰好同时保住 Vulkan 主链路与 NPU。换句话说：**「启用 NPU 共存」与「改 BIOS 上 Gufo/Halogen/Strata」二选一**，本方案选前者，与前面所有报告的结论一致。来源：offsite.guru `amd_iommu=off ... takes the NPU with it`。

---

## 9. 分阶段实施步骤

> **变更留痕**：以下阶段 1–5 均为**状态变更操作**，本次会话只完成阶段 0。执行前需少爷明确授权。

### 阶段 0（本次已完成，零变更）

只读复核 + 方案 + 配套文件落盘。未动 BIOS、内核、服务、进程、`docproxy.py`、`start-docproxy.sh`、MCSManager 配置。

### 阶段 1：面板新建 NPU 实例，起 8219（不碰 18090）

1. `flm validate` 已通过（本次实测），无需驱动操作。
2. 处理 `flm` 三坑（项目 `MEMORY.md` 第六节）：`unset ROCM_PATH HIP_PATH LD_LIBRARY_PATH`、`HF_ENDPOINT=https://hf-mirror.com`、`FLM_MODEL_PATH=$HOME/.config/flm/models`（其下多一层 `models/`）。
3. MCSManager 面板新建「通用实例」，配置照抄 `docproxy-18090` 的结构（本次读取 `/opt/mcsmanager/daemon/data/InstanceConfig/d81ea6096b1c46709f9d9b43fc8137f7.json`）：
   - `nickname`: `flm-npu-8219`
   - `startCommand`: `env $HOME/WorkBuddy/调试本地模型/start-flm-npu.sh`
   - `stopCommand`: `^c`；`type`: `universal`；`processType`: `general`；`ie/oe`: `utf8`
   - `basePort`: `8219`；`eventTask.autoStart`: `true`、`autoRestart`: `true`
   - **必须前台 `exec`**，不能后台化（面板靠前台主进程判存活）。
4. 自检：`curl -s http://127.0.0.1:8219/v1/models`、`python3 tools/test-npu.py health`、`python3 tools/test-npu.py bench`。

### 阶段 2：18091 隔离验证分流（不碰生产 18090）

1. 备份：`cp -p tools/docproxy.py tools/docproxy.py.bak.20261108-npu`。
2. `python3 tools/apply-npu-route.py --dry-run` 查看将改的 12 处；确认后 `--apply`。
3. 用**独立进程**在 18091 起验证代理（仅验证用，验完即停）：
   ```
   NPU_UPSTREAM=http://127.0.0.1:8219 \
   python3 tools/docproxy.py serve --port 18091 --upstream http://127.0.0.1:8080
   ```
   > 18091 是临时验证实例，不是长期服务；验收后关闭，不留在面板。
4. `python3 tools/verify-npu-route.py --proxy 18091 route` 跑 4 条分流用例：默认走 GPU、显式头走 NPU、主模型别名被正确改写、embeddings（若已启用 sidecar）。

### 阶段 3：A/B 验收

`python3 tools/verify-npu-route.py --proxy 18091 ab`：GPU 单独 3 次 vs NPU 持续加压时 GPU 3 次，采 `timings.predicted_per_second`、`MemAvailable`、功耗、sclk。判定门槛见 §11。

### 阶段 4：授权后应用到生产 18090

1. 用 MCSManager 面板（或等价 API，历史用户明确选择「面板手动重启」）重启 `docproxy-18090` 实例 uuid `d81ea6096b1c46709f9d9b43fc8137f7`，并在 `startCommand` 前注入 `NPU_UPSTREAM=http://127.0.0.1:8219`。
2. 验证 `curl -s http://127.0.0.1:18090/health` 返回 `npu_enabled: true`。
3. **注意**：当前会话本身很可能走 18090 → 8080，重启会短暂中断链路；应避开正在进行的长任务。

### 阶段 5：应用层接入

在杂活调用侧加 `X-Backend: npu` 头，或把 `model` 设为 `qwen3.5:4b`。优先改造 automations、memory 压缩、日志归类、图片 OCR 这几类高频低价值调用。

### 模型下载目录约定

少爷永久约定「所有模型下载一律到 `$HOME/models`」。flm 硬性要求权重放在 `FLM_MODEL_PATH` 下且多一层 `models/`。P1 拉新模型前建议：

```
mkdir -p $HOME/models/flm/models
ln -s $HOME/.config/flm/models/models/Qwen3.5-4B-NPU2 \
      $HOME/models/flm/models/Qwen3.5-4B-NPU2      # 复用已装 4.7 GB
export FLM_MODEL_PATH=$HOME/models/flm
flm pull embed-gemma:300m
flm pull whisper-v3:turbo
```

符号链接能否被 flm 正确识别 **需阶段 1 验证** `[UNVERIFIED]`；若不行，直接 `mv` 4.7 GB 目录（同盘，秒级）。

---

## 10. 配套文件

| 文件 | 用途 | 是否改动生产 |
|---|---|---|
| `start-flm-npu.sh` | 面板托管启动脚本，处理三坑 + 前台 `exec` + 端口/模型预检 | 新建，不自动生效 |
| `tools/apply-npu-route.py` | docproxy 分流补丁（12 处精确替换），支持 `--dry-run` / `--apply` / `--revert`，自动备份 | **未执行** |
| `tools/verify-npu-route.py` | 分流用例验证 + GPU/NPU 并发 A/B 验收 | 新建，不自动生效 |
| `tools/test-npu.py`（已有） | flm 8219 健康/吞吐/并发基线，直接复用 | 未改 |

`apply-npu-route.py` 的 12 处替换全部是**增量、带默认值**的改动；任一 `old_string` 不唯一或不匹配即中止，不会写出半截文件。

**本次已做的只读验证**（未写 `docproxy.py`）：

```
$ python3 tools/apply-npu-route.py --check
  ① ~ ⑫ 全部「匹配 1 处 OK」，[OK] 共 12 处替换点

$ 生成补丁后代码到临时文件并 py_compile
  [OK] 打补丁后的 docproxy 语法检查通过
  [OK] 补丁前后行数: 707 -> 789

$ bash -n start-flm-npu.sh            [OK]
$ python3 -m py_compile apply/verify  [OK]
$ --dry-run 输出 175 行 unified diff，未写文件
```

三个配套脚本均已设可执行位。`--apply` / `--revert` 本次**未执行**。

---

## 11. 验收 A/B 与判定门槛

### 11.1 测法

- **GPU decode**：`POST /v1/chat/completions`，`max_tokens=256`，prompt 带**随机 uuid 前缀**（规避 `--cache-idle-slots` 的 LCP 复用导致秒回），取 `timings.predicted_per_second`；各 3 次取中位。来源：`tools/bench-35b-20261003.py`。
- **NPU 加压**：并发 2 路持续打 `qwen3.5:4b` 的 400-token 生成，覆盖整轮 GPU 测量窗口。
- **并发采集**：`MemAvailable`（`/proc/meminfo`）、`amdgpu_pm_info` 功耗、`pp_dpm_sclk`、NPU `usage.decoding_speed_tps`、8219 是否 502、`dmesg` 是否有 reset/MODE2。

### 11.2 门槛（全部满足才进阶段 4）

| 指标 | 门槛 |
|---|---|
| GPU decode 降幅 | **≤ 3%**（相对基线 90.14 t/s，即 ≥ 87.4 t/s） |
| `MemAvailable` 全程 | **≥ 4 GiB** |
| GPU reset / MODE2 | **0** |
| 8219 502 / 排队超时 | **0**（`-q 4` 下允许正常排队，不允许报错） |
| 主会话 TTFT 稳定性 | 无明显退化（长会话复用仍 < 1 s）`[UNVERIFIED]` 需专门观测 |
| 18090 `/health` | `npu_enabled: true`，未分流请求行为与补丁前一致 |

### 11.3 若超标的处置顺序

1. `--pmode powersaver` 或降 `-q` 到 2；
2. 提高 `NPU_MIN_MEMAVAIL_MIB` 到 6144；
3. 只保留 P0 的分类/格式化类极小请求，去掉 OCR；
4. 仍不达标 → `NPU_UPSTREAM` 置空回滚，判定「本机 UMA 带宽/功耗墙下并存不成立」。

---

## 12. 回滚方案（三层，均不需要改 BIOS）

| 层级 | 操作 | 耗时 |
|---|---|---|
| L1 逻辑回滚 | 面板 `startCommand` 去掉 `NPU_UPSTREAM` 并重启 18090；或 `export NPU_UPSTREAM=` | 秒级，分流全消失 |
| L2 代码回滚 | `python3 tools/apply-npu-route.py --revert`（从 `.bak.20261108-npu` 恢复） | 秒级 |
| L3 服务回滚 | 面板停止 `flm-npu-8219` 实例；`amdxdna` refcount 归 0 | 秒级 |

任何一层都不影响 8080 `llama-server` 与 96 GiB carve-out。`start-flm-npu.sh` 与两个 tools 脚本均为新增文件，删除即可完全复原。

---

## 13. 风险与 `[UNVERIFIED]` 清单

| 项 | 状态 | 处置 |
|---|---|---|
| 本机固件/SMU 与 1bit 实测平台不同（`7.0.0-42` / `FW 1.1.2.65` vs `7.3.0-rc4` / `SMU 100.7.0`） | `[UNVERIFIED]` | 不引用其 ~13% 数字做决策，以本机 A/B 为准 |
| **「NPU busy 时 GPU decode 掉多少」所有来源均未给** | `[UNVERIFIED]` | §11 A/B 的核心待测项 |
| `--embed` / `--asr` 在 v0.9.45 Linux 上同时挂载是否稳定、RAM 实际增量 | `[UNVERIFIED]` | 阶段 1 单挂验证，逐个加 |
| flm 对 `chat_template_kwargs` 未知字段的容忍度 | `[UNVERIFIED]` | 补丁已对 NPU 请求跳过注入 |
| `model` 字段自动改写是否影响客户端解析响应 | `[UNVERIFIED]` | 阶段 2 用例 3 验证 |
| `/v1/systemone` 决策端点在 v0.9.45 是否可用 | `[UNVERIFIED]` | 不用，P0 全走 chat/completions |
| 符号链接模型目录能否被 flm 识别 | `[UNVERIFIED]` | 阶段 1 验证，失败改 `mv` |
| 主 slot LCP 被杂活打断的 148 s 损失 | 机制推断 `[UNVERIFIED]` | 需专门的长会话 A/B 观测 |
| `--pmode balanced` 是否真给 iGPU 让出功耗预算 | `[UNVERIFIED]` | A/B 采 `amdgpu_pm_info` |
| GTT 与 host RAM 同源，flm 的 6.5 GB RSS 会不会抬 GTT used | 已知共享 | 阶段 3 一并采 `mem_info_gtt_used` |

---

## 14. 来源清单

**本机实测（2026-11-08 19:38–19:45 CST）**
`/proc/meminfo`、`/sys/class/drm/card1/device/mem_info_{vram,gtt}_{total,used}`、`ss -ltnp`、`ps -eo pid,user,rss,args`、`lsmod`、`id`、`/dev/accel0`、`flm validate`、`flm --version`、`flm --help`、`flm port`、`flm list --filter installed`、`/opt/fastflowlm/share/flm/model_list.json`、`/opt/mcsmanager/daemon/data/InstanceConfig/d81ea6096b1c46709f9d9b43fc8137f7.json`

**项目内**
`tools/docproxy.py`（第 44–76、392–485、515–555、557–664 行）、`start-docproxy.sh`、`tools/test-npu.py`、`tools/bench-35b-20261003.py`、`tools/mcsm-api.py`、`.workbuddy/memory/MEMORY.md`、`2026-10-07-NPU-8219-测试与使用手册.md`、`2026-11-08-NPU与GPU共存可行性及收益预测.md`、`2026-11-08-Gufo加载27B与35B及NPU单独加载35B-收益预测.md`、`2026-11-07-Halogen与Gufo-本机适配性对比判定.md`

**外部一手**
`https://fastflowlm.com/docs/instructions/server/openapi/`、`https://fastflowlm.com/docs/models/embeddinggemma/`、`http://fastflowlm.com/docs/models/whisper`、`https://deepwiki.com/FastFlowLM/FastFlowLM/4.1-openai-api-compatibility`、`https://deepwiki.com/FastFlowLM/FastFlowLM/4-api-reference`、`https://raw.githubusercontent.com/FastFlowLM/FastFlowLM/main/README.md`、`https://raw.githubusercontent.com/1bit-MONSTER/engine/main/docs/hybrid.md`、offsite.guru `halogen-strix-halo`、halobench `clm-0013`

---

## 15. 待办

1. 少爷授权后执行阶段 1（面板新建 8219 实例）。
2. 阶段 2 前先 `cp -p` 备份 `docproxy.py`，`--dry-run` 查看补丁。
3. 补做「NPU busy 时 GPU decode 掉多少」本机 A/B（所有外部来源均缺此数字）。
4. 补做「杂活打断主 slot LCP」的长会话 A/B，验证 §4 的 148 s 推断。
5. 核对本机固件/SMU 版本，判断能否引用 1bit 的 ~13% 带宽折损数据。
6. P1 拉 `embed-gemma:300m` / `whisper-v3:turbo` 前先落地 `$HOME/models/flm` 目录约定。

---

> 许可：CC0-1.0，公共领域贡献，无任何限制。
