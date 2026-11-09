# NPU 旁路模型选型：`qwen3.5:4b` 是否最优，还有哪些推荐

- 日期：2026-11-08
- 场景：**维持 96 GiB UMA + Vulkan + MTP 不变**，NPU 作为「任务级旁路工人」挂 8219
- 上游方案：`2026-11-08-维持现状下的NPU任务分配推荐方案.md`
- 本次性质：**只读实测 + 官方文档核对 + 选型判定**。未改动任何生产文件、服务、进程、BIOS 或内核参数

---

## 一、结论

**`qwen3.5:4b` 不是最优。按本方案的收益口径，它甚至不是合适的默认值。**

它是「本机唯一已装、能力最全」的默认，但在旁路任务真正看重的四项指标上全面落后：短请求延迟、常驻内存、输出干净度、切换成本。

| 判定维度 | `qwen3.5:4b` | 推荐替代 | 差距 |
|---|---|---|---|
| decode @1k（官方） | 15.9 t/s | `lfm2.5-it:1.2b` 62 t/s / `qwen3.5:0.8b` 44.83 t/s | 慢 **2.8–3.9×** |
| decode @32k（官方） | 9.98 t/s | `lfm2.5-it:1.2b` 46 t/s / `qwen3.5:0.8b` 22.8 t/s | 慢 **2.3–4.6×** |
| prefill @8k（官方） | 599.95 t/s | 2677 / 2007.97 t/s | 慢 **3.3–4.5×** |
| 720p 图片 TTFT | 3.4 s | `qwen3.5:0.8b` 1.3 s | 慢 **2.6×** |
| 常驻 footprint | 5.2 GiB | 0.96 / 1.4 GiB | 多占 **3.7–5.4×** |
| 下载体积 | 4.64 GiB | 0.94 / 1.23 GiB | 多下 **3.8–4.9×** |
| 思考链 | `think=true`，清单无 `think_toggleable` | LFM2 `think=false` 且不可开 | 旁路任务被迫多吐 token |
| 默认 `presence_penalty` | **1.5**（`qwen3.5:*` 全族） | LFM2 = 0 | 结构化输出有畸变风险 |

来源：FastFlowLM 官方 `docs/benchmarks/qwen3.5_results/`、`qwen3_results/`、`lfm2_results/`、`gemma4_results/`；本机 `/opt/fastflowlm/share/flm/model_list.json`；hf-mirror 模型 API。

**分层推荐（详见第七节）**

| 层级 | 模型 | 用途 |
|---|---|---|
| **P0 默认（换）** | `lfm2.5-it:1.2b` | 分类 / 路由 / JSON 抽取 / 格式化 / guard / query 改写 / 日志归类 |
| **P0 视觉（加）** | `qwen3.5:0.8b` | 图片 OCR / 描述 / 截图理解 |
| **P1 专用端点（常驻）** | `embed-gemma:300m` + `whisper-v3:turbo` | embeddings / ASR，与主 chat 并发加载，不换模 |
| **质量兜底（保留）** | `qwen3.5:4b` | 复杂推理 / 长摘要 / tool calling，已装零下载 |
| **场景专用（可选）** | `medgemma1.5:4b` / `translategemma:4b` / `gemma4-it:e2b` | 医疗图文 / 翻译 / 音视频一体 |
| **中期（升级 FLM 后）** | `qwen3.5-flash:2b` / `qwen3vl-flash:4b` / `hy-mt2-flash:1.8b` | 官方为旁路短任务专设的 Flash 模型 |

**换模型不需要改脚本**：`start-flm-npu.sh` 已把 `MODEL_TAG` 参数化，面板 `startCommand` 加 `env MODEL_TAG=lfm2.5-it:1.2b EMBED=1 ASR=1 ...` 即可。

---

## 二、判定口径：收益不是「多一个工人」

沿用上游方案的结论，本方案的真实收益是**保护 8080 的 `-np 1` 主 slot 的 LCP 前缀缓存**：

- 项目 `.workbuddy/memory/MEMORY.md` 第三节：同会话 LCP 前缀复用 **18–202×**，冷启动 84K ≈149 s → 复用后 <1 s。
- 任何前缀不同的杂活挤进同一 slot 都会逐出这段 KV，使主会话退回冷启动。
- **主模型 90.14 t/s 不会变快**；NPU 已顶在 XDNA2 带宽墙，多一个工人只是「杂活不再抢主 slot」。

因此选型权重依次为：

