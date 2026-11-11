# 升级 FLM v1.0.x 后，Flash 模型是否是更优选择？

**日期**：2026-11-08 20:4x CST
**范围**：只评估 NPU 旁路链路；8080 主链路（96 GiB UMA + Vulkan + MTP + 35B-A3B）不动。
**方法**：一手资料（GitHub Releases API / 官方文档与 benchmark 页 / 本机 dpkg·sysfs·`flm validate`·`model_list.json`）+ 前四轮已落盘判定。

---

## 一、结论（确定性）

| 问题 | 判定 |
|---|---|
| **Flash 模型是否是更优旁路选择？** | **否。严格劣于现推荐的 `lfm2.5-it:1.2b`。** |
| **升级 FLM v1.0.x 是否值得？** | **值得，但理由与 Flash 无关**：为 prefix cache、constrained decoding、`embed-gemma` 修复、host RAM 优化。 |
| **升级后该用哪个模型？** | **仍是 `lfm2.5-it:1.2b`**（+ `--embed 1 --asr 1`），一个字节都不用改。 |
| **「专为分类/路由而生」的模型是哪个？** | **d3 Decision 3.0，不是 Flash**——此前笔记把两者混为一谈，本报告订正。 |
| **8080 主模型会变快吗？** | **不会。** 升级只动 NPU 侧，90.14 t/s 与 120 W 墙无关。 |

**一句话**：Flash 是「牺牲灵活性换极短单轮 TTFT」的旧思路；v1.0.11 起官方给所有标准 chat 模型加了 8 槽 prefix cache，把 Flash 唯一的优势用更通用、更便宜的方式覆盖，并明确把 Flash 排除在外。升级后换 Flash 等于主动退回没有缓存的分支。

---

## 二、本机现状与升级前置（2026-11-08 20:4x 只读实测）

| 项 | 读数 | 来源 |
|---|---|---|
| FLM | `fastflowlm 0.9.45-12-ga6bd056`（deb），`/opt/fastflowlm/bin/flm` | `dpkg -l`、`readlink -f /usr/bin/flm` |
| 驱动栈 | kernel `7.0.0-42-generic`、`amdxdna 0.7`（DKMS `7.0.0-rc1+git20260310`）、`libxrt-npu2 2.21.75` | `dpkg -l`、`uname -r` |
| NPU 自检 | `flm validate`：`/dev/accel/accel0 with 8 columns`、FW `1.1.2.65`、Memlock `infinity` | 本机命令 |
| 清单 | 27 族 / 37 变体，**无 flash / d3 / decision 条目**；顶层键 `['model_path','models']` | `/opt/fastflowlm/share/flm/model_list.json` |
| 已装 | `qwen3.5:4b ✅`（4.7 GB）；`FLM_MODEL_PATH=$HOME/.config/flm/models` | `flm list --filter installed` |
| host 内存 | `MemTotal 30.47 GiB` / **`MemAvailable 15.18 GiB`** / SwapFree 12.69 GiB | `/proc/meminfo` |
| 端口 | 8080、18090、23333 在听；**8219 未监听** | `ss -ltnp` |

**升级前置核对**：官方 `docs/linux-getting-started.md` 要求 `amdxdna`（kernel 7.0+ 或 DKMS）、**NPU FW ≥ 1.1.0.0**、XRT stack、memlock unlimited。本机 **四项全满足** → 升级不存在驱动/固件阻塞，无需动 BIOS、内核参数或 XRT。

**版本线**（`api.github.com/repos/ROCm/FastFlowLM/releases?per_page=12`）：

| 版本 | 日期 | 关键内容 |
|---|---|---|
| v1.0.0 | 08-11 | 并入 ROCm 组织 |
| v1.0.2 / v1.0.3 | 08-19 / 08-27 | **Qwen3.5 家族 / Qwen3.6-MoE 权重量化改为 FLM 自制，必须重下** |
| **v1.0.6** | 09-18 | 引入 3 个 Flash 模型 |
| **v1.0.10** | 10-22 | **xgrammar constrained decoding**（`response_format` / `tool_choice`） |
| **v1.0.11** | 10-29 | **Decision 3.0 + Prefix Cache 覆盖几乎所有 chat 模型** |
| **v1.0.12** | 11-05（最新） | DFlash、`qwen3.5-flash:2b`、`d3:edge`/`d3:flash`、省 RAM、修复 `embed-gemma` |

