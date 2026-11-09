# 今日项目雷达：`synchopate/llama-modchip` —— CPU-only 跑 284B MoE，本机可借鉴点

> 分析时间：2026-11-09 08:2x｜本机：RYZEN AI MAX+ 395 / 96 GiB VRAM carve-out / 30.47 GiB host / Vulkan build 10824
> 标注口径：**【实测】**=本次在本机跑出或读出的原始数据；**【推导】**=用本机实测数推算；**【待实测】**=尚未在本机验证

---

## 一、结论先行（5 条）

1. **它的成立前提与本机相反。** 项目解决的是「64 GB RAM 装不下 76.87 GiB 的模型」——用 1.71 bpw 极限量化压到 56.56 GiB，再靠 CPU 内核优化硬扛。**本机有 96 GiB 独占显存，`unsloth/DeepSeek-V4-Flash-GGUF` 的 `UD-IQ1_S` 恰好 76.9 GiB【实测】**，根本不需要压到 1.71 bpw，也不需要 CPU 推理。**照抄它的量化 = 主动给自己增加 20 GiB 信息损失。**
2. **本机真正缺的是"能不能跑 284B"，而这块拼图已经齐了。** 本机二进制已含 `LLM_ARCH_DEEPSEEK4`、Vulkan FWHT（64/128/256/512 四档）、`IQ1_S` 的 `matmul`/`matmul_id`/`dmmv` 全套管线、以及 `-ncmoe` 与 `--moe-cache-mib`【实测】。**Q1_S 77 GiB + KV + 计算缓冲 ≈ 81–85 GiB < 96 GiB**，显存容得下。
3. **CPU-only 路线在本机物理不可行。** 本机 host 池只有 **30.47 GiB**（96 GiB 被 BIOS 划走给 iGPU，OS 看不见），而项目的最小 checkpoint 是 56.56 GiB。**差 26 GiB，无解**，除非改 BIOS UMA 且放弃显存——与现有全部产线冲突。
4. **最该立刻抄的是"零预填"那一段，不是内核。** `/dev/shm` KV 槽快照 + 自动恢复守卫，把它的冷启压到 **18.9–32.6 ms**；本机 docproxy 冷启是 **149 s**。`/dev/shm` 现有 16 GiB 可用、本机 256K KV(q8_0) 仅 2.66 GiB【实测】，装得下。
5. **别信"MoE Top-K 降档能白捡 38%"那个数。** 我们的 35B 是 **256 专家 / top-8**，每 token 读 2.751 GB，其中常驻权重（注意力+共享专家+lm_head）占 1.99 GB（72%）——**降 Top-K 的天花板只有 +4.9%~+17.4%**。它那个 +38.5% 来自 `Qwen3-30B-A3B`（128 专家，routed 占活跃字节约一半），**模型结构不同，不可类比**。

---

## 二、项目是什么（事实层）

| 项 | 值 |
|---|---|
| 仓库 | `synchopate/llama-modchip` v2.4.0，Apache-2.0，创建 2026-10-29，480 ★ / 25 fork【实测元信息】 |
| 主命题 | 纯 CPU（0 GPU）在 **64 GB DDR5 笔记本（Zen 5 16C）** 上跑 **DeepSeek-V4-Flash 284.33B（13.17B 激活）** |
| 重量级数字 | 1.71 bpw / 56.56 GiB 权重 / 256K ctx 时 VmRSS **58.9 GiB** / decode **9.06–10.74 t/s**（PVS 后 11.5–14.7）/ CPU prefill **41.6–44.4 t/s** |
| 另两条产品线 | Nemotron-3.5-30B-A3B：`Fractal-64` 14.35 GiB，纯 CPU 25.02 t/s、Vulkan 混合 80.8 t/s；Qwen3-30B-A3B：`LLAMA_MOE_TOP_K=4` 8→4，25.12→34.80 t/s |
| 三根支柱 | ① 极限量化（`Fractal-64` `Q2_0` 3.75 bpw + `SwiGLU-H2` 二阶重要性）② CPU 四层缓存平铺（ZMM 寄存器 + L1D + L2 + L3，`{8,4,3,2}` 多列）③ 无神经 draft 的投机解码（Stockfish-PVS，1.64 MB）+ `/dev/shm` KV 快照 |
| 论文级证据 | 逐算子 profiling（4551 节点 / token）、`perf stat` PMU 计数、KL/PPL 质量闸门（100 分制）、**独立"负结果"章节** |

