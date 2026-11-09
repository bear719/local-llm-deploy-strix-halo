# Halogen 与 Gufo：本机适配性对比判定

日期：2026-11-07 03:50 GMT+8
对象：AMD Ryzen AI MAX+ 395 / Strix Halo / gfx1151 / 128 GiB 物理统一内存主机
上承：`2026-11-06-Gufo方案-本地部署可行性分析.md`、`2026-11-06-Strata方案-本地部署可行性与对比分析.md`、`2026-11-06-Strata方案-社区经验收益预测.md`

---

## 一、结论（先给判定）

**分层判定，不给单一「谁更好」：**

| 场景 | 判定 |
|---|---|
| **A. 部署进当前生产机（不改 BIOS）** | **两者都不适合，物理上起不来。** Gufo 连最小的 27B Q4 都差 8.67 GiB；Halogen 在 GTT < 103 GiB 时 `cannot allocate at all`，本机差 72.53 GiB。 |
| **B. 改 BIOS 做一次隔离 PoC（唯一可行路径）** | **Gufo 更适合。** 决定性理由不是速度，是**可回滚性**：MIT 开源、标准 GGUF 权重、有 27B Q4 小套降级验证路径、闭源黑盒风险为零、PoC 失败后权重还能被现有 llama.cpp fork 复用。 |
| **C. 唯一指标是 Flash-Next 端到端性能，且愿意把本机永久改成单用途 appliance** | **Halogen 更快**（同机中文 33 题 754 s vs Gufo 910 s；Aider 21.5 min vs 36.0 min；中文长文 51.8 vs 33.4 t/s），但这不是「更适合本机」，是**换掉本机现在的用途**——它要求独占整机、headless、闭源引擎、110 GiB 专有权重，与本机「桌面 + WorkBuddy + docproxy + 视频/图像生成 + NPU」的混合生产形态正面冲突。 |
| **D. 当前最优动作** | **两者都不上，维持 96 GiB UMA + Vulkan + MTP 现状**，执行收益预测报告的场景 D（单点调优）。 |

**一句话**：Halogen 是更强的引擎，Gufo 是更适合这台机器的选择；但在这台机器上，正确答案是第三个——都不换。

**判定中同时订正前两份报告的两处口径错误，见第六节。**

---

## 二、判定口径（把「适合」拆成可判维度）

本机不是基准测试机，是混合生产机。按此设权重：

| # | 维度 | 权重 | 判据 |
|---|---|---|---|
| 1 | 当前 BIOS 下物理可部署性 | 最高 | 本机 GTT / MemAvailable 是否满足引擎硬门槛 |
| 2 | 与现有生产链路共存 | 最高 | 是否需要停 llama-server / sd-cli / docproxy / 桌面会话 |
| 3 | 可回滚性与沉没成本 | 高 | 改 BIOS 失败后能否一键还原；下载的权重能否被其他引擎复用 |
| 4 | 主力模型覆盖 | 高 | 能否服务 35B-A3B / 27B / mmproj / MiniMax-H3 现有链路 |
| 5 | 可审计与长期维护 | 中 | 许可、源码可见性、故障可定位性、版本节奏 |
| 6 | 峰值性能 | 中低 | 同模型族内的 decode / prefill / 端到端任务 |

**若把权重倒过来（只看第 6 项），结论会反转成 Halogen。这是本报告与纯性能横评结论不同的唯一原因。**

---

## 三、本机实测状态（2026-11-07 03:49:40 CST，一手）

| 项 | 读数 | 来源 |
|---|---|---|
| 内核 | `7.0.0-42-generic` | `uname -r` |
| host MemTotal | `31954696 kB` = **30.47 GiB** | `/proc/meminfo` |
| host MemAvailable | `3738536 kB` = **3.57 GiB** | `/proc/meminfo`（11-06 为 12 GiB，进一步恶化） |
| swap | 15 GiB，已用 8.7 GiB | `/proc/meminfo` |
| VRAM carve-out total / used | `103079215104 B` = **96.00 GiB** / `53961392128 B` = **50.25 GiB** | `/sys/class/drm/card1/device/mem_info_vram_{total,used}` |
| GTT total / used | `32721608704 B` = **30.47 GiB** / `3738591232 B` = 3.48 GiB | sysfs + `rocm-smi --showmeminfo gtt < /dev/null` |
| 8080 / 18090 / 23333 | 8080 **未监听**；18090 docproxy 在听；23333 MCSManager 在听 | `ss -ltnp` |
| 正在占显存的进程 | `sd-cli -M vid_gen --diffusion-model .../minimax_h3_fl2va-Q4_K_M.gguf`（PID 3250005，RSS 6.1 GiB） | `ps -eo pid,user,rss,args --sort=-rss` |
| 桌面会话 | GNOME Shell + Firefox（主进程 RSS 4.3 GiB）在跑 | `ps` |

