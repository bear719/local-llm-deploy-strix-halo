# Gufo 方案：本地部署可行性分析

日期：2026-11-06 23:30 GMT+8
对象：AMD Ryzen AI MAX+ 395 / Strix Halo / gfx1151 / 128 GiB 物理统一内存主机
上承：`2026-11-06-Strata方案-本地部署可行性与对比分析.md`、`2026-11-06-Strata方案-社区经验收益预测.md`

---

## 一、结论（先给判定）

**Gufo 是本机硬件的原生专属引擎（gfx1151 是其唯一生产目标），硬件匹配度 100%，但本机当前 BIOS 内存分法下物理不可部署；改 BIOS 后可部署，代价是摧毁现有 Vulkan 生产栈。判定：可做隔离 PoC，不可替换现状。**

**与上一份 Strata 报告合并后的决策变更：若最终决定改 BIOS 做隔离 PoC，优先测 Gufo，不测 Strata。** 两者改 BIOS 的代价完全相同，但 Gufo 有同机中文实测支撑的 prefill / 并发 / 冷加载收益，Strata 的速度收益已被社区收敛到 ≈1×。

四条硬阻塞：

1. **GTT 容量（决定性）**：Gufo 权重走 GTT / OS 可见 RAM。官方 `BENCHMARKS.md` 实测 Flash-Next 峰值 GTT **88,931.12 MiB（86.85 GiB）**、27B Q4 最小 **39.14 GiB**；本机 GTT Total **30.47 GiB**、MemAvailable **12 GiB** → **连最小的 27B Q4 都装不下，所有文本主模型全灭**。社区独立实测「需腾出 90GB 以上，84GB 可用直接 `bad_alloc`」与官方数字吻合。
2. **BIOS 层零和**：要跑 Gufo 必须把 BIOS UMA 从 96 GiB 改到 512 MiB，让 OS 可见 ~120 GiB。改后 carve-out 塌到 0.5 GiB，现有 35B-A3B Q4_K_P、Q5_K_P（43.7 GiB）、MiniMax-H3（40.85 GiB）、sd.cpp / Qwen-Image-2.1 视频图像链路全部无法加载。
3. **模型零重叠**：本机 6 个 GGUF 无一个能被 Gufo 读取（ROCmFP4 私有 type 101 + Gufo 只吃 pinned 的 Unsloth 特定量化）。少爷主力 35B-A3B 只存在于**第三方 fork**，且需 Q6dense 特制权重。
4. **链路与运维**：8080 端口冲突、MCSManager 面板托管铁律、docproxy 的 `enable_thinking` 注入 Gufo 不认、`model` 字段强制匹配、`amd_iommu=off` 连带禁用已打通的 NPU。

**一句话**：这次不是「引擎不适配硬件」，是「硬件被我们按另一种方式切了」。Gufo 与本机是同一块硅，但内存分法互斥。

---

## 二、Gufo 是什么（事实核对）

| 项 | 值 | 来源 |
|---|---|---|
| 仓库 / 许可 | `gufo-org/gufo`，MIT（原创代码），适配代码保留各自 NOTICE | README |
| 定位 | **垂直 Strix Halo 引擎**：`Ryzen AI MAX+ 395 / Radeon 8060S (gfx1151) / up to 128 GiB`，Linux x86-64 是唯一生产目标 | README、`docs/PERFORMANCE.md`「The only production target is Linux x86-64 on AMD Strix Halo」 |
| 当前版本 | **v0.30.0（2026-11-04）**；v0.29.0（同日）含 `⚠ BREAKING CHANGES`、删除 API-key auth | GitHub Releases API |
| 社区规模 | 976 star / 167 fork，日更（v0.27→v0.30 在 7 天内） | Bee catalog、Releases |
| 引擎本质 | **不是 llama.cpp 分支**。C++20 + 手写 Wave32/Wave64 HIP 内核，参考 llama.cpp 的 GGUF/正确性路径、vLLM 的连续批处理、hipEngine 的无 torch HIP 执行 | README Reference Projects、`docs/PERFORMANCE.md` |
| 后端 | **ROCm HIP**（hipBLAS / hipBLASLt / rocBLAS / rocWMMA），不是 Vulkan | README 依赖表 |
| 权重加载 | mmap GGUF 分片**直接注册给 HIP**：`The production Qwen3.8-27B loader registers mapped GGUF shards directly with HIP`；Flash-Next host buffers 用 Linux long-term pins | README、`docs/PERFORMANCE.md` |
| 投机解码 | DFlash2（27B）、MTP（Flash-Next / 35B）、DSpark（DeepSeek V4 Flash）、prompt lookup | README、`docs/CLI.md` |
| 模型清单 | Qwen3.8 27B、Qwen3.8 Flash-Next、DeepSeek V4 Flash、Qwen3-ASR 1.7B、Qwen3-TTS 1.7B、EmbeddingGemma 2、Qwen-Image-2.1 / Turbo、MiniMax H3 | README + `docs/models/` 目录（**无 35B 目录**） |
| API | OpenAI Chat Completions + Responses，支持 images / function tools / structured output / streaming；默认示例 8080 | README、`docs/CLI.md` |
| 已经明确不支持 | **Claude Code**（每轮注入 system message 导致每轮全量重算 prefill，issue #522） | README Harness notes |
| 容器 | `ghcr.io/gufo-org/toolboxes/gufo-runtime:latest`，rootless Podman + `--group-add keep-groups`（需 crun） | README Quickstart |
| 工具链 | Nix 与普通 CMake 各一套生产配置；pinned **GCC 16.2 + ROCm 10.1.0 / HIP Clang 24**；早期版本为 GCC 15.3 + ROCm 7.2.3 | README（一个月内 ROCm 7.2.3→10.1.0，迭代极快） |

