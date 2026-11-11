# Strata 方案：结合社区经验的收益预测（社区证据折算与四场景决策矩阵）

日期：2026-11-06
对象：AMD Ryzen AI MAX+ 395 / Strix Halo / gfx1151 / 128 GiB 物理统一内存主机
上承：`2026-11-06-Strata方案-本地部署可行性与对比分析.md`
任务原话：`结合社区经验，给出收益预测`

---

## 一、口径声明（先立规矩，再给数字）

1. **对照物固定**：所有倍数均相对「本机当前生产链路」= `llama-qwen4exp-rocmfpx/build-vk4/bin/llama-server`（Vulkan）+ 35B-A3B Q4_K_P + MTP `n-max=2` + q8_0 KV + `--cache-idle-slots`，即 `2026-10-03-35B速度复测.md` 的实测基线。
2. **不跨表直比**（沿用官方 `Compare numbers within one table, not across`）。异机数据只迁移「比值」，不迁移「绝对值」。
3. **官方自测一律打折**：维护者自测 / 宣传口径标 `[UNVERIFIED]`，用社区独立复现结果做校准。
4. **外部数据先校验**：数值范围、口径、硬件一致性检查不通过者标 `[UNVERIFIED]` 并剔除出基准，不得进入决策。
5. **预测输出格式**：区间 + 置信度 + 推导依据 + 风险 + 回滚。不使用「大概 / 可能 / 我认为」。

---

## 二、本机基线（决策锚点）

| 指标 | 值 | 来源 |
|---|---:|---|
| 35B-A3B decode 中位 | **90.14 t/s** | `2026-10-03-35B速度复测.md` |
| 长 prefill（89K tokens / wall 171 s） | **≈ 520 t/s** | 同上 |
| MTP 累计接受率 | **77.4%** | 同上 |
| 27B dense ROCmFP4 decode | 22.4 t/s（带宽墙 ~23） | `~/.workbuddy/MEMORY.md` |
| MoE 每 token 权重读取量 | ≈ 1.6 GB（激活 3B） | 同上 |
| 推算有效带宽 | **≈ 144 GB/s**（1.6 × 90.14） | 本次推导 |
| BIOS UMA carve-out / host MemTotal / MemAvailable | **96.00 / 30.47 / 16.35 GiB** | `2026-11-06-Strata方案-本地部署可行性与对比分析.md` 第三节 |
| GTT Total | 30.47 GiB = host MemTotal | 同上 + 项目 `MEMORY.md` GTT 口径澄清 |
| 视频栈显存需求 | MiniMax-H3 四组件 40.85 GiB 全落 carve-out | 项目 `MEMORY.md` 第七节 |
| SoC 功耗墙 | **120 W 锁定**，满载 average = current = 120.01 W | 项目 `MEMORY.md` / 2026-10-30 实测 |

> **带宽余量判定**：LPDDR5X-8000 256-bit 理论带宽 256 GB/s，本机实测有效 ≈ 144 GB/s（约 56%）。decode 已接近内存带宽主导区，引擎层优化的可提升空间被物理带宽与 120 W 功耗墙双重压缩。

---

## 三、社区证据与折算系数

