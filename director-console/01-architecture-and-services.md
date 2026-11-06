# 01 · 架构、组件与部署

一套跑在单机上的短剧生产台。核心设计取向：**不用 ComfyUI**，不引入任何需要 CUDA 的组件，
全部走 Vulkan，把 96 GiB 统一显存池用满。

---

## 一、组件清单

| # | 组件 | 进程 / 端口 | 职责 | 技术栈 |
|---|---|---|---|---|
| 1 | 导播台前端 | Vite `127.0.0.1:5173` | 剧本、角色、分镜、任务、素材、配置七个工作区 | React 19.2 / Vite 8.3 / TS 6.0 |
| 2 | 只读看板 | `127.0.0.1:5174` | 渲染进度投影屏，不写任何状态 | Node 静态服务 |
| 3 | Agent API | FastAPI `127.0.0.1:8000` | 会话、剧本、清单、任务、渲染编排；SSE 推送 | FastAPI + loguru |
| 4 | 文本推理 | llama-server `127.0.0.1:8080` | 剧本 / 分镜 / 提示词生成 | llama.cpp（Vulkan） |
| 5 | 文本代理 | docproxy `127.0.0.1:18090` | 注入 `chat_template_kwargs`、裁剪 system prompt、渐进式披露 | Python asyncio |
| 6 | 图像 / 视频推理 | `sd-cli`（子进程，无端口） | 关键帧（`-M img_gen`）、视频段（`-M vid_gen`） | stable-diffusion.cpp（Vulkan） |
| 7 | GPU 仲裁器 | API 进程内模块 | 出片前停 llama-server、结束恢复 | asyncio + HTTP |
| 8 | 渲染续跑守护 | systemd `drama-render` | 自动算未完成镜头、断点续跑、无进展熔断 | Python |

**关键取舍**：**没有 ComfyUI**。渲染后端是 stable-diffusion.cpp 原生 C++ 二进制，
用一个子进程一次跑完一段。好处是零 Python 依赖、显存记账可预测；
坏处是没有节点图，所有能力得自己从 CLI 参数拼。

> 历史遗留：配置里仍有 `comfyui.comfyui_url=http://127.0.0.1:8188`，
> 但 8188 从未监听，每个镜头都报一次 `/free Connection refused`。置空即可消除噪声。

---

## 二、数据流

```
              ┌──────────────────────────────┐
  用户 ──▶ 1 导播台（React）                 │
              │  POST /api/series/...  SSE   │
              ▼                              │
           3 FastAPI ──▶ Agent 循环（LLM tool calling）
              │  ▲                           │
              │  │ 5 docproxy :18090         │
              │  └──────── 4 llama-server :8080
              │
              ├──▶ 剧本 / 分镜真源  projects/{series_id}/dramas/.../epNNN.md
              ├──▶ 关键帧清单      assets/keyframes/keyframes.manifest.jsonl
              ├──▶ 7 GPU 仲裁器 ──HTTP──▶ MCSManager :23333 停/启 llama 实例
              └──▶ 6 sd-cli 子进程 ──▶ shots/SHOT-00X/{segments,video.mp4,tail_frame.png}
                        │
                        ▼
                   ffmpeg 合成 ──▶ output/EPNNN/master.mp4
```

### 真源原则

| 层 | 真源 | 派生物 |
|---|---|---|
| 剧本 | `dramas/{系列}/episodes/epNNN.md` | 分镜表 `.md`、清单 `.jsonl`、提示词 |
| 关键帧 | `assets/keyframes/keyframes.manifest.jsonl` + PNG | 视频首帧 |
| 成片 | `shots/{shot_id}/video.mp4` + `tail_frame.png` | 母版 |

> ★ **手写分镜表会与真源分叉**。一旦有人手改分镜表而没改剧本，
> 下一次从真源重建就把改动抹掉。正确做法：分镜表**永远由脚本从剧本生成**，
> 人不直接编辑（本次已落地 `scripts/gen_ep002_shot_table.py`）。

---

## 三、四单元 systemd 部署