---

## 三、Flash 模型到底是什么（订正此前口径）

此前笔记写「v1.0.x 才有 Flash 模型，专为 classification/extraction/routing 而生，固定 system prompt 前缀缓存」——**半对半错**，需拆成三件事：

1. **Flash 确实是短请求专用**，官方 `docs/models/flash/` 逐字：
   > Flash models trade context length for a much faster time-to-first-token. They are single-turn (every request starts from a clean KV state; a system prompt is pinned and reused), have a fixed **1k-token** context, and do not support tool calling. They are built for high-throughput, short, independent requests: classification, captioning, extraction, routing, translation.

2. **它不是新权重、不是新分类模型**：v1.0.6 release notes 逐字 `These are not new checkpoints — they run the same weights as their standard counterparts through optimized kernels, so there is no weights update and nothing new to download`。这是它唯一的低成本优点：**A/B 只需改 `model` 字段，零下载**。

3. **「固定 system prompt 前缀缓存」≠ v1.0.11 的 prefix cache**。前者是 Flash 内建的单一 pinned system prompt，每请求 clean state；后者是跨会话、跨 8 个槽位、按 exact-from-start token 匹配的通用 KV 快照复用。**v1.0.11 文档明确把 Flash 排除在后者之外**：
   > Not covered: the single-turn models (`hy-mt2-flash`, `qwen3vl-flash`, `gemma4e-flash`, `nemotron3.5-bolt-dflash-flash`: they take one request and pin their system prompt, so there is nothing to reuse)...

**Flash 清单**（`docs/models/flash/` + v1.0.12）：`gemma4e-flash:e2b` / `:e4b`（图+音）、`qwen3vl-flash:4b`（图）、`nemotron3.5-bolt-dflash-flash:e4b`（图+音+投机）、`hy-mt2-flash:1.8b`（翻译）、`qwen3.5-flash:2b`（v1.0.12 新增）。

**硬限制**：固定 1k ctx；单轮（含 assistant 历史的请求被拒）；**不支持 tool calling**；**不支持 `continue_final_message`**（`request_parameters` 页逐字 `single-turn (flash) models ... continue_final_message is not supported`）；固定媒体预算（`qwen3vl-flash:4b` 图片长边缩到 **256 px**、不支持音频；`gemma4e-flash` 音频**截断前 30 s**）；`gemma4e-flash:*` 载入默认 `presence_penalty=1.0`。

---

## 四、性能头对头：Flash 不更快

**官方 Flash benchmark**（`docs/benchmarks/flash_results/`，v1.0.12 / Ryzen AI 9 370 Strix Point 32 GB / Performance / text-only / 无 system prompt / 7 次中位）：

| 模型 | TTFT 64→1024 tok (s) | prefill @1024 (t/s) | **decode @1k (t/s)** |
|---|---:|---:|---:|
| `hy-mt2-flash:1.8b` | **0.13 → 0.84** | **1,214** | **52.2** |
| `gemma4e-flash:e2b` | 0.20 → 1.53 | 668 | 22.6 |
| `qwen3vl-flash:4b` | 0.24 → 1.83 | 558 | 19.6 |
| `nemotron3.5-bolt-dflash-flash:e4b` | 0.32 → 2.53 | 405 | 18.2 |
| `gemma4e-flash:e4b` | 0.33 → 2.57 | 398 | 12.6 |

同页逐字：**`Flash only changes how prefill runs. Decode speed matches the non-flash model, so decoding numbers are taken from the corresponding benchmark page.`**
（`nemotron...` 三行与 `gemma4e-flash:e4b` 的 0.32/0.32/0.58/1.17/2.52 s 另在 **Ryzen AI MAX+ PRO 395 / Strix Halo** 实测，与本机同芯片。）

**现推荐 `lfm2.5-it:1.2b`**（`docs/benchmarks/lfm2_results/`，v0.9.30 / Strix Point 组，注明 comparable to Strix Halo）：

| 上下文 | 1k | 2k | 4k | 8k | 16k | 32k |
|---|---:|---:|---:|---:|---:|---:|
| decode (t/s) | **56** | 55 | 54 | 51 | 49 | **45** |
| prefill (t/s) | **1,487** | 1,992 | 2,436 | 2,518 | 2,257 | 1,839 |