**两条即时推论：**

1. **内核 7.0.0-42 满足 Halogen `AGENTS.md` 的 `kernel 7.0 or newer`** —— 这是 Halogen 相对 Gufo 唯一「本机已现成满足、无需任何改动」的条件。Gufo 无内核硬门槛，但官方工具链要求 ROCm 10.1.0 / GCC 16.2（容器自带，非阻塞）。
2. **headless 前提不满足。** offsite.guru 逐字：`Run it headless. A desktop session cost me about 7 GiB of the margin.` 本机 GNOME + Firefox + WorkBuddy 桌面常驻，且 `MemAvailable` 只剩 3.57 GiB。CycleUser 中文对比文更直接：`还要独占整机`、`这台机器基本得专门给它用`。

---

## 四、共同前提：两者在当前 BIOS 下都物理不可部署

| 引擎 | 内存需求（一手来源） | 本机可用 | 缺口 |
|---|---|---:|---:|
| **Gufo** 27B Q4 AR（最小文本模型） | **39.14–40.20 GiB** GTT（`docs/models/qwen3.8-27b/BENCHMARKS.md`） | 30.47 GiB | **−8.67 GiB** |
| **Gufo** Flash-Next Q4 MTP | **88.93 GiB** GTT = `88,931.12 MiB`（`docs/models/qwen3.8-flash-next/BENCHMARKS.md`） | 30.47 GiB | −58.46 GiB |
| **Halogen** 启动硬阈值 | **≈103 GiB** GTT：`below roughly 103 GiB the engine cannot allocate at all`（offsite.guru） | 30.47 GiB | **−72.53 GiB** |
| **Halogen** 完整布局 | **≈123 GiB**：68 权重锁 RAM + 14 KV + 21 working + 20 page cache（offsite.guru） | 30.47 GiB | −92.53 GiB |

两者权重的后盾都是 **OS 可见页 / GTT**，不是 carve-out。项目 `MEMORY.md` 已订正：旧修法「降 `pages_limit` 到 80 GiB 让 HIP 改走 carve-out」只对 KFD `hipMalloc` 类分配成立，对这两个 host-mapped HIP 栈不适用。

### 改 BIOS 的共同代价（两者完全相同，不是差异项）

| 代价 | 说明 |
|---|---|
| 现有 Vulkan 栈全灭 | UMA 96 GiB → 512 MiB：35B Q4_K_P（~31 GiB）、Q5_K_P（43.7 GiB）、MiniMax-H3 四组件（40.85 GiB）、sd.cpp 视频/图像链路全部无法加载 |
| NPU 失效 | `amd_iommu=off`：`It also disables DMA translation machine-wide and takes the NPU with it`（offsite.guru）；本机 flm v0.9.45 / 8219 已打通 |
| 生产任务中断 | 本次实测 `sd-cli` 正在跑 MiniMax-H3 vid_gen，VRAM 已用 50.25 GiB |
| headless 化 | 需停桌面会话，与 WorkBuddy / docproxy / OpenClaw 本机形态冲突 |
| 可回滚性 | BIOS + grub + `amd_ttm.conf` 需快照，重启两次，期间整机不可用 |

**Halogen 额外代价（Gufo 没有）**：`one GPU, one model family` + 独占整机是硬前提，不是建议。CycleUser：`甚至 IOMMU 关闭与否都会影响 prefill ... 还要独占整机`。

---

## 五、头对头对比表

