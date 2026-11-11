# 03 · 出片规格、耗时实测与优化清单

本机出一秒成片要多少分钟、参数怎么配、哪些优化真正有效。
全部数据来自 `logs/render_*.out` 真实日志与 `ffmpeg -i` 直接探测，非估算。

---

## 一、出片规格实测

| 产物 | 分辨率 | 像素格式 | 帧率 | 时长 | 编码 |
|---|---|---|---|---|---|
| 单段 `tmp/r2v_*_s0*.mp4` | **768×1344**（4:7 竖屏） | `yuvj420p`（**full range**） | 24 fps | 1.63 s（39 帧） | H.264 High 1.6–6.5 Mbps |
| 镜头 `shots/SHOT-00X/video.mp4` | 768×1344 | `yuv420p` | 24 fps | 3.00 s（72 帧 / 2 段） | H.264 High ~2.1 Mbps |
| 母版 `output/EPNNN/master.mp4` | **1080×1920**（9:16） | `yuv420p` | 24 fps | 按镜头拼接 | H.264 High ~2.5 Mbps |

音频三档统一：AAC 32 kHz stereo，单段 ~187 kb/s、镜头 ~195 kb/s、母版 ~185 kb/s。

编码参数：

```
libx264 -preset veryfast -crf 18 -pix_fmt yuv420p -movflags +faststart
音频 aac 192k
```

### 1.1 母版是上采的不是原生的

单段 768×1344 → 母版 1080×1920（`fit=cover`），**原生像素从未达到 1080p**。
这与短剧平台要求的 1080×1920 只是「容器达标」，锐度上不去。

### 1.2 ⚠ 色彩范围瑕疵

单段是 `yuvj420p`（full range 标记）。转码时若写 `scale=in_range=full:out_range=full`，
成品被打上 full-range 标记；部分播放器/平台按 limited 解释 → 发灰或对比过冲。

修法（已落地）：`out_range=tv`。

```diff
- scale=in_range=full:out_range=full
+ scale=in_range=full:out_range=tv
```

---

## 二、耗时实测：分钟 / 秒成片

### 2.1 单段（39 帧 = 1.625 s，768×1344）

| 日期 | 步数 | 耗时 | s/帧 |
|---|---|---|---|
| 10-14 | 20 | **2033 s（33m53s）** | 52.1 |
| 10-14 | 20 | **2003 s（33m23s）** | 51.4 |
| 10-20 | 12 | **1091 s（18m11s）** | 28.0 |
| 10-20 | 12 | **1259 s（20m59s）** | 32.3 |
| 10-20 | 12 | **1260 s（21m00s）** | 32.3 |
| 10-12（扫描） | 4 | 56/73/90 帧 = 478/602/764 s | ~8.5 |

### 2.2 整条镜头 / 整集

- 10-20 实测：镜头 `SHOT-001` 设定 4.88 s（117 帧）→ 超 39 帧上限 → **拆 3 段**，
  总耗时 **60.2 分钟**
- 同规格但两个 sd-cli 并存时：**73.2 分钟**（+21%）

### 2.3 换算（这是做预算用的唯一数字）

| 档位 | 分钟 / 秒成片 |
|---|---|
| 12 步 · 768×1344 | **≈ 12.3** |
| 20 步 · 768×1344 | **≈ 20.5** |
| 9 步 · 800×448（EP001 实际） | ≈ 9.5 秒/帧，9 镜共 **595.5 分钟** |
| 8 步 + turbo LoRA | 356 s / 56 帧 ≈ **2.03× 加速**（对比同分辨率无 LoRA） |

> 一集 100 秒的短剧，20 步档 = **约 34 小时**纯算力。
> 这就是为什么「段数」比「分辨率」更值得优化。

---

## 三、三角约束：画布 × 帧数 × 步数

三者不是独立可调的，被三条硬边界夹住：