**判定**：

- decode：Flash 除翻译专用 `hy-mt2-flash:1.8b`（52.2）外全在 **12.6–22.6**，是 `lfm2.5-it:1.2b`（56）的 **0.23–0.40×**；即使 32k 长上下文，LFM2 仍有 45 t/s。
- prefill：LFM2 @1k 1,487 t/s > Flash 最快 1,214 t/s（口径不同：Flash 的 `prompt/TTFT` 含首 token 生成，LFM2 为纯 prefill；**只作定性，不折算倍数**）。
- TTFT：Flash 在 64-token 无 system prompt 时快到 0.13–0.24 s；但旁路任务恰恰是**带长固定 system prompt 的重复短请求**，这正是 prefix cache 的主场。

**Flash 唯一量化的单点收益**（v1.0.12 release notes）：`qwen3.5-flash:2b` 与 `qwen3.5:2b` 同权重、零下载，TTFT **0.49 s vs 0.81 s @1k**（−40%）、decode **33 vs 29 t/s**。
**口径冲突**：benchmark 页说 decode 不变，release notes 说 +14% → **[UNVERIFIED]**，且两者都远慢于 LFM2 的 56。

---

## 五、决定性证据：prefix cache 覆盖标准模型，排除 Flash

`docs/instructions/server/prefix_cache/`（v1.0.11 起，Linux XRT 后端测试）：

- 支持清单**包含 `lfm2.5-it:1.2b`**（及 `lfm2:1.2b`、`lfm2.5-tk:1.2b`）、`qwen3.5:0.8b/2b/4b/9b`、`qwen3.6-moe:35b-a3b` 等；端点 `POST /v1/chat/completions`（现有 docproxy 补丁正是这个端点）。
- **明确不含 4 个 Flash 单轮模型**、developer-preview `*-core`、`lfm3`、语音/embedding/机器人模型。
- 默认开：8 槽（max 32，`0`=off）、`--prefix-cache-mb 4096`（**limit 非 reservation**）、`--prefix-min-gain 128`、`FLM_DISABLE_PREFIX_SLOTS=1` 可整关。
- 机制：在 system prompt + tools 末尾与 prompt 末尾各存一份快照；新请求找**最长 exact-from-start 匹配**；不同会话共享同一 system prompt 时复用同一份；图片按内容匹配；短 side call 不会挤掉主会话快照（<64 token 不保存）。
- **`lfm2.5-it:1.2b` 的缓存成本是全表最低档**：12 KiB / saved token + fixed <1 MiB，一个 4k-token prompt 仅 ≈**48 MiB**（对比 `qwen3.5:4b` 32 KiB/token + 49 MiB fixed ≈ 511 MiB）。默认 4096 MiB 预算下毫无压力。
- **限制（须记）**：LFM2 家族有 sliding window / convolution state，`a saved prompt is resumed only when the new prompt starts with all of it`，共享前段时退回到 system-prompt 起点恢复 —— 旁路单轮 + 固定 system prompt 恰好满足全前缀匹配，命中率高。

**cold → cached TTFT（官方）**：

| 模型 / 条件 | cold | **cached** |
|---|---:|---:|
| `qwen3.5:2b` / 14k prompt | 12.1 s | **1.6 s** |
| `qwen3.5:4b` / 14k | 26.4 s | **2.0 s** |
| `qwen3.5:9b` / 14k | 37.7 s | **3.0 s** |
| `lfm2.5-tk:1.2b` / 2k | 1.4 s | **0.5 s** |
| `minicpm-v-4.7:1b` / 1.6k 带图 | 1.3 s | **0.2 s** |

Hermes 真实多 agent：`qwen3.5:2b` 8.4 → **4.6 s**；4 轮 chat 5.4 → **3.2 s**。

**结论**：Flash 在 64-token 省下的 0.1–0.3 s，在带系统提示的重复请求上被标准模型 + prefix cache 反超（1.4→0.5 s，−64%；长提示 12.1→1.6 s，−87%），且标准模型没有 1k ctx / 单轮 / 无 tool calling 的限制。**换 Flash = 主动放弃缓存。**

---

## 六、按旁路任务维度判定