| 维度 | **Gufo** | **Halogen** | 对「本机」的胜者 |
|---|---|---|---|
| 许可 | **MIT**，原创代码开源 | `Other` / `NOASSERTION`，`The engine is closed source and is not in this repository. This tree holds the deployment surface only.`（AGENTS.md） | **Gufo** |
| 可审计 / 故障定位 | 源码、CI、逐模型质量报告可见 | 引擎黑盒，仓库不接受 PR（补丁进不到闭源引擎，CycleUser） | **Gufo** |
| 权重格式 | **标准 GGUF**（Unsloth `UD-Q4_K_XL` 等 pinned 量化） | **专有 `.hgn`**；HF 模型卡逐字 `will not load in transformers, vLLM, or llama.cpp` | **Gufo** |
| 权重体量 | 27B 小套可先验证；Flash-Next 约 90 GiB 门槛 | 0.15+ v2：62.1 GiB checkpoint + 47.7 GiB ngram ≈ **110 GiB**；全量文件可达 307.1 GB | **Gufo** |
| PoC 失败后权重去向 | 可被现有 `llama-qwen4exp-rocmfpx` fork / 其他 GGUF 工具复用 | **完全沉没**，无任何第三方运行时可加载 | **Gufo** |
| 内存硬阈值 | 最小 39.14 GiB，**有 27B 降级路径** | <103 GiB `cannot allocate at all`，**无小模型降级** | **Gufo** |
| 模型族 | 27B / Flash-Next / DeepSeek V4 Flash / ASR / TTS / Embedding / 图像 / 视频 | `One GPU, one model family`，仅 Qwen3.8-Flash-Next | **Gufo** |
| 与本机 6 个 GGUF 重叠 | **0**（私有 ROCmFP4 type 101 + pinned 量化白名单；35B 仅第三方 fork Q6dense） | **0**（`.hgn` 专有） | 平（都全灭） |
| 35B-A3B 路径 | 第三方 fork `NinjaPear/gufo-Qwen3.6-35B-A3B-Q6dense`，需 Q6dense 特制权重 | **无路径** | Gufo（弱胜） |
| 内核要求 | 无明确硬门槛 | `kernel 7.0 or newer` → **本机 7.0.0-42 已满足** | **Halogen** |
| headless / 独占整机 | 未作硬要求 | **硬前提**（offsite.guru + CycleUser） | **Gufo** |
| NPU 小模型 | 无此依赖 | 0.8B 分类器 / 0.6B embedding / 0.6B rerank，同端口 | 名义 Halogen，实际见第九节 |
| `amd_iommu=off` 后功能损失 | 无 NPU 依赖 → 无功能损失 | **NPU 小模型特性失效**（见第九节） | **Gufo** |
| API 面 | OpenAI Chat + Responses；**不支持 Claude Code**（issue #522） | OpenAI + Anthropic + Responses，单端口 8731；`/v1/moderations`、`/v1/systemone` | Halogen |
| 端口安全面 | 单端口 8080 | API 8731 + **engine 8730 无认证必须不发布**（AGENTS.md） | Gufo |
| 配置方式 | CLI flags + 面板实例 | 全 `HALOGEN_*` 环境变量，容器一条命令 | Halogen |
| 已知运维坑 | `enable_thinking` 注入不认、`model` 字段强制匹配、默认 8 MB body、`--cache-ram-bytes` 需显式、v0.29 破坏性变更删 API-key auth | `reasoning_effort` 默认 xhigh 烧 token budget；prompt cache 与 build/weights/context/levers 精确绑定；必须看 engine request line 而非客户端首字；warm/cold answer 默认不 bitwise identical；`/proc/buddyinfo` 2 MiB 连续块 <512 会假死 | 平 |
| 容器运行时 | podman 未装、docker 权限 denied、nix 未装 | 同样缺 podman；`HALOGEN_DOWNLOAD` 自动拉 110 GiB | 平 |
| 中文长文 decode | 33.4 t/s | **51.8 t/s** | **Halogen** |
| 端到端中文 Agent 33 题 | 910 s，30 全对 + 3 部分 | **754 s，33 全对** | **Halogen** |
| Aider polyglot（KBlip，70 W） | 36.0 min | **21.5 min** | **Halogen** |
| 长上下文 prefill | 1,493–1,625 t/s（8K–118K） | 1,250（10K）/ 1,423（43K）/ 1,408（147K） | 平（同档） |
| 社区规模 | 976 star / 167 fork | 1,245 star / 83 fork | Halogen |

**读表结论**：Halogen 赢的全部是「引擎能力 / 性能」项；Gufo 赢的全部是「能不能在这台机器上落、落错了能不能退」项。本机是生产机，后者权重更高。

---

