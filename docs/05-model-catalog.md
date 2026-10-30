# 社区推荐的量化模型清单（对标 Qwen3.6-35B-A3B）

> 生成日期：2026-10-07
> 本机：AMD Ryzen AI Max+ 395 / Radeon 8060S (gfx1151) / 96 GiB VRAM / GTT 104.8 GB
> 当前基线：Qwen3.6-35B-A3B-Uncensored-Q4_K_P（34.66B MoE，3B 激活，23.4 GB，多模态，`-c 131072`）

---

## 0. 本机环境结论（关键）

**无需重新编译即可跑的模型** —— 现有 `build-vk4`（llama.cpp b10821，commit 925c32a20，Vulkan 后端）已支持下列架构：

```
GEMMA4 / GEMMA4_ASSISTANT    → Gemma 4 全系（含 MTP 头部）
GLM4_MOE                     → GLM-4.7-Flash
QWEN3NEXT / QWEN35MOE        → Qwen3-Next-80B / Qwen3.5-122B
NEMOTRON_H / NEMOTRON_H_MOE  → Nemotron 3 Super 120B
MINIMAX_M3 / MISTRAL4 / MIMO2
BAILINGMOE / BAILINGMOE2/3   → Ling 系列
GRANITE_MOE / HUNYUAN_MOE
```

二进制路径：`$HOME/llama-qwen4exp-rocmfpx/build-vk4/bin/llama-server`

> 注意：`QWEN4EXP`（ROCmFP4 私有类型 101）仍只能由该 fork 跑，不可换上游二进制。

---

## 1. 社区实测解码速度（Strix Halo，Vulkan RADV，无投机解码）

来源：visorcraft/strix-halo-llm-perf、Strix Halo Guide、SpecPicks 汇总（2026-09 数据）

| 模型（量化） | 权重文件 | 激活/总参数 | 实测解码 | 带宽上限 |
|---|---|---|---|---|
| Qwen3.6-35B-A3B (UD-Q4_K_M) | 22.1 GB | 3B / 35B | **62.56 t/s** | ~135 |
| gpt-oss-120b (MXFP4) | 63.4 GB | 5.1B / 117B | **55.57 t/s** | ~92 |
| Qwen3.8-Flash-Next (UD-IQ4_XS) | 93.7 GB | 6B / 125B | 27.16 t/s | ~57 |
| Qwen3.5-122B-A10B (UD-Q4_K_XL) | 77.0 GB | 10B / 122B | 22.9 t/s | ~41 |
| Nemotron 3 Super 120B-A12B (UD-IQ4_XS) | 64.5 GB | 12B / 120B | 18.43 t/s | ~40 |
| Llama 3.1 70B (Q4_K_M, dense) | 42.5 GB | 70B / 70B | 4.7–4.9 t/s | ~6 |

**规律**：解码速度由**激活参数**决定，与总参数无关。
- 22 GB 的 35B-A3B 比 42 GB 的 dense 70B 快约 13 倍。
- 上下文填满后掉速显著：Qwen3.6-35B-A3B 在 128K KV 满时降到 32.23 t/s（短上下文约 62）。

来源：https://specpicks.com/reviews/strix-halo-llm-benchmark-2025-amd-ai-rigs

---

## 2. 社区「真金白银投票」榜（r/LocalLLaMA，2026 年 10 月）

128GB 统一内存机器跑 Agent，47 条实名投票高度收敛：

| 定位 | 模型 | 说明 |
|---|---|---|
| 日常首选 | **Qwen3.8-Flash-Next** (125B MoE / 6B 激活) | 「第一个真正敢用于实际工作的本地模型」 |
| 批量并发 | **DeepSeek-V4-Flash** (284B MoE / 13B 激活) | MIT，需 3-bit 约 103 GB |
| 质量保险 | **GLM-5.3** | 公认最强之一，但「所有人都说慢」 |

来源：今日头条编译 r/LocalLLaMA 帖（2026-10）

---

## 3. 分档推荐（对标 Qwen3.6-35B-A3B）

### A 档｜同档能力，速度更快（直接替换）