1. **单请求端到端延迟**（短 prompt + 短输出，杂活典型形态）
2. **常驻内存**（host RAM 30.47 GiB 是全机共享池，不是 NPU 独占）
3. **输出确定性**（不带思考链、不畸变 JSON、采样参数不粘滞）
4. **模型切换成本**（`NPUAccessManager` 全局互斥 + `switch_model` 卸载重载）
5. 最后才是**质量上限**

`qwen3.5:4b` 只赢第 5 项。

---

## 三、本机事实（20:0x 只读复核）

| 项 | 读数 | 来源 |
|---|---|---|
| flm 版本 | **v0.9.45** | `flm version` |
| 模型清单 | **27 族 / 37 变体** | `/opt/fastflowlm/share/flm/model_list.json` |
| 已装 | 仅 `qwen3.5:4b ✅` 4.7 GB | `flm list --filter installed`（需注入 `FLM_MODEL_PATH`） |
| 空目录 | `Embedding-Gemma-300M-NPU2`、`Llama-3.2-1B-NPU2` 各 4.0K（曾尝试未下成） | `du -sh` |
| NPU 栈 | `flm validate` 通过（FW 1.1.2.65 / amdxdna 0.7 / 8 columns） | 上游方案 19:38 实测 |
| host RAM | `MemTotal 30.47 GiB` / `MemAvailable 16.49 GiB` | `/proc/meminfo` |
| 磁盘 | `/` 239 G 可用、`/data` 630 G 可用 | `df -h` |
| 端口 | 8080 ✅ / 18090 ✅ / **8219 未监听** | `ss -ltn` |
| 二进制符号 | 有 `think`(73)、`enable_thinking`(2)、`reasoning_effort`(3)、`presence_penalty`(5)、`NPUAccessManager`(7)、`switch_model`；**无** `chat_template_kwargs`、`prefix_cache`、`cached_tokens` | `strings /opt/fastflowlm/bin/flm` |

`flm serve --help` 关键参数：`--asr/-a`、`--embed/-e`、`--host`（默认 127.0.0.1）、`-p/--port`、`--pmode`（默认 performance）、`--ctx-len`、`--prefill-chunk-len`、`-q/--q-len`（默认 10）、`-s/--socket`（默认 10）、`-r/--img-pre-resize`。

---

## 四、全量候选清单（27 族 / 37 变体，按常驻内存升序）

`foot` = NPU 运行时 footprint（GiB）；`ctx` = 默认上下文；`下载` = hf-mirror 文件总和（GiB）。

| tag | 参数 | foot | ctx | VLM | ASR | think | 标签 | 下载 |
|---|---:|---:|---:|:---:|:---:|:---:|---|---:|
| `embed-gemma:300m` | 300M | **0.62** | 2048 | – | – | false | embeddings | 0.61 |
| `whisper-v3:turbo` | 1B | **0.62** | 448 | – | ✅ | false | audio,transcription | 0.61 |
| `qwen3:0.6b` | 0.6B | 0.66 | 32768 | – | – | 可切换 | reasoning | 0.65 |
| `lfm2:1.2b` / `lfm2.5-it:1.2b` | 1.2B | **0.96** | 32768 | – | – | **false** | 无思考链 | 0.94 |
| `lfm2.5-tk:1.2b` | 1.2B | 0.96 | 32768 | – | – | 不可关 | reasoning | – |
| `gemma3:1b` | 1B | 1.2 | 32768 | – | – | false | – | – |
| `llama3.2:1b` | 1B | 1.3 | 131072 | – | – | false | – | – |
| **`qwen3.5:0.8b`** | 0.8B | **1.4** | 32768 | ✅ | – | true | vision,reasoning | **1.23** |
| `qwen3:1.7b` | 1.7B | 1.6 | 32768 | – | – | 可切换 | reasoning | – |
| `lfm2:2.6b` / `lfm2-trans:2.6b` | 2.6B | 1.8 | 32768 | – | – | false | – | – |
| `qwen2.5-it:3b` | 3B | 2.5 | 32768 | – | – | true | – | – |
| `llama3.2:3b` | 3B | 2.7 | 65536 | – | – | false | – | – |
| `nanbeige4.1:3b` | 3B | 3.1 | 8192 | – | – | false | reasoning | – |
| `qwen3:4b` / `qwen3-it:4b` / `qwen3-tk:4b` | 4B | 3.1 | 32768 | – | – | 可切 / false / 不可关 | tool-calling 等 | – |
| **`qwen3.5:2b`** | 2B | **3.2** | 32768 | ✅ | – | true | vision,reasoning,tool-calling | 2.91 |
| `phi4-mini-it:4b` | 4B | 3.4 | 32768 | – | – | false | – | – |
| `qwen2.5vl-it:3b` | 3B | 3.8 | 32768 | ✅ | – | true | vision | – |
| `qwen3vl-it:4b` | 4B | 3.9 | 32768 | ✅ | – | false | vision,tool-calling | 3.85 |
| `gemma3:4b` / `translategemma:4b` / `medgemma:4b` / `medgemma1.5:4b` | 4B | 4.5 | 65536 | ✅ | – | false | vision | 4.45 |
| **`qwen3.5:4b`（当前）** | 4B | **5.2** | 32768 | ✅ | – | true | vision,reasoning,tool-calling | 4.64 |
| `llama3.1:8b` / `deepseek-r1:8b` / `qwen3:8b` | 8B | 5.4–5.6 | 16384 | – | – | – | reasoning 等 | – |
| `gemma4-it:e2b` | 5B | 6.0 | 32768 | ✅ | ✅ | true | audio,vision,tool-calling | 5.58 |
| `qwen3.5:9b` | 9B | 8.94 | 32768 | ✅ | – | true | vision,reasoning,tool-calling | – |
| `gemma4-it:e4b` | 8B | 9.1 | 32768 | ✅ | ✅ | true | 同上 | – |
| `gpt-oss:20b` / `gpt-oss-sg:20b` | 20B | 14.0 | 8192 | – | – | 不可关 | reasoning / safeguard | – |
| `qwen3.6-moe:35b-a3b` | 35B | 24.3 | 32768 | ✅ | – | true | vision,reasoning | – |