**它的技术底色是可信的**：给出了 `L2-cosine 1.00000` 的逐位等价证明、`-98.3%` TLB miss 的 PMU 数据、Top-2 崩溃的复现（3365 token 不停机）。这不是营销稿，是带复现步骤的系统研究。

---

## 三、本机底牌核对（决定"能不能借鉴"的硬约束）

### 3.1 CPU 侧 —— 与作者测试机（9955HX）几乎同构

| 项 | 本机【实测】 | 9955HX（作者机） | 结论 |
|---|---|---|---|
| 核心 | 16C/32T Zen 5，**2 × 32 MiB L3**（2 CCX） | 16C/32T，2 CCD × 32 MiB | **拓扑一致**，CCD 绑定策略可直接套 |
| L1d / L2 | 48 KiB/core、1 MiB/core | 同 | 一致（`TILE_I0=64` 的假设成立） |
| AVX-512 | `f bw cd dq vl vnni bf16 vbmi vbmi2 ifma vp2intersect vpopcntdq bitalg` | 同 | **全档可用** |
| THP | `madvise`；`AnonHugePages` 仅 102 MiB | 打了 `MADV_HUGEPAGE` | **本机缺这一步**（见 §5.3） |
| 内存带宽 | **≥210 GB/s（推导）** | DDR5-5600 双通道 ≈89.6 理论 / ~75 实测 | **本机约 2.8 倍** |

> **★ 本次新得的关键数：有效带宽 ≈210 GB/s**【推导】
> 35B 的 GGUF 张量按类别统计：routed experts **24.29 GiB（93.1%）**、注意力+router+norm 0.83、lm_head 0.39、token_embd 0.33、共享专家 0.10 → 合计 26.09 GiB【实测】。
> top-8/256 ⇒ 每 token 实读 `24.29×8/256 + 1.80 = **2.751 GB**`；实测 76.3 t/s ⇒ **2.751 × 76.3 = 209.9 GB/s**。
> LPDDR5X 256-bit 理论 256 GB/s ⇒ **已达 82% 效率，这个模型在本机没有带宽余量了**。
> （此前记忆里的「144 GB/s 有效带宽」偏低，那是另一口径的测量，应予订正。）

### 3.2 内存池 —— 这是本机与项目最大的分歧点

| 池 | 容量 | 谁能用 | 对本项目的意义 |
|---|---|---|---|
| **VRAM carve-out** | **96.0 GiB**（当前 33.1 GiB 在用）【实测】 | Vulkan / HIP | **能装下 76.9 GiB 的 284B** |
| **host RAM** | **30.47 GiB**（available 8.5 GiB）【实测】 | CPU / GTT | **装不下任何 56+ GiB 的 checkpoint** |
| `/dev/shm` | 16 GiB（已用 25 MB）【实测】 | 双方 | 够放 2.66 GiB 的 256K KV 快照 |

> **★ 铁律复述**：本机 96 GiB 显存是 BIOS UMA 划走的，**OS 完全看不见**，CPU 无法直接寻址。所以"CPU-only 跑大模型"这条路在本机不是慢，是**不存在**——除非把 UMA 改小（代价：现有全部 Vulkan 产线崩掉）。

### 3.3 软件侧 —— 拼图已经齐了【实测】