## 六、性能同机数据与两处口径订正

### 6.1 可直接对比的同机数据

| 指标 | Gufo | Halogen | 来源 |
|---|---:|---:|---|
| 中文长文单路 decode | 33.4 t/s | **51.8 t/s** | 微信公众号 / 今日头条《AMD MAX+ 395 实测 halogen 和 gufo》 |
| 33 道中文 Agent 题 | 910 s / 30 全对 + 3 部分 | **754 s / 33 全对** | 同上 |
| Aider polyglot Python（70 W TDP，128K） | 36.0 min | **21.5 min** | KBlip 十引擎横评 |
| 长文档 prefill | 1,493 / 1,625 / 1,602 / 1,551 t/s（8K/32K/64K/118K） | 1,250 / 1,423 / 1,408 t/s（10K/43K/147K） | 中文横评 / offsite.guru |
| Flash-Next decode（官方 / 作者） | 28.29 AR、35.79 MTP mixed、58.3 中文单路均值 | 43（10K）、38（43K）、~38（147K） | Gufo `BENCHMARKS.md` / offsite.guru |

**Halogen 在端到端任务上确实更快，这点不打折。** KBlip 的反向校验同样成立：Gufo prefill 峰值与 Halogen 同档，但 Aider 用时多 67% → **prefill 峰值 ≠ 端到端收益**。

### 6.2 ★ 订正 A：Gufo 报告 7.3 的 `decode 0.9–1.3×` 不能折算到本机基线

`2026-11-06-Gufo方案-本地部署可行性分析.md` 第 7.3 节把「社区 1.74×」折算成相对本机 35B-A3B 的 `decode 0.9–1.3×`。**该折算口径错误，作废。**

理由：社区 1.74× 的对照组是**同一颗 Qwen3.8-Flash-Next（约 125B MoE）在未调优 llama.cpp 上的 33.6 t/s**，不是本机 35B-A3B 的 90.14 t/s。项目 `MEMORY.md` 第四节早已定性：`decode 由激活参数决定，与总参数无关` —— 35B-A3B 每 token 只激活 3B，Flash-Next 激活量高一个量级，两条 decode 曲线不可互推。

**正确表述**：Gufo / Halogen / Strata 跑的都是 Flash-Next，实测 decode 落在 **28–58 t/s**；相对本机 35B-A3B 的 90.14 t/s 是 **0.31–0.64×，即腰斩**。`0.9–1.3×` 只在「同一 Flash-Next 模型族内、对照未调优 llama.cpp」时成立。

**这条订正直接改变决策**：换任何一个 Flash-Next 专用引擎，本机主力场景（对话 / 代码 / 文档 / Agent）的 decode 都会倒退一半以上；唯一能拿到的结构性收益是长 prefill（本机 89K ≈520 t/s → 1,250–1,625 t/s，约 **2.4–3.1×**）与并发吞吐。而本机 `2026-10-03-35B速度复测.md` 的主力指标恰好吃 decode。

### 6.3 ★ 订正 B：`amd_iommu=off` 的 +13~16% prefill 对 translated mode 未验证

`2026-11-06-Strata方案-社区经验收益预测.md` 把 `amd_iommu=off`（prefill +13~16%）列为「场景 D 唯一有 upstream 量化实测的优先单项」。新查到的一手拆解 `noamsto/nix-amd-ai/docs/halogen-flash-teardown.md` 给出原始对照：

> `arm | package power | shader clock | prefill @ 2048` — `IOMMU off 108–118 W / 2549–2713 MHz / 460 tok/s`；`iommu=pt 122–127 W / 2357–2409 MHz / 385 tok/s`
> `Their caveats are load-bearing: one machine, and they compared off against passthrough only. Translated mode was never measured, and Translated is what our hosts run.`

**订正**：13–16% 是 `off` vs **`pt`（passthrough）** 的单机对比，机制是 IOMMU 翻译功耗挤占 shader 功耗预算（108–118 W vs 122–127 W），不是内存带宽。**本机默认是 translated mode，该模式从未被测过**，收益幅度和方向均 [UNVERIFIED]。场景 D 中该项从「唯一有实测的优先项」降级为「必须先在本机做 off / pt / translated 三臂 A/B 的待验证项」，其余单项（新 RADV、FA、no-mmap、CPU 限频）排序不变。

