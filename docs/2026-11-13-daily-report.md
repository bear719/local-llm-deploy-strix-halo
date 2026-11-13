# 本地大模型日报 · 2026-11-13（第 55 次执行 · 全 API 通道版）

> 探测时间：2026-11-13 05:00 CST（自动化窗口）｜主机：AMD Ryzen AI MAX+ 395（Strix Halo / gfx1151 / Radeon 8060S），统一内存 128 GiB，BIOS UMA 车分 96 GiB｜引擎：llama.cpp（fork `$HOME/llama-qwen4exp-rocmfpx`，Vulkan RADV STRIX_HALO，Mesa 26.0.8 钉死）
> 实测模型以步骤 0 探测为准：当前在线为 **模型 A 的 Q5_K_P 变体**，清单「模型 C（Qwen3.8-Flash-Next）」仍离线。

---

## 1. 抓取通道状态表

| 通道 | 状态 | 结果摘要 | 失败原因/降级 |
|---|---|---|---|
| P0 GitHub releases | ✅ 成功 | 最新 `b12327`（2026-11-12T20:59Z） | — |
| P0 GitHub PRs | ✅ 成功 | 取 15 条，新 `#32162`(open, vulkan ssm_scan state96)、`#32163`(open, llama_batch 迁移文档)、`#32023`(open, jinja 渲染减负)、`#27418`(open, server sleep-mode reset)、`#32107`(open, flint 原生语法) | — |
| P0 GitHub issues | ✅ 成功 | 取 15 条，`#27845`(closed, `-sm tensor` token 生成内存泄漏) | — |
| P0 kyuz0/amd-strix-halo-toolboxes | ✅ 成功 | 最近 11-07（Maya toolbox 公开、pinned GGUF） | — |
| P0 Nathanw1014/strix-halo-llamacpp | ✅ 成功 | 最近 10-25（Vulkan EXL3/TRELLIS 构建、Mesa 26.2.4 绑定） | — |
| P0 drluoto/llama.cpp | ✅ 成功 | 最近 08-28（含 vulkan view-alias 修复、Qwen4exp graph split） | — |
| P0 gufo-org/gufo | ✅ 成功 | **11-12 极活跃**：cache 保留、serve Windows 独占绑定、npu XDNA XRT、build curl pin、qwen SSM post-norm kernel | — |
| P0 kingjones777/MTP-Heads-GGUF | ❌ 失败 | 404（连续多日） | 降级 → kingjones30/strix-halo-quant-lab ✅（11-12 索引 159 仓库，每日刷新） |
| P1 Hacker News (Algolia) | ✅ 成功 | llama.cpp 9 条（14 天窗口内与昨日一致，无新增）；`>` 已写 `%3E` | — |
| P2 WebSearch（内置，freshness d14） | ✅ 成功 | 3 组查询 ×5 条，均为搜索引擎收录结果，**二手聚合，非站内直采** | — |
| 🚫 抖音/小红书站内直采 | 已停用 | 不恢复、不重试（headless DOM 未渲染 + 需登录 + 无 Xvfx） | — |
| 🚫 Reddit (r/LocalLLaMA) | 已停用 | 本机 HTTP 000 网络层阻断 | — |
| 🚫 gh CLI | 未安装 | 改用 curl + api.github.com | — |

---

## 2. 当前运行方案实测表（来自步骤 0 真实数据）