> 注：`docs/` 里没有 HARDWARE.md / SETUP.md / INSTALL.md；GitHub 代码搜索 `repo:gufo-org/gufo gttsize` 返回 **0 命中**。官方**完全不写 BIOS / GTT 配置**，把「大 GTT」当作环境前提。本报告第四节的 BIOS 结论来自社区实证交叉验证，不是官方明文要求。

---

## 三、本机已满足的条件（阻塞不在内核能力）

2026-11-06 23:26 实测：

| 检查项 | Gufo / 社区要求 | 本机实测 | 判定 |
|---|---|---|---|
| 内核版本 | ≥ 6.18.4（Halogen/Gufo handover）；≥ 6.16.9（通用 GTT） | `7.0.0-42-generic` | 满足 |
| `CONFIG_HSA_AMD_SVM` | =y | `CONFIG_HSA_AMD_SVM=y`、`CONFIG_HSA_AMD=y`、`CONFIG_DRM_AMDGPU_USERPTR=y` | 满足 |
| KFD `gfx_target_version` | `110501` | `110501`（node 1，simd_count 80） | 满足 |
| KFD capability bit `0x08000000` | 必须置位 | `capability=671326848=0x2803a280`，位运算 `& 0x08000000 = True` | 满足 |
| `/dev/kfd`、`/dev/dri/renderD*` 权限 | render + video 组 | `crw-rw----+ root render`；`lc` 在 `render(990)` / `video(44)` | 满足 |
| `mem_info_vram_total` / `gtt_total` | — | `103079215104`（96.00 GiB）/ `32721608704`（30.47 GiB） | 见第四节 |
| host MemTotal / MemAvailable | — | 30.47 GiB / **12 GiB**（swap 15 GiB 已用 8.2 GiB） | 见第四节 |
| ttm 参数 | 社区 `32505856`（124 GiB） | `/etc/modprobe.d/amd_ttm.conf`：`pages_limit=25600000`、`page_pool_size=25600000`（≈97.66 GiB 允许上限） | 允许上限够，**物理后盾不够** |
| ghcr.io 可达性 | 拉容器镜像 | `https://ghcr.io/v2/` 返回 HTTP 401（匿名探测预期响应），0.59 s | 满足（国内慢，见第六节） |
| 磁盘 | 几十 GB ~ 260 GB | `/` 可用 **240 GiB** | 满足 |
| 系统 ROCm | 容器自带 userspace | 系统 ROCm 7.1.0（打包）；社区 handover 明确 `No ROCm on the host. The container image carries its own userspace` | 非阻塞 |

**结论：内核、驱动、SVM、KFD、设备权限、网络、磁盘全部达标。唯一阻塞是 BIOS 把 96 GiB 划给了 carve-out，只留 30.47 GiB 给 OS/GTT。**

---

## 四、决定性冲突：GTT 容量

### 4.1 官方实测的 GTT 峰值（一手证据）

`docs/models/qwen3.8-flash-next/BENCHMARKS.md`（PR #877 控制组，2026-11-04，ROCm 10.1，同机）逐字：

> `Peak driver GTT is identical: AR 84,774.46 MiB and MTP 88,931.12 MiB. Host RSS peaks are AR 3,117 → 3,085 MiB and MTP 3,125 → 3,147 MiB`

> `## Memory occupation` 表：`pp2048 + tg128 | Gufo 88.78 GiB | llama.cpp 84.84 GiB`；`16K prefix | 90.53 GiB | 85.31 GiB`