**① Qwen3-Next-80B-A3B（社区大 MoE 首选）**
- 架构：80B MoE / 3B 激活，混合线性注意力（hybrid linear-attention）
- 量化：UD-Q4_K_M **50.4 GB**（~45 t/s）｜Q8_0 **84.8 GB**（~24 t/s）
- 优势：能力显著高于 35B-A3B，速度仍接近；KV 成本低于标准 GQA（仅稀疏全注意力层缓存）
- 获取：`ollama run qwen3-next:80b`
- 本机适配：✅ build-vk4 支持 `QWEN3NEXT`

**② Gemma 4 26B-A4B（QAT 量化，体积最小）**
- 架构：25.2B MoE / ~3.8B 激活，30 层，262K 上下文，原生多模态
- 量化：**QAT 版 14.3 GB**（对比标准动态版 17.0 GB，同质量更小）
- 基准：GPQA Diamond 82.3 / LiveCodeBench v6 77.1 / MRCR-128k 44.1
- 获取：`unsloth/gemma-4-26B-A4B-it-qat-GGUF`（QAT）或 `-it-GGUF`（UD-Q4_K_XL）
- 本机适配：✅ build-vk4 支持 `GEMMA4`

**③ gpt-oss-120b（速度/能力比之王）**
- 架构：117B MoE / 5.1B 激活，原生 MXFP4（4-bit 即原生精度，非事后量化）
- 量化：MXFP4 **63.4 GB**，实测 **55.57 t/s**（b11146 上 56.14）
- 亮点：65,536 token 长提示下 prefill 仍保持 293.73 t/s
- 获取：`ggml-org/gpt-oss-120b-GGUF`（`gpt-oss-120b-mxfp4.gguf`）
- 本机适配：✅ MXFP4 走 GGUF，build-vk4 可载（需实测确认 gfx1151 Vulkan 路径）

**④ GLM-4.7-Flash（Agent/工具调用最强档）**
- 架构：31.2B-A3B MoE，MIT，202,752 上下文
- 量化：Q4_K_M **18.3 GB**（社区另有 Q3Q4 混合版 13.41 GB）
- 基准：SWE-bench Verified **59.2**、τ²-Bench 79.5、GPQA Diamond 75.2、AIME25 91.6
- **必读三坑**：① 关闭 repeat penalty（设 1.0）；② `--min-p 0.01`（llama.cpp 默认 0.05）；③ **必须用 2026-01-21 之后修复版 GGUF**（旧版会循环输出，因 softmax→sigmoid 修复）；Ollama 有 chat template 兼容问题
- 本机适配：✅ build-vk4 支持 `GLM4_MOE`

### B 档｜能力跃升，速度换质量

**⑤ Qwen3.5-122B-A10B**
- 122B MoE / 10B 激活，262K 上下文，原生多模态，Apache 2.0
- 量化：UD-Q4_K_XL **77.0 GB**，实测 **22.9 t/s**（ROCm 21.3）
- 用途：长上下文文档分析、复杂 Agent 循环（vdf.ai 评为 64–128GB 档 Agent 首选之一）
- 本机适配：✅ build-vk4 支持 `QWEN35MOE`

**⑥ Nemotron 3 Super 120B-A12B**
- 120B MoE / 12B 激活，社区评价「Agent 工作流、长上下文、推理」
- 量化：UD-IQ4_XS **64.5 GB**，实测 18.43 t/s
- 本机适配：✅ build-vk4 支持 `NEMOTRON_H_MOE`

**⑦ Ling-3.0-flash**
- 124B / Q4_K_M **77.8 GB**，~28 t/s（Mac Studio 口径）
- 定位：Agentic coding、长上下文、推理
- 本机适配：✅ build-vk4 支持 `BAILINGMOE` 系列

### C 档｜激进路线（需专用引擎，非 llama.cpp）