| 项 | 实测值 | 来源 |
|---|---|---|
| 探测端口 | **8080 在线**（首端口命中） | `curl /props /v1/models` |
| model_path | `$HOME/models/Qwen3.6-35B-A3B-Uncensored-Q5_K_P.gguf` | `/v1/models` |
| model_ftype | `Q5_K - Medium`（清单「模型 A」的 Q5_K_P 变体，非 Q4_K_P） | `/props` + `/v1/models` |
| size | 28,016,404,992 B（≈28.0 GB） | `/v1/models` |
| n_params | 34,660,610,688（34.66B） | `/v1/models` |
| n_embd | 2048 | `/v1/models` |
| n_vocab | 248320 | `/v1/models` |
| n_ctx / n_ctx_train | 262144 / 262144 | `/props` + `/v1/models` |
| total_slots | 1 | `/props` |
| modalities | vision=true, video=true, audio=false | `/props` |
| **speculative（MTP）** | **已启用（三处交叉验证）**：`/slots` 原始字段 `"speculative":true`；`ps` 命令行 `--spec-type draft-mtp --spec-draft-n-max 2`；`/metrics` 草稿 755275 / 接受 604168 = **79.99%**。⚠️ `/props` 的 `default_generation_settings.params.speculative.types="none"` 属本 fork 已知不可信字段，**以 /slots+ps+/metrics 为准** | `/slots`+`ps`+`/metrics` |
| **MTP 接受率** | **79.99%**（604168 / 755275，累计计数器，较昨日 198228/158454 大幅增长 → 持续高频使用） | `/metrics` |
| KV cache | `q8_0`（`-ctk q8_0 -ctv q8_0`） | `ps` |
| 采样默认 | temp=1.0、top_k=20、top_p=0.95、min_p=0.05、repeat_penalty=1.0；samplers 顺序含 dry/top_n_sigma/typ_p/xtc | `/props` |
| build_info | `b10824-75147a27e` | `/props` |
| 关键启动参数 | `-ngl 999 -c 262144 -np 1 -b 4096 -ub 1024 --mmproj f16 --context-shift --cache-idle-slots -cms 8192 --cache-ram 16384 --ctx-checkpoints 16 --metrics --host 0.0.0.0 --port 8080` | `ps` |
| MoE 专家缓存 | **未开**（无 `--moe-cache-mib`）→ 待优化 A1 | `ps` |
| 暴露面 | `--host 0.0.0.0`（A0 未收窄，连续 40+ 日） | `ps` |
| 18090 代理 | `mode=passthrough`，upstream=8080 OK；`npu_enabled=true`，`npu_upstream=http://127.0.0.1:8219`（8219 `/health` 返回 JSON 错误页 → 有进程监听，身份未明，延续监控） | `/health` |
| 8219 探测 | `{"error":"Not Found"}`（HTTP 服务存活，非 000） | `curl 8219/health` |
| 模型 C（Qwen3.8-Flash-Next） | **未在线**（`/v1/models` 仅返回模型 A） | `/v1/models` |
| 本机实测 decode | **本次未重测速**（单 slot 避免扰动）；引用 11-04 固化值 **72.41 t/s**（Q5_K_P，短 prompt，temp0）｜`[历史值，待本机验证]` | 11-04 日报 |
| 本机实测 prefill | 引用 09-24 值 **~400 t/s**｜`[历史值，待本机验证]`（建议近期固定长 prompt 重测） | 09-24 日报 |

---

## 3. minimax h3 专题（专项检查项逐条结论）

> 数据源：本机 `$HOME/drama-series-agent/config.json`（本次实测）+ 进程/端口实测 + 社区共识（P2）。