| 任务 | 现推荐 | Flash 可行？ | 判定 |
|---|---|---|---|
| 意图/路由分类、guard | `lfm2.5-it:1.2b` | 可（`*-flash` 定位含 classification/routing） | **不选**：decode 更慢、丢 prefix cache、丢 `tool_choice` 强制选项 |
| JSON 抽取 / 格式化 | `lfm2.5-it:1.2b` + `response_format` | 可但**不能保证 schema** | **不选**：v1.0.10 xgrammar 只走标准模型语法约束路径 |
| 标题/摘要/日志归类 | 同上 | 可 | **不选**：短 side call 本就不保存快照，Flash 无额外收益 |
| 图片 OCR / 描述 | `qwen3.5:0.8b` | `qwen3vl-flash:4b` **缩到 256 px** | **不可用**：256 px 读不了文字 |
| 音频转写 | `whisper-v3:turbo` | `gemma4e-flash` 截前 30 s | **不可用** |
| embeddings | `embed-gemma:300m` | 不支持 | 不适用 |
| 翻译 | `translategemma:4b` | `hy-mt2-flash:1.8b` 52.2 t/s / TTFT 0.13 s | **唯一可考虑项**，但需新增 tag、引入换模（NPU 全局互斥），且本机无翻译刚需 |
| 多轮 / tool calling / 长上下文 | 标准模型 | **明确不支持** | 硬排除 |

---

## 七、真正为分类/路由而生的是 d3，不是 Flash

`docs/models/d3/`（v1.0.11 起，v1.0.12 补 `d3:edge`/`d3:flash`）：`--decision <tag>` / `POST /v1/systemone`，**返回每个选项的概率，不生成文本**（`output_tokens: 0`），是 vLLM Semantic Router 用于 `routing, guardrails and tool selection` 的模型。

| tag | 下载 | 常驻 / 峰值 | 单问题延迟 |
|---|---:|---:|---:|
| `d3:edge`（0.8B 截 12 层） | **0.58 GiB** | 2.0 GB / 4.8 GB @32k | **0.26 s @1k**，1.8× faster than lite |
| `d3:lite`（0.8B） | 0.72 GiB | 文本 ~0.1 s / 图片 ~0.4 s | 0.4 s @1k |
| `d3:nano` / `mini` / `flash` | 1.9 / 3.2 / 5.7 GiB | 5.3 / 8.6 / 14 GB 峰值 | 0.6 / 1.3 / 2.3 s @1k |
| `d3:turbo` / `ultra`（27B） | 15.4 GiB | **需 28 GB free memory** | 3 s 起 |

**但仍不推荐现在上 d3**，三条硬理由：

1. **NPU 一次只跑一个请求**，官方实测 `qwen3.5:0.8b` + `d3:lite` 同服：decision **146 ms alone → 12.7 s** 当它撞上 600-token chat 生成；`A second flm serve for the decision model does not avoid this: the two processes contend for the NPU and both slow down`。旁路架构若把分类与 chat 放在同一 NPU，会互相拖死。
2. **新端点 `/v1/systemone`**：现有 `tools/apply-npu-route.py` 的 12 处补丁只路由 `/v1/chat/completions`，接 d3 需要改代理并新增请求/响应转换（概率 → 标签）。
3. `d3:turbo/ultra` 需要 28 GB 空闲内存，本机 `MemAvailable 15.18 GiB` 不满足；`d3:edge` 虽轻，但要拉新权重、新增端点、新增排队风险，收益只是把「分类」从 ~0.5 s 降到 ~0.26 s。

---

## 八、升级的真实收益（四项，全部与 Flash 无关）