**本机 v0.9.45 兼容性**：`qwen3.5:0.8b` / `:2b` / `:4b` 与 `qwen3.6-moe:35b-a3b` 要求 `flm_min_version 0.9.45` —— 本机**刚好满足**；其余候选的 min version 均 ≤0.9.43，全部可用。

---

## 五、官方性能一手数据

### 5.1 Qwen3.5 全族（FLM v0.9.38，Kraken Point / 32 GB，Performance 档）

| 模型 | decode 1k→32k (t/s) | 衰减 | prefill 1k→8k (t/s) | 图片 TTFT 720p / 1080p |
|---|---|---:|---|---|
| 0.8B | 44.83 → 22.8 | −49% | 851.21 → 2007.97 | 1.3 / 2.6 s |
| 2B | 28.92 → 17.98 | −38% | 625.99 → 1367.84 | 2.1 / 4.6 s |
| **4B** | **15.9 → 9.98** | **−37%** | **322.37 → 599.95** | **3.4 / 6.8 s** |
| 9B | 9.9 → 7.24 | −27% | 248.76 → 420.5 | 4.4 / 9.4 s |

### 5.2 Qwen3（FLM v0.9.31，同平台）

| 模型 | decode 1k→32k | 衰减 | prefill 1k→8k |
|---|---|---:|---|
| 0.6B | 66.5 → 14.1 | **−79%** | 1494 → 1981 |
| 1.7B | 40.2 → 12.5 | −69% | 956 → 1411 |
| 4B | 19.6 → 8.5 | −57% | 509 → 576 |

→ **0.6B 短 prompt 极快，但长上下文崩塌最严重**，不适合上下文会涨的杂活（如日志归类、长文档摘要）。

### 5.3 LFM2（FLM v0.9.30，**官方给了 Strix Point 组并注明 comparable to Strix Halo**）

| 模型 / 平台 | decode 1k→32k | 衰减 | prefill 1k→8k |
|---|---|---:|---|
| LFM2-1.2B / Kraken Point | 62 → 46 | −26% | 1537 → 2677 |
| **LFM2-1.2B / Strix Point** | **56 → 45** | **−20%** | **1487 → 2518** |
| LFM2-2.6B / Strix Point | 27 → 22 | −19% | 715 → 1206 |

→ **唯一官方明确说可外推到 Strix Halo 的一组数字**；也是长上下文衰减最小的一族。`lfm2.5-it:1.2b` 官方注明性能与 LFM2-1.2B 相当（"Fine-tuned models show performance comparable to their base models"）。

### 5.4 其他

