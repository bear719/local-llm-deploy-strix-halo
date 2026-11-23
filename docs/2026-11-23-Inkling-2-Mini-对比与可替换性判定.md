# Inkling 2 Mini vs 本机 Qwen3.6-35B-A3B：可替换性判定

> 核查时间：2026-11-23 17:30（GMT+8）
> 本机基线：`Qwen3.6-35B-A3B-Uncensored-Q5_K_P` + MTP，`-c 262144`，Vulkan，build 10824 / `75147a27e`（2026-10-07）
> 判定对象：Thinking Machines Lab `Inkling-2-Mini`（2026-11-20 发布，Apache 2.0）

---

## 0. 结论（先行）

| 用途 | 判定 |
|---|---|
| 替换 8080 主力（中文对话/病历/科室统计/导播台） | **否决**。中文与多轮多约束指令是硬伤，官方自认落后 Qwen3.8-27B，且易陷推理循环 |
| 并行副实例（agentic coding / 图像输入 / 1M 文档） | **值得试**。VRAM 余量够，能力面互补 |
| 去审查版 | **存在，3 个来源**，但均非官方；官方 AUP 含「禁止移除模型内措施」条款，需自行评估合规 |

替换的成本不是显存，是**编译**：本机 fork 停在 10-07，`src/llama-arch.cpp` 的 121 个架构里**没有** `LLM_ARCH_INKLING2_LOOP`，必须另编上游 ≥ b12641。

---

## 1. 规格对照

| 项 | Qwen3.6-35B-A3B（本机现行） | Inkling 2 Mini | 来源 |
|---|---|---|---|
| 总参数 / 激活 | 35B / ~3B | 26.4B / 3.4B（含 loop **5.4B 有效激活**） | HF 模型卡 |
| 架构 | MoE + 10 层 attention + 30 层 SSM | **looped transformer**：24 物理层，中间 12 层（blk 6–17）跑 3 次 → 48 层应用 | HF 模型卡 |
| MoE 路由 | 256 专家 top-8 | 128 专家 top-8，selected-score 归一化 ×8 | aitoolsoasis 技术表 |
| 注意力 | GQA + SSM 混合 | hybrid local（窗口 1024）/ global；24 Q heads / 8 KV heads | alexkmiller 实测 |
| 上下文 | 262144（已用满） | 声明 1M | HF 模型卡 |
| 模态 | text + image（mmproj f16） | 原生 VLM（ViT），text + image in | HF 模型卡 |
| 原生精度 | GGUF Q5_K_P | 多数 NVFP4 + 末 4 层 MXFP8，~20 GB | HF 模型卡 |
| 许可 | 第三方 uncensored 微调 | Apache 2.0 + 单独 Acceptable Use Policy | HF 模型卡 |

**KV / 缓冲（决定本机能不能吃满 262144 的关键）**

| 项 | 值 | 来源 |
|---|---|---|
| KV cache | **~17.4 KiB/token**（仅 full-attention 层） | alexkmiller，双 R9700 实测 |
| KV 结构 | 24 层 → **48 个 KV 槽 + 48 个 conv-state 槽**（每个 loop pass 独立） | vLLM 发布说明引述 |
| compute buffer | **~96 KB/token @ `-ub 512`**，约等于 attention cache 的 3 倍 | atomic.chat 排障节 |
| 262144 时占用 | KV 4.35 GiB + compute 24 GiB（`-ub 512`）/ 12 GiB（`-ub 256`） | 推导 |

> 35000 vs 26000 的直觉在这里失效：**权重更小，缓冲更大**。本机 262144 必须显式 `-c 262144 -ub 256`，不能用 `-c 0`。

---

## 2. 能力对照（全部为厂方或第三方公开数，非本机实测）