| # | 版本 | 能力 | 对旁路链路的价值 |
|---|---|---|---|
| 1 | **v1.0.10** | xgrammar **constrained decoding**：`response_format` 支持 `text` / `json_object` / `json_schema`，`tool_choice` 支持 `auto`/`none`/`required`/forced function | **把「JSON 合法率」从靠 prompt + 后处理变成引擎保证**（前提 `finish_reason=stop`）：不会拼错字段名、类型错、缺 required、包 Markdown fence。前一轮 `tools/bench-npu-models.py` 的核心验收指标直接由引擎兜住。首次 grammar 编译约 0.3 s，后续复用；未约束请求零开销。 |
| 2 | **v1.0.11** | **Prefix cache**：8 槽、system+tools 快照、图片按内容匹配、`usage.prompt_tokens_details.cached_tokens` | 共享 system prompt 的旁路请求 TTFT −64%~−87%；`lfm2.5-it:1.2b` 每 4k prompt 仅 ≈48 MiB。**这是升级最大收益。** |
| 3 | **v1.0.12** | 嵌入表改只读 mmap，**省最多 3.7 GiB host RAM**（`gemma4-it:e4b` 3.9→0.3 GiB；`qwen3.5:2b` 省 0.92 GiB） | 本机 host 仅 30.47 GiB、`MemAvailable` 在 3.6–18 GiB 间波动，省 RAM 直接降低与 8080 争用风险。 |
| 4 | **v1.0.12** | **修复 `embed-gemma:300m`** + `/v1/embeddings` 错误码 + Qwen3.5 上下文超限 `//////` + Flash 复用过期 system prompt + 每条请求 `Request done:` 日志（含 prompt/generated tokens、prefill/decode 速度、**cached tokens**） | 官方逐字：`Since v0.9.45, its vectors were unrelated to the model's, changed between server starts, and some requests hung for 60 seconds or more`。**本机 v0.9.45 恰是坏版本 → `--embed 1` 必须先升级，否则 embeddings 结果不可用。** `Request done:` 日志让 A/B 不必自己埋点。 |

**附带**：v1.0.x 文档已确认「采样字段粘滞且跨客户端共享」、`presence_penalty` 模型默认值表（`qwen3.5:*`=1.5、`gemma4e-flash:*`=1.0、LFM2=0）、未知字段忽略不报 400 —— 上一轮选型报告里 `[UNVERIFIED]` 的参数行为在升级后变成已验证行为，补丁第 ⑨ 处「补发三个顶层字段」的改法有据可依。

---

## 九、升级代价与风险（须授权）

| 项 | 内容 | 缓解 |
|---|---|---|
| **权重失效** | v1.0.2 / v1.0.3 release notes 逐字 `you'll need to re-download weights for the Qwen3.5 family and Qwen3.6-MoE — existing local copies from prior versions are not compatible`。本机已装 `qwen3.5:4b` 4.7 GB 失效 | 反正推荐模型是 `lfm2.5-it:1.2b`（0.94 GiB），**直接拉新 tag，绕过重下 4B**；`hf-mirror.com` 可用 |
| **需 sudo** | `sudo apt install ./fastflowlm_1.0.12_ubuntu*.deb` 是系统级写入 | 按 SOUL.md 变更留痕，**须少爷显式授权**；本轮不执行 |
| **跨 13 个版本** | model_list 结构、CLI flag、默认端口、`--embed/--asr` 行为可能变 | 升级前备份 `/opt/fastflowlm/share/flm/model_list.json` 与 `~/.config/flm/models/`；升级后重跑 `flm validate` / `flm serve --help` / `flm list --filter installed` |
| **A/B 基线重建** | `embed-gemma` 从坏变好、prefix cache 从无到有 | 先跑 `tools/bench-npu-models.py` 建立新基线，再与旧记录对比；用 `FLM_DISABLE_PREFIX_SLOTS=1` 做缓存开关对照 |
| **NPU 排队** | 若误启用 `--decision` 与 chat 同服 | 本方案**不启用 `--decision`**；只 `--embed 1 --asr 1`（官方 `loaded concurrently`，不换模） |
| **Flash 干扰** | 模型清单升级后会出现 flash tag，容易被误选 | 面板 env 固定 `MODEL_TAG=lfm2.5-it:1.2b`；代理侧白名单不放 flash |

**回滚**：保留旧 `.deb`（`fastflowlm_0.9.45*.deb`）与备份目录 → `sudo apt install ./旧.deb` 降级 → 恢复 `model_list.json` 与模型目录 → `flm validate` 复核。因为 8219 尚未启动、18090 生产未打补丁，**当前回滚成本为零**。

---

## 十、量化收益预测（升级 v1.0.12 + 维持 `lfm2.5-it:1.2b`）