`docs/models/qwen3.8-27b/BENCHMARKS.md` 逐字：

> `Gufo now loads the vision projector by default, and HIP counts retained RAM prompt snapshots: with --cache-ram-bytes 1073741824, Q4 peaks at 39.14 GiB in both rows.`

> 表：Q4 AR `40.20 GiB`（16K prefix `50.27 GiB`）；Q8 AR `53.15 GiB`（16K prefix `63.22 GiB`）

换算与对照：

| 模型 / 场景 | Gufo 官方峰值 | 本机 GTT Total | 缺口 |
|---|---:|---:|---:|
| 27B Q4 AR（最小文本模型） | **39.14–40.20 GiB** | 30.47 GiB | **−8.7 GiB** |
| 27B Q8 AR | 53.15–63.22 GiB | 30.47 GiB | −22.7 GiB 起 |
| Flash-Next Q4 AR | 84.84 GiB（HIP）/ GTT 82.79 GiB | 30.47 GiB | −52.3 GiB |
| Flash-Next Q4 MTP | **88.93 GiB**（GTT 88,931 MiB） | 30.47 GiB | −58.5 GiB |

**host MemTotal 只有 30.47 GiB，MemAvailable 只有 12 GiB。Gufo 连最小的 27B Q4 都加载不了，不存在「先跑个小模型验证」的降级路径。**

### 4.2 社区交叉验证（三方独立，数字吻合）

| 来源 | 原文要点 |
|---|---|
| 微信公众号 / 今日头条同机中文横评（AMD MAX+ 395 128GB） | 「**gufo 跑 Flash-Next 131K 上下文要占 86GB 左右显存（统一内存里的 GTT），机器上要先腾出 90GB 以上。我第一次起 gufo 时只有 84GB 可用，直接报了 bad_alloc**」；「halogen 建议把 BIOS 里的 UMA 显存划分设到最小，而不是 Auto」 |
| Reddit r/StrixHalo（`gsqhalocpp` 帖） | 「**For the ROCm backends I set the BIOS UMA to 512 MB and used `amdgpu.gttsize=126976 ttm.pages_limit=32505856`. With my old 64 GB carveout, Vulkan worked but ROCm would have been capped by the 40 GB GTT limit.** Gufo with Q4 uses the whole box.」 |
| LlamaStash / Halogen + gufo handover 指南 | 「**The UMA frame buffer must be at its smallest explicit value (for example 512 MB), not Auto**」；「Set `amdgpu.gttsize` and `ttm.pages_limit` to about the installed RAM. For 128 GB that is `amdgpu.gttsize=126976 ttm.pages_limit=32505856`」；「**Each Flash-Next engine takes 80 to 90 GiB**」 |

社区「86GB / 需 90GB+」与官方 88,931 MiB（86.85 GiB）**独立吻合**，构成完整证据链。

### 4.3 项目旧笔记的「降 pages_limit 让 HIP 走 carve-out」修法对 Gufo 不适用

项目 `MEMORY.md` 第二节记有一条未执行的修法：`pages_limit → 20971520`（80 GiB）使 GTT < VRAM，让 KFD 改用 carve-out。**该修法不能作为 Gufo 的绕行路径**，三条理由：

1. **分配路径不同**：该修法针对 KFD `hipMalloc` 类 VRAM 分配（`drm/amdkfd: use GTT for VRAM on APUs only if GTT is larger`）。Gufo 用 `mmap` GGUF 分片 + `hsa_amd_register_*` 系统内存注册（README 原文见第二节），后盾是 **OS 可见的宿主页**，不是 KFD VRAM 分配。
2. **官方数字直接证伪**：Gufo 自己报的 `Peak driver GTT = 88,931 MiB`、`Host RSS ≈ 3 GiB`，说明权重/KV 全在 GTT 侧，没走 carve-out。
3. **物理上限仍在**：即便该修法对某类 HIP 应用成立，96 GiB carve-out + 30.47 GiB host 的分法下，Gufo 需要的是 **OS 可见的 ~89 GiB 可映射页**，carve-out 是 OS 不可见的固件保留区，无法替代。

判定：此路**无实证支持，不列入可行路径**。要证伪须做隔离实测，但代价已与改 BIOS 等同。

### 4.4 改 BIOS 的连带代价（比 Strata 分析新增两项）

