# 抖音「提升 Qwen3.8-Flash-Next」案例 — 内容还原 + 本机对账与判定

日期：2026-11-11　分析对象：titan909《提升Qwen3.8-Flash-Next》（aweme_id 7699095452372813049）
本机：AMD Ryzen AI Max+ 395 / Radeon 8060S / VRAM carve-out 96 GiB / host 30.47 GiB

---

## 一、结论先行

1. **视频讲的是「用 Qwen3.8-Flash-Next 替换 Qwen3.6-35B-A3B」，不是速度提升，是智能提升。** 作者原话：
   「虽然没有 Qwen3.6-35B-A3B 快，但日常最快也能到 40 token/s，关键是智能程度提升了一个很大的台阶。」
2. **视频的启动方案本机物理不可复制**：UD-Q4_K_XL = 111.3 GB，加上 KV/compute 需 ≈130 GB，
   而 96 GiB carve-out 只有 **103.08 GB**。差 27 GB，不是调参能补的。
3. **本机已经在跑这个模型**（9-26 下载，`Qwen3.8-Flash-Next-ROCmFP4-FAST-imatrix-v2.gguf` 93.48 GB），
   decode 35.4~39.2 t/s 与视频 40 t/s **基本打平**；但 prefill 38~80 t/s 对视频 300 t/s **差 4~8 倍**。
4. **真正的可用提升点不是换 UD-Q4_K_XL，而是换 UD-IQ4_XS（93.7 GB）继续让 n-gram 表落磁盘** ——
   同构改造、显存反而更省、精度按 Unsloth Dynamic v3.1 基准恢复率 99.4%~99.9%（相对全精度）。
   详见第六节。

---

## 二、视频内容还原

来源：今日头条同文《经过一周的试用我决定用Qwen3.8-Flash-Ne...》（`m.toutiao.com/article/7682773416826389035`）
＋ ima「大模型部署案例收集」条目

| 项 | 视频陈述 |
|---|---|
| 硬件 | AMD max+395，Ubuntu 24.04，ROCm 10.1.0 |
| 权重 | unsloth **UD-Q4_K_XL**（111.3 GB）+ MTP 草稿 |
| 引擎 | unsloth 提供的**支持 MTP 的 llama.cpp 分支** |
| 显存 | ≈**101 GB** |
| decode | 日常最快 **40 t/s** |
| prefill | OpenClaw 首轮 27,000 token → **300 t/s** |
| 实测任务 | OpenClaw 修图（摩托改红色、双图合成）成功 |
| 作者判断 | 「AMD 给 395 的定位是开发测试终端，只能解决能不能运行，不解决运行速度」 |
| 作者建议 | 「对智能要求不高可选 IQ4、IQ3，速度还能提升」 |

**这是同类硬件上的同场景部署，可对标性极高**（同 SoC、同 128 GB 统一内存、同 OpenClaw、同 MTP 分支）。

---

## 三、模型技术事实（官方口径）

来源：`qwen.ai/blog?id=qwen3.8-flash-next`

| 项 | 值 |
|---|---|
| 总参 | 180B = **125B 主模型** + **51B n-gram Embedding** + 4B MTP |
| 每 token 激活 | **6B**（MoE 512 专家，top-10 + 1 共享） |
| 层结构 | 48 层，hidden 2560，12 组「3×(GDN→MoE) → 1×(QSA→MoE)」 |
| 上下文 | 原生 262,144，YaRN 可至 1,000,000 |
| Prefill 加速 | 1M 上下文下最高 **7.6×**（对 Qwen3.7-Plus） |
| Decode 加速 | 1M 上下文下最高 **4.9×** |
| 前缀缓存吞吐 | **8.6×** |
| 训练成本 | 前代 **1/9** |
| AA 智能指数 | 56（同类开放权重中位数 28） |

**对本机的意义**：48 层里只有 **12 层是 QSA 稀疏注意力**，其余 36 层是 GDN 线性注意力（固定状态）。
KV 是「小 KV + 大固定状态」结构，与本机现役 35B-A3B 的「10 层 attention + 30 层 SSM」同构 ——
**这就是为什么它可以吃 262144 上下文而不炸显存**，也是本机 prompt-cache 落显存改造能直接复用的原因。

---

## 四、本机对账