| # | 证据（原文要点） | 来源 | 折算 / 用途 | 置信度 |
|---|---|---|---|---|
| E1 | `community tests show about 2x llama.cpp speed, versus the advertised 6x` | himiao.ai | **官方 6× → 社区 2×，折扣系数 0.33** | 中 |
| E2 | `About twice my best llama.cpp number, with no hardware changes`（RTX 4070 + 64GB DDR5，60K ctx，53.2 vs 27 t/s），并自述 not controlled experiment | digestai.news | 印证 2× 收敛 | 中 |
| E3 | 「对上调好的 MTP 版 llama.cpp，持续差距其实更接近 2 倍，而不是早期流传的 5–10 倍」；5070ti 43K ctx `Strata 51 vs llama.cpp 23`；Carteakey 60K `53.2 vs 20.8` | 微信公众号横评 | **关键**：本机已调优，应取此收敛值而非 5–10× | 中高 |
| E4 | `llama.cpp runs the model too, and was about 5x slower on prefill for me` | offsite.guru/blog/halogen-strix-halo | prefill 上限参考（短窗口/热态） | 中低 |
| E5 | `amd_iommu=off is the one setting upstream actually measured: worth 13-16% of prefill` | 同上 | 唯一有量化实测的开关 → +13~16% prefill | 中高 |
| E6 | `512 MiB BIOS UMA` + large GTT + new RADV + FA + no-mmap：`+18.4% PP, +1.5% TG, +5.9% combined`（Vulkan/RADV 198.53 PP / 17.34 TG / 62.84 combined vs ROCm 188.03 / 15.65 / 57.58）；结论 `faster than ROCm 10.0` | github.com/ddifofeu/strix-halo-128gb-llm-guide | 场景 D 调优点；**Vulkan 并不弱于 ROCm** | 中 |
| E7 | `96 GB (current) ~32 GB ... Too aggressive— starves the OS`；推荐 `Auto / 512 MB`；`ttm.pages_limit=32000000`；`IOMMU Off ~6% memory bandwidth improvement` | community.qtorque.io/jstormes/StrixHalo | 场景 C 容量前提 | 中 |
| E8 | `Long prompts ... HIP wins by +42 to +48%`；`Long generation ... Vulkan wins by +13 to +19%` | github.com/nabe2030/hip-vs-vulkan-evo-x2 | **HIP 在 decode 端反而吃亏** → 抵消 Strata 引擎收益 | 中高 |
| E9 | `Vulkan outperforms ROCm by 19-22 percent on Q4_K_M decode`；`ROCm outperforms Vulkan by 117-121 percent on BF16 decode`；`GGML_HIP_ROCWMMA_FATTN=OFF ... up to 145% higher prefill at 8K` | Zenodo 论文 | Q4 量化下 Vulkan 更优；BF16 结论不适用本机 | 中高 |
| E10 | llama.cpp HIP+WMMA+FA `50.97 / 368.77`；Vulkan Q4_0 `45.8 / 998`；无 FA 8K gen `7.54`；CPU only `28.94 / 294.64` | datahardware.ai/tools/benchmarks | 后端开关可造成 6.4× 摆动 → 场景 D 价值 | 中 |
| E11 | Strata 官方 Linux 128GB gfx1151 0.1.40：8K prefill 1242–1293 t/s、decode 42.8–59.7 t/s（维护者自测） | `docs/STRIX_HALO.md` | `[UNVERIFIED]`，仅作上界参考 | 低 |
| E12 | `Default (Windows) 96.0 GB ... Net 84.5 GB`；`Tuned headless Linux 119 GB ... Net 113 GB` | willitrunai.com | 改 BIOS 的容量收益上界 | 中 |

### 合理性校验（剔除 / 降权项）

| 数据 | 校验结果 | 处置 |
|---|---|---|
| GitCode 横评 RTX 5070 prefill `1600 vs 183` = 8.7×，decode `54 vs 15` = 3.6× | 同一来源内部：prefill 倍数与 decode 倍数差 2.4 倍，且与 E1/E2/E3 的「约 2×」冲突 → 判定为短窗口 / 热态 / 单次测量 | `[UNVERIFIED]`，**不进入基准** |
| 官方 0.2.9 宣称 1.6–1.8× prefill 提速 | 官方原文 `Linux gfx1151 keeps the opt-in above until it is measured there` → Linux 未测 | 不计入场景 B |
| Vulkan Q4_0 prefill 998 t/s（E10） vs 本机 520 t/s（89K） | 短窗口 vs 89K 长上下文，窗口长度差一个量级 | 禁止直比 |
| Zenodo BF16 decode ROCm +117–121%（E9） | 本机为 Q4_K_P / q8_0 KV，量化格式不符 | 不适用，剔除 |
| E2 的 53.2 t/s、E3 的 51 t/s、E11 的 53.8 t/s | 硬件为 RTX 4070 / 5070ti / gfx1151 且模型量级不同（125B Flash-Next vs 本机 35B-A3B） | 只用比值，不用绝对值 |
| `willitrunai.com` `Qwen3.8 Flash Next ~28.6 tok/s` | 与本机 35B-A3B 90.14 t/s 属不同模型 | 不直比 |

### 社区倍数收敛结论

```
官方宣称       5–10×  ──┐
社区独立复现   ~2×    ──┼── 折扣系数 0.25–0.40
对已调优 MTP   ~2×    ──┘
本机折算       0.9–1.4×  ← 再扣 MTP 77.4% 接受率 + HIP decode 劣势 13–19%
```

---

## 四、四场景收益预测

### 场景 A：现状直上 Strata（不改 BIOS、不换栈）