| 基准 | Inkling 2 Mini | Qwen3.8-27B | 判读 |
|---|---:|---:|---|
| AA Intelligence Index v5.0 | 20.1 | 20.1 | 并列 |
| Vals Index v2.2 | 46.5% | – | **Vals 独立排名 38/43**，厂方口径与独立口径分歧大 |
| DeepSWE v1.1 | **48.2%** | 42.2% | <100B 开源第一 |
| SWE-bench Verified | 79.2%（厂方） | – | 未经独立复现 |
| Terminal Bench v2.1 | 71.6% | 73.0% | 输 |
| MCP Atlas | 82.7% | 77.3% | 赢 |
| AutomationBench-AA | 41.8% | 48.2% | 输 |
| AA-Omniscience 非幻觉率 | 63.4% | 71.4% | **输，事实召回弱** |
| 破坏性动作率（低者优） | 10.2% | 35.2% | 赢 |

**注意**：上表对标的是 Qwen3.8-27B dense，**不是**本机的 Qwen3.6-35B-A3B-Uncensored。后者无公开基准，且 uncensored 微调通常会掉一点对齐类能力。跨模型比分数只能定方向，不能定结论。

**官方自陈的硬缺陷（模型卡原文要点）**
1. 事实召回弱于 Inkling 2 Small，**更容易「自信地错」**
2. 调试代码时**易陷长推理循环**，反复自检不前进 → 必须设 `max_tokens` 与 agent 轮次上限
3. 工具使用与项目约定遵循不可靠，**可能误报结果**
4. **英语以外显著较弱**（`Weaker outside English`）
5. `reasoning_effort=none` **不能真正关闭思考**
6. 可能未经确认执行删除/覆盖文件

第 4 条直接打死本机主力场景（中文病历、A 股、科室统计）。第 2、3、6 条打死无人值守 agent 场景。

---

## 3. 本机可运行性

### 3.1 硬前提：必须换 build

| 检查项 | 结果 | 证据 |
|---|---|---|
| 本机 fork 支持 `inkling2_loop` | **否** | `grep -ril inkling` 在 `$HOME/llama-qwen4exp-rocmfpx` 零命中；arch 表 121 项无 INKLING |
| 上游支持起点 | PR **#32694**（commit `29b52d398`），2026-11-20 22:01 UTC，**b12600** 起 | alexkmiller / ssdnodes / atomic.chat 三方一致 |
| 关键修复 | PR **#32807**（commit `5bacb7c`，11-22 合入）：loop 第 2/3 pass 误用第 1 pass 上传的专家。**b12641 尚未包含** | aimastery b12633 指南 |
| 该 bug 是否影响本机 | 触发条件 = 专家张量留在 host（`--n-cpu-moe` / `-ot ...=CPU`）。本机 96 GiB 可全量 offload，**大概率不触发**，但必须实测 | 同上 |

**判定：不要 rebase 主力 fork。** `75147a27e`（10-07）到 `b12641` 跨 1.5 个月，且主力 fork 带三项私有改造（`LLM_ARCH_QWEN4EXP` type 101、`Vulkan_HostDL` prompt cache、sd.cpp 侧 ggml 分支），rebase 冲突面无法控制。正解 = **单独 clone 上游 b12641+ 编一个 Vulkan build，只服务 Inkling，独立端口 + 独立面板实例**。

### 3.2 显存预算（96 GiB carve-out）

| 方案 | 权重 | KV@262144 | compute@`-ub 256` | 合计 | 与 35B 共存 |
|---|---:|---:|---:|---:|---|
| ggml-org IQ4_NL | 16.42 GiB | 4.35 GiB | 12 GiB | **~33 GiB** | 33.4 + 33 = 66.4 / 96 ✅ |
| ggml-org Q8_0 | 25.91 GiB | 4.35 GiB | 12 GiB | **~42 GiB** | 33.4 + 42 = 75.4 / 96 ✅（余 20） |
| Unsloth UD-Q5_K_XL（估） | ~19 GiB | 4.35 GiB | 12 GiB | ~35 GiB | ✅ |
| 去审查 AD-Q4_K | ~17 GiB | 4.35 GiB | 12 GiB | ~33 GiB | ✅ |