| 代价 | 说明 | 来源 |
|---|---|---|
| 现有 Vulkan 栈全灭 | carve-out 96 → 0.5 GiB：35B Q4_K_P（~31 GiB）、Q5_K_P（43.7 GiB）、MiniMax-H3 四组件（40.85 GiB）全落此处；sd.cpp 已因显存弃用 704×1280 | 项目 `MEMORY.md` 第二、七节 |
| **NPU 失效** | `amd_iommu=off` 是 Gufo/Halogen 大 GTT 配置的标准项；offsite.guru 原文：`It also disables DMA translation machine-wide and takes the NPU with it`。本机 NPU（flm v0.9.45 / 8219）已打通 | 项目 `MEMORY.md` 第六节 + offsite.guru |
| 当前生产任务中断 | 实测时本机 `sd-cli` 正在跑 `Qwen-Image-2.1` 图像生成（drama-series-agent EP005 SHOT-012），VRAM used 21.5 GiB；8080 未监听、18090 docproxy 在听 | 本机 `ps` / `rocm-smi` / `ss -ltnp` |
| 前提不成立 | 社区 512 MiB UMA 配置均来自 **headless 专用模型服务器**；本机是「桌面 + WorkBuddy + docproxy + 视频/图像生成」混合生产 | 上一份收益预测报告场景 C |

---

## 五、模型兼容性（零重叠）

| 本机已有文件 | Gufo 能否直接用 | 原因 |
|---|---|---|
| `Qwen3.8-Flash-Next-ROCmFP4-FAST-imatrix-v2.gguf`（88 GiB） | **否** | 私有 ggml type 101，只有 `llama-qwen4exp-rocmfpx` fork 能读；Gufo 走 pinned 上游 GGUF 块格式 |
| `Qwen3.8-Flash-Next-MTP-ROCmFP4-FAST.gguf`（2.3 GiB） | **否** | 同上；Gufo 需 Unsloth `MTP/mtp-Qwen3.8-Flash-Next-shared-Q8_0.gguf` |
| `Qwen3.6-35B-A3B-Uncensored-Q4_K_P.gguf`（22 GiB）/ Q5_K_P（27 GiB） | **否** | 官方 `docs/models/` 无 35B 目录；仅第三方 fork 支持 |
| `Qwen3.6-35B-A3B-MTP-ONLY-Q4_K_M.gguf`（1.6 GiB） | **否** | MTP head 格式不匹配 |
| 两个 mmproj（858 / 863 MiB） | **否** | Gufo 27B 默认加载自带 vision projector，路径/格式由模型卡固定 |

**Gufo 的量化白名单很窄**（Reddit 实测）：

> `Gufo is the fastest, but it only accepts unsloth Q4_K_XL for Flash-Next. Its Flash-Next loader only allows Q4_K/Q5_K/Q6_K/Q5_1/Q8_0 experts. IQ3 was requested in issue #303 and declined.`

**35B-A3B 的唯一路径是第三方 fork** `NinjaPear/gufo-Qwen3.6-35B-A3B-Q6dense`（自述 `a fork of gufo to support Qwen 3.6 35B A3B for workloads that prioritizes speed over intelligence`），需 **Q6dense 特制权重 + native MTP**，报 `3,095.44 tok/s pp @4,096 depth`、`190.67 tok/s tg` 单用户、`334.35` 8 并发。该数字是 fork + peak + repetitive output，**不可作为本机基线对比依据**。

下载代价：全部按少爷永久约定落到 `$HOME/models`，不覆盖现有文件；本机 `hf` CLI 未装（项目 `MEMORY.md` 第九节），走 `curl` + `hf-mirror.com`；容器镜像国内慢，社区用 `ghcr.nju.edu.cn` 镜像源。磁盘 240 GiB 够放一套 Flash-Next + 一套 27B，但不足以并行多套。

---

## 六、链路与运维冲突

