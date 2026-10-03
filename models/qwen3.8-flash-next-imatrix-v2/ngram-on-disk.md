# Qwen3.8-Flash-Next-ROCmFP4-FAST-imatrix-v2 + `--ngram-on-disk` 实施方案

日期：2026-09-27　机器：AMD Ryzen AI MAX+ 395（Radeon 8060S，VRAM 96 GiB / host 30 GB）
二进制：`$HOME/llama-qwen4exp-rocmfpx/build-vk4/bin/llama-server`（build 10820，commit b2cc77659）

## 一、结论

**可行，已实测跑通。** 该模型是 joined 表布局，`--ngram-on-disk` 是它的正确打开方式，
不是可选项而是必选项：表常驻内存会直接把 30 GB 的主机内存压进 swap。

## 二、为什么必须用 `--ngram-on-disk`（判定依据）

| 项 | 值 | 来源 |
|---|---|---|
| 架构 | `qwen4exp`（48 层，512 专家，A3B） | GGUF KV `general.architecture` |
| 表布局 | **joined**：单张量 `per_layer_token_embd.weight` | `tools/gguf_probe.py` 解析张量名 |
| 表形状 / 类型 | (160, 320001536)，ggml type 104 = `Q3_0_ROCMFPX`（3.5 bpw） | 同上 |
| 表体积 | 22,400,107,520 B = 20.87 GiB | 加载日志 `unused tensor ... (size = 22400107520)` |
| 对齐检查 | `ne0=160 % QK_ROCMFPX(32) == 0` → 通过 | `ggml/rocmfpx/rocmfpx.h` |

若**不加**该参数，这张表按 `TENSOR_READ_LAZY` 常驻主机内存。fork 文档
`ROCMFPX-NOTES.md:353-360` 实测 joined 布局会占用 21.1 GiB host 内存并触发 156 major
faults/sec 的换页；本机 host 仅 30 GB 且 swap 已写满 7 GB，后果是整机卡顿。

**对比：旧的 `v2-ple16` 是 per-head 布局（16 × `ple_ngram_embd.%d`，每个 ~1.3 GiB），
`--ngram-on-disk` 对它无效**——源码 `src/models/qwen4exp.cpp:216` 会打印
`--ngram-on-disk ignored` 后走 per-head 分支。所以两个文件不能套同一套参数。

## 三、`--ngram-on-disk` 是否真的生效（三重验证）

1. **加载期读盘量**：`/proc/<pid>/io` 的 `read_bytes` = 71.09 GB，
   恰为文件大小 93.48 GB 减去表 22.40 GB → 表的字节一次都没被读进内存或 mmap。
2. **推理期随机读**：112 token 的请求产生 2,584 次 pread、17.9 MB 读
   （≈160 KB/token，4 KiB 对齐的 O_DIRECT 随机读）。
3. **显存**：表未进入 VRAM，模型主体 66.2 GiB 全部 `-ngl 999` 上卡。

> 注：加载日志里出现 `unused tensor per_layer_token_embd.weight ... ignoring` 是
> `TENSOR_SKIP` 的正常表现，不代表 PLE 被禁用；该 fork 未打印
> "PLE n-gram table stays on disk" 这行 INFO。

## 四、实测数据（CT2000P310SSD8 NVMe，temperature 0.7）

| 配置 | 显存占用 | prefill | decode | 备注 |
|---|---|---|---|---|
| 无 MTP，`-c 16384` ×4 槽 | 73.3 GB | 79 t/s | **27.6 t/s** | 基线 |
| MTP，`-c 16384` ×4 槽 | 76.8 GB | 39~84 t/s | **31.3~35.2 t/s** | draft 接受率 45.5%（363/797） |
| MTP，`-c 65536` ×4 槽 | 79.2 GB | 39~81 t/s | **26.4~29.4 t/s** | |
| MTP，`-c 262144` `-np 1` `-ub 1024` | 90.6 GB | 38~80 t/s | **35.4~39.2 t/s** | 推荐配置 |

加载耗时约 55 秒（93 GB）。并发 2 请求输出无串扰、无 error/abort。

## 五、推荐命令