| 能力 | 状态 | 证据 |
|---|---|---|
| `deepseek4` 架构 | **已支持** | `src/llama-arch.h:87 LLM_ARCH_DEEPSEEK4`；`llama-model.cpp:201/2360/2762` 有专门分支 |
| Vulkan FWHT（DSV4 的 512 点 Hadamard） | **已支持** | `ggml-vulkan.cpp` `ggml_vk_fwht_pipeline_idx()` 对 n=64/128/256/512 有 pipeline |
| Vulkan `IQ1_S` | **已支持** | `matmul_iq1_s_f32`、`matmul_id_subgroup_iq1_s_f32`、`mul_mat_vec_iq1_s` 全套 |
| MoE 专家放 host | **已支持** | `-ncmoe/--n-cpu-moe`、`--moe-cache-mib`（默认 0 = 关） |
| MTP 投机 | 已用 | baseline 76.3 t/s 来自 `--spec-draft-n-max 2` |

---

## 四、12 项技术逐条判定

图例：✅ 可直接搬｜⚠️ 需改造/弱收益｜❌ 本机不适用｜🛑 已否决（勿试）

| # | 技术点 | 它宣称的收益 | 本机判定 | 理由（本机口径） |
|---|---|---|---|---|
| 1 | `Fractal-64`（`Q2_0`，3.75 bpw）+ 1.71 bpw 全模型 | 76.87→56.56 GiB | ❌ | **无 Vulkan shader**（作者自己写了 IMPORTANT 警告，`Q2_0` 只实现于 `ggml-cpu`）。本机 96 GiB 显存根本不用压；强压反损 20 GiB 精度 |
| 2 | `SwiGLU-H2` 免校准重要性向量 `I_ej = ‖W_gate[j,:]‖²·‖W_up[j,:]‖²` | 免 imatrix 达到分层量化精度 | ✅ | 纯数学、零数据依赖，可写进自建量化脚本替代 imatrix 采集。**这是它最有普适价值的原创** |
| 3 | 分层锚定（{0,1,26,28,41,42}→IQ2_XXS） | 保住首尾路由层 | ⚠️ | 仅对 DSV4 层号成立；但**"贴边层不压"的思路**可迁移到 35B 自建量化 |
| 4 | MoE Top-K 降档 + `L2` 正交重标定 | Qwen3-30B 8→4：+38.5%；DSV4 6→5：+7% | ⚠️ **弱杠杆** | 本机 256 专家/top-8 ⇒ **天花板 +4.9%(→7) / +8.0%(→6) / +17.4%(→4)**【推导】。且 `qwen35moe` 硬编码 `norm_w=true` 会自动重归一化，**不需要**它那套 L2 α（那是给不重归一化的 DSV4 实现打的补丁） |
| 5 | `_MM_HINT_NTA` 非时态权重流 + KV 分层预取 | L3 miss −5.8%、cycles −9% | ❌ | 计算在 iGPU，L3 不在关键路径；Vulkan 无对应原语 |
| 6 | **2MB THP（`MADV_HUGEPAGE`）** | TLB miss **−98.3%**、token 时间 −13.2 ms（占 24%） | ✅ | 本机 THP=`madvise` 且 `llama.cpp` 全文**无** `madvise(HUGEPAGE)`（只有 `MAP_POPULATE`）；**仅在走 `-ncmoe` / host 专家时才有意义**。两行补丁，风险极低 |
| 7 | AVX-512 `{8,4,3,2}` 多列平铺 / `q4_0_8x8` repack / `MQA8` FlashAttn | prefill +77%、decode +53% | ❌ | 全部作用于 `ggml-cpu`；本机 prefill 走 iGPU（短 prompt 已 260 t/s，是它的 6 倍） |
| 8 | Stockfish-PVS n-gram draft（1.64 MB）+ **盈亏平衡定理 `p > B_cpu−1`（≈0.58）** | Nemotron 25→48 t/s | ⚠️ | 深改 `llama-server` 源码，且**本机 MTP 已覆盖**（MTP 的 draft 是模型自带的头，比 n-gram 更准）。**但定理本身值得抄**：作为"要不要上任何投机方案"的判据 |
| 9 | **`/dev/shm` KV 槽快照 + `_ensure_slot0_restored` 守卫** | 冷启 → **18.9–32.6 ms** | ✅ **ROI 最高** | 本机 149 s 冷启是真实痛点；`--slot-save-path /dev/shm/...` 是 llama.cpp 原生参数，零代码 |
| 10 | `--cache-reuse 256` | 25K+ 多轮 TTFT 148–546 s → 0.29–0.49 s | ✅ 已有 | 本机已开；但注意 `--mmproj` 下会自动禁用 —— 与本机多模态定位冲突，需按实例区分 |
| 11 | 张量-角色切分 `-ot "\.ffn_.*_exps\.=CPU"` / `-ncmoe` / `--moe-cache-mib` | 让"超显存"的模型可用 | ✅ **已在手未用** | 本机二进制原生支持。**这是 96→116 GiB 区间的唯一出路**：注意力/共享专家留显存，冷专家落 host |
| 12 | EAKV 非对称 KV（低熵 q4 / 高熵 f16）+ VPI | KV DRAM 流量 −58% | ❌ | 本机 KV 已 q8_0、且 DSV4 是 MLA 压缩 KV 结构完全不同；收益场景（CPU 长上下文）本机不存在 |
| 13 | AQLM / 后训练三值（`TQ1_0`） | 2 bit 压缩 | 🛑 | 它自己实测：Zen 5 上 `VGATHERDPS` 串行化 → **慢 3–4 倍**；三值后训练直接崩 router |
| 14 | 负结果：Top-2「脑叶切除」、无门控静态码本 OOD 0.71–0.94× | —— | ✅ **当护栏** | 我们做 Top-K 实验时，**8→6 起步，绝不下 4** |