同一拆解另给出可复用的两条判据：
- `A firmware graphics carve-out is invisible and costs page cache` —— carve-out 不出现在 `/proc/meminfo`，损失落在文件缓存上，与本机 96 GiB carve-out 的观察一致。
- `free and MemAvailable overstate available memory by the size of the model while Mlocked and Unevictable both stay at zero` —— Halogen 锁定的权重被算作可回收 page cache；启动前须查 `/proc/buddyinfo` zone Normal 的 2 MiB 连续块 ≥512，否则会 100% 单核假死数分钟。本机在未改 BIOS 前无需处理，改 BIOS 后做 PoC 必须纳入检查表。
- `Publish the power envelope. An independent tester on a 70 W handheld landed 11 to 12 percent under both of their decode figures` —— 与本机 120 W 功耗墙结论同向，进一步支撑 6.2 的 decode 不可外推。

---

## 七、决定性差异 1：许可与权重沉没成本

PoC 的性质是「大概率回滚」。按 SOUL.md 的可回滚原则，比较的是**回滚后还剩什么**：

| | Gufo | Halogen |
|---|---|---|
| 下载物 | 标准 GGUF，落 `$HOME/models` | `.hgn` 110 GiB（v2 62.1 + ngram 47.7），全量文件可达 307.1 GB |
| 回滚后能否复用 | **能**：GGUF 可被现有 fork / llama.cpp / 量化工具读取 | **不能**：HF 模型卡明写 `will not load in transformers, vLLM, or llama.cpp` |
| 失败能否自查 | 能，源码 + CI + 逐模型质量报告 | 不能，引擎闭源；仓库不接受 PR |
| 磁盘沉没 | 可控（27B 小套先验证） | 110 GiB 起，本机 `/` 可用 240 GiB，占近半 |

**Halogen 官方另有两个更小的 checkpoint 可缓解**：`qwen38-flash-next-ht43.hgn` 53.7 GiB（约省 8 GiB 常驻）、0.14 时代约 118 GiB 全套。但格式仍是 `.hgn`，沉没成本性质不变。

---

## 八、决定性差异 2：内存硬阈值与降级路径

- **Gufo**：改 BIOS 后 GTT ≈124 GiB，可**分步验证** —— 先下 27B Q4 小套（39.14 GiB）跑通链路 / docproxy / 面板托管，再决定是否下 Flash-Next（88.93 GiB）。任一步失败都可停，损失可控。
- **Halogen**：`below roughly 103 GiB the engine cannot allocate at all`，且 `one GPU, one model family`、只有一套 Flash-Next checkpoint。**没有小模型可用来分步验证**，第一次启动就是全量 110 GiB 权重 + 123 GiB 内存布局 + 完整 BIOS/grub 改动。一次失败 = 全部代价已付。

对本机这种「不能长时间停机」的机器，可分步验证是硬需求。

---

## 九、决定性差异 3：NPU 卖点与 IOMMU 配置冲突（新证据）

Halogen 的差异化卖点是 NPU 小模型同端口服务（GitHub description `plus small NPU models`；CycleUser：0.8B 分类器 / 0.6B embedding / 0.6B rerank）。但本次查到的官方 NPU 模型卡给出宿主前提：

> `The host needs the NPU driver, XRT with its NPU plugin, and the GPU's fabric clock held while the NPU works beside the GPU.`
> —— ModelScope `peonist-ai/halogen-npu-qwen3guard-stream-0.6b` / HF `halogen-npu-d3-nano` 模型卡

而 Halogen 社区标准大 GTT 配置必须 `amd_iommu=off`，offsite.guru 逐字：`It also disables DMA translation machine-wide and takes the NPU with it`。

**判定**：在「照搬社区 512 MiB UMA + `amd_iommu=off` 大 GTT 配置」这条唯一已知可部署路径下，Halogen 的 NPU 小模型特性**拿不到**。要么保留 IOMMU（NPU 可用，但按 6.3 订正，prefill 收益 [UNVERIFIED] 且 GTT 上限与启动阈值需重新验证），要么关 IOMMU（引擎能起，NPU 全灭并连带本机已打通的 flm 8219）。

**这是配置层面的二选一，不是推测**。是否可通过其他 IOMMU 模式或 host unit 同时保留两者，上游文档未说明 → 列待核项第 1 条，不自行断言有解或无解。

