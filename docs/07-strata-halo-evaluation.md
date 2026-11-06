# Strata 方案：本地部署可行性与现有方案对比分析

日期：2026-11-06
对象：AMD Ryzen AI MAX+ 395 / Strix Halo / gfx1151 / 128 GiB 物理统一内存主机

---

## 一、结论（先给判定）

**可以安装并启动，但在本机当前 BIOS/内核配置下不能有意义地部署，也不建议替换现有方案。**

三条硬阻塞：

1. **内存池互斥（决定性）**：Strata 在 Linux gfx1151 上走 HIP，把「显存」定义为 GTT 池，按 `MemAvailable` 计算可用量。本机 96 GiB 被 BIOS UMA carve-out 划给 Vulkan（OS 不可见），host 只剩 30.47 GiB、MemAvailable 16.35 GiB。官方测量机是「64 GiB carve-out + 64 GiB OS 可见」，两者物理机相同但 BIOS 分法相反。**要让 Strata 跑出标称速度必须改 BIOS UMA 96→64 GiB，而这一改动会直接挤压现有 llama.cpp/sd.cpp 栈所依赖的 96 GiB carve-out。二者零和，不可兼得。**
2. **模型不兼容**：本机 `Qwen3.8-Flash-Next-ROCmFP4-FAST-imatrix-v2.gguf`（88 GiB）是 ROCmFP4 私有 ggml type 101，只有本机 `llama-qwen4exp-rocmfpx` fork 能读。Strata 使用 pinned 上游 ggml revision，不认 type 101。要跑 Strata 必须另下 66–94 GB 的 ISTA-DASLab / Unsloth packs。
3. **端口与托管铁律冲突**：Strata 默认监听 8080，与现有 llama-server 端口相同；且少爷定策「llama 推理实例一律经 MCSManager 面板启动，禁止裸跑」，Strata 需新建面板实例并改端口才能纳入管控。

补充定性：官方把 Strix Halo 支持标为 `**Status: experimental.**`，Linux 侧无 DeepSeek engine、WSL 下 HIP 引擎会 hang、gfx1151 编译告警 `unvalidated`、屏幕冻结时长「Not known yet」。

---

## 二、Strata 是什么（事实核对）

| 项 | 值 | 来源 |
|---|---|---|
| 仓库 / 作者 / 许可 | `Niko1221/Strata`，Niko Veit，MIT，2026-09-24 创建 | GitHub README；linuxcompatible 报道 |
| 引擎本质 | **C++ 引擎，基于 pinned 的 llama.cpp / ggml**（CMake 拉取固定 revision），不是与 llama.cpp 并列的独立后端 | `docs/STRIX_HALO.md`「llama.cpp's ggml sources are pinned by this repository」 |
| 当前版本 | 0.2.9（AppImage / setup.exe / `strata launch`）；engine 变体 `linux-x86_64-hip-halo` | README、STRIX_HALO.md Quick start |
| 核心机制 | MoE 专家分层：GPU 放最热 ~4,000 / 24,576 experts，RAM 放全部，SSD 放 29 GB lookup table（Engram）；每 token 仅激活 10 个专家 | besthub.dev、STRIX_HALO.md |
| 投机解码 | MTP draft layer + prompt-lookup；setup 默认 `--mtp --spec 4 --spec-min-p 0.5` | `docs/DETAILS.md` |
| API | `127.0.0.1:8080`，OpenAI `/v1/chat/completions`、Anthropic `/v1/messages`、OpenAI Responses `/v1/responses`（stateless）、`/props`、`/slots`、`/metrics`、`/unload`、`/load` | `docs/DETAILS.md` |
| 支持模型族 | Qwen3.8-Flash-Next、Qwen3.6-35B-A3B、DeepSeek V4.1-Flash-1017 | README Models |
| 是否通用 GGUF 加载器 | **否**。只吃带 pinned SHA-256 的特定 packs；`strata models import` / `--gguf-dir` 要求文件名与 revision 与 setup 展示一致 | `docs/MODELS.md`、`docs/DETAILS.md` |
| 上下文 | setup 在 8K–262K 选择；模型训练位置 262,144；超长请求拒绝、不静默截断；默认 int8 KV | `docs/DETAILS.md` |

**「strata+llama.cpp」不是叠加关系**：Strata 本身就是 llama.cpp/ggml 的下游 fork + 专家分层调度器 + 一键安装器 + Web UI。对比对象应是「Strata 打包栈」对「本机自维护的 llama.cpp fork 栈」。