---

## 五、落地建议（按 ROI 排序）

### 5.1 L1｜零风险，只改脚本，不动模型（建议本周做）

**A1. `/dev/shm` 槽快照消除 149 s 冷启**（学 §3.8 HARP-Cache）

```bash
# 面板托管脚本 start-qwen36-35b-a3b.sh 里加一行（脚本属主 lc，可改；面板 startCommand 不动）
--slot-save-path /dev/shm/llama-slots
```
- 预算：256K KV(q8_0) **2.66 GiB** ≪ `/dev/shm` 16 GiB【实测】。
- 流程：预热一次系统提示（docproxy 的 connectors/automations 前缀）→ `POST /slots/0?action=save` → 后续重启先 `restore`。
- 预期：冷启 149 s → **1 s 量级**（它的 18.9 ms 是 22K token 的 GQA 模型；本机 256K MLA 结构更大，取 0.3–1 s 保守估计【待实测】）。
- 回滚：删该行 + `systemctl` 不动，面板重启即恢复。

**A2. docproxy 侧加"槽冷则自动恢复"守卫**（学 `_ensure_slot0_restored`）
- 在 `tools/docproxy.py` 转发前查 `GET /slots`，`n_prompt_tokens < 阈值` 就触发 restore。
- 与现有 `NPU_SIDECAR` 分流逻辑正交，失败只记日志不阻塞（沿用 §6.1 的"纠错失败不阻塞"范式）。

**A3. `MADV_HUGEPAGE` 两行补丁**（学 §3.4）
```cpp
// ggml/src/ggml.c: ggml_aligned_malloc 末尾
if (size >= 2*1024*1024) madvise((void*)((uintptr_t)p & ~4095ULL), size, MADV_HUGEPAGE);
// src/llama-mmap.cpp: mmap 成功后
madvise(addr, file->size(), MADV_HUGEPAGE);
```
- 只对 **host 侧权重**（`-ncmoe` / `--moe-cache-mib` / CPU 推理）有意义；纯显存推理零收益。
- 风险：本机 host 池仅 30.47 GiB，THP 会加剧碎片；**必须先在独立实例上量 `MemAvailable` 曲线**。

### 5.2 L2｜高价值实验：让 284B 进 96 GiB 显存（要下 76.9 GiB）

