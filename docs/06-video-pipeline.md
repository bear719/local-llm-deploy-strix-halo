# 视频模型本地部署方案 —— 不影响现有 llama.cpp

生成时间：2026-10-08
主机：AMD Ryzen AI MAX+ 395（Strix Halo / gfx1151 / Radeon 8060S）
内核：7.0.0-34-generic
现有服务：llama-server（build-vk4，Vulkan 后端）`0.0.0.0:8080`，Qwen3.6-35B-A3B-Q5_K_P + MTP + mmproj

---

## 一、结论摘要

| 方案 | 是否重启 | 与 llama.cpp 冲突 | 可用内存 | 功能完整度 | 推荐度 |
|---|---|---|---|---|---|
| **① sd.cpp + Vulkan**（纯 C/C++，与 llama.cpp 同架构） | **否** | **零冲突**（同后端、同 carve-out 池、独立进程） | carve-out 剩余 **≈64 GiB** | Wan2.2 / LTX-2.x / HunyuanVideo 1.5 / MiniMax-H3 | **★ 首选** |
| ② 修正 TTM 参数 → HIP 改走 carve-out | 是（1 次） | 低（Vulkan 分配不受 TTM 影响，需重启验证） | 同上 | ComfyUI 全生态 + Wav2Lip | 需 ComfyUI 时选 |
| ③ 限流 ComfyUI/HIP ≤12 GiB | 否 | 中（争 host RAM，余量薄） | **≈12 GiB** | 仅小模型 + CPU offload | 应急 |

**首选路线 ① 的理由**：本机 llama.cpp 本身就是 Vulkan 后端，实测其显存分配落在 **VRAM carve-out（96 GiB）** 而非 GTT，占用 31.4→33.4 GiB 全程稳定。sd.cpp 使用**同一套 ggml Vulkan 后端**，实测其权重与计算缓冲落在**同一个 carve-out 池**（日志 `... VRAM) on Vulkan0`），HIP 那条「GTT 撑爆 host RAM」的路径完全不经过。

**⚠️ 一处必须修正的措辞**：最初判断 sd.cpp「完全不触碰 host RAM」**不准确**。实测它仍有宿主占用，只是随负载变化：480×832 档 **0.6 GB**（可忽略）、704×1280 档 **6.5 GB**（不可忽略）。因此正确的表述是：
> **显存记账与 llama.cpp 完全独立（不再有 GTT 那条坑）；host RAM 仍是共享资源，用小分辨率档时余量充足，不要用大分辨率档把 host 压满。**

机制上已经跑通并出片，见 4.5。

---

## 二、一手实测数据（本机，2026-10-08）

### 2.1 内存池隔离实测

用 `wan2.2-venv`（torch 2.12.0+rocm7.14.0a20260606）做显存分配阶梯测试：

| HIP 累计分配 | llama.cpp VRAM_used | GTT_used | host avail | hip_free |
|---|---|---|---|---|
| 0（基线） | **31.39 G** | 1.78 G | 16487 M | 28.49 G |
| 4 G | **31.40 G** | 5.92 G | 12452 M | 24.30 G |
| 8 G | **31.40 G** | 9.92 G | 8066 M | 20.30 G |
| 12 G | **31.41 G** | 13.92 G | 4183 M | 16.30 G |
| 16 G | **31.42 G** | 17.92 G | 1737 M | 12.30 G |
| 20 G | **31.22 G** | 21.82 G | **494 M** | 8.30 G |

**关键结论**：
1. HIP 分配 → 全部计入 **GTT 池**，且**逐字节消耗 host 可用内存**（16 G → 0.5 G）。
2. 同期 llama.cpp 的 **VRAM_used 纹丝不动**（31.39→31.42 G），证明 **VRAM carve-out 池与 GTT 池在记账上相互独立**。
3. 验证期间对 8080 发真实请求，正常返回（25.3 t/s）。

### 2.2 OOM 事故取证

```
10月 08 20:49:23 ubuntu kernel: wpsoffice invoked oom-killer: ...
10月 08 20:49:25 ubuntu kernel: oom-kill:constraint=CONSTRAINT_NONE,...,global_oom,...
10月 08 20:49:25 ubuntu kernel: Out of memory: Killed process 3225371 (workbuddy) ...
```