```bash
$HOME/llama-qwen4exp-rocmfpx/build-vk4/bin/llama-server \
  -m $HOME/models/Qwen3.8-Flash-Next-ROCmFP4-FAST-imatrix-v2.gguf \
  -md $HOME/models/Qwen3.8-Flash-Next-MTP-ROCmFP4-FAST.gguf \
  --spec-type draft-mtp \
  --ngram-on-disk --ngram-cache 512 --ngram-io-threads 64 \
  -ngl 999 -c 262144 -np 1 -b 4096 -ub 1024 \
  --metrics --host 127.0.0.1 --port 8080
```

已封装为 `start-qwen38-imatrix-v2.sh`（`long` / `multi` / `fg` / `bg` / `stop` / `status` / `check` 七种用法）。

## 五之二、在 MCSManager 面板里跑（必读）

面板把「前台主进程退出」当作实例停止。旧版脚本用 `nohup ... &` 后台化，于是脚本
一结束面板就显示"已停止"，再点启动又会因为上一个进程还占着 8080 而失败，
表现为：

```
已启动 PID 21220 ... → [INFO] 实例已停止 → [ERROR] 实例进程启动失败
```

（此时 llama-server 其实**活着且能正常推理**，只是脱离面板管控，成了孤儿进程。）

修复后的脚本行为：

- stdin 不是 tty（面板 / systemd / cron）时**自动改前台 `exec`**，日志直出到面板控制台；
  桌面终端里仍是后台 + 日志留存。想强制就显式写 `fg` / `bg`。
- root 经面板启动时拿不到 PAM 注入的环境变量，脚本自行兜住
  `VK_ICD_FILENAMES=/usr/share/vulkan/icd.d/radeon_icd.json`
  （少了它 Vulkan 枚举不到设备 → 静默退化 CPU 推理，速度掉一半以上且**不报错**）。
- 启动前自检：二进制/模型是否存在、**端口是否被占**（占用就直接报错，不再"启动即死"）。
  单独跑自检用 `./start-qwen38-imatrix-v2.sh check`。
- 日志与 PID 文件带 uid 后缀（`/tmp/qwen38-imatrix-v2-server-<uid>.log`），
  避免 root 和 lc 两种身份互相写不动。

面板侧配置（实例 `start-qwen38-imatrix-v2`，type=universal，processType=general，非 docker）：

| 项 | 值 |
|---|---|
| 启动命令 | `env $HOME/WorkBuddy/调试本地模型/start-qwen38-imatrix-v2.sh fg` |
| 停止命令 | `^c`（前台模式下 SIGINT 可被 llama-server 正常接收） |
| 工作目录 | 任意（脚本内部会切到二进制目录） |

实测（2026-09-27，以 root / 非交互方式跑 `fg`）：自检通过、ICD 正确注入、
前台加载正常，面板可完整接管启停。

> 注：脚本监听 `0.0.0.0` 且未设 API key（llama-server 会打 CORS 安全警告）。
> 只在可信网络内使用；跨网请加 `--api-key`。

### 参数说明

- `--ngram-cache 512`：行缓存 512 MiB ≈ 7.3 M 行（占表 2.3%）。默认 256 MiB。
  纯随机哈希访问命中率有限，但成本极低，给到 512~1024 无害。
- `--ngram-io-threads 64`：默认 64。O_DIRECT 随机读靠队列深度换吞吐，
  fork 注释写明该 NVMe 在 qd16/64/128 分别为 62k/130k/160k IOPS，不要调小。
- `--ngram-direct-io`：默认开（绕开 page cache）。若文件系统不支持 O_DIRECT
  会自动回退到 buffered 并打一条 WARN，无需干预。
- `-np 1`：draft-mtp 在多槽下有 cross-slot contamination（上游 PR #28123 作者声明）。
  要并发就接受这个风险，或关掉 MTP。

## 六、磁盘与内存预算（风险）

- **磁盘**：根分区剩 38 GB（93% 已用）。当前配置不再写盘，可正常运行；
  但**不要**再下载/转换第二个 93 GB 文件。`gguf_split_ple_heads.py` 需要等量额外空间，
  除非先删除 `Qwen3.8-Flash-Next-ROCmFP4-FAST-v2-ple16.gguf`（93.48 GB，已被本模型取代）
  或挂载空闲的 `nvme0n1p6`（976.6 GB，未挂载）。
- **显存**：262 K 上下文已到 90.6 GB / 103 GB。Vulkan 受 GTT 104.8 GB 硬上限约束，
  超限报 `vk::Queue::submit: ErrorDeviceLost`（不是 OOM，易误判）。
  想留余量就用 `-c 65536 -np 4`（79.2 GB）。