| 项 | 冲突 | 修法 |
|---|---|---|
| 端口 | Gufo 示例 `--port 8080`，与现有 llama-server 同端口；18090 docproxy 上游硬编码 8080 | Gufo 固定改到 **8082**，8080/18090 不动 |
| 面板托管铁律 | 少爷定策「llama 推理实例一律经 MCSManager 面板启动，禁止裸跑」；GPU arbiter 会 kill 非托管进程 | 新建面板实例，`startCommand` 前台 `exec`，端口 8082；禁止 `docker run -d` 裸跑 |
| **thinking 注入** | docproxy 注入 `chat_template_kwargs.enable_thinking=false`，Gufo 不认该字段；Gufo 用 `think=off`，且 `Auto uses the model default: enabled for Qwen3.8` → 默认开思考，会复现「content 空」类问题 | 改 `tools/docproxy.py` 注入逻辑，或启动加 `--think off` |
| **model 字段** | 社区实测「gufo 要求请求里的 model 字段和服务名一致，不一致会报 400」；docproxy 透传的是本机 llama 模型名 | 改 `servedModelName` 或在 docproxy 做模型名重写 |
| 请求体 | 社区 gotcha「default 8 MB request limit rejects large images」；WorkBuddy 注入 40K+ tokens 用 chunked 无 Content-Length | 显式加大 `maxRequestBytes`，并验证 Gufo 对 chunked 上传与 SSE 的处理 |
| 缓存 RAM | 社区 gotcha「Set `--cache-ram-bytes` explicitly because of issue #387」；与本机 llama.cpp `-cram` 默认 8 GiB 吃 host RAM 同类坑，本机 host 仅 30 GiB | 显式设小值（官方基准用 1 GiB） |
| 容器运行时 | **podman 未安装**；`docker` 已装但 `lc` 不在 docker 组（`permission denied ... /var/run/docker.sock`）；`nix` 未装 | 装 podman + crun（rootless），或把 lc 加进 docker 组并适配 `--device /dev/kfd --device /dev/dri --group-add render --group-add video`；避免源码构建 |
| 系统 ROCm | 系统 7.1.0，官方 10.1.0 | 容器自带 userspace，非阻塞；只需宿主内核驱动 |
| 版本节奏 | v0.27→v0.30 在 7 天内，v0.29.0 有 BREAKING CHANGES 且删 API-key auth | 固定 tag 部署，禁止 `latest`；升级前读 CHANGELOG |
| 中文输出 | Windows fork 文档：`--mtp-draft-vocab latin is not recommended for Chinese output (draft acceptance fell to 3% on zh prose, decode -34%)`；中文社区实测 Gufo 中文长文 33.4 t/s 落后 Halogen 51.8，27B 中文长文 17.3 < llama.cpp 19.1 | 中文场景必须单独 A/B，不套用英文/代码数字 |

---

## 七、性能与收益（同口径折算）

### 7.1 官方同机 Gufo vs llama.cpp 参考构建

来源：`docs/models/qwen3.8-flash-next/BENCHMARKS.md`，同一 Strix Halo 128GB、`UD-Q4_K_XL`、HTTP / greedy / thinking off；llama.cpp 为 pinned Nix 参考构建 `b11069` / `6fcaa16f`，**不是本机调优 fork**。

| 场景 | Gufo | llama.cpp 参考 | 增益 |
|---|---:|---:|---:|
| AR pp2048 @depth 0 | 1,801.01 t/s | 489.59 | +267.9% |
| AR pp2048 @131,072 | 1,557.18 | 144.78 | +975.5% |
| AR tg128 @depth 0 | 28.29 | 22.20 | +27.4% |
| AR tg128 @131,072 | 27.85 | 7.98 | +249.0% |
| **MTP tg mixed @depth 0** | **35.79** | 31.73 | **+12.8%** |
| MTP tg repetitive @depth 0 | 116.93 | 48.12 | +143.0% |
| 并发 8 / AR 聚合 | 125.48 | 68.79 | +82.4% |
| 并发 8 / MTP mixed 聚合 | 127.02 | 61.92 | +105.1% |
| 冷加载至 HTTP ready | **16.42 s** | 117.83 s | +617.6% |

官方自己标注 `Peak measured workloads ... Peaks include repetitive output`，`+143%` 那类数字来自重复文本下投机接受率虚高，**不能当持续吞吐**。

### 7.2 中文社区同机实测（AMD MAX+ 395 128GB，四场景中位）

来源：微信公众号 / 今日头条《AMD MAX+ 395 实测 halogen 和 gufo》，同一台机器、同一份 `UD-Q4_K_XL` GGUF、客户端计时。

| 指标 | Gufo | llama.cpp | 倍数 |
|---|---:|---:|---:|
| 单路生成四场景平均 | 58.3 t/s | 33.6 | **1.74×** |
| 中文长文单路 | 33.4 | 22.1 | 1.51× |
| 长文档 prefill（8K / 32K / 64K / 118K） | 1,493 / 1,625 / 1,602 / 1,551 | 228 / 298 / 266 / 232 | **5.2–6.9×** |
| 118K 文档首字延迟 | 74 s | 510 s | 6.9× |
| 8 路并发合计（Gufo 关投机 83 / 开 MTP 72） | 83 | 43 | **1.93×** |
| 27B + DFlash2 中文长文 | 17.3 | 19.1 | **0.91×（Gufo 更慢）** |
| 27B 降 AI 改写（10 段，temp 1.0） | 38.4 t/s / 75 s | 32.8 t/s / 86 s | 1.12–1.17× |
| 33 道中文 Agent 题 | 30 全对 + 3 部分，910 s | — | 对照 Halogen 33 全对 / 754 s |