| 项 | 预测 |
|---|---|
| 配置变更 | 仅新增 Strata 面板实例，端口 8082，下载官方 pack 到 `$HOME/models` |
| 可用显存 | **`device_free_bytes()` ≈ 8.4–10.4 GiB**。口径 A：`MemAvailable 16.35 − 6 GiB = 10.35`（`docs/STRIX_HALO.md` 原文）；口径 B：`16.35 − 8 GiB desktop reserve = 8.35`（前份报告 4.3 节，取 `max(8 GiB, 8% RAM)`）。前份报告两处数字不一致，此处以区间统一 |
| 容量缺口 | 最小 pack Q2_0 需 37.6 GB → 缺 27–29 GiB → 必走 SSD Engram 分层，官方原话 `works and is much slower` |
| decode | **0.3–0.8× 基线**（等价 27–72 t/s，且随 SSD 命中率剧烈抖动） |
| prefill | **0.2–0.6× 基线** |
| MTP 接受率 | 无法达到本机 77.4%，分层调度引入额外延迟 |
| 净收益 | **负** |
| 置信度 | **中高**（容量约束是算术事实，非 benchmark） |
| 风险 | 复现 2026-10-08 全局 OOM（HIP 分配 20 GiB 时 host available 仅 494 MiB）；SSD 磨损；与 sd.cpp / 8080 争用 |
| 附加成本 | 70 GB+ 下载（`github.com` 直连 TLS 中断需走 `gh-proxy.com`），且 ROCmFP4 type 101 私有量化不可用 |
| 建议 | **不执行** |

### 场景 B：隔离 PoC（改 BIOS 为大 GTT / 小 carve-out，单独跑 Strata）

| 项 | 预测 |
|---|---|
| 配置变更 | BIOS UMA `96 GiB → 512 MiB`（或 64 GiB 折中档）+ `ttm.pages_limit/page_pool_size≈29360128` + `amd_iommu=off` + headless + 新 RADV + `--no-mmap` + FA；**期间停用现有 Vulkan 栈** |
| 容量收益 | OS 可见 RAM `30.47 → ~110–120 GiB`（E7/E12）、`device_free_bytes ≈ 100–113 GiB` — **唯一确定的正收益** |
| decode（相对同机未调优 llama.cpp） | **2.0–2.6×**（E1/E2/E3 收敛值） |
| decode（相对本机已调优 90.14 t/s） | **0.9–1.4×，中位 1.1×**。推导：① 本机 MTP 接受率 77.4%，已把 decode 推到 ≈144 GB/s 有效带宽；② E8/E9：`Long generation ... Vulkan wins by +13 to +19%` / `Vulkan outperforms ROCm by 19-22% on Q4_K_M decode`，HIP 后端先天吃亏 13–19%，直接抵消引擎层收益；③ E1/E3 的 2× 对照物是未调优 llama.cpp |
| prefill（热态短窗口） | **1.5–3×**（E4 的 5× 因对照物已调优而折半） |
| prefill（冷态长上下文 89K） | **1.0–1.8×**；叠加 `amd_iommu=off` +13~16%（E5）后上限 ≈ **2.1×** |
| 净收益 | **容量显著为正，速度中性偏微正** |
| 置信度 | **低**（gfx1151 官方标 `experimental`，无本机 head-to-head，社区横评全在 NVIDIA / Apple 硬件） |
| 风险 | 中文输出质量：`Coder quant systematically breaks Chinese output`（himiao.ai）；改 BIOS 需重启；70 GB+ 下载；Strata 0.2.9 的 prefill 提速在 Linux gfx1151 未测 |
| 建议 | 仅在「验证专家分层机制」为唯一目的时做，且必须可回滚 |

### 场景 C：永久切换到大 GTT / 小 carve-out，仍保留混合负载

| 子场景 | 预测 |
|---|---|
| C1 `512 MiB UMA` | carve-out 塌到 0.5 GiB。现有 35B-A3B Q4_K_P（~31 GiB）、Q5_K_P（43.7 GiB）、MiniMax-H3（40.85 GiB）**全部无法加载** → 文本链路与视频链路净收益 **−80%~−100%** |
| C2 折中 `64 GiB UMA` | carve-out 64 GiB 仍可单跑 35B Q4_K_P（余 33 GiB），但 Q5_K_P + MiniMax-H3 无法并存；host 可见 64 GiB → `device_free_bytes ≈ 58 GiB`，仍不足 UD-IQ4_XS 需 72 GB → Strata **仍部分走 SSD** |
| 净收益 | **负** |
| 置信度 | **高**（架构决定，不依赖 benchmark） |
| 依据 | E7 的 `512 MiB UMA` 经验来自 **headless 专用模型服务器**；本机是「桌面 + WorkBuddy 生产 + docproxy + sd.cpp 视频生成」混合布局，前提不成立。E6/E7 明确 `96 GB ... Too aggressive— starves the OS` 只针对纯 HIP 负载 |
| 建议 | **不执行** |