文件大小来自 HF API 实测（`ggml-org/Inkling-2-Mini-GGUF`、`AtomicChat/Inkling-2-Mini-Uncensored-GGUF` 的 siblings 列表）。

### 3.3 速度推算 `[估算，必测]`

本机实测基准：35B-A3B Q5_K_P 每 token 实读 **2.751 GB**，76.3 t/s → 有效带宽 **209.9 GB/s**。

| 方案 | 每 token 读取量 | 理论上界 | 预期区间 |
|---|---:|---:|---|
| IQ4_NL（5.4B × 0.667 B/param） | 3.60 GB | 58 t/s | **45–58** |
| Q8_0（5.4B × 1.053 B/param） | 5.69 GB | 37 t/s | **30–38** |

**此推算不可靠，原因有三**（ssdnodes 与 aimastery 均明确警示）：
1. loop 使中间 12 层权重在一个 token 内被读 3 次，L2/Infinity Cache 装不下 8 GiB 专家权重 → 实际重复落 DRAM，可能比线性模型更差
2. 48 层应用带来 48 份 conv-state 与 KV 槽，访存模式与 35B-A3B 完全不同
3. 「带宽 ÷ 权重」公式在 looped MoE 上失效

**prefill 更悲观**：48 层应用 + 48 份 KV，100K 冷 prefill 大概率**慢于** 35B-A3B 的 216 s。这是本机「100K 文档喂料」主力场景的直接风险点 `[待实测]`。

---

## 4. 去审查版清单

官方模型带对齐（32 个有害请求全拒），且 AUP 写明「不得移除模型内措施」。社区去审查版有 **3 个独立来源**：

| # | 仓库 | 方法 | 格式 | 拒答实测 | 质量代价 | 可否 llama.cpp |
|---|---|---|---|---|---|---|
| 1 | `OpenUncensored/Inkling-2-Mini-Uncensored` | **abliteration**，只改 20 个 BF16 attention 输出投影（layer 4–23），专家张量逐字节原样 | safetensors（原厂 NVFP4/MXFP8，~20 GB）+ PEFT LoRA | 32/32 → **0/32**（chat 与 thinking 双模式） | MMLU 78.95 → **79.47%**（无损失） | ❌ 需 SGLang/Transformers；其 GGUF 由他人转换 |
| 2 | `AtomicChat/Inkling-2-Mini-Uncensored-GGUF` | 全 49 个 residual writer 上的 **Rank-1 LoRA** | GGUF：`AD-IQ2_M` / `AD-IQ3_S` / `AD-Q4_K` + `LoRA.gguf` 适配器 + mmproj | 81/81 → **0/81**（含 100 条俄语） | MMLU −1.5 分 | ✅ b12600+，**但文件布局有争议**（见下） |
| 3 | `JoaoZaokk/Inkling-2-Mini-uncensored` | **Heretic** 工具 | GGUF UD-Q2_K_XL → UD-Q4_K_XL，5 文件 + DSpark draft | 100% → **20.0%**（chat）/ **58.3%**（thinking） | 未公布 | ✅ llama.cpp |

**口径冲突（必须实测才能定）**
- atomic.chat 自称 11-21 已按 merged 布局（24 层 + loop 参数）重传，b12600+ 直接可载
- toolhalla（11-21）称 AtomicChat 的 GGUF 用 PR #32695 的 48 层布局，在 b12600+ **加载失败**
- 判据唯一可靠：读 GGUF metadata — `general.architecture = inkling2_loop` 且 `block_count = 24` → 可载；`block_count = 48` → 报 `tensor 'blk.24.attn_q.weight' not found`

**次要风险**：`github.com` 直连 TLS 中断，HF 走 `hf-mirror.com` 已验证可用（本轮 API 查询成功）。模型一律落 `$HOME/models`。

---

## 5. 替换路径建议

**不建议**：改 8080 主力。中文场景、judge 链路（`jev-local/judge.py` 依赖 18090）、OpenClaw 白名单全部按 35B 调好的，换模型等于重跑一遍 11 月全部验证。