**这是本次雷达唯一"能力跃迁"级别的机会**，且不需要任何补丁。

```bash
# 1) 下载（$HOME/models 永久约定；hf-mirror 可用）—— 仅 UD-IQ1_S，3 分片 76.9 GiB
hf download unsloth/DeepSeek-V4-Flash-GGUF --include "UD-IQ1_S/*" --local-dir $HOME/models/dsv4

# 2) 面板新建实例（禁止裸跑），关键参数：
-m $HOME/models/dsv4/UD-IQ1_S/DeepSeek-V4-Flash-UD-IQ1_S-00001-of-00003.gguf
-c 32768 -fa on -ngl 99 -np 1 --jinja
-ctk q8_0 -ctv q8_0          # MLA 下 KV 极小，32K 约 0.8–1.6 GiB
--cache-ram 1024             # 铁律：默认 8192 会吃 host
```

**显存预算【推导】**：权重 76.9 + KV 1.6 + 计算缓冲 2–4 + Vulkan 预留 ≈ **81–85 GiB**，余 11–15 GiB。

**速度预期【推导，务必实测再引用】**
- 每 token 有效字节 ≈ **2.85 GB**（它的 1.71 bpw / 13.17B 激活口径）
- 若 Vulkan 达到当前 Q5_K 的字节效率（210 GB/s）→ 理论上限 **73 t/s**
- 扣掉 `IQ1_S` 的 LUT 反量化开销 + 256 专家小 batch gather（M=6 的 GEMM 在 iGPU 上利用率低）打 0.25–0.5 折 → **18–37 t/s**
- **判据**：≥15 t/s 即值得常备（284B 前沿能力 vs 35B 的差距远大于 5 倍延迟）；<8 t/s 只留作"离线攻坚"

**量化档位阶梯**（同一仓库，按显存余量选）【实测体积】
| 档 | 体积 | 权重+KV(32K)+缓冲 | 判定 |
|---|---:|---:|---|
| `UD-IQ1_S` | 76.9 GiB | ≈ 82 GiB | ✅ 推荐起步，余量最大 |
| `UD-IQ1_M` | 80.9 GiB | ≈ 86 GiB | ⚠️ 质量更好，余量 10 GiB |
| `UD-IQ2_XXS` | 84.6 GiB | ≈ 90 GiB | ⚠️ 极限，KV 只能 16K |
| `UD-Q2_K_XL` | 90.2 GiB | — | ❌ 装不下 |
| `UD-IQ3_XXS` | 95.9 GiB | — | ❌ 超 |

> **⚠️ 别下错仓库**：`DeepSeek-V4.1-Flash-1017` 的 `UD-IQ1_S` 是 **217 GiB**（约 1T 参数）【实测】，本机绝对放不下。要的是 **`DeepSeek-V4-Flash`（284B）**，不是 `.1`。

### 5.3 L3｜量化侧（自建量化时用）

- **`SwiGLU-H2` 免校准重要性**：写进 `llama-quantize` 的 imatrix 替代路径，对 MoE 的 `down_exps` 按行加权。价值在于**不需要跑校准集**——我们做 35B 的 Q4/Q3 复刻时省一整套流程。
- **分层锚定**：首层、末层、路由敏感的中间层保 `IQ2_XXS`/`IQ1_M`，主体 `IQ1_S`。这是"同样平均 bpw 下质量更高"的正解。
- **Top-K 降档**：可先零补丁试 `--override-kv qwen35moe.expert_used_count=int:6`（`norm_w=true` 会自动重归一化）。**但先看 §6 的收益账，别期待 +38%。**

---

## 六、收益账（为什么 Top-K 在本机是弱杠杆）

| 配置 | 每 token 字节【推导】 | 等效率外推 t/s | 相对 +8 |
|---|---:|---:|---:|
| top-8（现行） | 2.751 GB | 76.3 | — |
| top-7 | 2.649 GB | 79.2 | +3.8% |
| top-6 | 2.547 GB | 82.4 | +8.0% |
| top-5 | 2.446 GB | 85.8 | +12.5% |
| top-4 | 2.344 GB | 89.6 | +17.4% |