---

## 三、本机实测状态（2026-11-06 06:41 GMT+8）

| 指标 | 实测值 | 命令 / 来源 |
|---|---|---|
| 内核 | `7.0.0-42-generic` | `/proc/cmdline` |
| BIOS UMA carve-out（VRAM） | **103,079,215,104 B = 96.00 GiB** | `rocm-smi --showmeminfo vram` |
| VRAM 已用 | 51,442,966,528 B = 47.91 GiB | 同上 |
| GTT Total | **32,721,608,704 B = 30.47 GiB** | `rocm-smi --showmeminfo gtt` |
| GTT 已用 | 205,717,504 B | 同上 |
| host MemTotal / MemAvailable | **30.47 GiB / 16.35 GiB** | `/proc/meminfo`（31,954,696 / 17,142,596 kB） |
| Swap | 15 GiB，已用 7.4 GiB | `free -h` |
| ttm 参数 | `pages_limit=25600000` ≈ 97.66 GiB 上限（非内核 cmdline，走 modprobe.d） | `/etc/modprobe.d/amd_ttm.conf`、`/sys/module/ttm/parameters/` |
| 系统 ROCm | 7.1.0（dpkg） | `dpkg -l \| grep rocm` |
| 磁盘可用 | 241 GiB（`/`，NVMe） | `df -h $HOME` |
| 端口 | 8080 **未监听**；18090 docproxy 在听；8081/3000/23333/24444 在听 | `ss -ltnp` |
| 当前占显存任务 | `sd-cli` MiniMax-H3 视频生成（pid <进程号>） | `ps`（Vulkan 权重落 carve-out，KFD fdinfo 仅报 375 MiB 属正常） |
| 已装模型 | 35B-A3B Q4_K_P 22 GiB / Q5_K_P 27 GiB / Qwen3.8-Flash-Next ROCmFP4 **88 GiB** + MTP 2.3 GiB / 两个 mmproj | `ls -lh $HOME/models/*.gguf` |

> 数据校验说明：`GTT Total = 30.47 GiB` 恰好等于 `host MemTotal = 30.47 GiB`，证实 APU 上 GTT 的后盾就是 OS 可见 RAM；`pages_limit` 撑到 97.66 GiB 只是允许上限，物理后盾仍是这 30.47 GiB。项目长期笔记中「GTT 97.66 GiB（虚标）」与本次 `rocm-smi` 读数不一致，以本次实测为准。

---

## 四、决定性冲突：内存池分法互斥

### 4.1 官方 Strata 对 gfx1151 的内存定义（逐条引自 `docs/STRIX_HALO.md`）

- `Strata runs there through the same HIP backend as the Radeon cards` — **HIP，不是 Vulkan**。
- `**Unified memory.** The GPU's "VRAM" is the GTT pool of the same RAM. device_free_bytes() ... counts what Linux can give back (MemAvailable less 6 GiB for the system)` — **显存按 host `MemAvailable` 算，不按 carve-out 算**。
- `To let the GPU use most of a 128 GB machine, the maintainers' box boots with ttm.pages_limit=29360128 ttm.page_pool_size=29360128 (a 112 GiB GTT...) and amd_iommu=off`。
- `one pool of 128 GB (the BIOS carve-out plus the RAM)`、`Unified memory is counted once.`
- 测量机配置：`Measured on: Ryzen AI Max+ 395, 128 GB, gfx1151, Linux ... Ubuntu 26.04, kernel 7.0, ROCm 7.14.1`；Windows 侧写明 `64 GB BIOS carve-out plus 64 GB seen by Windows`。
- `Known limits: the 128 GB machine was tested. A 64 GB or 32 GB Strix Halo gets a smaller store and is slower` — 官方只测过整机 128 GB 且 OS 可见约 64 GB 的分法。

### 4.2 本机双池现状（项目长期笔记，2026-10-08 实测）

| 池 | 大小 | 使用者 | 是否吃 host RAM |
|---|---|---|---|
| VRAM carve-out（BIOS UMA） | 96.00 GiB，OS 不可见 | **Vulkan：llama.cpp / sd.cpp** | 否 |
| GTT | 本就受限于 host RAM 30.47 GiB | **HIP / PyTorch** | **是** |