断电 / 重启后全链路自动拉起，渲染不需要手工续跑。

| unit | 作用 | `Restart=` | 备注 |
|---|---|---|---|
| `drama-api.service` | FastAPI :8000 | `always` / 5s | |
| `drama-web.service` | Vite :5173 | `always` / 5s | `After=drama-api.service` |
| `drama-board.service` | 只读看板 :5174 | `always` / 5s | |
| `drama-render.service` | 渲染续跑 | `on-failure` / 120s | `SuccessExitStatus=0`、`RuntimeMaxSec=604800` |

前置：`loginctl show-user $USER | grep Linger=yes`，否则用户退出登录服务即停。
若为 `no`：`sudo loginctl enable-linger $USER`。

### 3.1 渲染单元的六条关键设定

`drama-render.service` 是整个部署里唯一有难度的部分：

```ini
[Service]
WorkingDirectory=/home/lc/drama-series-agent
TimeoutStartSec=300
ExecStartPre=.../startup-delay.sh 60          # 仅开机 300s 内延迟，运行期崩溃不等

ExecStart=.../with-env.sh .../python scripts/render_resume.py \
            --series 四级手术 --episode EP001 --wait-running 86400

Restart=on-failure
RestartSec=120
SuccessExitStatus=0                            # 正常跑完 exit 0 不重启
RuntimeMaxSec=604800                           # 单轮 7 天兜底，含等待时间
TimeoutStopSec=120                             # 给 sd-cli 清理中间产物的时间
KillMode=control-group

Environment=SDCPP_TIMEOUT=43200                # 单段 12h（默认 7200s 在内存抖动时会被误杀）
UnsetEnvironment=CODEBUDDY_TOOL_CALL_ID CODEBUDDY_SAFE_DELETE_BULK_STATE_DIR
StandardOutput=append:.../logs/render.service.out
```

| 设定 | 为什么 |
|---|---|
| `--wait-running 86400` | 渲染守护与「人工前台跑的渲染」可能并存。检测到后者时每 60s 复检、最多等 24h，对方一结束就自动接管 → 实际效果是「守护常驻，谁在跑让谁跑」 |
| `SuccessExitStatus=0` + 应用层熔断 | 连续 3 轮未完成数不下降 → 写 `run/render_resume.break` 并 exit 0 → systemd 不重启 → 避免「崩溃→重启→崩溃」烧机时 |
| `KillMode=control-group` | `npm run dev` / `render_resume.py` 都会 fork 出子进程，必须整组回收 |
| `UnsetEnvironment=CODEBUDDY_*` | 渲染链路大量删中间产物，不能继承外部工具链的批量删除计数变量 |
| `SDCPP_TIMEOUT=43200` | 内存抖动时单段会远超 2h，默认 7200s 会误杀正在推进的任务 |
| `ExecStartPre` 里的开机延迟 | 刚开机时 llama-server / MCSManager 还没起，同时抢内存会让双方都慢 |

### 3.2 未完成镜头的判据必须与 runner 完全一致

```python
# 已完成 ⟺ shots/<shot_id>/video.mp4 存在 且 shots/<shot_id>/tail_frame.png 存在
```

**只判存在性，不判文件大小。** 两边判据一旦错位，就会出现
「systemd 认为没渲完、runner 认为渲完了」的死循环。

另一个必修的坑：`render_shots.py` 没有自动算「哪些镜头没完成」的能力，
`--shots` 必须手传；`render_resume.py` 就是这层包装。且**不能用 `--purge`**
（会把 `shots/<id>/` 移走，破坏跳过判据 → 已完成镜头重渲）。

### 3.3 为什么不用 systemd 的 `EnvironmentFile=`

项目 `.env` 里有

```
LLM_API_KEY=${OPENCLAW_APIKEY_LLAMACPP:-sk-local-nokey}
```

`${VAR:-default}` 是 **bash 语法**，systemd 的 `EnvironmentFile=` 只做字面量解析，
会把整串当成密钥值原样带入。改走一个 `with-env.sh`：