- **Gemma4 E2B**（FLM **v1.0.4**，Kraken）：decode 22.6→10.1，prefill 721→1124，图片 TTFT 1.7 s。⚠ 版本比本机新，数字仅作量级参考。
- **Whisper-V3-Turbo**（测试机就是 **Ryzen AI MAX+ PRO 395 / Strix Halo**，FLM v1.0.12+）：5 分钟录音 wall 25.3 s（RTF 0.082），中文 CER 11.59%；"Before" 列 44.7 s（RTF 0.146）。⚠ 本机 v0.9.45 对应 "Before" 口径。
- **冷加载**（soothill.io，EVO-X3 同芯片）：0.8B ready 3.044 s / API check 0.509 s；4B 4.417 s / 1.310 s；35B 16.611 s / 2.865 s。
- **本机实测 4B**（`2026-10-07-NPU-8219-测试与使用手册.md`）：TTFT 1.19 s / decode 12.4 t/s / prefill 24.7 t/s / RSS 6.5 GB / <2 W / 不占 iGPU 显存。⚠ prefill 24.7 与官方 322 口径不同（极短 prompt 的 wall 换算），**不可与官方表横向比较**。

### 5.5 相对倍数（`lfm2.5-it:1.2b` vs `qwen3.5:4b`，Kraken 同表口径）

```
decode  @1k    62   / 15.9     = 3.90×
decode  @32k   46   / 9.98     = 4.61×
prefill @1k    1537 / 322.37   = 4.77×
prefill @8k    2677 / 599.95   = 4.46×
内存            5.2  / 0.96     = 省 5.42×
下载            4.64 / 0.94     = 省 4.94×
```

用本机实测 12.4 t/s 与 Strix 组 56 t/s 折算，decode 倍数 ≈ **4.5×**（跨平台，标 [UNVERIFIED]）。

---

## 六、五处机制订正（覆盖上游方案）

这五条是本次查官方文档 + 反查本机二进制新发现的，**直接影响分流补丁的正确性**。

### 6.1 `think` 是请求体顶层字段，不是 `chat_template_kwargs.enable_thinking`

- 官方 `docs/instructions/server/reasoning_and_tools/`：关闭思考链用 `extra_body={"think": False}`，等价于 raw JSON **顶层 `"think": false`**；也可用 `reasoning_effort: "none"`。
- 本机二进制有 `think` / `enable_thinking` / `reasoning_effort` 符号，但**无 `chat_template_kwargs`** → docproxy 现在注入的嵌套写法对 flm 不生效。
- 上游补丁第 ⑨ 处只做了「NPU 请求**跳过** `enable_thinking` 注入」，没做「**补发** `think:false`」→ 用 `qwen3.5:*` 时思考链仍会跑。

### 6.2 设置会「粘住」，必须每条请求显式发

原文：

> **The setting sticks.** `think` and `reasoning_effort` are applied to the loaded model and stay in effect for later requests that don't mention them. If your application mixes thinking and non-thinking calls, send the setting on **every** request.

采样字段同理：

> **Settings stick.** Sampling fields are applied to the loaded model and stay in effect for every later request that doesn't send them, **including requests from other clients**.

→ 分流补丁必须对**每条** NPU chat 请求无条件注入 `think:false`、`presence_penalty:0`、`temperature:0`，不能只在首条发。

### 6.3 `qwen3.5:*` 默认 `presence_penalty = 1.5`

官方 `request_parameters/` 表格：`qwen3.5:*`、`qwen3.6-moe:35b-a3b`、`qwen3.8-*` 载入时 `presence_penalty = 1.5`；`every other model = 0`。重复惩罚 1.5 会压制重复词，对 JSON 抽取、固定格式标签、枚举分类是**畸变源**。换 LFM2 后默认 0，天然规避。

### 6.4 未知字段被忽略，不会 400

> **FLM ignores fields it doesn't read. It doesn't reject them.**

→ 上游补丁「跳过注入」的做法**安全但无效**；补发顶层字段也不会因字段冲突报错。唯一会 400 的是 malformed 的 `messages` / `tool_choice` / `response_format` 等已知字段。

### 6.5 `--embed` / `--asr` 与主 chat **并发常驻**，不是换模

官方 EmbeddingGemma 文档：

> The embedding model must be used with an LLM (**loaded concurrently**) in Server Mode.
> `flm serve gemma3:4b --embed embed-gemma:300m` # Load the embedding model in the background, with **concurrent LLM loading**
> `--embed` / `-e` take an embedding model tag; `1` selects the default and `0` turns it off.

本机二进制佐证：`SafeTensors::switch_model`、`NPUAccessManager::try_acquire_npu_access` / `release_npu_access` / `is_npu_available` → **只有 chat↔chat 才走 `switch_model`（卸载重载、清 KV），全局互斥**；embedding / ASR 走并发行车。

→ 架构应为 **一个 `flm serve` 实例 = 1 个固定 chat tag + 常驻 embed + 常驻 ASR**，三个端点齐备，`NPU_MODEL_TAG` 固定不切。要第二个 chat 模型（如医疗 VLM）时接受一次换模开销，或另起实例（NPU 仍互斥串行，不推荐）。