- **主机内存**：实测 used 14 GB，无换页压力——这正是 `--ngram-on-disk` 换来的。

## 六之二、速度调优实测（2026-09-27，同一 3 组 prompt × 5 次取中位数，temp 0.7）

| # | 配置 | decode | prefill | 结论 |
|---|---|---|---|---|
| A | long 档基線（`draft-mtp`），GPU **auto** 档 970 MHz | 31.96 t/s | 62.2 | 参照点 |
| B | `rocm-smi --setperflevel high`（sclk → 2900 MHz） | **33.70 t/s** | 61.1 | **+5.3%，唯一确定有效** |
| C | B + `--spec-draft-p-min 0.3` | 32.60 t/s | 61.9 | 无增益，已弃用 |
| D | B + `--spec-type draft-mtp,ngram-map-k` | 34.35 t/s | 63.4 | +2%，噪声级，保留（无害） |
| E | D + `-ctk q8_0 -ctv q8_0` | **34.55 t/s** | 61.7 | +2.5%，但**显存 90.99 → 86.84 GB（-4.16 GB）**，值得留 |

已固化进脚本，并在启动前自动尝试 `rocm-smi --setperflevel high`（无权限则静默跳过）。

## 六之三、`--spec-draft-n-max` / `--spec-draft-p-min` 网格实验（三轮，共 15 组）

统一条件：long 档（`-c 262144 -np 1 -b 4096 -ub 1024`）、GPU `high` 档 2900 MHz、
`-ctk q8_0 -ctv q8_0`、temperature 0.7，每组先预热 1 次再取 N 次中位数。
工具：`tools/spec-grid.sh`（自动改脚本 → 抢端口重启 → 等 `/health` → 调 `bench-server.py`）。

### 第一轮：`n-max` 扫描 + `p-min` 扫描（各 5 次）

| 组 | 配置 | decode | 接受率 | draft/步 | 每步接受 | 判断 |
|---|---|---|---|---|---|---|
| A | **默认 `n-max=3`, `p-min=0`** | 32.80 t/s | 43.1% | 3.05 | 1.31 | 基线 |
| B | `n-max=1` | **34.08** | 66.5% | 1.00 | 0.66 | 更快 |
| C | `n-max=8` | **11.51** | 19.9% | 7.94 | 1.58 | **崩塌 -65%** |
| D | `n-max=16` | **8.64** | 10.6% | 15.69 | 1.66 | **崩塌 -74%** |
| E | `p-min=0.3` | 33.71 | 49.0% | 2.83 | 1.39 | 噪声级 |
| F | `p-min=0.6` | 32.16 | 63.1% | 2.32 | 1.46 | 无增益 |
| G | `n-max=8 --spec-draft-adaptive` | 30.42 | 46.3% | 2.63 | 1.22 | 只救回大 n-max |
| H | 纯 `--spec-type ngram-map-k`（无 MTP） | 32.26 | 41.4% | 2.99 | 1.24 | ≈ 基线，无叠加 |

### 第二轮：隔离 `ngram-map-k` 混杂（各 8 次）

| 组 | 配置 | decode | 接受率 | 每步接受 |
|---|---|---|---|---|
| I | `n-max=2` + `ngram-map-k` | **35.11** | 53.4% | 1.07 |
| J | `n-max=1` + `p-min 0.3` | 34.11 | 70.5% | 0.71 |
| K | 纯 MTP `n-max=1`（去掉 ngram） | 34.61 | 69.6% | 0.70 |
| L | `n-max=1` + `--spec-ngram-mod-n-max 4` | 34.38 | 69.8% | 0.70 |

### 第三轮：纯 MTP 下 1 / 2 / 3 的干净对照（各 12 次）

| 组 | 配置 | decode | 接受率 | 每步接受 |
|---|---|---|---|---|
| M | 纯 MTP `n-max=1` | 34.22 t/s | 67.8% | 0.68 |
| N | 纯 MTP `n-max=2` | **34.75 t/s** | 53.3% | 1.06 |
| O | 纯 MTP `n-max=3`（默认） | 33.08 t/s | 44.5% | 1.33 |

### 结论与机制

