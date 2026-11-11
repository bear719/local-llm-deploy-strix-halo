# 02 · GPU 独占仲裁器：96 GiB 单池怎么记账

单机同时要养「常驻对话模型」和「按需出片」。这两件事在一张 96 GiB 的 UMA 显卡上抢同一块内存，
而 AMD 的失败方式是**整个 GPU context 被复位**，不是干净的 OOM。
本篇是把这个失败模式变成可预测账本的完整记录。

---

## 一、先算账：谁要多少

| 使用者 | 占用（GiB） | 来源 |
|---|---|---|
| 常驻 llama-server（Qwen3.6-35B-A3B，Q5_K_P + MTP，`-c 131072`） | **31.4 – 35.5** | `rocm-smi` / `amdgpu_pm_info` 实测 |
| MiniMax-H3 权重（文本编码器 17.4 + 扩散 17.9 + VAE 5.6） | **≈ 39.9** | sd-cli 启动日志 `total params memory size = 40886.55MB` |
| H3 激活缓冲 | **10.0（兜底常量）** | 更精确的按画布估算见第四节 |
| 合计 | **≈ 81 – 85** | 池 96 GiB |
| **余量** | **≈ 11 – 15** | ← 看着够，实测不够 |

关键：`auto-fit` 在 UMA 上会退化成 `RAM 0.00MB` —— **没有任何 CPU 兜底**。
显存放不下就是直接死，不会降级到内存跑。

---

## 二、★ 失败模式：不是 OOM，是 device lost

```
vk::Queue::submit: ErrorDeviceLost
radv/amdgpu: The CS has been cancelled because the context is lost.
              This context is innocent.
```

「This context is innocent」是 radv 的原话 —— 它明说**这个 context 是无辜的**，
是被同池的另一个 context 连坐打死的。

这带来三个后果：

1. **不能靠 try/except 兜底**。进程收到的是 GPU 层面的复位，两个进程一起死。
2. **日志里没有 OOM 字样**，极易误判成「分辨率太高」进而降画质，方向全错。
3. **radv 在 UMA 上虚报可用显存**。日志里报过 `free 145964 MB`（远超 96 GiB 物理池），
   照这个数判断「够用」必然踩坑。

### 实测崩溃边界（最关键的一张表）

条件：llama 常驻基线 35.5 GiB，H3 并跑，`logs/gtt_*.log`：

| 画布 × 帧数 | 合计占用 | 结果 |
|---|---|---|
| 576×1024×90 | **81.09 GiB** | ✅ OK（5.5 min 跑完） |
| 576×1024×107 | **82.06 GiB** | ❌ `ErrorDeviceLost`（8 个不同 tag 复现，均在 ~28s 首步崩） |

**差 1 GiB 就是全过 / 全崩的阶跃。**
「留一点余量再上」这种渐进调参在这里不成立 —— 没有中间档，只有过和不过。

> 由此定策：**视频渲染前无条件让出**，不等显存逼近上限。

---

## 三、仲裁器策略（五条）

### 1. 视频渲染无条件暂停

`force_pause=True`。H3 一开跑就把匹配的 llama 实例停掉。
出图（Flux / Qwen 扩散，12–17 GiB）才按需判断：够就不动 llama，不够才停（`force_pause=False`）。

### 2. 粘滞窗口（`resume_linger_sec`）

租约是**按镜头**逐个 acquire/release 的。一集几十个镜头若每个都停/启一次 llama，
光冷启就白花十几分钟。所以 release 不立刻恢复，而是起一个粘滞窗口；
窗口内来了新镜头就继续持有。

```
镜头 1: acquire ──┐
镜头 2: acquire ──┤ 持有中，llama 保持停止
镜头 3: acquire ──┘
        release ──▶ [linger 窗口] ──▶ 真闲下来了才 resume
```

### 3. 只恢复「本模块暂停的、且暂停前确实在运行」的实例

绝不误启其它档位。本机 35B-A3B 与 27B-dense 两档显存互斥，误启会互相挤爆。

### 4. 崩溃兜底恢复

进程被 `kill -9` 时内存里的租约状态就丢了。所以暂停状态落盘到 `.gpu_pause_state.json`，
下次任意调用或后端启动时按 `stale_pause_sec` 判断「这状态已经过期」并自动补偿恢复。

### 5. 走面板 API，不直接 kill

实例配了 `eventTask.autoRestart=true, autoRestartMaxTimes=-1`。
外部 `kill` 会被面板立刻拉起（文案 `Unexpected instance stop detected.`）。

而**面板主动 stop 不触发 autoRestart** —— 实测停 5 分钟以上未拉起，
显存从 41.7 GB 掉到 1.3 GB 并保持。