**反向校验（怀疑一切）**：KBlip 十引擎横评（70 W TDP，128K 窗口，Aider polyglot Python）里，Halogen 21.5 min、CIRU 24.6 min、**gufo 36.0 min**，尽管 gufo 的 prefill 峰值与 Halogen 同档（1,000+ t/s）。→ **prefill 峰值不等于端到端任务收益**，必须看真实 workload。中文 33 题 gufo 用时也长于 Halogen，与该结论一致。

### 7.3 折算到本机基线

本机基线（`2026-10-03-35B速度复测.md`）：35B-A3B decode **90.14 t/s**、89K 长 prefill **≈520 t/s**、MTP 接受率 **77.4%**、有效带宽 ≈144 GB/s、120 W 功耗墙。

| 维度 | 预测（改 BIOS 且隔离 PoC 后） | 依据 / 折扣 |
|---|---|---|
| decode（mixed 中文） | **0.9–1.3×**（≈81–117 t/s） | 社区 1.74× 是相对未调优 llama.cpp + 125B 模型；本机 MTP 77.4% 已近带宽墙，且 HIP 在 Q4 decode 上不占优；27B 中文实测 0.91× 提供下界 |
| prefill（长上下文） | **2–3×** | 中文实测 5–7×，对照物已调优打 0.4 折；官方 131K 的 10× 属参考构建长上下文严重衰减，不取 |
| 并发吞吐 | **≈2×**（唯一结构性收益） | 8 路 83 vs 43；本机 `-np 1`，连续批处理是 Gufo 的一等公民 |
| 冷加载 | **3–7×** | 官方 16.42 vs 117.83 s、6.27 vs 23.33 s |
| 置信度 | **中** | 有同机中文实测，但模型（125B Flash-Next / 27B dense）与本机主力 35B-A3B 不同；35B 只在第三方 fork |

**不取的数字**：fork 的 190.67 t/s（Q6dense 特制权重 + peak + repetitive）；官方 116.93 t/s（repetitive）；README 的 1,801 pp（AR 峰值、短窗口）。

---

## 八、与 Strata 的对比（承接前两份报告）

| 维度 | Strata | **Gufo** |
|---|---|---|
| 硬件定位 | 通用（NVIDIA / Mac / Windows），gfx1151 为 `experimental` | **gfx1151 唯一生产目标，手写 HIP 内核** |
| 后端 | HIP + SSD 专家分层（Engram 29 GB） | HIP + mmap GGUF + 连续批处理 + 磁盘 prompt cache |
| 内存需求 | `device_free_bytes = MemAvailable − 6 GiB` ≈ 8–10 GiB（本机） | **GTT 峰值 88.93 GiB（官方）/ 需 90 GiB+（社区）** |
| 本机可用 | 8.4–10.4 GiB → 必走 SSD，极慢 | 30.47 GiB → **连最小模型都装不下，直接 bad_alloc** |
| 本机模型兼容 | 0（type 101 不认） | 0（需 Unsloth 特定量化；35B 仅第三方 fork） |
| 社区倍数 | 官方 6× → 社区 2× → 本机折算 0.9–1.4× | 中文同机实测 decode 1.74×、prefill 5–7×、并发 1.93× → 本机折算 decode 0.9–1.3×、prefill 2–3× |
| 中文 | `Coder quant systematically breaks Chinese output` | 中文长文相对弱、27B 中文更慢，但 33 题 Agent 30 全对 |
| 成熟度 | 0.2.9，experimental，Linux gfx1151 提速未测 | v0.30.0，976 star，日更，CI + 逐模型质量报告 |
| API | OpenAI / Anthropic / Responses | OpenAI Chat + Responses；**Claude Code 不支持** |
| 改 BIOS 代价 | 相同（零和 + NPU 失效 + 视频栈停摆） | **相同** |
| 结论 | 不建议 PoC | **若要 PoC，选这个** |

---

## 九、部署清单（仅在少爷授权后执行）