1. **`n-max` 是最强杠杆，且越小越快；1~2 是最优区间，≥8 直接崩塌。**
   这推翻了早前「`nextn_predict_layers=1` 所以 `n-max` 无效」的判断——
   实测 draft/步 = 1.00 / 3.05 / 7.94 / 15.69，`n-max` 确实完全生效。
2. **机制**（源码 `common/speculative.cpp:1455-1461` + draft 循环 ~L380-440）：
   本机 `n_mtp_layers = 1`，`chain_heads = false`，所以 draft 走**串行循环**——
   想 draft N 个 token，就要对草稿模型**串行跑 N 次前向**，成本线性叠加；
   同时接受率随 N 增大暴跌（67.8% → 53.3% → 44.5% → 19.9% → 10.6%），
   每步有效产出只从 0.68 涨到 1.66 token（2.4x），而单步耗时涨了约 10x，**净亏**。
3. **`p-min` 无实质影响**：它确实能让接受率从 43% 抬到 63%（过滤掉低置信 draft），
   但 draft 总数同步减少（1602 → 932），净速度不变 → 保持默认 0，不必设。
4. **`--spec-draft-adaptive` 是大 `n-max` 的补救措施，不是加速手段**：8 → 30.42 t/s，仍输给小 `n-max`。
5. **最终固化**：`TUNING=(--spec-type draft-mtp,ngram-map-k -ctk q8_0 -ctv q8_0 --spec-draft-n-max 2)`
   实测复验 8 次：**35.59 t/s**（区间 33.74~37.00），显存 86.18 GB。
   相对默认 `n-max=3`（32.80）**+8.5%**，相对原始无调优基线（31.96）**+11.4%**。

### 真正的天花板在哪

- 无投机 27.6 → 有投机 35.59 t/s，**MTP 净增益 +29%**，接近 `n_mtp_layers=1` 串行结构下的极限。
- 剩余瓶颈：每 token 要搬运的 MoE 激活权重（512 专家取 10）× 约 256 GB/s 统一内存带宽。
  这条在本机硬件上无法靠参数突破，只能靠更激进的权重量化（牺牲质量）或换硬件。
- **35~36 t/s 是这台机器在这份权重上的新水位**（旧记录 33~35 已被 `n-max=2` 顶上去）。

## 七、备选方案：把 joined 表拆成 per-head（需磁盘空间）

`gguf-py/gguf/scripts/gguf_split_ple_heads.py` 可双向转换，逐字节拷贝不重量化。
per-head 布局下 16 张表跟随 `-ngl` 上 GPU，无需 on-disk 读盘。

fork 文档 `ROCMFPX-NOTES.md:363-368` 的对照测量：

| 表布局 | VRAM | swap | s/pass | PPL |
|---|---|---|---|---|
| joined（上游） | 64.5 GiB | 21.10 GiB | 5.39 | 4.6744 |
| per head | 85.1 GiB | 0.1 GiB | 5.31 | 4.6785 |
| 完全无表 | — | — | 5.42 | 6.2089 |

即：per-head 快 1.5%、不换页，但多吃 20.6 GiB 显存，留给 KV cache 的空间被压缩。
**本机 96 GiB 显存下，joined + on-disk 是更划算的一侧**（KV cache 更宽裕）。

## 八、排错清单

| 现象 | 原因 | 处理 |
|---|---|---|
| `tensor ... has invalid ggml type 101/104` | 用了上游二进制 | 必须用 fork `vulkan/qwen4exp-rocmfpx` 分支编出的二进制 |
| `PLE n-gram table ... is not a whole number of blocks` | 表行宽不是块大小整数倍 | 当前模型 160 % 32 = 0，不会触发 |
| `--ngram-on-disk ignored` | 文件是 per-head 布局 | 换 joined 布局文件，或用 `-mp` 指定 sidecar |
| 加载后极慢、整机卡 | 表进了 host 内存/swap | 检查 `--ngram-on-disk` 是否真的在命令行里 |
| `ErrorDeviceLost` | 显存超 GTT 104.8 GB | 降 `-c` 或降 `-np` |

## 九、验证工具

`tools/gguf_probe.py <file.gguf> [--tensors]`：零依赖解析 GGUF 头，
输出 PLE 布局判定（joined / per-head）与关键 KV，用于在新模型下载后
**先判定布局再决定参数**，避免 55 秒的无效加载。
