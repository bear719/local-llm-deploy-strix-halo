# Gufo GPU+NPU 分摊 prefill 方案 — 本机适配性判定（含一手证据修正）

日期：2026-11-11　对象：titan909《CPU+NPU 跑 Gufo 提升 Qwen3.8-Flash-Next prefill》
证据等级：本机实测 + GitHub 一手 PR/issue，**不采信二手媒体转述**

---

## 一、结论（含对上一份分析的重大修正）

| # | 判定 |
|---|---|
| 1 | **视频的核心卖点不成立**：NPU offload 在 `gufo serve llm` 里**结构上不可达**，只有 `gufo bench` 能触发。给 WorkBuddy / OpenClaw 提供 API 的服务模式下，NPU 一个 token 都不会算 |
| 2 | **性能数字被二手渠道放大**：llamaperf 报的 Flash-Next 2125 t/s 是社区 fork 自报，**Gufo 官方明确写 "We have not reproduced them"**；官方自己评估同一 fork 的分歧只有 **+7.2%**（1,698 → 1,821 t/s，bench 模式） |
| 3 | **官方自己的 NPU 实现已被关闭未合并**（PR #568，`merged_at: None`），且有已知数值损坏 bug（PR #1040） |
| 4 | **本机四道硬件门过三道半**：gfx1151 ✓ / IOMMU 开 ✓ / fclk 已锁 2000 MHz 最高档 ✓ / XRT 2.21.75 ✓；**唯一硬阻塞是 host 内存分法**（30.47 GiB vs 需 ~90 GiB） |
| 5 | **真正的 30 倍 prefill 差距来自「引擎 + 表在内存」，与 NPU 无关**：Gufo 纯 GPU 就 1,698 t/s，本机 38~80 t/s |
| 6 | **判定：不跟**。若哪天要追这条路线，目标是「Gufo 引擎 + 大 host 内存」，NPU 部分应当跳过 |

**一句话**：视频标题写的是 NPU，真正值钱的是 Gufo 引擎；而 NPU 那一半，在服务模式下是死的。

---

## 二、视频主张 vs 一手证据对账

### 视频陈述（截图章节）

- 00:05 引言：**最近有开发者利用 CPU+NPU 运行 gufo，提升了 Qwen3.8 Flash Next 的 prefill**
- 00:45 性能对比：不使用 NPU vs GPU+NPU 的 prefill 对比
- 01:10 部署：封装 docker 镜像
- 02:57 结语

### 一手证据（GitHub API，2026-11-11 07:25 抓取）

| 证据 | 内容 | 对本方案的影响 |
|---|---|---|
| **PR #568** `feat(qwen38-flash-next): offload dense prefill projections to the XDNA2 NPU` | `state: closed`，**`merged_at: None`** → 关闭未合并 | 官方路径未进入主线 |
| **PR #558** `perf(npu): overlap deferred prefill projections on XDNA2 (evaluate the mikealanni/gufo fork)` | `state: open`。fork 自报 bench：`-p 16384` GPU-only **1,698** → GPU+NPU **1,821 t/s (+7.2%)**；served 40k cold **1,637**。原文：**"We have not reproduced them"** | 增幅是 **7.2%**，不是 18% |
| **PR #1040** `bug(npu): Flash-Next two-bank prefill returns non-finite logits at 16K` | 16K two-bank 下 `logits_nans=4202496`；**UD-IQ4_XS 3-shard 包在 plain NPU 下也损坏**（`logits_nans=65664`），GPU-only 路径正常 | 数值正确性未过关 |
| **PR #568 评论（qjy0128, 10-22）** | 「NPU 路径能工作，在 `gufo bench` 下有可测量收益，但**它在 `gufo serve llm` 里结构上不可达**：offload 门槛要求 `n_tokens` 是 4096 的精确整数倍，而 server 的 prefill 分块永远不会产生这个数」 | ★ **致命** |
| 环境对齐 | 该评论测试环境：gfx1151 / XDNA2 `RyzenAI-npu5` / FW **1.1.2.65** / **XRT 2.21.75** | **与本机完全一致** |
| 分支实存 | 主线仓库分支 `perf/qwen27b-dflash2-npu`（官方分支，非外部 fork 独有） | 路径存在但不进 serve |

### NPU 到底算了什么（PR #568 技术细节）

不是"分摊每个 projection"，只承担三类 dense 投影：

1. linear-attention `ssm_in` 的 **16 个 1024 行切片中的 6 个**（z rows），在 GDN 扫描后从 NPU stream 直读
2. 16 个 attention head 的 **query 与 gate 行**（`attn_qkv`）
3. **shared-expert 的 gate 与 up 投影**，swiglu 从 NPU stream 计算

启用方式：`-DGUFO_ENABLE_NPU=ON`（需 `GUFO_XRT_INCLUDE_DIR` 头文件）+ 运行时 `GUFO_NPU_DIR=tools/npu`。

---

## 三、本机四道门实测（2026-11-11 07:20）