**建议**（若少爷要试）：
1. `git clone` 上游 → `checkout` 含 `5bacb7c` 的提交（≥ b12641 之后）→ 编**仅 Vulkan**，独立目录 `$HOME/llama-inkling/build-vk`
2. 下载 `ggml-org/Inkling-2-Mini-GGUF` 的 `IQ4_NL`（16.42 GiB）+ `mmproj-Q8_0` → `$HOME/models/inkling-2-mini/`
3. 面板新建实例，端口 **8090**（8080/8090 分开），`-c 262144 -ub 256 -ngl 99 --jinja --temp 1.0`，禁 `--n-cpu-moe`/`-ot CPU`（绕开 #32710）
4. 验收顺序：① 单轮中文问答（判语言能力）→ ② 5K 长 prompt smoke（判 #32710）→ ③ 100K prefill 计时（判是否可用）→ ④ `cache_n` 复用（判 prompt cache 是否跟上）
5. 全绿再考虑接去审查版；接管一个独立用途（如 Claude Code 本地后端），**不动 18090**

---

## 6. 风险清单

| 风险 | 等级 | 说明 |
|---|---|---|
| 中文能力不足 | **高** | 官方自述；本机全部主力场景是中文 |
| 长推理循环 + 误报结果 | **高** | 官方自述；agent 无人值守场景不可接受，可能无确认删文件 |
| 100K prefill 变慢 | 中 | 48 层应用 + 96 KB/token 缓冲；需实测 |
| Vulkan loop 路径未在 AMD APU 验证 | 中 | 公开复现均在 CUDA/HIP/R9700；Strix Halo 无案例 |
| #32710 NaN 输出 | 中 | 全 offload 大概率不触发；仍须 5K prompt 冒烟 |
| GGUF 布局错配 | 中 | AtomicChat 有争议，须核 `block_count` |
| AUP 合规 | 中 | Apache 2.0 允许改，但 Thinking Machines AUP 禁止「移除模型内措施」；医疗/科研用途建议只用官方版 |
| fork 维护分叉 | 低-中 | 新 build 独立目录，不污染主力 |

---

## 7. 一句话

**能跑，装得下，快不过 35B，中文打不过 35B，但在写代码和读图这两件事上确实比 35B 强——所以它的定位是「第二个实例」，不是「换掉第一个」。**

---

## 来源

1. https://thinkingmachines.ai/news/inkling-2-mini/ （官方发布，2026-11-20）
2. https://huggingface.co/thinkingmachines/Inkling-2-Mini （模型卡：架构/参数/局限）
3. https://alexkmiller.com/blog/2026/11/21/inkling-2-mini-dual-r9700-1m-context.html （KV 17.4 KiB/token、48 KV 槽、ROCm 构建）
4. https://www.ssdnodes.com/learn/run-inkling-2-mini-on-a-cpu-vps-with-llama-cpp （PR #32694 合并时间、b12600、带宽公式失效）
5. https://www.aimastery.page/guides/run-inkling-2-mini-locally （#32710 / #32807 / commit 5bacb7c）
6. https://atomic.chat/blog/guides/how-to-run-inkling-2-mini-uncensored-locally （去审查版三选一、96 KB/token 缓冲、block_count 判据）
7. https://huggingface.co/blog/OpenUncensored/inkling-2-mini-uncensored （abliteration 方法、20 张量、MMLU 数据）
8. https://www.abliteratedmodels.org/inkling-2-mini-uncensored （全部分支仓库与下载量）
9. https://www.toolmintx.in/blog/inkling-2-mini-vram-loop-kv-cache （评测对照表）
10. HF API 实测：`ggml-org/Inkling-2-Mini-GGUF`、`AtomicChat/Inkling-2-Mini-Uncensored-GGUF` 文件清单（2026-11-23）
11. 本机实测：`$HOME/llama-qwen4exp-rocmfpx` git HEAD `75147a27e`；`src/llama-arch.cpp` 无 INKLING 架构

> 许可：CC0-1.0，公共领域贡献，无任何限制。