### 6.6 附带两条

- **OpenAI API 无状态**：官方明写 `No KV cache is kept between turns`，每轮全量重 prefill。这与 GPU 侧 llama.cpp 的 slot LCP 缓存是两回事，不要混淆。v1.0 的 Flash 模型是例外（固定 system prompt 前缀缓存）。
- **前缀缓存本机没有**：`strings` 无 `prefix_cache` / `cached_tokens`，v0.9.45 不具备官方 v1.0 文档的 `usage.prompt_tokens_details.cached_tokens`。

---

## 七、推荐清单

### 7.1 第一梯队：当前 v0.9.45 直接可用

**① `lfm2.5-it:1.2b` —— 纯文本旁路任务的新默认（首推）**

| 项 | 值 |
|---|---|
| 下载 / 内存 | 0.94 GiB / 0.96 GiB |
| 速度 | Strix Point 组 decode 56→45 t/s、prefill 1487→2518 t/s（官方注明 comparable to Strix Halo） |
| 长上下文 | 32k 仅衰减 20%，全清单最稳 |
| 输出 | `think=false` 且 `think_toggleable=false` → **无思考链**，输出干净 |
| 采样 | `presence_penalty` 默认 0，无需纠偏 |
| 适用 | 意图/路由分类、guard、JSON 抽取、格式化、标题摘要、query 改写、automations/memory 压缩、日志归类 |
| 代价 | 无 VLM、无 tool calling（LFM2 有 pythonic tool syntax，但本方案不用）；质量上限低于 4B，需按第九节 A/B |

**② `qwen3.5:0.8b` —— 需要视觉时的首推**

| 项 | 值 |
|---|---|
| 下载 / 内存 | 1.23 GiB / 1.4 GiB（含 `vision_weight.q4nx` 192 MB） |
| 速度 | decode 44.83→22.8 t/s、prefill 851→2008 t/s |
| 图片 TTFT | 720p **1.3 s** / 1080p 2.6 s / 2K 5.0 s（4B 对应 3.4 / 6.8 / 12.6 s） |
| 适用 | 图片 OCR、截图理解、图表描述、化验单/报告图像初筛 |
| 注意 | `qwen3.5:*` 全族 `presence_penalty=1.5`；`think=true` 且清单无 `think_toggleable` → 必须按 6.1/6.2 注入 `think:false`，并实测是否生效 |

**③ `qwen3.5:2b` —— 视觉 + 质量折中**

3.2 GiB / 2.91 GiB 下载，decode 28.92→17.98，带 `tool-calling` 标签。仅在 0.8B 质量不达标时上。

### 7.2 第二梯队：专用端点（与主 chat 并发常驻，强烈建议开）

| tag | 端点 | 下载/内存 | 说明 |
|---|---|---|---|
| `embed-gemma:300m` | `POST /v1/embeddings` | 0.61 / 0.62 GiB | 2048 chunk，RAG / 去重 / 聚类 / 语义路由；`--embed 1` 即默认 |
| `whisper-v3:turbo` | `POST /v1/audio/transcriptions` | 0.61 / 0.62 GiB | 30 s 窗口；Strix Halo 同款测试机 RTF 0.082（v1.0.12+）/ 0.146（本机口径） |

⚠ v1.0.12 的 Whisper 反量化缓存会额外占 1.0–2.4 GB host RAM（`WHISPER_CACHE_DEQUANT=0` 可压到 1.0 GB，代价是每窗口 +0.8 s）。本机 v0.9.45 是否同样行为需实测。

### 7.3 第三梯队：场景专用（按需，非默认）

| tag | 内存/下载 | 适用 | 判定 |
|---|---|---|---|
| `medgemma1.5:4b` | 4.5 / 4.45 GiB | **医疗图文**（内镜报告、病理/影像描述、病历结构化） | 少爷专业方向唯一对口模型；但 65k ctx + VLM，比 4B 还重，且准确率无本机数据 → 单独立项验证 |
| `translategemma:4b` | 4.5 / 4.45 GiB | 中英医学文献翻译 | 有专用价值，但 4.5 GiB 常驻换一个低频任务不划算；需要时再切 |
| `gemma4-it:e2b` | 6.0 / 5.58 GiB | audio+vision+tool-calling **一体** | 单模型覆盖 ASR+VLM，理论上省换模；但比「0.8B + whisper」重 3.3 GiB，且 benchmark 是 v1.0.4 口径 → 不推荐当前上 |
| `qwen3vl-it:4b` | 3.9 / 3.85 GiB | 纯 VLM + tool-calling、无思考链 | 若 0.8B 视觉质量不足且不需要 reasoning，比 `qwen3.5:4b` 更轻更快 |