| # | 门 | 要求 | 本机实测 | 判定 |
|---|---|---|---|---|
| 1 | 芯片 | gfx1151 / Strix Halo | KFD `gfx_target_version=110501` | ✅ |
| 2 | IOMMU | 必须开（NPU 依赖 DMA 翻译） | `/proc/cmdline` 无 `amd_iommu=off`；`/dev/accel0` 在用 | ✅ |
| 3 | fabric clock | 锁最高档，否则 **GPU+NPU 挂机** | `pp_dpm_fclk` 档 7 `2000Mhz *`；`perf_level = high` | ✅ **已规避挂机风险** |
| 4 | NPU 运行时 | XRT + amdxdna | `libxrt2 1:2.21.75`、`libxrt-npu2 1:2.21.75`、`amdxdna-dkms 7.0.0-rc1`、FW 1.1.2.65 | ✅（与证据环境同版本） |
| 4b | XRT **开发头文件** | `GUFO_XRT_INCLUDE_DIR` 需要 | `/usr/include/xrt` **不存在** | ⚠ 缺 dev 包 |
| 5 | **内存分法** | GTT 峰值 **86.85 GiB** | GTT **30.47 GiB** / host total **30 GiB**，available **9 GiB** | ❌ **卡住** |

**四道门过三道半，卡在内存分法。** 这与 11-06 Gufo 判定一致；
新信息是「这个 NPU 分支反过来依赖 NPU，所以 IOMMU 必须开」——本机现状恰好满足。

---

## 四、致命发现：serve 模式结构不可达

这是本次分析最重要的单条事实，直接决定视频价值：

```
gufo bench  -p 16384              → 走 NPU，1,821 t/s  ← 视频演示的就是这个
gufo serve llm（给 OpenClaw/WorkBuddy 提供 API）
    prefill 分块 = 动态 uBatch
    门槛要求    = n_tokens % 4096 == 0
    → 永不满足 → NPU 路径 0 次触发 → 纯 GPU，1,698 t/s
```

**影响**：
- 视频 00:45 的「性能对比」如果是 bench 跑出来的，**对实际部署无意义**
- 本机所有应用（WorkBuddy 18090 / OpenClaw 18789 / judge / docproxy）走的是 **serve**，不是 bench
- 所以即便把 BIOS、引擎、权重全部按视频配齐，**NPU 那部分收益仍然是 0**

**→ 推论：这条路线的正确目标不是 NPU，是 Gufo 引擎本身。**

---

## 五、真实因果链：30 倍差距来自哪

| 环节 | 本机现役 | Gufo（纯 GPU，serve） | 该环节贡献 |
|---|---:|---:|---|
| prefill (Flash-Next) | 38~80 t/s | 1,698~1,801 t/s | — |
| ① n-gram 表位置 | 22.4 GB **落 NVMe**，每 token 16 次随机 pread | 28.8 GB **在 GTT** | **≈20~30×（主因）** |
| ② 引擎内核 | Vulkan + 通用 QSA | HIP 手写 Wave32/64 内核 + 专用 hybrid checkpoint | ≈1.5~2× |
| ③ NPU 分摊 | 无 | serve 下 **不生效** | **0** |

**上一份分析说「prefill 差距是表落盘的必然代价」—— 方向正确。**
本份只补一条：在 serve 场景下，NPU 不是解法，把表搬进内存才是。而本机搬不进去，因为 BIOS 把 96 GiB 切给了显存。

**这形成闭环**：本机 prefill 慢 ↔ 表必须落盘 ↔ 显存占用了物理内存 ↔ 为了跑 35B 需要 96 GiB carve-out。
根子在内存分法，不在引擎选型，更不在 NPU。

---

## 六、三条路线判定（修正后）

### 路线 A — 维持现状 ✅ 推荐

| 项 | 值 |
|---|---|
| BIOS | UMA 96 GiB / host 30.47 GiB |
| 35B-A3B | decode **76.3** / prefill **935** |
| Flash-Next | decode 37 / prefill **38~80** |
| 保留 | sd.cpp 视频、Qwen-Image、prompt cache 落显存、flm NPU、docproxy、MCSManager 托管、Claude Code 链路 |

### 路线 B — Gufo 全量换用途（含 NPU）❌ 否决

| 收益 | 代价 |
|---|---|
| Flash-Next prefill 1,698~1,801 t/s（+22~35×，纯 GPU 即可）<br>长上下文 checkpoint 恢复 0.24~1.38 s（本机 14.3 s） | BIOD UMA→512 MiB，Vulkan 全灭<br>ROCmFP4 93.48 GB 作废，重下 93.7~111.3 GB<br>flm NPU 三模型停（Gufo 独占）<br>**Claude Code 不可用**（Gufo 明确不支持）<br>NPU 部分 **serve 下不生效**（本条即可部分否决） |

### 路线 C — Gufo 纯 GPU + 折中分法（UMA 48 GiB）⚠ 唯一有意义的折中