| # | 检查项 | 实测 | 结论 |
|---|---|---|---|
| B0 | render.backend | `sdcpp` | ✅ 一致（非 ComfyUI） |
| B1 | 主 LLM 8080 与 sd.cpp 不冲突 | 8080 在线、sd-cli 当前空闲（无渲染进程） | ✅ 无冲突 |
| B2 | render 步数 / CFG（draft） | `render.steps=12`, `render.cfg_scale=1.0` | ⚠️ 漂移延续：draft 偏低（社区共识 20-30 步 / CFG 4-8，见 §4/§5） |
| B2' | quality / image 步数 | `image.steps=20`, `image.cfg_scale=4.0` | ✅ 对齐社区正式档（20 步 / CFG 4） |
| B3 | **llm.base_url / model** | `base_url=http://127.0.0.1:18090/v1`, `model=Qwen3.6-35B-A3B-Uncensored-Q5_K_P.gguf` | ✅ **稳定为本地 Qwen3.6 / 18090**（昨日「回退本地」今日已坐实，非临时漂移） |
| B4 | 画布 / 母版 | `800x448` / `master 1920x1080`, 24fps, crf18, aac192k | ✅ 一致 |
| B5 | sd.cpp bin | `$HOME/sdcpp-git/build-vk4/bin/sd-cli`（存在） | ✅ 一致（vk4 优于 vk2 6.8%） |
| B6 | 8000 API / 5173 前端 | 8000 监听（root 404，API 正常）、5173 HTTP 200 | ✅ 在线 |
| B7 | 8188 ComfyUI | `8188=000` 无监听 | ✅ 一致（已弃用） |
| B8 | `comfyui.comfyui_url` | `http://127.0.0.1:8188`（config 实测，非空） | ⚠️ 漂移延续（#8）：与 10-20「已清空」记录不符，8188 无监听仅噪音 |
| B9 | `SDCPP_EXTRA_ARGS` | `.env` 第 29 行 `SDCPP_EXTRA_ARGS="--vae-tiling"` | ✅ **已确认生效**（昨日「待复核」今日闭环，VAE tiling 防 OOM） |
| B10 | gpu.arbiter | `need_gib=64`, `instance_uuid=9770784bb1f940ada5c5890fd003efb3`, `auto_resume=true` | ✅ 一致（qwen 实例暂停/恢复护栏） |
| B11 | 驱动栈 / 后端 | Vulkan RADV STRIX_HALO，Mesa 26.0.8（apt-mark hold 钉死） | ✅ 一致（勿升 26.2.x） |

**专项小结**：10 项零漂移 + B9 关闭（SDCPP_EXTRA_ARGS 确认）+ B3 由「新漂移」转为「稳定本地」；**仅余 2 项历史漂移**（B2 draft 步数/CFG 偏低、B8 comfyui_url 回退 8188）。

---

## 4. 其他近期关键动态（事实 vs 他人实测值）