- 内核补丁 `drm/amdkfd: use GTT for VRAM on APUs only if GTT is larger` 使本机 HIP 全走 GTT。
- 2026-10-08 事故：HIP 分配 0→20 GiB 期间 llama.cpp VRAM 恒定 31.4 GiB 不动（双池不互挤），但 20 GiB 时 host available 仅 494 MiB → **全局 OOM**。
- 当时的修法方向是把 `pages_limit` 降到 80 GiB 使 GTT < VRAM，让 HIP 改用 carve-out —— **与 Strata 要求「把 GTT 撑到 112 GiB」方向完全相反**。

### 4.3 推论

1. 本机 Strata 的 `device_free_bytes()` ≈ `16.35 − 8（desktop reserve，取 max(8 GiB, 8% RAM)）≈ 8.35 GiB`。Strata 会认为自己只有约 8–10 GiB 显存。
2. Qwen3.8-Flash-Next 最小 pack Q2_0 需 **37.6 GB**（RAM+VRAM），Coder 约 32 GB；Unsloth UD-IQ4_XS 需约 72 GB 才能把全部 experts 放 RAM。本机 host 总内存仅 30.47 GiB → **连最小 pack 都放不下全部 experts**，必然落到 `--mmap-experts` / SSD 分层，官方文档原话 `If RAM is short, setup can read experts from the SSD instead ... that works and is much slower`。
3. 若同时跑现有 Vulkan 栈（占 carve-out 30–48 GiB）与 Strata HIP（吃 host RAM），2026-10-08 的全局 OOM 场景会重现。
4. **要跑出官方标称速度，必须把 BIOS UMA 从 96 GiB 改到 64 GiB**（让 OS 可见 ~64 GiB）+ 内核加 `ttm.pages_limit=29360128 amd_iommu=off`。但 carve-out 缩到 64 GiB 后：现有 35B-A3B Q4_K_P（约 31 GiB 显存）、Q5_K_P（43.7 GiB）、MiniMax-H3 四组件 40.85 GiB 全落 carve-out 的余量被大幅压缩，sd.cpp 视频链路（已因显存弃用 704×1280）会进一步受限。

**结论：现有 Vulkan 栈要 carve-out 尽量大、GTT 尽量小；Strata HIP 栈要 GTT 尽量大、carve-out 尽量小。同一台 128 GiB 机器上两者是 BIOS 层的零和分配，无法同时优化。**

---

## 五、模型与量化兼容性

| 本机已有文件 | Strata 能否直接用 | 原因 |
|---|---|---|
| `Qwen3.8-Flash-Next-ROCmFP4-FAST-imatrix-v2.gguf`（88 GiB） | **否** | ROCmFP4 私有 ggml type 101，仅 `llama-qwen4exp-rocmfpx` fork 支持；Strata pinned 上游 ggml 不认 |
| `Qwen3.8-Flash-Next-MTP-ROCmFP4-FAST.gguf`（2.3 GiB） | **否** | 同上，且 Strata 自带 MTP draft 层（约 6 GB） |
| `Qwen3.6-35B-A3B-Uncensored-Q4_K_P.gguf`（22 GiB） | **否** | Strata 的 `--family qwen36` 只吃 Unsloth UD-Q4_K_XL / UD-Q6_K_XL / Q8_0，且需 pinned revision + SHA-256 |
| mmproj（35B 858 MiB / Qwen3.8 863 MiB） | **部分** | Strata 视觉用 `mmproj-Qwen3.8-Flash-Next-BF16.gguf`（0.9 GB），配置 `"mmproj"` 可指向自有文件；但本机 35B 的 n_embd=2048 与 Qwen3.8 不通用 |

代价：需按少爷约定下载到 `$HOME/models`，新增 66–76 GB（ISTA-DASLab Q2_0/IQ2_XS/IQ3_XXS）或 94–188 GB（Unsloth），外加 MTP draft ~6 GB、mmproj 0.9 GB。磁盘 241 GiB 够，但下载量 70 GB+ 且 `github.com` 直连 TLS 中断需走 `gh-proxy.com`。

---

## 六、性能数字对比（必须同口径，勿跨表直比）

### 6.1 Strata 官方在 Ryzen AI Max+ 395 / 128 GB / gfx1151 / Linux 的实测
来源：`docs/STRIX_HALO.md` History 表，Strata 0.1.40 code + fast configuration（`--spec 4 --mtp --lookup-chain 3 --mtp-q4 all --prefill 16384`，int8 KV，all experts in unified memory），3 次中位数，**维护者自测，非本机实测 → [UNVERIFIED]**。