### 场景 D：不引入 Strata，只移植社区调优点到现有栈（唯一低风险正收益）

| 调优点 | 单项预测 | 来源 | 置信度 | 是否改 BIOS |
|---|---|---|---|---|
| `amd_iommu=off` | prefill **+13~16%**；内存带宽 **+6%** | E5、E7 | 中高 | 否（内核 cmdline，需重启） |
| 新 RADV / Mesa（26.2.3 级） | PP **+18.4%**、TG **+1.5%**、combined **+5.9%** | E6 | 中 | 否 |
| Flash Attention + `--no-mmap` | 未单独量化；E10 显示「有无 FA」可造成 8K gen `7.54 → 50.97 t/s` 级差 | E6/E10 | `[UNVERIFIED]` | 否 |
| headless（关桌面合成器） | 释放 host RAM 与 120 W 功耗预算，定性 | E7 | `[UNVERIFIED]` | 否 |
| 限 CPU 频率让功耗给 iGPU | decode **+5~8%**（120 W 墙下重分配，非超频） | 项目 `MEMORY.md` 2026-10-30 | `[UNVERIFIED]` | 否 |
| `GGML_HIP_ROCWMMA_FATTN=OFF` | 8K prefill 最高 +145% | E9 | — | **不适用**（仅 HIP 路径，本机走 Vulkan） |
| 组合上限 | **prefill +15~35%，decode 0~+8%**；**不改变 90.14 t/s 量级** | 本次推导 | 中低 | 否 |

> 硬约束：decode 上限受 **120 W SoC 功耗墙** 与 **≈144 GB/s 有效带宽** 双重限制，任何软件调优都无法把 35B-A3B 推到 2×。
> 执行纪律：逐项 A/B 隔离测试，每项单独回滚；不得一把梭。prompt 必须带随机 uuid 前缀规避 LCP 复用（项目 `MEMORY.md` 第八节）。

---

## 五、总判定矩阵

| 场景 | decode | prefill | 容量 | 净收益 | 置信度 | 执行 |
|---|---:|---:|---|---|---|---|
| A 现状直上 Strata | 0.3–0.8× | 0.2–0.6× | 8.4–10.4 GiB（不足） | **负** | 中高 | 否 |
| B 隔离 PoC（大 GTT） | 0.9–1.4× | 1.0–2.1× | 100–113 GiB | **容量正 / 速度中性** | 低 | 有条件 |
| C 永久切换大 GTT | −80%~−100% | — | — | **负** | 高 | 否 |
| D 只移植社区调优点 | 1.0–1.08× | 1.15–1.35× | 不变 | **微正** | 中低 | **是** |

---

## 六、决策建议（按优先级）

1. **维持现状**：96 GiB UMA + Vulkan + MTP 不变，Strata 不进生产。理由：场景 A/C 净收益为负且置信度高；场景 B 的速度收益被 HIP decode 劣势与已调优 MTP 抵消。
2. **执行场景 D**：先做 `amd_iommu=off` 单项 A/B（唯一有 upstream 量化实测），再做 RADV 版本、FA / `no-mmap`、headless、CPU 限频。预期 prefill +15~35%，成本为零（不改 BIOS、不动生产实例、可逐项回滚）。
3. **场景 B 仅在需要验证专家分层机制时执行**，且需少爷授权：改 BIOS + 重启 + 70 GB+ 下载 + 单独面板实例（端口 8082）+ 停用视频链路。跑完改回 96 GiB。
4. **若目标是突破 decode**，方向不是换引擎：受 120 W 功耗墙与带宽墙限制，可行路径是 BIOS 调 PPT/TDP 档位（55/80/120 W）或换激活参数更小的模型，而不是引入 Strata。
5. **若要 Anthropic Messages / Responses API**，成本最低是给 18090 docproxy 加 `/v1/messages` 转换层，不引入 Strata（沿用前份报告结论）。

---

## 七、回滚方案（可回滚原则，执行场景 B/D 前必须落盘）