| 项 | 值 |
|---|---|
| BIOS | UMA **48 GiB** / host **~78 GiB** |
| Vulkan 侧 | 35B Q5_K_P 33.4 + KV 2.92 + prompt cache 2.2 ≈ **38.5 GiB < 48** ✅ 262144 保住 |
| Gufo 侧 | 需 host ≥ 93.7 GB 才能跑 Flash-Next UD-IQ4_XS → **78 GiB 不够，拿不到**<br>35B-A3B Q6dense ≈ 28 GB 可跑，但 **Gufo `docs/models/` 至今无 35B 目录**（issue #889 仍关），3276 t/s 为官方 benchmark 口径，**serve 下实测未知 [UNVERIFIED]** |
| 代价 | 35B 与 sd.cpp 视频（40.85 GiB）不再能同时驻留 |
| 判定 | **风险大于收益**。为了一个未进 docs 的模型路径，牺牲双模型并行能力，不划算 |

---

## 七、为什么「多用途」与「Gufo」互斥

| 依赖 | 需要的分法 | 冲突 |
|---|---|---|
| llama.cpp Vulkan 96 GiB 栈 | 大 carve-out | 与 host 大内存零和 |
| sd.cpp 视频（MiniMax-H3 40.85 GiB） | 大 carve-out | 同上 |
| prompt cache 落显存（fork 改造） | 大 carve-out + host-visible | 同上 |
| flm NPU 三模型 | NPU 独占 | 与 Gufo NPU 零和（NPU 严格串行） |
| Gufo | 大 host + NPU | 与上面全部冲突 |

---

## 八、风险清单

| # | 风险 | 严重度 | 说明 |
|---|---|---|---|
| 1 | **NPU serve 不可达** | 致命 | 决定了本方案对生产无价值 |
| 2 | NPU 数值损坏 | 高 | PR #1040：16K two-bank `logits_nans=4202496`；UD-IQ4_XS 包直接坏 |
| 3 | 官方未复现 fork 数据 | 高 | PR #558 原文 "We have not reproduced them" |
| 4 | GPU+NPU 并发挂机 | 中 | 本机 fclk=2000 MHz 已锁，风险已规避；改 BIOS 后需复核 |
| 5 | XRT dev 头文件缺失 | 低 | 需装 `libxrt-dev` 类包才能 `-DGUFO_ENABLE_NPU=ON` |
| 6 | Gufo 日更 | 中 | 一周 3 版，锁 tag |
| 7 | podman 与 MCSManager 铁律 | 中 | 需 `start-gufo.sh` 前台 `exec podman run` 包一层 |

---

## 九、已完成的验证（本轮已做，无需重复）

| # | 项 | 结果 |
|---|---|---|
| 1 | Gufo NPU 分支是否真实 | ✅ 存在，主线分支 `perf/qwen27b-dflash2-npu`，但 PR #568 关闭未合并 |
| 2 | 官方是否复现社区数字 | ❌ **未复现**（PR #558 明文） |
| 3 | NPU 在 serve 是否生效 | ❌ **结构上不可达**（qjy0128，环境与本机同版本） |
| 4 | 本机硬件四道门 | 3/4 过 + 缺 XRT dev 头 |
| 5 | 本机内存是否够 | ❌ GTT 30.47 GiB vs 需 86.85 GiB |

**剩余唯一值得做的动作**：无。本方案对本机已闭环否决。

---

## 十、来源

| 内容 | 来源 |
|---|---|
| 视频章节与陈述 | 用户截图（titan909，07:16） |
| NPU offload 实现细节 + 未合并 | `api.github.com/repos/gufo-org/gufo/issues/568` |
| 官方未复现 fork 数据 + 7.2% | `api.github.com/repos/gufo-org/gufo/issues/558` |
| 数值损坏 bug | `api.github.com/repos/gufo-org/gufo/issues/1040` |
| serve 模式不可达 | PR #568 评论 qjy0128（2026-10-22，XRT 2.21.75 / FW 1.1.2.65） |
| Gufo 支持模型清单 | `api.github.com/repos/gufo-org/gufo/contents/docs/models`（**无 35B**） |
| 35B-A3B 支持请求 | issue #889（已关闭，docs 未收录） |
| 二手报道（2125 t/s，已被本报告降级） | https://llamaperf.com/report/d439a4f7-8010-4f12-b5dc-97b8bbf4a36c |
| Gufo 主线 benchmark | https://discovergit.app/repo/gufo-org/gufo（Flash-Next 1,801.01 pp / 73.17 tg） |
| 长上下文 checkpoint | https://thenextgentechinsider.com/pulse/gufo-unveils-specialized-caching-for-hybrid-ai-models-on-amd-strix-halo-hardware |
| 本机硬件实测 | `/proc/cmdline`、`pp_dpm_fclk`、`dpkg -l`、`free -g`、`mem_info_gtt_total` |

---

> 许可：CC0-1.0，公共领域贡献，无任何限制。
