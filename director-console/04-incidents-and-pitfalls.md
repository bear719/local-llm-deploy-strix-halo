# 04 · 事故复盘与踩坑清单

六起真实事故。每起都有「现象 / 根因 / 修法 / 下次怎么发现」四段。
这些坑的共同特征是：**系统不报错，或者报的是错的那件事**。

---

## 1. 跨进程 GPU 互斥缺失 → 慢 21%

### 现象

渲染 `SHOT-001`（22 帧 / 12 步，768×1344）耗时 **73.2 分钟**，
而历史同规格基线是 **60.2 分钟**。同时段显存 90.3 / 96 GiB，但没崩。

### 根因

- `render_shots.py`（视频段）**没有 flock**
- `gen_keyframes.py`（关键帧）用的是 `run/gen_keyframes.lock` —— **不同的锁**
- 两把锁互不相认 → 同一时刻有两个 `sd-cli` 并存（`-M vid_gen` + `-M img_gen`）

GPU 仲裁器只负责「渲染 vs llama」，管不了「渲染 vs 渲染」。

### 修法

两者共用同一把锁：

```python
import fcntl, pathlib

LOCK = pathlib.Path("run/gpu_render.lock")

@contextmanager
def gpu_lock(timeout=86400):
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    fh = open(LOCK, "w")
    end = time.time() + timeout
    while True:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except BlockingIOError:
            if time.time() > end:
                raise TimeoutError(f"等 GPU 锁超时: {LOCK}")
            time.sleep(5)
    try:
        yield
    finally:
        fcntl.flock(fh, fcntl.LOCK_UN)
        fh.close()
```

### 下次怎么发现

`nvidia-smi` 的 AMD 等价物：`pgrep -af sd-cli | wc -l`，**必须 = 1**。

```bash
watch -n 5 'echo "sd-cli 实例数: $(pgrep -c -f sd-cli)"; rocm-smi --showmeminfo vram < /dev/null'
```

---

## 2. 裸调脚本绕过 GPU 仲裁 → 第 2 镜必崩

### 现象

EP002 渲染跑到第 2 镜必然 `ErrorDeviceLost`；第 1 镜正常。

### 根因（三个叠加，缺一即复发）

1. 手工执行 `render_shots.py` 时**没走 wrapper**，于是漏了：
   - `DRAMA_H3_FORCE_ROUTE=ref`（路线选择）
   - `env -u CODEBUDDY_TOOL_CALL_ID ...`（清理继承的删除计数变量）
   - 常驻实例的重启脚本
2. 渲染 11:57 开跑，而 **MCSManager 面板 13:26 才启动** →
   仲裁器的 `_pick_victims()` 枚举不到实例 → 判定「没有需要暂停的」→ 直接放行
3. radv 又虚报了可用显存 → 不再有任何拦截

### 修法

固定为一条 wrapper：**任何渲染都必须经它启动**，它负责
设环境变量、检查面板可达、检查 llama 实例存在、再 exec 真脚本。

```bash
#!/usr/bin/env bash
# render-guard.sh —— 唯一的渲染入口
set -euo pipefail
unset CODEBUDDY_TOOL_CALL_ID CODEBUDDY_SAFE_DELETE_BULK_STATE_DIR
export DRAMA_H3_FORCE_ROUTE=ref

# 面板必须可达，否则仲裁器形同虚设
curl -fsS --max-time 3 http://127.0.0.1:23333/api/instance/list >/dev/null \
  || { echo "[ERROR] MCSManager 面板不可达，仲裁器失效，拒绝渲染"; exit 3; }

exec "$@"
```

### 下次怎么发现

渲染日志里**没有**「自动暂停推理服务」这句，就说明仲裁器没跑过。
把这条当成硬性验收项。

---

## 3. 改了代码，但后台任务跑的是旧代码

### 现象

11:13 启动关键帧任务，11:23 修好 `build_worker.py` 的提示词注入逻辑。
重新看结果 —— 修复完全没生效。

### 根因

Python 进程启动时已把模块加载进内存。11:13 的进程用的是 11:13 那一刻的代码。
改文件对已在跑的进程零影响。

### 修法（纪律，不是代码）

**改了代码 → 必须重跑「清单生成 + 关键帧生成」全部前置步骤，再渲染。**
中间产物是按旧提示词生成的，只重跑最后一步等于白改。

```bash
# 标准重跑顺序，缺一步就白做
scripts/gen_ep002_shot_table.py      # 1. 从真源重建分镜表
scripts/inject_cast_looks.py --restyle  # 2. 重注入角色外观
scripts/gen_keyframes.py             # 3. 重生成关键帧
# 4. 逐张目视复核关键帧
# 5. 才开始渲染
```