**根因**：本机 35B 是 256 专家、每 token 只碰 8 个（3.1%），**routed 只占每 token 字节的 28%**，其余 72% 是必须全读的注意力/共享专家/lm_head。它家 `Qwen3-30B-A3B` 是 128 专家/top-8，routed 占比接近一半，所以才有 +38.5%。

**结论**：Top-K 最多值 +17%，而质量风险在 Top-4 才开始显现（它实测 Top-2 直接崩）。**性价比低于"换 284B"一个数量级，排到最后。**

---

## 七、🛑 明确不要抄的（避免重复踩坑）

1. **`Fractal-64`/`Q2_0`**：无 Vulkan shader，任何被 `-ngl` 沾到的 `Q2_0` 张量都会输出垃圾（作者原文警告）。
2. **AVX-512 那 4 层平铺**：前提是"CPU 是执行单元"。本机执行单元是 iGPU，移植等于给不存在的瓶颈做优化。
3. **CPU-only 跑 56 GiB 模型**：host 只有 30.47 GiB，物理不可能。
4. **AQLM / 后训练三值**：它自己的负结果已经写明（Zen 5 上 gather 串行化，慢 3–4 倍）。
5. **无门控静态码本 draft**：OOD 上 0.71–0.94×，反而更慢。

---

## 八、可复用的方法论（比代码更值钱）

1. **逐算子账本**：它把 110 ms/token 拆成 7 类算子的毫秒数，并标注每类被哪个优化打掉多少。我们的 `timings` 只有 decode/prefill 两个数 —— **缺一张 `LLAMA_PROFILE_OPS` 级别的账本**。
2. **负结果单列一章**：把"试过且失败"的 4 条写进正文，直接挡住后来者。我们的记忆里也有这类铁律（压测分组 A/B 是错的），应同样固化成"勿再试"清单。
3. **质量闸门用 KL/PPL，不用"看着还行"**：它的 Top-5 是 `0.0042 nats / +0.42% PPL / Top-1 95.8%`。我们评估 Top-K 降档时应照抄这套量化闸门，而不是凭几条样例主观判断。
4. **"不静默回落"**：与 docproxy 的 `NPU 死→502 不回落` 同源。**分流类设计必须显式失败**，否则会用小模型冒充大模型并污染主 slot 的 LCP 前缀。

---

## 九、待实测清单 `[UNVERIFIED]`

1. DSV4-Flash `UD-IQ1_S` 在本机 Vulkan 的**实际 decode**（预期 18–37 t/s）与显存峰值。
2. `deepseek4` 在 Vulkan 上是否有算子落回 CPU（HADAMARD 已确认有 FWHT pipeline，但 `Sinkhorn/HC_PRE/HC_POST` 未逐个核）。
3. 77 GiB 单缓冲在 RADV 的 `maxMemoryAllocationSize` 下能否一次分配（本机 heap 96 GiB，理论够）。
4. `/dev/shm` restore 在本机 256K MLA 槽上的真实耗时（它 18.9 ms 是 22K token GQA）。
5. `--override-kv qwen35moe.expert_used_count=int:6` 是否被本 fork 的 hparams 加载路径接受，以及质量影响。
6. THP 补丁在 host 池 30.47 GiB 约束下的碎片/可用量代价。

---

## 十、一句话给少爷

> **这个项目的价值不在"CPU 跑 284B"，在"它证明了 1.7 bpw 的 284B 是可用的"**——而本机恰好有 96 GiB 显存可以**不用 1.7 bpw、直接 76.9 GiB 全量进显存**。真正该抄的是它的 `/dev/shm` 零预填、`SwiGLU-H2` 免校准重要性、和那份"负结果清单"；该丢的是它的 CPU 内核与 Fractal 量化。

---

> 许可：CC0-1.0，公共领域贡献，无任何限制。