### 7.4 中期：升级 FLM v1.0.x 后的 Flash 模型（旁路任务的最终形态）

官方 `openapi/` 逐字：

> **Flash** models — `gemma4e-flash:e2b`, `gemma4e-flash:e4b`, `nemotron3.5-bolt-dflash-flash:e4b`, `qwen3.5-flash:2b`, `qwen3vl-flash:4b`, and `hy-mt2-flash:1.8b` — trade context length for a much faster time-to-first-token. They are built for **high-throughput, short, independent requests: classification, captioning, extraction, routing, translation**.

这**逐字对应**本方案 P0 任务清单。额外机制：

- 固定 system prompt 的 KV **预填一次并跨请求复用**，第二条起延迟显著下降；
- context 固定 1k、单轮、无 tool calling、system prompt 变动会失效。

**但本机 v0.9.45 的 `model_list.json` 无任何 flash 条目**，二进制也无 `prefix_cache` / `cached_tokens` → 必须升级。GitHub `ROCm/FastFlowLM` 已发布 v1.0.9 / v1.0.10（2026-10-15 / 10-22），带 `fastflowlm_1.0.10_linux.tar.gz` 与 ubuntu24.04/25.10/26.04 的 `.deb`。

**判定**：不并入本次方案。升级会替换 `/opt/fastflowlm`、模型清单、内核接口行为，且本机 `amdxdna 0.7` / FW 1.1.2.65 与新版的兼容性未验证 → 需单独授权、单独立项、单独回滚快照。

### 7.5 明确不推荐

| tag | 理由 |
|---|---|
| `qwen3.6-moe:35b-a3b` | 24.3 GiB，本机历史一手记录加载即 SIGKILL 137（峰值 ≈58.6 GB）；decode 8–16 t/s 与 4B 同量级，TTFT 32k 126.3 s |
| `gpt-oss-sg:20b` | guard 专用但 14 GiB 常驻，host RAM 30.47 GiB 全机共享，性价比最低 |
| `qwen3:0.6b` | 1k 时 66.5 t/s 最快，32k 崩到 14.1（−79%），长日志/长文档杂活会翻车 |
| `qwen3-tk:4b` / `lfm2.5-tk:1.2b` / `deepseek-r1*` | 官方明列「thinking 不能关」，思考链永远进 `reasoning_content`，旁路任务白付 token |
| 任何 8B / 9B / 20B | 内存与延迟全面劣化，且质量仍远不及 8080 主模型，定位重叠 |

---

## 八、三套推荐组合与落地命令

### 组合 A：极简（只换默认，零新增下载以外的成本）

```bash
# 面板 startCommand
env MODEL_TAG=lfm2.5-it:1.2b $HOME/WorkBuddy/调试本地模型/start-flm-npu.sh
```

- 下载 0.94 GiB；常驻 0.96 GiB；只有 `/v1/chat/completions`。
- 适用：先验证「杂活不抢主 slot」这一核心收益。

### 组合 B：均衡（**推荐**）

```bash
env MODEL_TAG=lfm2.5-it:1.2b EMBED=1 ASR=1 \
    $HOME/WorkBuddy/调试本地模型/start-flm-npu.sh
```

- 下载：0.94 + 0.61 + 0.61 = **2.16 GiB**
- 常驻：0.96 + 0.62 + 0.62 = **2.20 GiB**（≈ 4B 单模型的 42%）
- 端点：chat + embeddings + ASR 三件套，一次加载不换模。
- 代价：无 VLM。图片类杂活仍走 8080（会抢主 slot）——若图片任务占比高，改用组合 C。

### 组合 C：全功能

```bash
env MODEL_TAG=qwen3.5:0.8b EMBED=1 ASR=1 \
    $HOME/WorkBuddy/调试本地模型/start-flm-npu.sh
```

- 下载：1.23 + 0.61 + 0.61 = **2.45 GiB**
- 常驻：1.4 + 0.62 + 0.62 = **2.64 GiB**（≈ 4B 单模型的 51%）
- 端点齐全 + VLM；纯文本速度略低于 LFM2（44.83 vs 56 t/s），但省一个模型切换。
- **若 P0 任务以图片 OCR / 截图为主，这是最优组合。**

### 模型落盘位置（少爷永久约定）