| 边界 | 值 | 来源 |
|---|---|---|
| 单段像素×帧数预算 | **≈ 53.08 M**（0.59 MP × 90 帧） | 显存 + 模型训练分辨率 |
| 单段帧数在 1.03 MP 下的实测上限 | **39 帧** | 768×1344 下再高即 device lost |
| 合法帧数网格 | **5 + 17k** | H3 的时序压缩步长（17 帧 = 0.708 s） |

推论：

```
0.59 MP（576×1024）× 90 帧  = 53.08 M   ✅ 官方稳定档
1.03 MP（768×1344）× 39 帧  = 40.1 M    ✅ 实测可用（但段数多）
1.03 MP（768×1344）× 90 帧  = 92.7 M    ❌ 必崩
```

**同样 8 秒的镜头**：

| 画布 | 单段帧数 | 段数 | 固定开销（2.5 min/段） |
|---|---|---|---|
| 768×1344 | 39（1.63 s） | 5 段 | 12.5 min |
| 576×1024 | 90（3.75 s） | 3 段（按 3.75 s 取整，含 5+17k 网格对齐后 2–3 段） | 7.5 min |

**段数减少 = 少加载 40 GiB 权重的次数**，这是纯赚的。

---

## 四、A / B / C 三级优化清单

按「动系统的程度」分级。全部带备份与回滚。

### A 级：只改配置（不重建、不动系统）

| 编号 | 项 | 改法 | 预期 |
|---|---|---|---|
| A1 | **画布降到 576×1024，单段吃满 90 帧** | `render.width=576` `render.height=1024` `max_frames_area=90` `max_duration_area=3.75` | 单镜头 60.2 → 约 35 min（−42%） |
| A2 | **步数 12 → 20** | `render.steps=20` | 画质达标（<15 步有闪烁斑点/气泡），代价单段 20 → 33 min |
| A3 | 调度器 `simple` → `beta` | `render.scheduler='beta'` | R2V 场景社区反馈更优，需 A/B |
| A4 | 草稿档 | `steps=4` + `lora_scale=1.0`（挂 `h3-turbo4` 744 MB） | 仅用于构图/运镜确认，定稿切回 |
| A5 | **禁止项**：并发必须 = 1 | 不要动 `render.concurrency` | 96 GiB 池会 device lost |

一键切换脚本（`scripts/render_profile.sh`）：`draft` / `quality` / `beta` / `show` 四个子命令，
原子写 + 自动备份。

```bash
python3 - <<'PY'
import json
p='config.json'; c=json.load(open(p,encoding='utf-8'))
c['render'].update(width=576, height=1024, steps=20,
                   max_frames_area=90, max_duration_area=3.75,
                   lora_scale=0.0, concurrency=1)
json.dump(c, open(p,'w',encoding='utf-8'), ensure_ascii=False, indent=2)
print('OK', c['render']['width'], c['render']['height'], c['render']['steps'])
PY
```

回滚：`cp "$(ls -t config.json.bak.* | head -1)" config.json`

### B 级：环境清理（不改模型、不重建）

| 编号 | 项 | 结论 |
|---|---|---|
| B1 | GPU 仲裁器真正生效 | `gpu.arbiter.need_gib=64`，见 [02](02-gpu-arbiter.md) |
| B2 | GPU 频率拉满 | `sudo rocm-smi --setperflevel high`（对 sd-cli 同样有效）。注意 2900 MHz 拿不到，真因是 120W SoC 功耗墙 |
| B3 | 消除 ComfyUI 残留 | `comfyui.comfyui_url=""`，清掉每镜一次的 `/free Connection refused` |
| B4 | 日志轮转 | `gzip` 归档后 `: >` 清空 |
| B5 | Mesa 升级 | 26.1.6 → 26.2.4（他人实测，未本地复测，系统级改动先快照） |
| B6 | 降低 llama `-c` | `131072` → `65536`，缩短仲裁停/启等待 |

### C 级：需重启或重建

