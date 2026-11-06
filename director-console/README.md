# 自建导播台 · Strix Halo 单机出片工作台

在一台 AMD Ryzen AI MAX+ 395（Radeon 8060S / RADV / 96 GiB 统一显存池）上，
从零搭一套「聊剧本 → 拆分镜 → 出关键帧 → 出视频段 → 拼母版」的本地短剧生产台。

- 文本侧：llama.cpp（Qwen3.6-35B-A3B）+ docproxy 代理，负责剧本、分镜、提示词生成
- 视频侧：stable-diffusion.cpp（Vulkan）+ MiniMax-H3，负责画面与音轨联合生成
- 编排侧：FastAPI（Agent API，走 LLM tool calling）+ React 19 / Vite 8 前端
- 守护侧：systemd user service 四单元（api / web / board / render）
- GPU 侧：独占仲裁器，出片前通过 MCSManager 面板停掉常驻 llama-server

本目录只写**工程实现层**的经验：架构、显存记账、出片规格、耗时实测、优化清单、事故复盘。
**创作方法论**（分镜语法、提示词锚定、台词时长模型）见同级 [`../drama/`](../drama/README.md)。

---

## 目录

| 文件 | 内容 |
|---|---|
| [01-architecture-and-services.md](01-architecture-and-services.md) | 八个组件、端口、数据流、四单元 systemd 部署、SSE 同源代理 |
| [02-gpu-arbiter.md](02-gpu-arbiter.md) | 96 GiB 单池的账本、实测崩溃边界、仲裁器策略与状态机 |
| [03-render-profile-and-cadence.md](03-render-profile-and-cadence.md) | 出片规格实测、单段耗时表、画布×帧数×步数的三角约束、A/B/C 级优化清单与执行结果 |
| [04-incidents-and-pitfalls.md](04-incidents-and-pitfalls.md) | 六起真实事故与踩坑：跨进程互斥缺失、裸跑脚本绕过仲裁、后端跑旧代码、面板未起、色彩范围、单段超时 |

---

## 一句话结论（给赶时间的人）

| 结论 | 数值/依据 |
|---|---|
| 单机只能**串行出片**，并发必须 = 1 | 96 GiB 单池，H3 一次吃 40 GiB、llama 吃 31–35 GiB；两进程并跑必 `ErrorDeviceLost` |
| 出片成本是**分钟/秒成片**，不是帧/秒 | 12 步档 ≈ 12.3 min / 秒成片；20 步档 ≈ 20.5 min / 秒成片 |
| 最大的浪费是**段数**，不是分辨率 | 每段都是一次独立 sd-cli 进程，重载约 40 GiB 权重 ≈ 2.5 min 固定开销 |
| 排第一位的手工优化是**画布降到 0.59 MP** | 768×1344（1.03 MP）→ 576×1024（0.59 MP），单段帧数从 39 提到 90，段数腰斩 |
| 显存越线**不报 OOM**，只有 device lost | radv 在 UMA 上虚报可用显存（日志报过 `free 145964 MB`） |

---

## 硬件前提

| 项 | 值 |
|---|---|
| CPU/GPU | AMD Ryzen AI MAX+ 395 / Radeon 8060S（`deviceType=INTEGRATED_GPU`） |
| Vulkan | RADV STRIX_HALO，`apiVersion=1.4.354`，Mesa `26.1.6~kisak1~r` |
| ICD | `VK_ICD_FILENAMES=/usr/share/vulkan/icd.d/radeon_icd.json` |
| 显存 | BIOS UMA 划走 96 GiB，系统可用 RAM 仅 ~30 GiB |
| 后端 | **纯 Vulkan**：`ldd sd-cli` 无 `libamdhip64` / `librocm` |

> HIP 路线（ComfyUI + PyTorch）在本机走 GTT 池，吃的是系统 RAM 那 30 GiB，
> 40 GiB 权重必然 OOM。这不是遗漏，是刻意的设计取舍。详见仓库 `docs/06-video-pipeline.md`。

---

## 许可

本目录内全部文字、命令、配置、脚本片段按 **CC0-1.0** 提供（公共领域贡献，无任何限制）。
可自由复制、修改、商用、二次发布，无需署名。