**【事实 · 一手源 GitHub】**
- `b12327`（11-12）：release 含 `ggml: dispatch SpacemiT Q4_1 32x256 HP kernel`、`chat: refactor gemma4 PEG parser`、`server: sleep-mode reset`(对应 #27418) 等。来源：https://github.com/ggml-org/llama.cpp/releases
- `#32162`（open）：`vulkan: support state size 96 in ssm_scan` — Vulkan 后端 SSM 模型支持扩展。来源：https://github.com/ggml-org/llama.cpp/pull/32162
- `#32163`（open）：`docs: add migration guide for llama_batch`。来源：https://github.com/ggml-org/llama.cpp/pull/32163
- `#27418`（open）：`server: add --sleep-mode rst`（与 HN 11-06 sleep mode 文章呼应，llama.cpp 原生 sleep 能力推进）。来源：https://github.com/ggml-org/llama.cpp/pull/27418
- gufo 11-12 极活跃（5+ commit）→ 模型 C（Qwen3.8-Flash-Next）上游生态持续利好。来源：https://github.com/gufo-org/gufo
- kingjones30/strix-halo-quant-lab 11-12 索引 **159 仓库**（同硬件 ROCmFP4 量化基准库，替代 404 的 kingjones777）。来源：https://github.com/kingjones30/strix-halo-quant-lab

**【事实 · HN P1】（14 天窗口，与昨日一致，无新增）**
- 「Inside Llama.cpp: How Local LLMs Run on Your Hardware」（11-11，视频）
- 「Qwen3.8-27B MTP Q4S head on Q6 quant is faster than q6, f16 slower = acceptance」（11-08）— 佐证 MTP 草稿头量化/采样器对齐对接受率的决定性影响（坐实 #27950）
- 「TokiRecur – KV-cache recycling launcher」（11-07）；「Swapping LLMs in Under Two Seconds: A Sleep Mode」（11-06）
- 注：窗口未翻页，9 条与昨日相同 → **HN 通道无实质新增**。

**【他人实测值 · P2 二手聚合，均待本机验证】**
- **getrigbase**（Strix Halo 128GB，Qwen3.8-Flash-Next，最小内存全驻留实测）：**68.8 tok/s**。来源：https://getrigbase.com/models/qwen3-8-flash-next ｜`[他人实测，待本机验证]`
- **deepu105 / dev.to**（同硬件 Strix Halo 128GB，Qwen3.8-Flash-Next ROCmFP4）：decode **23.7 tok/s**、prefill **96 tok/s**、常驻 ~86 GiB（对比 27B 仅 31 GiB）。来源：https://dev.to/deepu105/can-qwen-38-running-on-your-laptop-really-replace-claude-opus-for-agentic-coding-51gk ｜`[他人实测，待本机验证]`
  - ⚠️ 注意：68.8 vs 23.7 差距巨大，推测因上下文长度/量化/MTP 配置不同（getrigbase 或为短 ctx 无 MTP 基准，deepu 为含思考的长上下文）。两者均与本机 llamaperf 历史 41 t/s（262k ctx+MTP）不冲突，仅说明 **模型 C 速度高度依赖 ctx 与 MTP 配置**。
- **Strata 引擎**（MoE 拆分 GPU/RAM/SSD，草稿 1.6–1.8× 提速，Strix Halo/Mac 支持，11-07 v0.2.12）：可作为 llama.cpp 之外跑模型 C 的备选方案。来源：https://www.ithub.directory/local-llm-inference/strata ｜`[二手聚合]`
- **通用部署共识（多源）**：Q4_K_M 为质量/体积最佳平衡点；预算 75–80% 可用内存；**prefill（读 prompt 速度）才是本地可用性天花板，而非 decode**（siliconnoon）；MoE 按激活参数计费带宽、按总参数计费内存。来源：https://siliconnoon.com/how-to-run-a-local-llm、https://blog.arihantdeva.com/blog/local-llm-private-ai-setup ｜`[二手聚合]`
- **MiniMax H3 社区共识（多条独立源，11-12 仍在索引）**：steps **20-30 正式 / 10-15 草稿**；CFG **4-8**（hqwc 3-5、kwkr 4-8、lpqz 4-7，个别视频源 7-12）；竖屏分辨率 **576×1024**，帧数 8-32；VAE 保持自带避免精度不匹配；负向加 `text/watermark/logo/模糊/变形/闪烁`。来源：http://www.hqwc.cn/a/1601329.html、https://www.hqwc.cn/a/1595654.html、http://www.lpqz.cn/news/172512 等 ｜`[二手聚合，非站内直采]`

---

## 5. 现状 vs 社区同硬件最优对比表

| 维度 | 本机（模型 A Q5_K_P, Vulkan） | 社区同硬件（Strix Halo 35B-A3B） | 社区模型 C 基准（Flash-Next, 同硬件） | 差距 / 优先级 |
|---|---|---|---|---|
| decode t/s | 72.41（11-04 引用，temp0）`[历史]` | 61.8（无 MTP, b11401）`[他人]` | 68.8（getrigbase, 短ctx）`[他人]` / 41（llamaperf 262k+MTP）`[他人]` / 23.7（deepu 长ctx）`[他人]` | 本机 35B 已优于社区 35B 无 MTP；模型 C 速度随 ctx/MTP 剧烈波动，**P2** 待本机实测模型 C |
| prefill t/s | ~400（09-24 引用）`[历史]` | 未高报 | **1240-1335**（llamaperf）`[他人]` / 96（deepu）`[他人]` | 相对模型 C 基准差 ~3×，**P0**（A2 prefill 短板闭环）｜⚠️ 本机 prefill 自 09-24 未重测 |
| 上下文 | 262144（=训练） | 262144 | 262144 | ✅ 持平 |
| KV | q8_0 | q8_0（生产共识） | q8_0 | ✅ 已对齐 |
| GTT/显存 | 96 GiB（BIOS UMA） | 96-111 GiB usable | 96-98 GiB | ✅ 持平 |
| 驱动栈 | Mesa 26.0.8（钉死） | 26.2.x / 驱动 32.0.3 | Windows/Mesa 混合 | ⚠️ 本机刻意钉死防回归，**P0 稳定项** |
| build 版本 | b10824（commit 75147a27e） | b11401+ / b12327 上游 | gufo v0.31+ | **落后上游 ≈1503 build（+35/日）**，**P1**（C2 升级） |
| MTP 接受率 | 79.99%（n-max2，累计） | 未报 | 70-91%（n-max7） | 可试 n-max3，**P2**（A4）+ #27950 人核 |
| 暴露面 | --host 0.0.0.0 | 多本地 | 本地 | ⚠️ **P0 安全**（A0，#32098 背景） |
| MoE 缓存 | 未开 | 未明确 | spill disk cache | **P1**（A1 `--moe-cache-mib`） |

---

## 6. 可立即执行的优化清单

### ① 改启动参数即可（改 -flag 重启实例，无需重编译；须经 MCSManager 面板，勿裸跑）
```bash
# A0 安全：将 --host 0.0.0.0 收窄为 127.0.0.1（#32098 已修 CORS/DNS rebinding，但仍应仅监听本机）
#   修改 MCSManager 实例「start-qwen36-35b-a3b」(UUID 9770784bb1f940ada5c5890fd003efb3) 启动命令，
#   把 `--host 0.0.0.0` 改为 `--host 127.0.0.1`，保存后在面板重启；18090 docproxy 仍在 127.0.0.1，应用侧无影响。

# A1 MoE 专家缓存：减少重复权重读取（模型 A 为 MoE，未开则每请求重载专家）
#   在启动命令追加：--moe-cache-mib 8192

# A4 试 MTP n-max3（保持 -md MTP-ONLY-Q4_K_M.gguf --spec-type draft-mtp）
#   将 `--spec-draft-n-max 2` 改为 `--spec-draft-n-max 3`，重启后观察 /metrics 接受率与质量（需 #27950 人核）。
```

### ② 环境清理（低风险，立即）
```bash
# B8 噪音：config.json 的 comfyui.comfyui_url 仍回填 8188（无监听，仅日志噪音）
#   如确认不用 ComfyUI，置空：jq '.comfyui.comfyui_url=""' config.json > /tmp/c.json && mv /tmp/c.json config.json
#   （应用侧清理逻辑会跳过空值；面板显示回落 8188 属展示层，无害）

# B9 已确认：SDCPP_EXTRA_ARGS="--vae-tiling" 已在 .env（无需改）。

# Mesa 钉死复核：确认 6 包仍 hold，防止 apt upgrade 升到 26.2.x
apt-mark showhold | grep -E "mesa|libgbm"   # 应列出 6 个包

# 🆕 基线刷新建议：本机 decode 自 11-04、prefill 自 09-24 未重测，
#   用固定 2K/8K/32K prompt 各跑一次取均值，刷新 §5 对比基线（无需改参数）：
#   curl -s http://127.0.0.1:8080/v1/completions -H 'Content-Type: application/json' \
#     -d '{"prompt":"<固定长文本>","n_predict":256,"temperature":0}'   # 记录 prompt+tok/s 与 gen tok/s
```

### ③ 需重启或重建（cherry-pick / 升级二进制；先备 mesa deb 再动）
```bash
# C2 升级到上游 b12327（落后 1503 build，含 #32098 安全修复、#31418 vulkan 优化、#32162 ssm_scan）：
#   前置（三步走，缺一不可）：
#   1) 备份当前可用 mesa deb：apt-get download mesa-vulkan-drivers libgl1-mesa-dri libglx-mesa0 libegl-mesa0 mesa-libgallium libgbm1
#   2) 升级后先用 vulkaninfo 验证枚举正常，再重启业务
#   3) 升级本机 fork 须 git pull + 重建（fork 落后多，建议先 git log 确认无本地未提交改动）
cd $HOME/llama-qwen4exp-rocmfpx && git status --short   # 确认干净后再 pull
cmake --build build-vk4 --target llama-server -j16          # 重建（fork 用此目标，避免 all 被 tests 拖垮）

# C1 cherry-pick 关键 PR（若只想取安全修复）：#32098(CORS/DNS)、#31418(vulkan batched copy)、#32162(ssm_scan)
#   用 mcp__github 或 git cherry-pick <合并 commit>；cherry-pick 后同样重建 build-vk4。
```

---

## 7. 风险与验证

- **🔴 MTP 输出质量需人工核对（llama.cpp #27950）**：本机接受率 79.99% 仅表征「目标模型接受草稿」比例，**不证明语义质量无损**。社区（deepu105）已验证采样器不对齐 drafter 时接受率骤降且墙钟恶化。建议：用固定 temp=0 跑 8K/32K/64K 三档中文续写，人工比对开启/关闭 MTP 的输出差异。**连续 30+ 日未做，优先级 P1。**
- **Vulkan NaN 监控（#31509）**：本机 Vulkan 后端，留意 `/metrics` 或渲染日志中 NaN/inf；出现即回退并检查上游修复。
- **Mesa 26.0.8 钉死**：26.2.x 在本机（gfx1151）会导致 Vulkan 完全不可用（已立硬约束）。任何系统级驱动升级必须先备 deb + vulkaninfo 验证。
- **暴露面 A0**：`--host 0.0.0.0` 已持续 40+ 日；上游 #32098 修了 CORS/DNS rebinding，但仍应收窄到 127.0.0.1。
- **模型 C 离线**：Qwen3.8-Flash-Next 未在线，社区基准（68.8 / 41 / 23.7 t/s，差异源于 ctx/MTP 配置）仅作对标，本机未实测；建议择机上线模型 C 做同硬件基准对照。
- **基线老化**：本机 decode（11-04）/prefill（09-24）数据已较旧，建议近期刷新（见 §6②）。
- **8219 身份未明**：npu_upstream 持续指向 127.0.0.1:8219，有 HTTP 进程但用途不明，建议排查归属。

---

## 8. 今日相对昨日（11-12）的新增项

✅ **有实质增量，非注水：**

1. **上游推进 +35 build**：b12292（11-11）→ **b12327**（11-12），本机落后 ≈**1503 build**（昨日 1468）。
2. **🆕 模型 C 同硬件他人实测补充**（新数据源，与昨日 llamaperf 41 t/s 互补）：
   - getrigbase：Strix Halo 128GB **68.8 tok/s**（最小内存全驻留）。
   - deepu105：Strix Halo 128GB decode **23.7 t/s** / prefill **96 t/s** / 常驻 ~86 GiB。
   - 二者差距揭示**模型 C 速度高度依赖 ctx 长度与 MTP 配置**，已在 §5 标注。
3. **🆕 Strata 引擎入认知**：MoE 拆分 GPU/RAM/SSD + 草稿 1.6–1.8× 提速，可作 llama.cpp 之外跑模型 C 的备选（11-07 v0.2.12）。
4. **🆕 新 PR #32162**（vulkan ssm_scan state96）、#32163（llama_batch 迁移文档）、#27418（server sleep-mode reset，呼应 HN sleep mode）。
5. **✅ B9 闭环**：`SDCPP_EXTRA_ARGS="--vae-tiling"` 已确认写入 `.env`（昨日「待复核」今日关闭）。
6. **✅ B3 坐实**：config.json 实测 llm 连续两日为**本地 Qwen3.6 / 18090**，由「新漂移回退」转为稳定态。
7. **MiniMax H3 共识再确认**（11-12 仍索引的多源）：steps 20-30 / CFG 4-8 / 576×1024 / 帧 8-32，印证本机 draft（steps=12 / cfg=1.0）偏低（B2 漂移延续）。
8. **gufo 11-12 极活跃**（cache/serve/npu/SSM 多项 commit）→ 模型 C 生态持续利好；kingjones30 11-12 仍索引 159 仓库。

**无实质新增（已说明）：** HN 9 条与昨日窗口完全一致，未翻页新增。

**延续未解（不变）**：A0 host 收窄(40+日) / A1 MoE 缓存 / A2 prefill 短板 / A4 n-max3 + #27950 人核(30+日) / B2 draft 步数 CFG 偏低 / B8 comfyui_url 回退 / C2 升级 b12327（先备 mesa deb）/ Mesa 26.0.8 钉死 / #31509 Vulkan NaN 监控 / 8219 身份未明 / 模型 C 离线待基准。