| 指标 | v0.9.45 现状 | v1.0.12 预测 | 依据 / 置信 |
|---|---|---|---|
| 旁路单轮 TTFT（2k prompt，共享 system） | 1.4 s（无缓存） | **0.5 s** | 官方 `lfm2.5-tk:1.2b` cold→cached 表；族内旁证，**中置信** |
| 旁路单轮 TTFT（14k prompt） | 12.1 s 级 | **1.6 s 级** | 官方 `qwen3.5:2b` 表；跨模型外推，**低置信** |
| JSON 抽取合法率 | 靠 prompt + 重试 | **结构化保证**（`finish_reason=stop` 时） | xgrammar 官方保证，**高置信** |
| decode (t/s) | 56 @1k | **56（不变）** | Flash/缓存均不改 decode，**高置信** |
| host RAM 常驻 | `lfm2.5-it:1.2b` 0.96 + embed 0.62 + ASR 0.62 ≈ 2.20 GiB | 同量级；若改用 Qwen3.5 系可再省 0.92–3.7 GiB | v1.0.12 表，**高置信**（但本方案模型不变，收益不落在本方案） |
| embeddings 可用性 | **不可用**（错误向量 / 挂 60 s+） | **可用** | v1.0.12 修复公告，**高置信** |
| 8080 主模型 decode | 90.14 t/s | **90.14 t/s** | 不同设备、不同池，**高置信** |
| 换 Flash 的净效果 | — | decode **0.23–0.40×**、无缓存、1k ctx 上限 | benchmark 表，**高置信（负）** |

**净判定**：升级 = TTFT 与确定性输出的正收益，零主链路风险；换 Flash = 明确负收益。**升级与「用 Flash」是两件独立的事，前者该做，后者不该做。**

---

## 十一、推荐实施顺序（全部需授权，本轮未执行）

1. **备份**：`/opt/fastflowlm/share/flm/model_list.json`、`~/.config/flm/models/`、当前 `fastflowlm` 包版本号（`dpkg -l`）。
2. **取包**：从 `api.github.com/repos/ROCm/FastFlowLM/releases/latest` 拿 `fastflowlm_1.0.12_ubuntu24.04_amd64.deb`（按本机发行版选），校验后 `sudo apt install ./…deb`。
3. **复核**：`flm validate` → `flm list --filter installed` → `flm serve --help`（确认 `--embed`/`--asr`/`--prefix-slots` 旗标）→ 记录新 `model_list.json` 中 `lfm2.5-it:1.2b` 的 tag 与 footprint。
4. **拉模型**：`flm pull lfm2.5-it:1.2b`（0.94 GiB）、`embed-gemma:300m`、`whisper-v3:turbo`（各 0.62 GiB），**到 `FLM_MODEL_PATH` 指向的目录**；模型文件遵守少爷约定统一放 `$HOME/models`（可用软链，需验证 flm 是否识别）。
5. **起 8219**：MCSManager 新建面板实例 `flm-npu-8219`，`startCommand` = `env MODEL_TAG=lfm2.5-it:1.2b EMBED=1 ASR=1 …/start-flm-npu.sh`；前台 `exec`、`--host 0.0.0.0 --port 8219`。
6. **18091 隔离验证**：`tools/verify-npu-route.py` + `tools/bench-npu-models.py`，记录 `Request done:` 日志里的 `cached_tokens`。
7. **Flash A/B（低成本，建议做）**：因 Flash 与标准模型同权重，**只改 `model` 字段**即可对照 `qwen3.5:2b` vs `qwen3.5-flash:2b`，零下载；验证官方 0.81→0.49 s 与 29→33 t/s 口径冲突，以及共享 system prompt 下 Flash 无缓存的实际损失。
8. **A/B 验收**：GPU 单独 vs NPU 并发，指标 = GPU decode 降幅 ≤3%、`MemAvailable ≥4 GiB`、无 reset/MODE2、旁路 p50/p95、JSON 合法率。
9. **授权后才动生产**：重启 18090 注入 `NPU_UPSTREAM`（会短暂中断当前会话链路，须避让）；补丁第 ⑨ 处同时补发 `think:false` + `presence_penalty:0` + `temperature:0`，改完重跑 `--check` / `--dry-run` / `py_compile`。

---

## 十二、数据校验与剔除