- 性质：**全局 OOM**（`global_oom`），非 cgroup 限制
- 被杀：clawpanel.service 多个 MainThread、workbuddy 等
- 触发者：上述 20 GiB 分配测试把 host 可用内存压到 494 MB
- 教训：**HIP/GTT 分配的调节阀不是 rocm-smi 显示的池大小，而是 host 空闲内存**

### 2.3 内存池现状（记忆点）

| 项 | 值 | 来源 |
|---|---|---|
| BIOS UMA carve-out（VRAM） | 98304 M = 96.00 GiB | `dmesg` 启动日志 |
| GTT 实际大小 | 100000 M = 97.66 GiB | 同上 |
| TTM 上限（人为扩大） | `pages_limit=25600000` = 104.86 GB | `/etc/modprobe.d/amd_ttm.conf` |
| host MemTotal | 31.2 GiB | `free` |
| HIP 可见池 Pool 1 | 102400000 KB = 97.66 GiB（**GTT 池**） | `rocminfo` |
| ROCm 版本 | torch 2.12+rocm7.14.0a | — |

---

## 三、根因分析：为什么 HIP 会去吃 host 内存

### 3.1 机制

Strix Halo 没有独立显存，内存通过 **GPUVM 映射**，分为两个记账池：

- **VRAM / carve-out**：BIOS 独占预留（96 GiB），OS 不可见，GPU 直接可用
- **GTT**：GPU 可映射的系统内存，**消耗 OS 可见内存**