| 编号 | 项 | 结论 |
|---|---|---|
| C1 | 重建 sd.cpp Vulkan 版 | `build-vk2`（10-08 构建、源码无 `.git`，无法核 commit）→ `build-vk3`；冒烟通过后再切生产 |
| C2 | 色彩范围 full → tv | `sdcpp_backend.py` 里 `out_range=full` → `out_range=tv` |
| C3 | `--vae-tiling` | 降低 VAE 解码峰值显存，**代价是分块边缘可能出接缝**，须与原片对比确认 |

---

## 五、优化执行结果（2026-10-20 20:45–21:00）

| 编号 | 状态 | 结果 |
|---|---|---|
| A1 | ✅ 已生效 | 768×1344/39帧 → **576×1024/90帧（3.75s）** |
| A2 | ✅ 已生效 | `steps=20` |
| A3 | ⏸ 保留 A/B | 基线仍 `simple`，`render_profile.sh beta` 一键切换 |
| A4 | ✅ 能力就绪 | `render_profile.sh draft`（LoRA 在位） |
| A5 | ✅ 已核验 | `concurrency=1` |
| B1 | ⚠ 修正 | 发现仲裁器未真正生效，新增 `need_gib=64` |
| B2 | ⛔ 受阻 | 需 sudo |
| B3 | ✅ | `comfyui_url=""` |
| B4 | ✅ | 三个日志已 gzip 归档 |
| C1 | ✅ 构建+冒烟通过 | `build-vk3` 产出，生产 `bin` 暂未切换 |
| C2 | ✅ | `out_range=tv` |
| C3 | ✅ | `.env` 写入 `SDCPP_EXTRA_ARGS="--vae-tiling"` |

---

## 六、构建 sd.cpp 的正确姿势

两条必须记住：

1. **`ggml` 必须用 `leejet/ggml` 仓库的 `sd.cpp` 分支**。
   用 master 会报 `GGML_TYPE_F8_E4M3` / `ggml_quantize_i8_convrot` not declared。
2. **Vulkan 选项名因分支而异**：可能是 `SD_VULKAN` 也可能是 `GGML_VULKAN`，先 grep：

```bash
grep -riE "option\(.*VULKAN" CMakeLists.txt ggml/CMakeLists.txt
```

构建 + 冒烟：

```bash
cd ~/sdcpp-src
cmake -B build-vk3 -DCMAKE_BUILD_TYPE=Release -DSD_VULKAN=ON -DGGML_VULKAN=ON
cmake --build build-vk3 -j"$(nproc)"

# 冒烟：必须看到这一行才算 Vulkan 可用
./build-vk3/bin/sd-cli -M vid_gen --help 2>&1 | grep -i vulkan
# ggml_vulkan: Found 1 Vulkan devices: AMD Radeon Graphics (RADV STRIX_HALO) (radv) | uma: 1
```

---

## 七、一个反直觉的观察

**decode 之外的性能几乎全部由「每段重新加载权重」决定。**

| 观测 | 数值 |
|---|---|
| 权重加载速率（正常） | 3.6 – 4.1 GB/s |
| 40 GiB 权重加载时间 | ≈ 10–11 s（纯 IO） |
| 但冷启到首帧出图 | ≈ 2.5 min（含模型初始化、图构建、首步去噪） |
| 40 帧 / 20 步的实际去噪 | ≈ 33 min |

所以「加载慢」不是瓶颈，「初始化 + 首步」才是。这也是为什么段数翻倍代价巨大 ——
不是多读了一遍盘，而是多走了一遍完整的冷启动路径。

> ★ 排查「渲染变慢」的判据是**权重加载速率**，不是采样 s/it：
> 正常 3.6–4.1 GB/s，跌破 10 MB/s 即为内存/IO 抖动，立刻查 `free -h`，
> 别等 12h 超时。`vmstat 1 3` 的 `si`/`so` 非 0 = 正在换页。

---

**许可**：CC0-1.0，公共领域贡献，无任何限制。