所有模型文件一律到 `$HOME/models`。flm 找的是 `$FLM_MODEL_PATH/models/<模型名>/`，建议：

```bash
mkdir -p $HOME/models/flm/models
# 把已装的 4.7G 移过去（或软链），后续 pull 一律走该目录
export FLM_MODEL_PATH=$HOME/models/flm
HF_ENDPOINT=https://hf-mirror.com flm pull lfm2.5-it:1.2b
HF_ENDPOINT=https://hf-mirror.com flm pull embed-gemma:300m
HF_ENDPOINT=https://hf-mirror.com flm pull whisper-v3:turbo
```

⚠ 软链 / 自定义根路径能否被 `flm pull` 与 `flm list` 同时识别仍是上游方案的待核项；保守做法是先沿用已验证的 `$HOME/.config/flm/models`，验证通过后再迁。

### 对既有配套文件的 4 处改动点（**本次未执行，需授权**）

| # | 文件 | 改动 |
|---|---|---|
| 1 | `start-flm-npu.sh` | **无需改**（`MODEL_TAG` 已参数化）。仅需把 `PMODE=balanced` 纳入 A/B：官方所有 benchmark 都是 `performance` 档，`balanced` 会系统性低于本报告数字 |
| 2 | `tools/apply-npu-route.py` 第 ⑨ 处 | 从「跳过 `enable_thinking` 注入」升级为「**对每条 NPU chat 请求注入顶层 `think:false` + `presence_penalty:0` + `temperature:0`**」 |
| 3 | 同上 `NPU_MODEL_TAG` 默认值 | `qwen3.5:4b` → `lfm2.5-it:1.2b`（或随 `MODEL_TAG` 走同一 env）；`NPU_MODEL_ALIASES` 同步 |
| 4 | `tools/verify-npu-route.py` | 增加一条断言：NPU 分支发出的 body 必须含 `think:false` 与 `presence_penalty:0` |

改动 2–4 会使 `--check` 的 12 处替换点变化，需重新跑 `--check` + `--dry-run` + 补丁后 `py_compile`。

---

## 九、验收方法（确定性判定规则）

### 9.1 速度（工具已备）

```bash
# flm 自带基准，1k–32k 各 2 轮，输出 CSV
flm bench lfm2.5-it:1.2b
flm bench qwen3.5:0.8b
flm bench qwen3.5:4b --bench-iterations 4
```

或用配套 `tools/bench-npu-models.py` 走 HTTP，量真实端到端延迟与输出质量。

### 9.2 质量（必须做，官方无旁路任务准确率数据）

固定 100 条测试集：30 意图分类 / 30 JSON 抽取 / 20 guard 判定 / 20 短摘要，全部中文（含 20 条医疗文本）。逐模型跑，记录：

- 分类准确率、JSON 合法率、`finish_reason` 分布
- p50 / p95 端到端延迟、平均输出 token 数
- 是否出现 `reasoning_content`（思考链未关干净的标志）

**决策规则**：

```
若  lfm2.5-it:1.2b 准确率 ≥ qwen3.5:4b 准确率 − 2pp
    且 JSON 合法率 ≥ 98%
    且 无 reasoning_content
→ 换默认（组合 B / C）

否则
→ 保留 qwen3.5:4b 为默认，小模型只接「分类 / 路由」这类容错高的任务
```

### 9.3 共存（沿用上游方案门槛）

压 GPU 主会话的同时发 NPU 杂活，验收：

- GPU decode 降幅 **≤3%**
- `MemAvailable ≥ 4 GiB`
- 无 GPU reset / MODE2
- 主会话 TTFT 不出现冷启动回退（这是本方案的真实收益指标）

测速 prompt 必须带**随机 uuid 前缀**，否则会被 8080 的 `--cache-idle-slots` LCP 命中导致秒回。

---

## 十、风险与 [UNVERIFIED] 清单