**AMD 官方文档（ROCm 7.2.0 Strix Halo system optimization）**：
> GTT defines the amount of system RAM that can be mapped into GPU virtual address spaces for user processes. **This is the memory pool used by applications such as PyTorch**.
> If the GTT size is bigger than VRAM at that case the amdgpu driver for VRAM allocation using GTT (GTT-backed allocations).
> [来源: https://rocm.docs.amd.com/en/docs-7.2.0/how-to/system-optimization/strixhalo.html]

**内核补丁（Alex Deucher）**：
> `drm/amdkfd: use GTT for VRAM on APUs only if GTT is larger`
> [来源: https://lists.ubuntu.com/archives/kernel-team/2025-August/162311.html]

### 3.2 本机触发条件

```
GTT (100000 M) > VRAM (98304 M)   ← 成立
  ⇒ 内核判定 "GTT is larger" ⇒ VRAM 分配路由到 GTT
  ⇒ PyTorch/HIP 全部分配吃掉 host RAM（仅 31.2 GiB）
  ⇒ 分配 ~20 GiB 即全局 OOM
```

**根因定位**：`/etc/modprobe.d/amd_ttm.conf`（创建于 2026-08-07）把 TTM 上限抬到 104.86 GB，使 GTT 被撑到 100000 M，刚好**越过了 VRAM 的 98304 M**。若不调该参数，内核会走另一分支，PyTorch 直接用 96 GiB carve-out。

### 3.3 对照组证据

社区实测（HP ZBook Ultra G1a，96 GB carve-out）：
- 内核 6.12：`rocminfo` Pool 1 = 32646368 KB（31 GiB，GTT）→ PyTorch 只认 15.5 GB
- 内核 6.16.3+：`rocminfo` Pool 1 = **100663296 KB（96 GB，VRAM）** → 问题消失
[来源: https://github.com/ROCm/legacy-rocm-build/issues/5444]

本机内核 7.0.0-34 远新于 6.16，**补丁已在**，仅因 TTM 参数被人为撑大而回落到 GTT 分支。

---

## 四、首选方案：sd.cpp + Vulkan（零重启、零冲突）

### 4.1 为什么它能"走 VRAM 池"

`stable-diffusion.cpp`（leejet/stable-diffusion.cpp）：

- 纯 C/C++ 基于 **ggml**，"working in the same way as llama.cpp"
- 后端列表：**CPU / CUDA / Vulkan / Metal / OpenCL / SYCL**（**无 HIP/ROCm**）
- 视频模型：**Wan2.1 / Wan2.2、LTX-2.3/2.5、HunyuanVideo 1.5、MiniMax-H3、LingBot-Video**
- 权重格式：GGUF / safetensors / ckpt
- [来源: https://github.com/leejet/stable-diffusion.cpp]

**内存池推论**：本机 llama.cpp（同 ggml Vulkan 后端）实测占了 31.42 GiB 的 **carve-out**（见 2.1）。sd.cpp 走同一后端与同一 Vulkan DEVICE_LOCAL 堆，因此**同样落 carve-out**，不占 host RAM。

### 4.2 本机现状与依赖（实测状态）

| 项 | 状态 |
|---|---|
| 源码 | `$HOME/sdcpp-src`（master） |
| **ggml** | `$HOME/sdcpp-src/ggml`，**必须用 commit `89c4413f5da6fb20cc796f16033d37f129be81fd`**（= `leejet/ggml` 的 `sd.cpp` 分支 HEAD） |
| 构建目录 | `$HOME/sdcpp-src/build-vk2`（`-DSD_VULKAN=ON`） |
| 产物 | `build-vk2/bin/sd-cli`（82 MB）、`build-vk2/bin/sd-server`（82 MB）✅ **编译成功，1m59s** |
| 链接 | `libvulkan.so.1`（已验证 `ldd`） |
| 工具链 | cmake 4.2.3 / gcc 15.2.0 / glslc / glslangValidator / Vulkan headers ✅ |
| Vulkan ICD | `radeon_icd.json`（RADV STRIX_HALO）✅ |
| 网络 | GitHub 直连不通；`gh-proxy.com` 可下源码；模型走 `hf-mirror.com`（实测 3.55 MB/s） |
| hf CLI | **未安装**，改用 curl |

**★ 关键踩坑（已解决）**：`sd.cpp` 的 `ggml` 是 submodule，指向 `leejet/ggml` 的 **`sd.cpp` 分支 commit `89c4413f`**，而非 master 分支。若误用 master（`353b63b4`）会编译失败：
```
error: 'GGML_TYPE_F8_E4M3' was not declared; did you mean 'SD_TYPE_F8_E4M3'?
error: 'ggml_quantize_i8_convrot' was not declared
```
查准 submodule commit 的方法（GitHub API）：
```bash
gh api repos/leejet/stable-diffusion.cpp/contents/ggml   # 返回 sha = 89c4413f...
```
再按 sha 取 tarball：
```bash
curl -sL -o ggml.tar.gz \
  "https://gh-proxy.com/https://github.com/leejet/ggml/archive/89c4413f5da6fb20cc796f16033d37f129be81fd.tar.gz"
```

### 4.3 部署步骤（已执行到编译完成）

**Step 1 — 源码与编译**
```bash
# 网络：GitHub 直连不通，走 gh-proxy
cd /tmp && curl -L -o sd.tar.gz \
  "https://gh-proxy.com/https://github.com/leejet/stable-diffusion.cpp/archive/refs/heads/master.tar.gz"
mkdir -p $HOME/sdcpp-src && tar xzf sd.tar.gz -C $HOME/sdcpp-src --strip-components=1

# ggml 子模块（必须是指定 commit）
cd $HOME/sdcpp-src && mkdir -p ggml && curl -sL -o /tmp/ggml.tar.gz \
  "https://gh-proxy.com/https://github.com/leejet/ggml/archive/89c4413f5da6fb20cc796f16033d37f129be81fd.tar.gz" \
  && tar xzf /tmp/ggml.tar.gz -C ggml --strip-components=1

# 编译 Vulkan 版
cmake -B build-vk2 -DSD_VULKAN=ON -DCMAKE_BUILD_TYPE=Release
cmake --build build-vk2 -j16        # → build-vk2/bin/sd-cli
```

**Step 2 — 下载权重（统一放 `$HOME/models/wan`）**

最小可用组合（约 8 GB）：
```bash
mkdir -p $HOME/models/wan && cd $HOME/models/wan
B=https://hf-mirror.com
curl -L -C - -o Wan2.2-TI2V-5B-Q4_K_M.gguf   "$B/QuantStack/Wan2.2-TI2V-5B-GGUF/resolve/main/Wan2.2-TI2V-5B-Q4_K_M.gguf"
curl -L -C - -o Wan2.2_VAE.safetensors       "$B/QuantStack/Wan2.2-TI2V-5B-GGUF/resolve/main/VAE/Wan2.2_VAE.safetensors"
curl -L -C - -o umt5-xxl-encoder-Q4_K_M.gguf "$B/city96/umt5-xxl-encoder-gguf/resolve/main/umt5-xxl-encoder-Q4_K_M.gguf"
```

**Step 3 — 生成**（参数已按 4.5 实测修正，勿删 `--tensor-type-rules`）

一键脚本：`$HOME/WorkBuddy/调试本地模型/start-sdcpp-video.sh "提示词" 832 480 33 20`
```bash
cd $HOME/sdcpp-src
./build-vk2/bin/sd-cli -M vid_gen \
  --diffusion-model $HOME/models/wan/Wan2.2-TI2V-5B-Q4_K_M.gguf \
  --vae             $HOME/models/wan/Wan2.2_VAE.safetensors \
  --t5xxl           $HOME/models/wan/umt5-xxl-encoder-Q4_K_M.gguf \
  --vae-format wan --tensor-type-rules "^vae\.=f32" --vae-tiling \
  -p "a ginger cat walking on grass, cinematic lighting" \
  -W 832 -H 480 --video-frames 33 --steps 20 --cfg-scale 5.0 \
  --output $HOME/WorkBuddy/调试本地模型/out/test.mp4
```
| 参数 | 值 | 为什么 |
|---|---|---|
| `--tensor-type-rules "^vae\.=f32"` | 必加 | 防 FP16 VAE 解码偏绿（见 4.5） |
| `--cfg-scale` | 5.0 | Wan 官方推荐；默认 7.0 过饱和 |
| `--steps` | 20 | 默认值；<10 步流匹配不收敛 |
| `--video-frames` | 4k+1（33/49/81） | VAE 时间压缩 4× 的硬约束 |
| `-W/-H` | 16 的倍数 | 480×832 / 832×480 已验证 |

输出说明：sd.cpp 实际写 **AVI/MJPEG 容器**（后缀会被追加 `.avi`），需转码，见 4.5 末尾。

**Step 4 — 共存验证（关键）**
```bash
# 生成期间另开终端
watch -n2 'rocm-smi --showmeminfo vram | grep Used; free -m | head -2'
```
预期：VRAM_used 从 31.4 G 上涨（sd.cpp 占用），**host used 不显著上涨**。

### 4.4 显存预算

| 模型 | 量化 | 文件体积 | 合计（含 T5+VAE） | 96 GiB carve-out 余量（llama.cpp 已占 31.4） |
|---|---|---|---|---|
| Wan2.2 TI2V-5B | Q8_0 | ≈5.4 GB | ≈12 GB | 充裕 |
| Wan2.1 T2V-1.3B | Q8_0 | ≈1.6 GB | ≈8 GB | 充裕 |
| Wan2.1/2.2 T2V-14B | Q4_K_M | ≈9.7 GB | ≈17 GB | 充裕 |
| Wan2.1/2.2 T2V-14B | Q8_0 | ≈15.4 GB | ≈23 GB | 够 |
| HunyuanVideo 1.5 | GGUF Q4 | ≈8-11 GB | ≈16 GB | 够 |
| LTX-Video 13B | FP8 | ≈13-15.7 GB | ≈20 GB | 够 |

注：Wan2.2 A14B 为双模型（HighNoise + LowNoise），显存需求约翻倍。

### 4.5 端到端实测（2026-10-08 21:14–21:30，已完成）

**全流程跑通**，llama.cpp 全程可用。

| 轮次 | 分辨率 | 帧数 | 步数 | CFG | VAE | 采样耗时 | VAE 解码 | 总计 | 结果 |
|---|---|---|---|---|---|---|---|---|---|
| A | 480×832 | 33 | 8 | 7.0 | f16 | 70.6 s | 92.6 s | **165 s** | ❌ 严重偏绿 |
| B | 480×832 | 33 | 20 | 5.0 | f16 | 248.3 s | 115.9 s | **368 s** | ⚠️ 猫色正确，草地仍过饱和 |
| C | 480×832 | **5** | 20 | 5.0 | **f32** | 35.8 s | 10.9 s | **48.7 s** | ✅ **完全正常** |
| D | 704×1280 | 33 | 20 | 5.0 | f16 | 176.7 s/it → 中止 | — | — | ⛔ 过重，已中止 |

**★ 核心结论：偏色根因 = Wan2.2 VAE 的 FP16 解码溢出**

抽帧 RGB 通道均值（`PIL` 直读，非肉眼判断）：

| 轮次 | R | G | B | 判定 |
|---|---|---|---|---|
| A（8步/cfg7/f16） | 142.0 | 207.9 | **9.1** | 蓝通道被压死 → 整体偏绿 |
| B（20步/cfg5/f16） | 148.2 | 184.6 | 21.8 | 好转，草地仍荧光绿 |
| C（**VAE f32**） | 105.3 | 102.4 | **51.4** | **三通道平衡 ✅** |

→ 修复参数：**`--tensor-type-rules "^vae\.=f32"`**。Wan2.2 的 VAE 压缩比高（16× 空间 / 4× 时间、48 通道潜变量），FP16 累积溢出导致解码色彩失真。

**★ 第二个坑：分辨率与序列长度不是线性关系**

704×1280 像素仅比 480×832 多 2.26 倍，但步时从 8.7 s/it 暴增到 **176.7 s/it（=20 倍）**，且 host `available` 从 12.5 GB 掉到 5.2 GB、sd-cli 宿主 RSS 从 0.6 GB 涨到 6.5 GB。判定为注意力 O(n²) + 统一内存压力叠加。
**工程结论：先锁 480×832 / 832×480（≈40 万像素），别一上来跑 704×1280。**

**内存观测（全程）**

| 采样点 | VRAM_used | GTT_used | host available | sd-cli 宿主 RSS |
|---|---|---|---|---|
| 基线（仅 llama.cpp） | 33.37 GB | 1.79 GB | 12.5 GB | — |
| 生成中（480×832） | **41.99 GB** | **1.81 GB（未动）** | 12.0 GB | **0.58 GB** |
| 生成后 | 33.32 GB | 1.79 GB | 11.3 GB | 退出 |

- 日志原话：`model manager prepared params backend buffers (... MB, ... tensors, ... blocks, VRAM) on Vulkan0` —— **明确落在 VRAM**。
- 显存**精确回收**（33.37 → 33.32 GB），无泄漏。
- **修正此前推断**：sd.cpp 并非「零 host RAM」。480×832 档宿主占用仅 0.6 GB（可忽略），但 704×1280 档涨到 6.5 GB（不可忽略）。**host RAM 是共享资源，这才是必须留意的约束。**

**速度基线（480×832×33帧，20步，80.6 s 纯推理）**

| 场景 | 采样 | VAE 解码 | 总耗时 |
|---|---|---|---|
| 33 帧 / 20 步 | 248 s（12.4 s/it） | 116 s | **368 s** |
| 5 帧 / 20 步 | 36 s（1.74 s/it） | 11 s | **49 s** |

→ 实用档：**832×480 / 33 帧 / 20 步 ≈ 6 分钟一条 2 秒短片**（16 fps）。

**输出容器坑**：`--output xxx.mp4` 实际写出的是 **AVI/MJPEG 容器**（文件会变成 `xxx.mp4.avi`）。系统未装 ffmpeg，本机可用 `imageio_ffmpeg` 自带的静态二进制：
```bash
FF=$HOME/.workbuddy/binaries/python/envs/default/lib/python3*/site-packages/imageio_ffmpeg/binaries/ffmpeg-linux-*
# 显式按全范围解释，否则会二次偏色
$FF -y -i in.avi -vf "scale=in_range=full:out_range=full" \
    -c:v libx264 -pix_fmt yuv420p -crf 18 -movflags +faststart out.mp4
```

---

## 五、备选方案 ②：修正 TTM 参数（要 ComfyUI 时）

目的：把 PyTorch/HIP 从 GTT 池改回 carve-out 池。

**操作（需重启，执行前请确认）**
```bash
# 备份
sudo cp /etc/modprobe.d/amd_ttm.conf /etc/modprobe.d/amd_ttm.conf.bak.20261008
# 把 TTM 上限从 104.86 GB 降到 80 GiB（< VRAM 96 GiB）
sudo sed -i 's/pages_limit=25600000/pages_limit=20971520/'   /etc/modprobe.d/amd_ttm.conf
sudo sed -i 's/page_pool_size=25600000/page_pool_size=20971520/' /etc/modprobe.d/amd_ttm.conf
sudo reboot
```

**重启后验证（必须全绿）**
```bash
dmesg | grep -E "of VRAM memory ready|of GTT memory ready"   # 期望 GTT < VRAM
rocminfo | grep -A3 "Pool Info" | grep Size                  # 期望 gfx1151 Pool1 ≈ 96 GiB
curl -s http://127.0.0.1:8080/health                          # llama.cpp 正常
```

**回滚**
```bash
sudo cp /etc/modprobe.d/amd_ttm.conf.bak.20261008 /etc/modprobe.d/amd_ttm.conf && sudo reboot
```

**风险**
- TTM 是 amdgpu 全局参数。llama.cpp 走 Vulkan DEVICE_LOCAL（carve-out），理论上不受影响，但**属未经本机验证的假设**，必须先确认 8080 服务正常。
- 若本机内核不含 `use GTT for VRAM only if GTT is larger` 补丁，降 GTT 后 HIP 会**直接 OOM**（而非回退），比现状更糟。内核 7.0.0-34 几乎必然包含，但需实测确认。

---

## 六、应急方案 ③：限流 ComfyUI

不改任何系统配置，把 HIP 占用压在安全线内：

```bash
export PYTORCH_HIP_ALLOC_CONF=expandable_segments:True,garbage_collection_threshold:0.8,max_split_size_mb:512
```
补充手段：
- ComfyUI `--lowvram` / 逐块加载，T5 与 VAE 置于 CPU
- 单次只驻留一个模型，生成完即 `torch.cuda.empty_cache()`
- 硬上限建议 **≤12 GiB**（基线 host avail 16 GiB，留 4 GiB 安全垫）

实测副作用：分配 20 GiB 后释放，`hip_free` 仅从 8.3 G 回到 20.2 G（**未完全归还**），长时间运行需警惕碎片累积。

---

## 七、变更留痕

| 时间 | 操作 | 影响 |
|---|---|---|
| 2026-10-08 20:5x | 新建 `$HOME/sdcpp-src`（sd.cpp 源码 + ggml `89c4413f`） | 新增目录，未改动既有服务 |
| 2026-10-08 20:5x | 20 GiB 显存压力测试 | **引发全局 OOM，杀掉 clawpanel/workbuddy 若干进程**（已取证，见 2.2） |
| 2026-10-08 21:03 | 编译 sd.cpp Vulkan 版 → `build-vk2/bin/sd-cli`（耗时 1m59s） | 仅新增构建产物 |
| 2026-10-08 21:11 | 下载 Wan2.2 TI2V-5B 权重至 `$HOME/models/wan` | +8.1 GB 磁盘（磁盘余 80 GB） |
| 2026-10-08 21:14 | 轮次 A 生成 480×832×33（8步，f16 VAE） | 出片，偏绿；VRAM 33.37→33.52 GB，服务正常 |
| 2026-10-08 21:19 | 轮次 D 生成 704×1280×33 | **已中止**（176.7 s/it 过重，host available 压到 5.2 GB） |
| 2026-10-08 21:27 | 轮次 B 生成 480×832×33（20步，cfg5.0） | 368 s，猫色正常，草地过饱和 |
| 2026-10-08 21:29 | 轮次 C 生成 480×832×5（**VAE f32**） | **48.7 s，色彩完全正常 → 根因确认** |
| 2026-10-08 21:3x | 新建 `start-sdcpp-video.sh`（含修正参数与自动转码） | 仅新增脚本 |

**未改动**：`/etc/modprobe.d/amd_ttm.conf`、`/etc/environment`、内核 cmdline、grub、llama.cpp 任何配置。全程只新增目录与文件。

**尚未执行、需授权**：
- 修改 `/etc/modprobe.d/amd_ttm.conf` + 重启（方案 ②）
- 清理 swap（当前 9.9 GB 占用系 20:49 OOM 残留，`sudo swapoff -a && sudo swapon -a` 可回收）

---

## 八、磁盘与网络约束

- `/` 可用 **89 GB**（已用 83%），`$HOME/models` 已占 152 GB
- 单个视频模型 + 编码器约 8-25 GB，下载前需评估余量
- GitHub 直连不通，源码走 `gh-proxy.com`；模型走 `hf-mirror.com`（实测 3.55 MB/s）
- 本机可用仓库速查（已验证存在）：
  | 用途 | 仓库 | 关键文件 |
  |---|---|---|
  | 扩散模型 | `QuantStack/Wan2.2-TI2V-5B-GGUF` | `Wan2.2-TI2V-5B-{Q3_K_S,Q4_K_M,Q8_0}.gguf` |
  | VAE | 同上（同仓库） | `VAE/Wan2.2_VAE.safetensors` |
  | 文本编码器 | `city96/umt5-xxl-encoder-gguf` | `umt5-xxl-encoder-{Q3_K_M..Q8_0}.gguf` |
  | 14B 扩散模型 | `city96/Wan2.1-T2V-14B-gguf` | `wan2.1-t2v-14b-Q4_K_M.gguf` |
  | safetensors 全集 | `Comfy-Org/Wan_2.1_ComfyUI_repackaged`、`Wan_2.2_ComfyUI_Repackaged` | `split_files/diffusion_models/...`、`split_files/vae/wan_2.1_vae.safetensors` |