| 变更 | 快照 / 回滚 |
|---|---|
| BIOS UMA 96 GiB → 512 MiB / 64 GiB | 记录当前 UMA 值与 BIOS 版本；回滚 = 改回 96 GiB + 重启 |
| `/etc/default/grub`（加 `amd_iommu=off`、`amdgpu.gttsize`、`ttm.pages_limit`） | 改前 `cp /etc/default/grub /etc/default/grub.bak.YYYYMMDD`；回滚 = 还原 + `update-grub` |
| `/etc/modprobe.d/amd_ttm.conf`（`pages_limit=25600000`） | 改前 `cp` 到 `.bak.YYYYMMDD`；当前值已记入项目 `MEMORY.md` |
| MCSManager 实例 | 导出 `InstanceConfig/*.json`；35B uuid `9770784bb1f940ada5c5890fd003efb3`、docproxy uuid `d81ea6096b1c46709f9d9b43fc8137f7` 不变 |
| 端口 | Strata 固定 8082，不动 8080（llama-server）/ 18090（docproxy） |
| 模型 | 一律下载到 `$HOME/models`，不覆盖、不删除现有 GGUF |
| 复测方法 | `tools/bench-35b-20261003.py`，随机 uuid 前缀规避 LCP 复用，纯文本请求 |

---

## 八、来源清单

**本机（一手）**
- `$HOME/WorkBuddy/调试本地模型/2026-10-03-35B速度复测.md`
- `$HOME/WorkBuddy/调试本地模型/2026-11-06-Strata方案-本地部署可行性与对比分析.md`
- `$HOME/WorkBuddy/调试本地模型/.workbuddy/memory/MEMORY.md`
- `$HOME/.workbuddy/MEMORY.md`
- `https://raw.githubusercontent.com/Niko1221/Strata/main/docs/STRIX_HALO.md`

**社区（外部，已校验）**
- `https://himiao.ai/`（社区复现 ~2× vs 宣传 6×；Coder quant 中文输出问题）
- `https://digestai.news/`（RTX 4070 + 64GB，60K ctx，53.2 vs 27 t/s）
- 微信公众号 Strata vs llama.cpp 横评（5070ti 43K ctx 51 vs 23；调好 MTP 后差距约 2×）
- `https://offsite.guru/blog/halogen-strix-halo`（512MiB UMA；prefill 5×；`amd_iommu=off` +13~16%）
- `https://github.com/ddifofeu/strix-halo-128gb-llm-guide`（512 MiB UMA + 大 GTT + new RADV + FA + no-mmap；+18.4% PP / +5.9% combined）
- `https://community.qtorque.io/jstormes/StrixHalo`（96 GiB 过激；IOMMU Off +6% 带宽）
- `https://datahardware.ai/tools/benchmarks`（HIP+WMMA+FA / Vulkan Q4_0 / CPU only 对比）
- `https://github.com/nabe2030/hip-vs-vulkan-evo-x2`（长 prompt HIP +42~48%；长 generation Vulkan +13~19%）
- Zenodo Strix Halo Vulkan/ROCm 基准论文（Q4_K_M / BF16 decode；ROCWMMA_FATTN）
- `https://chooseto.ai/`（后端 flags 造成 6.4× 摆动）
- `https://willitrunai.com/`（Net 84.5 GB → 113 GB）
- GitCode 博客（RTX 3060/5070 横评，`[UNVERIFIED]` 已剔除出基准）
- `https://modelfit.io/`（M5 Max 侧 ~1.9×，仅作比值旁证）

---

## 九、待核项

1. 35B 长 prefill 旧记录「308 KB 请求体 → ≈26 s」与 2026-10-03「89K tokens / 171 s / 520 t/s」口径差异，下次长 prefill 复测时校准。
2. 本机 `Qwen3.8-Flash-Next-ROCmFP4-FAST-imatrix-v2.gguf`（88 GiB）无 decode 实测记录，无法给出与 Strata 官方 125B 数字的同模型差值。
3. `docs/STRIX_HALO.md` 的 `MemAvailable less 6 GiB` 与前份报告 4.3 节的 `max(8 GiB, 8% RAM)` 两处 reserve 口径不一致，场景 A 已用区间 8.4–10.4 GiB 覆盖；若做 PoC 应以实际 `strata` 启动日志中的 `device_free_bytes()` 为准。
4. 场景 D 各开关的组合收益来自不同机器 / 不同后端，非本机实测；必须逐项 A/B 后才可写入性能基线。

---

**许可**：CC0-1.0，公共领域贡献，无任何限制。