- **剔除**：v1.0.12 release notes 的 `qwen3.5-flash:2b decode 33 vs 29 t/s` 不用于倍数折算——与同版本 benchmark 页 `decode speed matches the non-flash model` 直接冲突，标 **[UNVERIFIED]**，留作 A/B 待测项。
- **不混用口径**：Flash 的 `prefill TPS = prompt_tokens / TTFT`（含首 token 生成）与 LFM2 页的纯 prefill TPS 不可直接相除；本报告只做大小定性。
- **平台差异**：Flash benchmark 主体在 Ryzen AI 9 370（Strix Point 32 GB），仅 `nemotron...` 三行与 `gemma4e-flash:e4b` 在 MAX+ PRO 395 实测；LFM2 页 v0.9.30 的 Strix 组注明 comparable to Strix Halo。所有外部速度数字均**不等于本机实测**，须以第 11 步 A/B 为准。
- **[UNVERIFIED] 清单**：`qwen3.5-flash:2b` 是否也在 prefix cache 排除清单（文档只列 4 个老 flash）；`response_format` / constrained decoding 在 flash 模型上是否可用（structured_output 页未提 flash）；小模型在 `PMODE=balanced` 下的真实速度（官方数据全是 Performance，而 `start-flm-npu.sh` 默认 balanced）；0.8B/1.2B 的中文医疗文本准确率；`FLM_MODEL_PATH` 指向 `$HOME/models/flm` 软链是否被识别；本机「NPU busy 时 GPU decode 掉多少」A/B 仍缺。

---

## 十三、来源清单

**官方一手**
- `api.github.com/repos/ROCm/FastFlowLM/releases?per_page=12` 与 `/releases/tags/{v1.0.0,v1.0.2,v1.0.3,v1.0.8,v1.0.9,v1.0.10,v1.0.12}`（版本线、Flash 引入、权重重下、prefix cache、embed-gemma 修复）
- `fastflowlm.com/docs/models/flash/`（定义、tag 清单、任务定位）
- `fastflowlm.com/docs/benchmarks/flash_results/`（TTFT / prefill / decode 全表、测试平台、`decode matches non-flash`）
- `fastflowlm.com/docs/benchmarks/lfm2_results/`（LFM2-1.2B Strix / Kraken 双平台表）
- `fastflowlm.com/docs/instructions/server/prefix_cache/`（适用/排除清单、8 槽与 4096 MiB、cold→cached TTFT、内存成本表、LFM2 sliding-window 限制）
- `fastflowlm.com/docs/models/d3/`（7 个 tag、下载/内存/延迟、`146 ms → 12.7 s` 排队实测、28 GB 要求）
- `fastflowlm.com/docs/instructions/server/structured_output/`（xgrammar、`response_format` 取值、保证与不保证、性能）
- `fastflowlm.com/docs/instructions/server/request_parameters/`（`Settings stick`、penalty 默认值表、未知字段忽略、flash 不支持 `continue_final_message`）
- `raw.githubusercontent.com/ROCm/FastFlowLM/main/{README.md,docs/linux-getting-started.md}`（Linux 前置、默认路径与端口、升级方式）

**本机实测**
- `dpkg -l | grep -E 'fastflowlm|amdxdna|xrt'`、`uname -r`、`flm validate`、`flm --version`、`/opt/fastflowlm/share/flm/model_list.json`、`/proc/meminfo`、`ss -ltnp`

**项目内既有判定**
- `2026-11-08-维持现状下的NPU任务分配推荐方案.md`
- `2026-11-08-NPU旁路模型选型-4B是否最优及推荐清单.md`
- `2026-11-08-NPU与GPU共存可行性及收益预测.md`
- `.workbuddy/memory/MEMORY.md` 第六节、`MEMORY-details-npu.md`

---

## 十四、变更留痕

本轮**只做只读实测与资料核对**，未执行以下任何动作：BIOS / 内核参数 / XRT / 驱动 / `apt` 升级 / `flm pull` / 服务启停 / 进程 / MCSManager 配置 / 生产 `tools/docproxy.py` / 18090 重启 / 补丁 `--apply`。

写入文件：本报告、`.workbuddy/memory/MEMORY-details-npu.md`（新建分册）、追加 `.workbuddy/memory/2026-11-08.md`、整理 `.workbuddy/memory/MEMORY.md`（14 KB → 精简，NPU 细节拆入分册）。

---

> 许可：CC0-1.0，公共领域贡献，无任何限制。