```bash
#!/usr/bin/env bash
# 用 bash source 加载项目 .env，再 exec 目标命令
set -a
. "$(dirname "$0")/../../.env"
set +a
exec "$@"
```

### 3.4 托管后必须停用的旧命令

旧的 `ui.sh stop` 按端口 kill 8000/5173，systemd 的 `Restart=always` 会立刻拉回来 ——
表现为「杀不死」，还会掩盖真正的失败原因。

| 目的 | ✅ 托管后 | ❌ 不要用 |
|---|---|---|
| 停服务 | `systemctl --user stop drama-api drama-web` | `ui.sh stop` |
| 重启 | `systemctl --user restart drama-web` | `ui.sh restart` |
| 看状态 | `systemctl --user status 'drama-*'` | — |

`ui.sh status` / `ui.sh logs` 是只读的，仍可安全使用。

---

## 四、前端：同源代理 + SSE

导播台要实时显示 Agent 的流式输出，前端与 API 不同端口就得处理 SSE。

`web/vite.config.ts` 的做法：

- 所有 `/api` 请求同源代理到 `VITE_API_PROXY_TARGET || 'http://127.0.0.1:18000'`
- SSE 通道把代理超时置 `0` 并设 `x-accel-buffering: no`（禁缓冲）

```ts
proxy: {
  '/api': {
    target: process.env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:18000',
    changeOrigin: true,
    // SSE 必须关掉代理超时与缓冲，否则事件被攒成一批才吐
    timeout: 0,
    configure: (proxy) => {
      proxy.on('proxyRes', (proxyRes) => {
        if ((proxyRes.headers['content-type'] || '').includes('text/event-stream')) {
          proxyRes.headers['x-accel-buffering'] = 'no'
        }
      })
    },
  },
}
```

> ★ 记一笔真实教训：曾因 frp 隧道故障 6.5 小时，前端报「所有配置丢失」。
> 根因不在配置存储，而在**前端读不到后端**时的空态提示有歧义。
> 现在这类故障的第一排查动作是 `curl 127.0.0.1:8000/health` + 看代理目标端口，而不是翻配置。

---

## 五、API 层的组织方式

FastAPI 侧按「会话 = 剧集」组织：一个 conversation ↔ 一个 `series_id`，
七个页面各自对接一组路由（会话 / 剧集 / 角色 / 分镜 / 任务 / 素材 / 系统配置）。

渲染是**异步 job**：`POST /api/series/conversations/{cid}/jobs` 提交，
前端订阅 SSE 拿进度。job 内部才去申请 GPU 租约 —— 申请与释放是**按镜头**成对出现的，
不是整集一次性持有（原因见 [02-gpu-arbiter.md](02-gpu-arbiter.md) 的粘滞窗口策略）。

---

## 六、给复刻者的最小骨架

```bash
# 1. 系统依赖（Debian 系）
sudo apt install -y build-essential cmake git ffmpeg \
                    mesa-vulkan-drivers vulkan-tools libvulkan-dev
vulkaninfo --summary | grep -E "deviceName|apiVersion"   # 必须看到 RADV STRIX_HALO

# 2. sd.cpp（Vulkan）
git clone https://github.com/leejet/stable-diffusion.cpp ~/sdcpp-src
cd ~/sdcpp-src
cmake -B build-vk -DCMAKE_BUILD_TYPE=Release -DSD_VULKAN=ON -DGGML_VULKAN=ON
cmake --build build-vk -j"$(nproc)"
./build-vk/bin/sd-cli --help | head -5

# 3. llama.cpp（Vulkan）—— 用本仓库 docs/00 的 fork 分支
# 4. 项目本体
git clone <本仓库> && cd local-llm-deploy-strix-halo
# 5. 起前后端
bash deploy/systemd/install.sh
```

> 检查 `ldd sd-cli | grep -E "hip|rocm"` 应为空 —— 一旦链上了 HIP 库，
> 显存就走 GTT 池（系统 RAM），40 GiB 权重必然 OOM。

---

**许可**：CC0-1.0，公共领域贡献，无任何限制。