| 量化 | 上下文 | Prompt t/s | Output t/s |
|---|---|---:|---:|
| UD-IQ4_XS | 8K | 1,293 | 53.8 |
| UD-IQ4_XS | 128K | 1,320 | 51.4 |
| UD-Q4_K_XL | 8K | 1,169 | 52.6 |
| IQ3_S | 8K | 1,242 | 59.7 |
| IQ3_S | 128K | 1,312 | 42.8 |

0.2.9 在 **Windows** + Strix Halo 的交错测试（appinn / linuxcompatible 转述，[UNVERIFIED]）：Qwen3.8 IQ3_S 8K 791→1,424 t/s、32K 778→1,460 t/s，decode 57.4→58.9 t/s。**Linux 侧官方明确写 `Linux gfx1151 keeps the opt-in above until it is measured there`，即这批 Windows 提速开关在 Linux 上尚未测量启用。**

### 6.2 本机现有栈实测（2026-10-03，`2026-10-03-35B速度复测.md`）
| 指标 | 值 |
|---|---|
| 35B-A3B decode 中位 | **90.14 t/s**（83.12–92.26） |
| 35B-A3B 长 prefill（89K tokens，wall 171 s） | **520 t/s** |
| 35B-A3B 短 prefill 中位 | 205.60 t/s |
| MTP 累计接受率 | 77.4% |
| 冷启动 84K tokens → 同 slot 复用 | 149 s → <1 s（18–202×） |
| 上下文上限 | 262,144（本 build 无 clamp） |

### 6.3 对比判读

| 维度 | 现有栈 | Strata | 判定 |
|---|---|---|---|
| decode | 35B-A3B **90.14 t/s** | 125B Flash-Next 53.8–59.7 t/s | 模型量级不同，**不可直接比**。同为 Qwen3.8-Flash-Next 时，本机 ROCmFP4 88 GiB 版本 **无 decode 实测记录**，无法给出差值 |
| prefill | 89K 长 prompt **520 t/s** | 8K–32K 短窗口 1,159–1,460 t/s | Strata 数字更高，但口径不同（短窗口 + hipBLASLt tuning table + `--prefill 16384`），官方自身警告 `Compare numbers within one table, not across` |
| 长上下文 | 262,144 实测可用 | 8K–262K，128K 下 decode 掉到 42.8–51.4 t/s | 现有栈在 262K 上已跑通并做了 LCP 复用优化 |
| 多轮复用 | `--cache-idle-slots` + slot 内 LCP，18–202× | `/slots` save/restore、prompt cache、expert profile 学习 | 两者思路类似；现有栈已针对 WorkBuddy 67K token 注入调优 |
| 多模态 | mmproj 已验证（35B / Qwen3.8） | 有 vision，AMD Linux 支持；CPU 读图数秒/张 | 现有栈可用 |
| API 丰富度 | OpenAI `/v1/chat/completions`（经 docproxy） | OpenAI + Anthropic Messages + Responses（Claude Code / Codex CLI 直连） | **Strata 明显更强** |
| 面板托管 | MCSManager 已接入，含自动重启/显存护栏 | 需新建实例、改端口 | 现有栈符合铁律 |
| 模型自由度 | 任意 GGUF（含 ROCmFP4 私有 type、QWEN4EXP 等新架构） | 3 个模型族 + pinned packs | **现有栈明显更强** |
| 稳定性 | 生产运行数月，docproxy 已修 chunked/SSE/marker 三类故障 | experimental，Linux gfx1151 未测完 | 现有栈明显更强 |

> 社区对照数字 `Qwen3.8-Flash-Next-IQ4_XS 27.2 t/s`（Vulkan RADV 无投机）来自项目长期笔记转述，非本机实测，**[UNVERIFIED]**，仅作背景。

---

## 七、若仍要部署：硬性清单