| 阶段 | 操作 | 备注 |
|---|---|---|
| 0 快照 | 记录当前 BIOS UMA=96 GiB；`cp /etc/default/grub /etc/default/grub.bak.20261106`；`cp /etc/modprobe.d/amd_ttm.conf *.bak`；导出 MCSManager `InstanceConfig/*.json` | 可回滚原则 |
| 1 BIOS | UMA Frame Buffer `96 GiB → 512 MiB`（或 Auto 的最小显式值）；Above 4G Decoding on | 需重启，期间生产全停 |
| 2 内核 | `amdgpu.gttsize=126976 ttm.pages_limit=32505856 amd_iommu=off`，`update-grub` + 重启 | NPU 将失效；验证 `mem_info_gtt_total` ≈ 133 GB、`free -h` ≈ 120 GiB |
| 3 运行时 | 装 `podman` + `crun`；镜像走 `ghcr.nju.edu.cn` 镜像源 | 或把 lc 加 docker 组并适配命令 |
| 4 权重 | `curl` + `hf-mirror.com` 下载 Unsloth `Qwen3.8-27B-UD-Q4_K_XL.gguf` + `z-lab DFlash2 Q4_K_M` 到 `$HOME/models` | **先只下 27B 小套验证链路**，别一上来 111 GB Flash-Next |
| 5 面板实例 | MCSManager 新建实例，`startCommand` 前台 `exec podman run --rm --device /dev/kfd --device /dev/dri ... --port 8082:8080 ... gufo serve --host 0.0.0.0 --port 8080 llm --model ... --speculative dflash2 --dflash-model ... --cache-ram-bytes 1073741824 --think off` | 不裸跑；端口 8082 |
| 6 docproxy 适配 | 改 `tools/docproxy.py`：注入方式由 `enable_thinking` 改为 Gufo 认的字段、模型名重写、加大请求体上限；验证 chunked 上传与 SSE | 改前备份；先在本机 18091 测试实例验证再上 18090 |
| 7 验证 | `gufo diagnose`；纯文本 / 中文长文 / 8 并发 / 冷加载四组；prompt 带随机 uuid 前缀规避缓存 | 对照 `tools/bench-35b-20261003.py` 口径 |
| 8 回滚 | BIOS 改回 96 GiB + 还原 grub / amd_ttm.conf + 重启；删面板实例；恢复 docproxy 原注入 | 权重文件保留不删 |

**验收门槛**：27B Q4 能起（GTT 40 GiB）、中文长文 decode ≥ 本机 27B 基线、8 路并发聚合 ≥1.5×、docproxy 18090 → 8082 链路 200 且 content 非空。任一不达标即回滚。

---

## 十、数据校验与剔除（怀疑一切）

| 数据 | 校验结果 | 处置 |
|---|---|---|
| `kwkr.cn/news/616484`「`gufo run --model qwen2.5-7b.gguf`」「Gufo 没有原生并发队列」 | 与官方 README 直接矛盾（Gufo 无 `gufo run`；连续批处理与并发是一等公民，官方有 8 并发表）→ AI 生成错文 | **剔除** |
| 微信文「unsloth UD-Q4_K_XL GGUF 文件 111GB」 | 与官方 `Memory occupation 88.78 GiB` 口径不同（可能含 n-gram 表 / 十进制 GB / 多分片） | `[UNVERIFIED]`，不用于容量计算；容量一律用官方 88.93 GiB GTT + 90 GiB 社区门槛 |
| 官方 README `116.93 tg` / fork `190.67 tg` | 官方自注 `Peaks include repetitive output`；fork 为第三方 + Q6dense 特制权重 | 不作持续吞吐，仅列上界 |
| 官方 `docs/` 无任何 BIOS / gttsize 说明 | GitHub 代码搜索 `gttsize` 0 命中 | BIOS 结论标注为**社区实证交叉验证**，非官方明文 |
| 官方 131K AR `+975.5%` | 分母是 llama.cpp 参考构建在 131K 衰减到 144.78 t/s，非本机调优 fork | 不用于本机折算 |
| KBlip Aider `gufo 36.0 min` vs Halogen 21.5 min | 与 prefill 峰值排名相反 | 保留作**反向校验**：峰值 ≠ 端到端收益 |

---

## 十一、决策建议（按优先级）

1. **维持现状**：96 GiB UMA + Vulkan + MTP 不变，Gufo 不进生产。理由：物理不可部署 + 改 BIOS 代价覆盖全部收益。
2. **场景 D 单点调优优先**（承接收益预测报告）：`amd_iommu=off` 单项 A/B（prefill +13~16%）、新 RADV（PP +18.4%）、FA / no-mmap / headless / CPU 限频逐项验证。**零 BIOS 改动、逐项可回滚，是唯一低风险正收益。**
   - 但注意：若采纳 `amd_iommu=off`，NPU 会失效，需先把 NPU 是否仍在使用确认清楚（本项目 MEMORY.md 第六节记录 flm 8219 已打通）。
