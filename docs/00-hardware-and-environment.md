# 硬件与环境基线

适用机器：AMD Ryzen AI MAX+ 395（Strix Halo），单台 mini 主机，集显即 GPU。

## 机器规格

- **CPU/GPU**：AMD Ryzen AI MAX+ 395，16 核 32 线程，Radeon 8060S（集显即 GPU，无独显）
- **物理统一内存** ≈ 128 GiB：host `MemTotal` ~30.5 GiB + BIOS UMA 分配给 iGPU 的 **96 GiB**
- **BIOS `UMA Frame Buffer = 96 GiB`** → Vulkan `VRAM Total` = 96.00 GiB（与 BIOS 设置一致）
- 注：早期「统一内存 107 GiB / 显存 32 GB」为过期数据

## 后端选型：Vulkan 优于 HIP

- 同模型 decode **27.5 vs 18.15 t/s**、prefill **86–117 vs 62–68 t/s**（Vulkan 快约 51%）
- 本机统一内存，Vulkan 直接吃显存；HIP 走系统 RAM，且受 `/etc/environment` 里的 `HSA_ENABLE_SDMA=0` / `ROCM_VMM_DISABLE=1` 影响
- **必须用 fork 分支 `vulkan/qwen4exp-rocmfpx` 编出的二进制**：上游 master 不识别私有量化 type 101/104（ROCmFP4_FAST），启动即报 `invalid ggml type`

## GTT 的真实大小与池路由

- **`rocm-smi --showmeminfo gtt` 的 `GTT Total` = host `MemTotal`（实测约 30.47 GiB）**，
  不等于 `ttm.pages_limit` 换算出上限。`pages_limit=25600000`（≈97.66 GiB）只是**允许上限**，
  物理后盾永远是 OS 可见 RAM。
- 判断「HIP 栈能分配多少」一律以 **`/proc/meminfo` 的 `MemAvailable`** 为准，不要看 GTT Total。
- **双池记账**：
  | 池 | 大小 | 使用者 | 吃 host RAM |
  |---|---|---|---|
  | VRAM carve-out（BIOS UMA） | 96 GiB，OS 不可见 | Vulkan：llama.cpp / sd.cpp | 否 |
  | GTT | ≤ host MemTotal ≈ 30.47 GiB | HIP / PyTorch / Strata | 是 |
- 内核补丁 `drm/amdkfd: use GTT for VRAM on APUs only if GTT is larger` 使本机 HIP 全走 GTT。
- **Vulkan 超过 carve-out 时报 `vk::Queue::submit: ErrorDeviceLost`**（不是 OOM，极易误判）→ 降 `-c` 或降 `-np`
- **BIOS 层是零和分配**：Vulkan 栈要 carve-out 尽量大，HIP 栈要 GTT 尽量大，两者不可同时优化
  （详见 `07-strata-halo-evaluation.md`）

## Vulkan ICD 坑（最高频）

- **症状**：llama.cpp 静默退化成 CPU 推理，速度掉 2 倍+，仅警告一句 `no usable GPU found`
- **根因**：`VK_ICD_FILENAMES` 指向不存在的文件（如误设 `amdvlk.json`，但本机只装了 `radeon_icd.json`）
- **排错口诀**：先 `echo $VK_ICD_FILENAMES`，确认文件真实存在；不存在就改指
  `/usr/share/vulkan/icd.d/radeon_icd.json`（注意 `/etc/environment` 是纯 `KEY=VALUE`，行内 `#` 注释会被当成值的一部分）
- 面板 / root 启动拿不到 PAM 注入的环境，启动脚本需自行 `export VK_ICD_FILENAMES=...`（见各 `start.sh`）

## GPU 频率

- `pp_dpm_sclk` auto 档只跑 ~1 GHz；启动前 `rocm-smi --setperflevel high`（→2900 MHz）decode +3~5%
- 非交互环境 rocm-smi 触发 sudo 密码提示会卡死 → 加 `< /dev/null` 让 sudo 直接失败、静默跳过

## 上下文上限

- **本 build 真实上限 = 262144**（2026-10-23 实测更正）：`llama-context.cpp` 仅 WARN 不截断，
  GGUF `qwen35moe.context_length=262144`，`-c 262144` 可正常分配（KV q8_0 约 2.66 GiB）
- 早期「被 clamp 到 131072」的记录源于当时脚本本身设了 `-c 131072`（请求 200020 > 131072），
  非 build 限制
- KV 显存吃紧时优先降 `-c` 或降 KV 量化档，而不是降 `-b`/`-ub`