### 下次怎么发现

日志开头打印所用文件的 mtime：

```python
for p in [build_worker.__file__, cinematography.__file__]:
    logger.info(f"模块 {p} mtime={time.ctime(os.path.getmtime(p))}")
```

跑完后比对文件 mtime 是否晚于进程启动时间。

---

## 4. 关键帧与清单版本漂移

### 现象

`SHOT-017.png` 生成于 08:59，但关键帧清单 09:16 才更新。
结果「图」与「提示词」不是一对 —— 复核时怎么都对不上。

### 根因

生成与清单更新是两个独立步骤，中间被人手工改过清单，又没重生成图。

### 修法

统一重建流程并做**指纹守卫**（sha256 + done 标记）：
每张关键帧记录「生成时用的提示词哈希」，复用前先校验；
哈希不一致就拒绝复用、强制重生成。

### 下次怎么发现

```bash
# 逐张比对 PNG mtime 与清单 mtime
stat -c '%y %n' assets/keyframes/*.png | sort | tail -3
stat -c '%y %n' assets/keyframes/keyframes.manifest.jsonl
```

清单比图新 = 已经漂移。

---

## 5. 色彩范围标记错误 → 成品发灰 / 对比过冲

### 现象

部分播放器里成片发灰，另一些播放器里对比度过头。同一文件两种表现。

### 根因

单段产物是 `yuvj420p`（full range 标记）。转码写
`scale=in_range=full:out_range=full` → 输出被打上 full-range 标记。
按 limited 解释的播放器把 0–255 当 16–235 处理 → 发灰；
按 full 解释的又叠加平台二次处理 → 过冲。

### 修法

```diff
- scale=in_range=full:out_range=full
+ scale=in_range=full:out_range=tv
```

### 下次怎么发现

```bash
ffprobe -v error -select_streams v:0 \
  -show_entries stream=pix_fmt,color_range,color_space,color_transfer \
  -of default=nw=1 master.mp4
# 期望：pix_fmt=yuv420p  color_range=tv
```

---

## 6. 单段超时被误杀 / systemd 重启风暴

### 现象 A：单段 2h 被杀

默认 `SDCPP_TIMEOUT=7200`。内存抖动时单段可远超 2h，
到点进程被 kill，而它其实还在正常推进。

修法：`Environment=SDCPP_TIMEOUT=43200`（12h）。

### 现象 B：unit 指向已被清空的系列 → 重启 11 次后放弃

`drama-render.service` 里系列名是写死的。20 号换了系列，
但 unit 仍指向已被 purge 的旧系列 → `render_resume.py` 因清单不存在而 exit 2
→ systemd 重启 11 次（`StartLimitBurst`）后放弃 → **守护整整一天处于 failed 状态**。

修法两层：

1. 「清单不存在」改为 **exit 0 + 明确提示**（不该让它看起来像崩溃）
2. `StartLimitIntervalSec=3600` / `StartLimitBurst=10` 兜住极端情况

### 下次怎么发现

```bash
systemctl --user status drama-render | head -5   # 看是不是 failed (start-limit-hit)
journalctl --user -u drama-render -n 50
```

`start-limit-hit` 字样 = 已经放弃重启，不是「正在重试」。

---

## 附：踩坑速查表

| 症状 | 第一怀疑 | 一行验证 |
|---|---|---|
| `ErrorDeviceLost` / `context is lost` | 显存越线，不是分辨率太高 | `rocm-smi --showmeminfo vram < /dev/null` |
| 渲染比基线慢 20%+ 但没报错 | 两个 sd-cli 并存 | `pgrep -c -f sd-cli` 必须 = 1 |
| 仲裁器日志里没「暂停」 | 面板没起 / `need_gib` 太小 | `curl -fsS 127.0.0.1:23333/api/instance/list` |
| 修了代码但结果没变 | 进程内模块已缓存 | 比对文件 mtime 与进程启动时间 |
| 关键帧跟提示词对不上 | 清单与图版本漂移 | `stat -c '%y %n'` 比 mtime |
| 成片发灰 | full/limited 标记 | `ffprobe -show_entries stream=color_range` |
| 渲染卡住不结束也不报错 | 内存抖动/换页 | `vmstat 1 3`，看 `si`/`so` |
| 权重加载掉到 MB/s 级 | 宿主内存不足 | `free -h`，看 available |
| `ui.sh stop` 杀不死进程 | systemd `Restart=always` | 改用 `systemctl --user stop` |
| `rocm-smi` 卡住不动 | 非交互环境的已知问题 | 加 `< /dev/null` |

---

**许可**：CC0-1.0，公共领域贡献，无任何限制。