| 项 | titan909 视频 | 本机现役 | 差 |
|---|---|---|---|
| 权重 | unsloth UD-Q4_K_XL **111.3 GB** | ROCmFP4-FAST-imatrix-v2 **93.48 GB** | −17.8 GB |
| n-gram 表（engram） | 28.8 GB，**含在权重内上卡** | 22.40 GB，**`--ngram-on-disk` 落 NVMe** | 关键分歧 |
| 显存占用 | ≈101 GB | 90.6 GB @ `-c 262144` | −10.4 GB |
| decode | 40 t/s（日常峰值） | **35.4~39.2 t/s** | **打平** |
| prefill | 27K → **300 t/s** | 27K 级 **38~80 t/s** | **−4~8×** |
| 引擎 | unsloth MTP 分支 | 自建 fork build 10824（Vulkan，qwen4exp 原生支持含 QSA/PLE） | 本机更底层 |
| 上下文 | 256K | 262144 | 同 |

**decode 说明本机的量化取舍没有吃亏**：ROCmFPX 3.5 bpw vs UD-Q4_K_XL ≈ 4.5 bpw，
单 token 读字节少，抵消了反量化开销。

**prefill 差距不是调参能解决的**，是结构性的：
`--ngram-on-disk` 每次 gather 都要按 token 做 **16 次不相关哈希偏移的 pread**（源码 `llama-ple-disk.h:15`），
27K token prefill = **432,000 次随机 4 KiB 读**。视频方案把这张表整个放进显存，没有这个放大。

**这是 96 GiB 下的必然取舍**：表上卡就要多 22.4 GB，262144 上下文直接不可能。

---

## 五、硬约束：视频命令为什么本机跑不了

96 GiB carve-out = **103,079,215,104 B = 103.08 GB**

| 组合 | 显存需求 | 判定 |
|---|---:|---|
| UD-Q4_K_XL 111.3 GB + KV/compute ≈19.5 GB | **≈130.8 GB** | ✗ 超 27.7 GB |
| UD-IQ4_XS 93.7 GB 全上卡 + ≈19.5 GB | **≈113.2 GB** | ✗ 超 10.1 GB |
| UD-Q3_K_XL 89.5 GB 全上卡 + ≈19.5 GB | ≈109.0 GB | ✗ 超 5.9 GB（边界，有风险） |
| **UD-IQ4_XS 93.7 GB，表 28.8 GB 落盘** | **≈84.4 GB** | ✓ 余 18.6 GB |
| 现役 ROCmFP4 93.48 GB，表 22.4 GB 落盘 | 90.6 GB（实测） | ✓ 余 12.5 GB |

> 体积来源：`hf-mirror.com/api/models/unsloth/Qwen3.8-Flash-Next-GGUF?blobs=true` 实测，
> UD-IQ3_XXS 83.6 / UD-Q3_K_XL 89.5 / UD-IQ4_XS 93.7 / UD-Q4_K_XL 111.3 / engram 28.8 / MTP(Q8_0) 4.1 GB

---

## 六、真正的「提升」路径：UD-IQ4_XS + 表落盘

**逻辑**：既然表无论如何都要落盘（否则 262144 上下文不可能），那么**换一张更准的表**就是纯收益。

| 维度 | 现役 ROCmFP4-FAST | 建议 UD-IQ4_XS | 变化 |
|---|---|---|---|
| 权重体积 | 93.48 GB | 93.7 GB | 持平 |
| 上卡主体 | 66.2 GiB | ≈60.5 GiB | **−5.7 GiB** |
| 落盘表 | 22.40 GB（3.5 bpw，Q3_0_ROCMFPX） | 28.8 GB（≈4.5 bpw） | **检索精度↑** |
| 量化方式 | 均匀 ROCmFPX | Unsloth **Dynamic v3.1**（门控/骨干专家 Q5_0 保护，长尾专家深压） | 结构性 |
| 基准恢复率 | — | 12 项基准 **99.4%~99.9%**（传统均匀量化 89%~96%） | 来源：Unsloth v3.1 实测 |
| DeepSWE v1.1 | — | 58.4（超 BF16 基线 55.8） | 长程代码修复 |
| Terminal Bench 2.1 | — | 70.8（超 BF16 基线 68.3） | 终端多步排障 |
| 预期 decode | 35.4~39.2 t/s | **38~42 t/s**（读字节 −8.7%） | ⚠ 推算，待实测 |
| 预期 prefill | 38~80 t/s | 38~80 t/s（同为磁盘随机读） | 无改善 |