| # | 动作 | 风险 / 回滚 |
|---|---|---|
| 1 | **改 BIOS UMA 96 → 64 GiB**（或至少让 OS 可见 ≥64 GiB） | 破坏现有 Vulkan 栈显存余量；回滚 = 改回 96 GiB + 重启。这是唯一能让 Strata 跑出标称速度的前提 |
| 2 | 内核 cmdline 加 `ttm.pages_limit=29360128 ttm.page_pool_size=29360128 amd_iommu=off` | 当前是 modprobe.d 的 `pages_limit=25600000`，非 cmdline；改动需 root + 重启。回滚 = 删参数 |
| 3 | 端口改到非 8080（如 8082），`--port` 或改 run script | 保持 18090 docproxy → 8080 现有链路不变 |
| 4 | 新建 MCSManager 实例托管 Strata，禁止裸跑 | 遵守少爷定策；`gpu_arbiter` 显存护栏需相应扩展 |
| 5 | 下载官方 packs 到 `$HOME/models`（66–94 GB） | `github.com` 走 `gh-proxy.com`；HF 走 `hf-mirror.com`；不删现有 ROCmFP4 文件 |
| 6 | 若坚持源码构建：ROCm 7.14.1 TheRock gfx1151（1.7 GB）+ CMake/Ninja HIP 构建约 25 分钟 | 系统 ROCm 7.1.0 不匹配但打包引擎自带 wheels，**非阻塞**；优先用 AppImage 免构建 |
| 7 | 验证：`strata launch --plan --family qwen --model iq2_xs` 先看计划不下载 | 可回滚：计划模式不落盘 |

**不建议的动作**：在现配置下直接 `strata launch` 跑大模型。按 4.3 推论会退化为 SSD 分层极慢，且 HIP 吃 host RAM 有全局 OOM 风险（2026-10-08 已实测）。

---

## 八、建议

1. **维持现状**：现有 llama.cpp + Vulkan 栈在 96 GiB carve-out 布局下是本机最优解，decode 90 t/s、262K 上下文、ROCmFP4 私有量化、多模态、面板托管全部可用，且经过数月生产验证。
2. **若目标是「Anthropic Messages / Responses API 直连 Claude Code」**：成本最低的做法是给现有 18090 docproxy 加 `/v1/messages` 转换层，而不是引入 Strata（会连带 BIOS 改动）。
3. **若目标是「验证 125B MoE 专家分层调度」**：可做隔离 PoC —— 单独改 BIOS 到 64 GiB、单独下载 IQ2_XS、单独端口 8082、跑完再改回 96 GiB。代价是一次重启 + 70 GB 下载 + 现有栈短暂停服，且 PoC 期间不能并存跑视频生成。
4. **不建议把 Strata 作为现有栈的补充常驻**：内存池零和 + 私有量化不兼容 + experimental 状态，三者叠加使收益（更丰富 API、更高短窗口 prefill）不抵成本。

---

## 九、来源清单

| 来源 | 用途 |
|---|---|
| `https://raw.githubusercontent.com/Niko1221/Strata/main/README.md` | 模型族、安装、硬件支持表、版本 0.2.9 |
| `https://raw.githubusercontent.com/Niko1221/Strata/main/docs/STRIX_HALO.md` | gfx1151/HIP/GTT/carve-out 定义、ROCm 7.14.1、官方 Linux 基准、experimental 状态与已知问题 |
| `https://raw.githubusercontent.com/Niko1221/Strata/main/docs/MODELS.md` | 各量化内存/磁盘需求、`--gguf-dir`、Qwen3.6-35B-A3B 章节 |
| `https://raw.githubusercontent.com/Niko1221/Strata/main/docs/DETAILS.md` | 端口 8080、API 端点、上下文 8K–262K、MTP 参数、idle unload / lazy start、SHA-256 校验 |
| `https://www.linuxcompatible.org/story/strata-v0140-brings-strix-halo-support-and-13x-faster-linux-startup` | v0.1.40 首次 HIP on gfx1151、1,293/53.8 t/s、13× 冷启动 |
| `https://www.appinn.com/strata-0-2-9/`、`https://www.linuxcompatible.org/story/strata-029-adds-1bit-deepseek-strix-halo-speedups-and-multigpu-fixes` | 0.2.9 Windows Strix Halo 提速数字 |
| `https://www.besthub.dev/articles/how-strata-runs-a-125b-model-on-a-12gb-gaming-gpu-47ec066aabfc`、`https://www.electronicsforu.com/?p=203668` | 专家分层机制、硬件门槛 |
| 本机 `free -h` / `/proc/meminfo` / `/proc/cmdline` / `rocm-smi --showmeminfo vram,gtt` / `ss -ltnp` / `df -h` / `ps` | 2026-11-06 实测状态 |
| 本机工作区 `.workbuddy/memory/MEMORY.md`、`2026-10-03.md` | 双池机制、2026-10-08 OOM 事故、ROCmFP4 type 101、性能基线、面板托管铁律 |
| `2026-10-03-35B速度复测.md` | 35B-A3B decode / prefill 实测 |