3. **若决定做隔离 PoC，选 Gufo，不选 Strata**：共同代价相同，Gufo 是 gfx1151 原生、有中文同机实测、收益更实在。按第九节清单执行，先只下 27B 小套。
4. **Anthropic Messages / Responses API 需求**：成本最低仍是给 18090 docproxy 加转换层，不引入 Gufo（Gufo 本身还不支持 Claude Code）。
5. **统一多模态栈（MiniMax H3 / Qwen-Image-2.1）**：Gufo 官方标 `In progress`，且本机 sd.cpp 链路已可用，暂不迁移。
6. **不改 BIOS 的替代路径**：继续跟踪 `strix-llama` / `GSQHalo.cpp` 等**同时支持 Vulkan carve-out 与更大上下文**的 llama.cpp 分支；它们在 96 GiB carve-out 布局下与现有栈同池，无需零和切换（社区 Reddit 帖已有 IQ3_S 在 96 GB 机器上双 256K slot 的实测）。

---

## 十二、来源清单

**本机一手（2026-11-06 23:26 实测）**
- `uname -r` / `/proc/cmdline` / `/boot/config-*` / `/sys/class/kfd/kfd/topology/nodes/1/properties`
- `/sys/class/drm/card1/device/mem_info_{vram,gtt,vis_vram}_total`
- `free -h`、`rocm-smi --showmeminfo {vram,gtt} < /dev/null`、`ss -ltnp`、`id`、`ls -l /dev/kfd /dev/dri/renderD128`、`df -h $HOME`、`dpkg -l | grep rocm`
- 项目 `MEMORY.md`、`2026-10-03-35B速度复测.md`、`2026-11-06-Strata方案-*.md`、`~/.workbuddy/MEMORY.md`

**Gufo 官方**
- `https://raw.githubusercontent.com/gufo-org/gufo/main/README.md`
- `https://raw.githubusercontent.com/gufo-org/gufo/main/docs/models/qwen3.8-flash-next/BENCHMARKS.md`
- `https://raw.githubusercontent.com/gufo-org/gufo/main/docs/models/qwen3.8-27b/BENCHMARKS.md`
- `https://raw.githubusercontent.com/gufo-org/gufo/main/docs/{CLI,PERFORMANCE,BENCHMARKS}.md`
- `https://api.github.com/repos/gufo-org/gufo/{releases,contents,contents/docs,contents/docs/models}`、GitHub code search API
- `https://raw.githubusercontent.com/NinjaPear/gufo-Qwen3.6-35B-A3B-Q6dense/main/README.md`
- `https://github.com/Chiakai-Chang/gufo/blob/windows-port/docs/WINDOWS.md`

**社区实证**
- 微信公众号 / 今日头条《AMD MAX+ 395 实测 halogen 和 gufo》（同机中文横评 + 部署坑）
- `https://reditr.com/r/StrixHalo/comments/1wwobcq/`（BIOS 512 MB + GTT 参数 + Gufo gotchas）
- `https://wpnews.pro/news/handover-halogen-gufo-behind-llamastash-on-strix-halo-...`（LlamaStash handover，最小 UMA + 80–90 GiB/引擎）
- `https://kblip.com/research/benchmarks-best-engine-for-qwen-3-8-flash-next-on-strix-halo-RNBQWMv`（十引擎横评 + Aider）
- `https://offsite.guru/blog/halogen-strix-halo`（`amd_iommu=off` +13~16% prefill、NPU 连带失效）
- `https://github.com/jstormes/StrixHalo`、`https://datahardware.ai/blog/strix-halo-vram-allocation-guide-2026`（UMA 分法对照表）
- `https://github.com/ROCm/hip/issues/3892`、`https://github.com/ggml-org/llama.cpp/issues/19818`（HIP 只看 VRAM aperture / GTT 上限问题）

---

## 十三、待核项

1. 27B Q4 官方峰值 39.14 GiB 是「含 vision projector + 1 GiB cache-ram」的数字；关掉 projector / 更小 context 后能否压到 30.47 GiB 以下，官方无数据 → 需实测，但不改变「Flash-Next 必然装不下」的结论。
2. 微信文「GGUF 文件 111 GB」与官方 88.78 GiB 的口径差异未核；磁盘规划按官方 90 GiB 门槛 + 27B 小套估算。
3. `amd_iommu=off` 对本机 NPU（flm 8219）的实际影响未实测，仅依据社区原文推定。
4. Gufo 对 docproxy chunked 上传、SSE 心跳、`X-Trim-Prompt` 的兼容性需实测；`maxRequestBytes` 默认值官方 CLI 文档未给（社区称 8 MB）。
5. 本机 35B-A3B 与 Gufo 第三方 fork 的 Q6dense 权重是否可从现有 Q4_K_P 转换，fork 未说明；若无现成权重则该分支不可行。

---

**许可**：CC0-1.0，公共领域贡献，无任何限制。