所以要调 `POST /api/protected_instance/stop`，用面板 apiKey 免密通道。

---

## 四、需求估算模型

静态常量 `need_gib = 49.9`（权重 + 激活）太粗 —— 它让「小档」也被判「必须停 llama」，
或者让「大档」判成「不用停」。改成按画布与帧数估算：

```python
H3_WEIGHTS_FIXED_GIB = 42.8      # 与帧数无关的常驻部分
H3_ACTIVATION_SLOPE  = 0.08      # GiB / 百万像素帧
H3_PIXFRAMES_BASE_M  = 10.0      # 低于此值激活增量按 0 计

def estimate_peak_gib(w, h, frames):
    mpf = w * h * frames / 1e6
    return 42.8 + 0.08 * max(0.0, mpf - 10.0)
```

### 标定点（`logs/gtt_sweep*.log` 反解）

| 画布 × 帧数 | 实测峰值 | 估算 | 偏差 |
|---|---|---|---|
| 576×1024×22 | 43.15 | 43.04 | −0.11 |
| 576×1024×56 | 45.79 | 45.33 | −0.46 |
| 576×1024×107 | 47.38 | 47.38 | 0.00 |
| 576×1024×226 | 52.65 | 53.01 | +0.36 |
| 800×448×216 | 50.90 | 48.99 | −1.91 ⚠ |

斜率在 `0.073 ~ 0.105` 之间浮动，取 0.08 偏上界。
唯一下偏的 800×448×216 是短宽画布，但该档一律判「停 llama」，
停完空闲 94 GiB，**精度不影响安全**。

> 教训：估算精度只需要在「可能放行的小档」区间内可靠。
> 大档估算偏高无害 —— 反正一律停。

---

## 五、判定逻辑（易错点：判「加载后总量」而不是「当前空闲」）

```python
# ❌ 错的判据
if free_gib >= need_gib:  pass

# ✅ 对的判据
allow_used = limit_gib - need_gib
if used_gib <= allow_used:  pass
```

为什么必须换成后者：`free` 在 radv 上会虚报（145964 MB），
一旦信 `free` 就会在真该停的时候放行。

而且 `force_pause=True` 时**完全不走这个捷径**，直接停 —— 因为第二节的实测已经证明
「差 1 GiB 就阶跃崩」，任何「看起来够」的判断都不可信。

---

## 六、事故：仲裁器代码在，但没生效（2026-10-20）

现象：

- 渲染 `SHOT-001` 期间 `llama-server` 仍在运行，显存 **90.3 / 96 GiB**
- 没有 `.gpu_pause_state.json`，日志里既无「暂停」也无「恢复」

根因：`need_gib` 默认 49.9 GiB，`acquire` 时判 `free >= need` 就放行；
而 radv 对可用显存的估计偏乐观 → 直接判「够」，压根没走暂停分支。

修正：`gpu.arbiter.need_gib = 64`，强制在 llama 占位时先停实例再渲染。

> ★ 通用教训：**显存仲裁器的判据不能基于「当前空闲量」**。
> 要么用「加载后总量 ≤ 池上限」，要么干脆按任务类型硬性停。
> 「看着够」在本机等于「必崩」。

下一次渲染的验证口径：日志里必须出现「自动暂停推理服务」字样 + 生成 `.gpu_pause_state.json`。

---

## 七、跨进程互斥的另一半：flock

仲裁器管的是「渲染 vs llama」，**管不了「渲染 vs 渲染」**。
所以还有一个文件锁层（见 [04-incidents-and-pitfalls.md](04-incidents-and-pitfalls.md) 第 1 节）。
两者职责不同，缺一不可：

| 机制 | 管什么 | 失效表现 |
|---|---|---|
| GPU 仲裁器 | 渲染 vs 常驻推理 | 两个进程一起 device lost |
| `flock` | 渲染 vs 渲染（视频段 / 关键帧） | 都能跑，但慢 21%，偶发 device lost |

---

## 八、可直接抄的检查命令

```bash
# 显存实况（非交互环境必须 < /dev/null，否则可能卡死）
rocm-smi --showmeminfo vram < /dev/null

# 判断是否走 UMA carve-out（Vulkan）还是 GTT（HIP）
ls -l /sys/class/drm/card*/device/mem_info_vram_total

# 仲裁器是否真的停过 llama
cat .gpu_pause_state.json 2>/dev/null
grep -E "仲裁|暂停|恢复|pause|resume" logs/render.service.out | tail

# 面板里哪些实例在跑（无需 sudo，配置与日志都是 644）
ls /opt/mcsmanager/daemon/data/InstanceConfig/
```

---

**许可**：CC0-1.0，公共领域贡献，无任何限制。