Gufo 无 NPU 依赖，不受此二选一影响。

---

## 十、决定性差异 4：专用机前提 vs 本机混合生产

| 来源 | 原文 |
|---|---|
| offsite.guru | `The goal was a boring appliance. Boot the box, the model is ready, agents connect to an OpenAI-compatible endpoint, nothing else runs on the machine.` / `Run it headless. A desktop session cost me about 7 GiB of the margin.` |
| CycleUser 中文对比 | `halogen 是一台 AMD Strix Halo 上跑容器 ... 还要独占整机` / `这台机器基本得专门给它用` |
| AGENTS.md | `One GPU, one model family.` |

本机现状（第三节实测）：GNOME 桌面 + Firefox + WorkBuddy + docproxy 18090 + MCSManager 23333 + `sd-cli` MiniMax-H3 视频生成 + NPU flm 8219 + OpenClaw 18789。这是**多用途混合生产机**，与 Halogen 的 appliance 定位正交。

Gufo 虽同样要求大 GTT，但没有「独占整机 / headless」的硬前提，且模型族更宽，PoC 期间可与桌面会话共存验证（性能会打折，但链路能通）。

---

## 十一、链路与运维冲突对照

| 项 | Gufo | Halogen |
|---|---|---|
| 端口 | 默认 8080 与 llama-server 冲突 → 改 8082 | API 8731 不冲突；**engine 8730 无认证，必须不发布** |
| 面板托管铁律 | 新建 MCSManager 实例，前台 `exec podman run --rm ...`，禁止 `docker run -d` 裸跑 | 同左；`HALOGEN_DOWNLOAD` 会自动拉 110 GiB，首次启动不可控 |
| docproxy 18090 | 上游硬编码 8080；注入的 `enable_thinking=false` Gufo 不认（它用 `think=off`）；`model` 字段须与 servedModelName 一致；默认 8 MB body | 需另写上游切换；`reasoning_effort` 默认 xhigh 会耗尽 token budget，必须显式压到 `low` |
| chunked / SSE | WorkBuddy 注入 40K+ tokens 用 `Transfer-Encoding: chunked`；Gufo 兼容性未实测 | 同左，未实测 |
| 计时口径 | 常规 | **必须看 engine request line**，客户端首字计时会把 prompt cache 命中算成性能 |
| 缓存 | `--cache-ram-bytes` 需显式设（issue #387） | prompt cache 与 build / weights / context / levers 精确绑定，任一变更即全失效 |
| 可复现性 | — | warm answer 与 cold answer 默认不 bitwise identical（offsite.guru） |
| 版本 | v0.27→v0.30 七天，v0.29 BREAKING + 删 API-key auth | 0.12.3 / 0.18.3 / 0.18.5 / 0.18.11 / 0.18.12 多版本共存，须 pin exact tag，never `:latest` |

---

## 十二、分场景判定矩阵

| 场景 | Gufo | Halogen | 说明 |
|---|---|---|---|
| 当前 BIOS 直接部署 | **不可** | **不可** | 第四节 |
| 改 BIOS 一次性 PoC | **推荐** | 不推荐 | 可回滚性 + 分步验证 + 可审计 |
| 永久替换现有栈 | 不推荐 | 不推荐 | decode 0.31–0.64× 倒退（6.2），Vulkan 栈全灭 |
| 只追 Flash-Next 端到端速度 | 次优 | **最优** | 但需专用机化，与本机用途冲突 |
| 保留 NPU / 多模型 / 视频链路 | **可行** | 不可 | 第九、十节 |
| Anthropic Messages / Responses API | 不支持 Claude Code | **原生** | 但成本最低仍是给 18090 docproxy 加转换层，不引入新引擎 |

---

## 十三、决策建议（按优先级）