**⑧ Kyojin 引擎 + EXL3/QTIP 量化（gfx1151 原生优化）**
- Yamz Labs 基于 ExLlamaV3，为 gfx1151 写了自定义 ROCm decode/prefill 路径
- 在 128GB 单机上跑 ~300B 级 MoE：
  - GLM-5.3-Flash（99.7 GB EXL3）：prefill 580 t/s @3.5K、546 t/s @64K；decode **26–30 t/s（带 MTP）**；与 FP8 Top-1 一致率 89.3%
  - MiMo-V2.6-Flash-MOPD（105 GB）：prefill ~650 t/s；decode 29 t/s 裸 / **44 t/s 投机解码**；一致率 92.0%
- 代价：脱离 llama.cpp 生态，需自建 Kyojin（ROCm），维护成本高
- 来源：https://github.com/Yamz-Labs/kyojin

---

## 4. 量化格式选择规则（2026 年社区共识）

| 格式 | 适用 | 本机 |
|---|---|---|
| **UD-Q4_K_XL** | 通用默认首选（Unsloth Dynamic，逐层敏感度分配） | ✅ |
| **Q4_K_M** | 标准甜点档，性价比最优 | ✅ |
| **QAT GGUF**（Gemma 4） | 同质量体积小 16%（14.3 vs 17.0 GB） | ✅ |
| **MTP GGUF**（Qwen3.5/3.6） | 约 2 GB 换 1.4–2.2× 加速 | ✅ 已用 |
| **MXFP4**（gpt-oss） | OpenAI 原生格式，非事后量化 | ⚠️ 需实测 |
| **NVFP4** | Blackwell 专属（vLLM/SGLang），**llama.cpp 不支持** | ❌ |
| **EXL3/QTIP** | Kyojin 专用 | ⚠️ 需专用引擎 |
| IQ 系列 / Q2/Q3 | **必须带 imatrix**，否则不可用 | ⚠️ |

**关键提醒**：
- `UD-Q4_K_XL` 的 GGUF 文件头 `file_type` 字段仍写 15（= `LLAMA_FTYPE_MOSTLY_Q4_K_M`），`_XL` 只是文件名标签，llama.cpp 官方类型表无此项。
- `UD-` 版优先于标准版：同体积质量更好，不加价。
- Q4→Q6 质量提升真实但边际递减（+33% 体积，日常任务差异不显著）；多数场景 Q4_K_M 最优。

---

## 5. 优先级建议

| 优先级 | 动作 | 理由 |
|---|---|---|
| P0 | 测 **Qwen3-Next-80B-A3B UD-Q4_K_M**（50.4 GB） | 能力跃升 + 速度仍高（~45 t/s）+ 本机零改动可跑 |
| P1 | 测 **gpt-oss-120b MXFP4**（63.4 GB） | 速度/能力比最优，55 t/s 远超 122B 档 |
| P2 | 测 **Gemma 4 26B-A4B QAT**（14.3 GB） | 最小体积同档能力，适合并跑第二实例 |
| P3 | 测 **GLM-4.7-Flash**（18.3 GB） | Agent/工具调用场景最优，注意三坑 |
| P4 | 评估 **Kyojin + EXL3** | 若需 300B 级质量且能接受专用引擎维护 |

---

## 数据来源

- SpecPicks: https://specpicks.com/reviews/strix-halo-llm-benchmark-2025-amd-ai-rigs
- PyShine AMD Ryzen 2026 深研: http://pyshine.com/Best-AMD-Ryzen-For-Local-AI-2026-Deep-Research
- Unsloth GLM-4.7-Flash 教程: https://unsloth.ai/docs/models/tutorials/glm-4.7-flash
- ValuestreamAI Unsloth 下载榜: https://valuestreamai.com/blog/most-downloaded-unsloth-models-2026
- Kyojin 引擎: https://github.com/Yamz-Labs/kyojin
- DataHardware 统一内存指南: https://datahardware.ai/blog/how-much-unified-memory-for-local-llm-2026
- vdf.ai Agent 模型榜: https://vdf.ai/blog/best-local-llm-for-agents-tool-calling
- 本地实测环境：`$HOME/llama-qwen4exp-rocmfpx/build-vk4`（b10821）

> ⚠️ 速度数据均为社区第三方实测（Vulkan RADV，无投机解码），非本机测量，需 A/B 验证。