| # | 项 | 状态 |
|---|---|---|
| 1 | v1.0.x 文档的 `think` / `reasoning_effort` / `presence_penalty` 在本机 **v0.9.45** 的 HTTP 行为 | 二进制有符号，但**未做 HTTP 实测** → [UNVERIFIED] |
| 2 | `qwen3.5:*` 的 `think` 能否关闭（清单无 `think_toggleable` 字段，官方「不能关」名单未含 qwen3.5） | [UNVERIFIED] |
| 3 | 小模型在 `PMODE=balanced` 下的实际速度（官方全是 `performance`） | [UNVERIFIED] |
| 4 | 0.8B / 1.2B 的中文与医疗文本准确率 | 官方 benchmark 只有速度，**无质量数据** → 必须本机 A/B |
| 5 | `lfm2.5-it:1.2b` 与官方 LFM2-1.2B 性能等价 | 官方仅注明 "comparable"，未给独立表 → 中置信 |
| 6 | Gemma4 / Whisper "Now" 列数字 | 分别是 v1.0.4 / v1.0.12+ 口径，本机 v0.9.45 不适用 |
| 7 | `FLM_MODEL_PATH` 指向 `$HOME/models/flm` 时 `flm pull` / `flm list` 是否识别 | 上游方案遗留待核项 |
| 8 | `--asr` 在本机 v0.9.45 是否接受模型 tag（官方 v1.0 写 `--asr whisper-v3:turbo`，本机 `--help` 示例只给 `--asr 1`） | [UNVERIFIED]，保守用 `ASR=1` |
| 9 | Whisper 反量化缓存 1.0–2.4 GB 额外 host RAM 是否适用于本机版本 | [UNVERIFIED] |
| 10 | Flash 模型 / prefix cache 升级到 v1.0.x 的驱动兼容性 | 未验证，需单独立项 |

**数据剔除**：`toolerific.ai` 与 `mygit.top` 的 README 镜像中「FLM v1.0.0 并入 ROCm」为新闻条目，与本机 v0.9.45 无关，仅用于确认升级路径存在；`deepseekharnessai.com` 的 `qwen3.5:0.8b 35.15 tok/s` 为第三方插件自测、平台与测量条件不明，仅作量级旁证，不进入倍数计算。

---

## 十一、来源清单

**本机一手（只读）**
- `/opt/fastflowlm/share/flm/model_list.json`（27 族 / 37 变体全字段）
- `flm version` / `flm serve --help` / `flm list --filter installed` / `flm validate`
- `strings /opt/fastflowlm/bin/flm`（`think` / `enable_thinking` / `presence_penalty` / `NPUAccessManager` / `switch_model`）
- `/proc/meminfo`、`df -h`、`ss -ltn`、`du -sh $HOME/.config/flm/models/models/*`
- hf-mirror `api/models/<repo>?blobs=true`（12 个候选的实际下载体积）
- `$HOME/WorkBuddy/调试本地模型/.workbuddy/memory/MEMORY.md` 第三/四/六节
- `2026-10-07-NPU-8219-测试与使用手册.md`（本机 4B 实测）
- `2026-11-08-维持现状下的NPU任务分配推荐方案.md`（上游方案）

**FastFlowLM 官方**
- `fastflowlm.com/docs/benchmarks/` 索引
- `.../qwen3.5_results/`、`.../qwen3_results/`、`.../lfm2_results/`、`.../gemma4_results/`、`.../whisper_results/`
- `.../instructions/server/openapi/`（4 个端点、Flash 模型定义）
- `.../instructions/server/reasoning_and_tools/`（`think` 开关、粘滞、不能关的模型）
- `.../instructions/server/request_parameters/`（未知字段忽略、`presence_penalty` 默认值、prefill chunking）
- `.../instructions/cli/`（`/load` 卸载重载清 KV、`/think` 仅部分模型、`flm bench`）
- `.../models/embeddinggemma/`（`--embed` 并发常驻、tag 语义）
- `github.com/FastFlowLM/FastFlowLM` README（`flm serve <tag>` 是初始模型、按 model 自动切换、默认端口 52625）
- `api.github.com/repos/ROCm/FastFlowLM/releases`（v1.0.9 / v1.0.10 Linux 产物）

**旁证**
- `soothill.io`（EVO-X3 同芯片冷加载时间）
- `binwh.com`（SER9 Strix Point 4B 实测 11.99 t/s / TTFT 2.22 s）

---

## 十二、变更留痕

**本次新建**：本报告、`tools/bench-npu-models.py`（候选模型 A/B 验收脚本，需授权启动服务后运行）。
**本次修改**：`.workbuddy/memory/2026-11-08.md`（追加选型结论）、`.workbuddy/memory/MEMORY.md`（第六节补入 4B 非最优与 flm 参数订正）。
**未执行**：任何 BIOS / 内核参数 / 服务 / 进程 / MCSManager 配置 / 生产 `docproxy.py` / 18090 重启 / `apply-npu-route.py --apply` / 模型下载。
**可回滚**：本报告为纯分析；配套脚本不写任何配置；换模型只需改面板 `MODEL_TAG` 环境变量，改回 `qwen3.5:4b` 即恢复上游方案原状。

---

> 许可：CC0-1.0，公共领域贡献，无任何限制。