1. **维持现状**：96 GiB UMA + `llama.cpp + Vulkan` + MTP 不变，Halogen / Gufo / Strata 均不进生产。依据：三者都物理不可部署，改 BIOS 后 decode 仍倒退一半以上。
2. **场景 D 单点调优，但重排优先级**：`amd_iommu=off` 从「优先项」降为「需三臂 A/B 的待验证项」（6.3）；优先做新 RADV、Flash Attention、no-mmap、CPU 限频这些**零 BIOS 改动、逐项可回滚**的项。
3. **若少爷授权做隔离 PoC**：选 **Gufo**，沿用 `2026-11-06-Gufo方案-本地部署可行性分析.md` 第九节 9 步清单，先只下 27B Q4 小套到 `$HOME/models`，端口 8082，MCSManager 托管，跑完 BIOS 改回 96 GiB。
4. **若少爷明确要 Halogen 的极致 Flash-Next 速度**：前置条件是接受「本机改为 headless 单用途模型服务器」，即停掉桌面 / WorkBuddy / docproxy / sd-cli / NPU，并单独准备 110–307 GiB 权重空间。这不是 PoC，是换用途，需单独授权。
5. **不改 BIOS 的替代路径**（长期）：继续跟踪 `strix-llama` / `GSQHalo.cpp` 等**在 96 GiB carve-out 布局下与现有栈同池**的 llama.cpp 分支；社区已有 IQ3_S 在 96 GB 机器上双 256K slot 的实测。

### PoC 验收门槛（沿用 Gufo 报告，新增三条）

- 27B Q4 能起（改 BIOS 后 GTT ≈124 GiB，40 GiB 占用）
- 中文长文 decode ≥ 本机 27B 基线；8 路并发聚合 ≥1.5×
- docproxy 18090 → 8082 链路 200 且 `content` 非空（含 chunked 上传 + SSE 心跳）
- **新增**：改 BIOS 后先查 `/proc/buddyinfo` zone Normal 2 MiB 连续块 ≥512
- **新增**：`amd_iommu` 三臂 A/B（off / pt / translated）分别记 prefill，不外推 13–16%
- **新增**：确认 NPU `flm 8219` 在所选 IOMMU 模式下是否仍可用，并写入回滚检查表

任一不达标即回滚：BIOS 改回 96 GiB + 还原 `grub` / `amd_ttm.conf` + 重启；删面板实例；恢复 docproxy 原注入。Gufo 的 GGUF 权重保留不删。

---

## 十四、数据校验与剔除（怀疑一切）

| 数据 | 校验结果 | 处置 |
|---|---|---|
| Bee catalog「Halogen 直接打开 llama.cpp GGUF，无需转换」「可跑自定义量化 checkpoint」 | 与 HF 官方模型卡 `.hgn will not load in transformers, vLLM, or llama.cpp`、AGENTS.md 的 `.hgn` 部署树方向相反；该页自注 `AI-generated content may be wrong or incomplete` | **剔除**，权重格式以 HF 模型卡 + AGENTS.md 为准 |
| Bee catalog「Guarantees byte-identical output ... at temperature 0」 vs offsite.guru「warm / cold answer 默认不 bitwise identical」 | 版本差异或口径差异（投机解码确定性 vs 缓存路径一致性） | `[UNVERIFIED]`，不用于判定 |
| BIOS UMA 设 `Auto` 还是 `minimum` | offsite.guru `the minimum (512 MB). Do not pre-carve 64 or 96 GB`；noamsto teardown `Their advice is Auto or minimum`；Bee catalog `minimum rather than Auto` | 三处不一致 → 取 offsite.guru 一手实测配置，Auto 列为待核 |
| offsite.guru 性能数字（1,250 / 1,423 / 1,408 t/s，43 / 38 t/s） | 作者单机自测，非独立复现；原文明确「看 engine request line 而非客户端首字」 | 标 `[UNVERIFIED]`，仅用于同表内趋势，不折算本机绝对值 |
| KBlip Aider 21.5 vs 36.0 min | 70 W TDP 手持机，本机 120 W 墙；同一拆解指出 70 W 下 decode 低 11–12% | 仅作**同表内名次**，倍数不外推 |
| 微信文「GGUF 111 GB」 | 与官方 Memory occupation 88.78 GiB 口径不同 | 沿用 Gufo 报告处置：不用于容量计算 |
| `amd_iommu=off` +13~16% | off vs **pt** 单机，translated 未测 | **订正降级**（6.3） |
| Gufo 报告 `decode 0.9–1.3×` | 跨模型族折算错误 | **订正作废**（6.2） |

---

## 十五、待核项