> ⚠ 诚实披露：`--ngram-on-disk` 路径的 prefill 与表精度无关，只与随机读次数有关。**这条路不解决 prefill**。
> 社区同源文章也记录了 UD 动态量化的代价：Fresh Prefill 衰减约 40~45%（`mp.weixin.qq.com` 寂寞的熊猫实测）。

**要改善 prefill 只有三条路**（按性价比排序）：

1. **`--ngram-cache` 从 512 MiB 提到 4096 MiB** —— 直接提高行命中率。
   代价：吃 host RAM（现 host avail 常态 6~14 GB，需实测确认不触发 swap）。
2. **`-ub` 从 1024 提到 2048** —— 单 batch gather 并行度翻倍（社区 benchmark 用 `-ub 2048`）。
   代价：compute buffer 变大，需重新核显存余额。
3. **放弃 262144，降到 `-c 65536` 换表上卡** —— 文献记录 `-c 65536` 时显存 79.2 GB，仍有余量；
   但 262144 是本机所有应用链路的前提，**不推荐**。

---

## 七、按场景给结论

| 场景 | 现役 35B-A3B Q5_K_P | Qwen3.8-Flash-Next | 判定 |
|---|---|---|---|
| **WorkBuddy 交互编码**（本机主用） | decode **76.3**，prefill 27.8K→**935**、100K→**463** | decode 37，prefill 27.8K→**50~80** | **✗ 净负**，prefill −92% 会毁掉交互体验 |
| OpenClaw 定时任务（视频场景） | decode 76.3 | decode 37 | **✓ 净正**，智能提升 > 速度损失 |
| sd.cpp 视频生成共存 | 占 33.4 GiB，余 62.6 GiB | 占 90.6 GiB，**余 12.5 GiB** | **✗** 视频链路会被挤死 |
| prompt cache 落显存 | 余量充裕 | 余量吃紧 | ⚠ 需重算 cache 预算 |

**核心判定：这不是「提升」，是场景置换。** 视频作者自己说得很清楚 ——
他的智能体跑的是定时任务，「对速度要求不高，对智能程度要求高」。
本机 WorkBuddy 是**同步交互**，prefill 就是首字延迟，463 → 65 t/s 意味着 100K 会话每次等 25 分钟。

---

## 八、待验证项（可执行）

| # | 假设 | 验证方式 | 判据 |
|---|---|---|---|
| 1 | UD-IQ4_XS 能被本机 fork 加载（架构名 qwen4exp / 张量名 `per_layer_token_embd` 对齐） | `llama-server -m UD-IQ4_XS-00001-of-00003.gguf --ngram-on-disk` 看加载日志 | 无 `unknown architecture` / `tensor not found` |
| 2 | UD-IQ4_XS decode 优于 ROCmFP4 | 预热 2 次丢弃 + A/B 交错，读 `timings.predicted_per_second` | ≥ 38 t/s 才算赢 |
| 3 | `--ngram-cache 4096` 改善 prefill | 同 prompt 冷 prefill 对比 512 vs 4096 | 提升 ≥ 15% 且 host avail 不跌破 4 GB |
| 4 | `-ub 2048` 改善 prefill | 同上 | 提升 ≥ 10% 且显存不超 100 GiB |

> 验证前必读铁律：实例一律经 MCSManager 面板启动，禁止裸跑；改参数改 `start-qwen38-imatrix-v2.sh`。
> 压测禁止分组 A/B，必须预热 2 次丢弃 + A/B 交错 + 另跑无干扰对照。

---

## 九、来源

| 内容 | 来源 |
|---|---|
| 视频文案全文 | https://m.toutiao.com/article/7682773416826389035（今日头条同文） |
| 案例库条目 | https://ima.qq.com/wiki/?shareId=927a440bb321810b3a4a728eceeb3dcdfdfc90012f70f3398b36d7dc8846b71b |
| 官方架构说明 | https://qwen.ai/blog?id=qwen3.8-flash-next |
| 各量化体积 | https://hf-mirror.com/api/models/unsloth/Qwen3.8-Flash-Next-GGUF?blobs=true |
| PLE 磁盘读源码 | `$HOME/llama-qwen4exp-rocmfpx/src/llama-ple-disk.h:12-30` |
| 本机现役实测 | `Qwen3.8-imatrix-v2-ngram-on-disk-方案.md` 第四节 |
| 第三方榜单 | https://new.qq.com/rain/a/20260828A04G0L00 |

---

> 许可：CC0-1.0，公共领域贡献，无任何限制。