1. Halogen 是否可在保留 IOMMU 的模式下同时满足 GTT 启动阈值与 NPU 小模型（上游无明文；涉及 `amd_iommu=pt` / translated 与 GTT 上限的组合）。
2. Halogen 0.18.x 的 `HALOGEN_HOST_RESERVE_GIB` / `HALOGEN_KV_POOL_POSITIONS` 在 128 GiB 机器上能否压到 103 GiB 阈值以下运行（官方称 <103 GiB 完全不能分配，无降级路径）。
3. `amd_iommu=off` 对本机 NPU（flm 8219）的实际影响未实测，仅依据 offsite.guru 原文推定。
4. 27B Q4 关闭 vision projector / 更小 context 后能否压到 30.47 GiB 以下，Gufo 官方无数据。
5. Gufo / Halogen 对 docproxy chunked 上传、SSE `select` 心跳、`X-Trim-Prompt` 的兼容性需实测。
6. 本机 35B-A3B 与 Gufo 第三方 fork 的 Q6dense 权重是否可转换 / 获取。
7. 35B 长 prefill 旧记录「308 KB 请求体 → 26 s」与 89K tokens / 171 s / ≈520 t/s 的口径差异（沿用 Gufo 报告待核项）。
8. Halogen warm/cold answer 非 bitwise identical 与 Bee catalog 的 byte-identical 声明，哪个是当前版本行为。

---

## 十六、来源清单

**本机一手（2026-11-07 03:49:40 CST）**
- `uname -r`、`/proc/meminfo`、`/sys/class/drm/card1/device/mem_info_{vram,gtt}_{total,used}`
- `rocm-smi --showmeminfo gtt < /dev/null`、`ss -ltnp`、`ps -eo pid,user,rss,args --sort=-rss`
- 项目 `MEMORY.md`、`2026-10-03-35B速度复测.md`、`2026-11-06-Gufo方案-本地部署可行性分析.md`、`2026-11-06-Strata方案-社区经验收益预测.md`

**Halogen 官方 / 一手**
- `https://api.github.com/repos/peonist-ai/halogen-flash-server`（license `NOASSERTION`、1245 star / 83 fork、`pushed_at 2026-11-06T11:34:47Z`、description）
- `https://github.com/peonist-ai/halogen-flash-server/blob/main/AGENTS.md`（闭源、one GPU one model family、kernel 7.0+、engine 8730 无认证、`HALOGEN_DOWNLOAD`）
- `https://huggingface.co/peonist-ai/halogen-qwen3.8-flash-next/.../README.md`（`.hgn` 专有格式、~118 GiB、68 GiB 常驻、v2 62.1 + ngram 47.7、`ht43` 53.7）
- ModelScope `https://www.modelscope.cn/models/peonist-ai/halogen-npu-qwen3guard-stream-0.6b`、HF `peonist-ai/halogen-npu-d3-nano`（NPU 宿主前提、`.hnpw`、0.18.3+/0.18.11+ 版本门槛）

**社区 / 第三方拆解**
- `https://offsite.guru/blog/halogen-strix-halo`（BIOS 512 MiB、grubby 参数、103 GiB 阈值、123 GiB 布局、headless、`amd_iommu=off takes the NPU with it`、性能表）
- `https://github.com/noamsto/nix-amd-ai/blob/main/docs/halogen-flash-teardown.md`（IOMMU off vs pt 原始功耗/时钟/prefill 表、translated 未测、carve-out 与 page cache、`/proc/buddyinfo`、power envelope）
- `https://blog.cycleuser.org/...`（中文 halogen vs Strata 对比：闭源但可用、独占整机、NPU 小模型、KV 池多 slot、绑死 gfx1151）
- 微信公众号 / 今日头条《AMD MAX+ 395 实测 halogen 和 gufo》（同机中文横评）
- `https://kblip.com/research/benchmarks-best-engine-for-qwen-3-8-flash-next-on-strix-halo-RNBQWMv`（十引擎 Aider 横评）
- `https://platform.beeknoee.com/github/peonist-ai/halogen-flash-server/ai`（Bee catalog，仅取其仓库元数据；AI 摘要部分已剔除）

**Gufo 官方**
- `https://raw.githubusercontent.com/gufo-org/gufo/main/README.md`
- `https://raw.githubusercontent.com/gufo-org/gufo/main/docs/models/qwen3.8-{flash-next,27b}/BENCHMARKS.md`
- `https://raw.githubusercontent.com/NinjaPear/gufo-Qwen3.6-35B-A3B-Q6dense/main/README.md`

---

> 许可：CC0-1.0，公共领域贡献，无任何限制。
