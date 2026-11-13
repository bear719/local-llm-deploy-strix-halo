# 本地大模型日报 · 2026-11-12（第 54 次执行 · 全 API 通道版）

> 探测时间：2026-11-12 清晨自动化执行窗口（CST）｜主机：AMD Ryzen AI MAX+ 395（Strix Halo / gfx1151 / Radeon 8060S），统一内存 128 GiB，BIOS UMA 车分 96 GiB｜引擎：llama.cpp（fork `$HOME/llama-qwen4exp-rocmfpx`，Vulkan RADV STRIX_HALO，Mesa 26.0.8 钉死）

---

## 1. 抓取通道状态表

| 通道 | 状态 | 结果摘要 | 失败原因/降级 |
|---|---|---|---|
| P0 GitHub releases | ✅ 成功 | 最新 `b12292`（2026-11-11T20:15Z） | — |
| P0 GitHub PRs | ✅ 成功 | 取 15 条，新 `#32098`(merged, CORS/DNS rebinding)、`#32043`(open)、`#32108`(open CUDA FA)、`#31418`(merged, vulkan batched copy) | — |
| P0 GitHub issues | ✅ 成功 | 取 15 条，`#32019`(open, 取消加载)、`#32099`(closed, Metal)、`#16000`(open, --numa mirror, 95 评论) | — |
| P0 kyuz0/amd-strix-halo-toolboxes | ✅ 成功 | 最近 11-07（Maya toolbox 公开、pinned GGUF 准备库） | — |
| P0 Nathanw1014/strix-halo-llamacpp | ✅ 成功 | 最近 10-25（Vulkan EXL3/TRELLIS 构建、Mesa 26.2.4 绑定） | — |
| P0 drluoto/llama.cpp | ✅ 成功 | 最近 08-28（含 vulkan view-alias 修复 `#27812`，Qwen4exp graph split） | — |
| P0 gufo-org/gufo | ✅ 成功 | **11-11 极活跃**：serve 按 RFC9112 解析、JSON 数字封顶 16 位、session runner 不计 prompt state（模型 C 利好） | — |
| P0 kingjones777/MTP-Heads-GGUF | ❌ 失败 | 404（连续多日） | 降级 → kingjones30/strix-halo-quant-lab ✅（11-11 索引 159 仓库） |
| P1 Hacker News (Algolia) | ✅ 成功 | llama.cpp 9 条 + local LLM 多条；`>` 已写 `%3E` | — |
| P2 WebSearch（内置，freshness d14） | ✅ 成功 | 3 组查询 ×5 条，均为搜索引擎收录结果，**二手聚合，非站内直采** | — |
| 🚫 抖音/小红书站内直采 | 已停用 | 不恢复、不重试（headless DOM 未渲染 + 需登录 + 无 Xvfb） | — |
| 🚫 Reddit (r/LocalLLaMA) | 已停用 | 本机 HTTP 000 网络层阻断 | — |
| 🚫 gh CLI | 未安装 | 改用 curl + api.github.com | — |

---

## 2. 当前运行方案实测表（来自步骤 0 真实数据）

| 项 | 实测值 | 来源 |
|---|---|---|
| 探测端口 | **8080 在线**（首端口命中） | `curl /props /v1/models` |
| model_path | `$HOME/models/Qwen3.6-35B-A3B-Uncensored-Q5_K_P.gguf` | `/v1/models` |
| model_ftype | `Q5_K - Medium`（即清单「模型 A」的 Q5_K_P 变体，非 Q4_K_P） | `/props` + `/v1/models` |
| size | 28,016,404,992 B（≈28.0 GB） | `/v1/models` |
| n_params | 34,660,610,688（34.66B） | `/v1/models` |
| n_embd | 2048 | `/v1/models` |
| n_ctx / n_ctx_train | 262144 / 262144 | `/props` + `/v1/models` |
| total_slots | 1 | `/props` |
| modalities | vision=true, video=true, audio=false | `/props` |
| **speculative（MTP）** | **已启用**：`/slots[0].speculative=true`，params `speculative.types="none,draft-mtp"`；`ps` 命令行 `-md .../Qwen3.6-35B-A3B-MTP-ONLY-Q4_K_M.gguf --spec-type draft-mtp --spec-draft-n-max 2` | `/slots`+`ps` 交叉验证 |
| **MTP 接受率** | **79.9%**（accept 158454 / draft 198228，计数器累计） | `/metrics` |
| KV cache | `q8_0`（`-ctk q8_0 -ctv q8_0`） | `ps` |
| 采样默认 | temp=1.0（slot 当前 0.4）、top_k=20、top_p=0.95、min_p=0.05 | `/props`+`/slots` |
| build_info | `b10824-75147a27e` | `/props` |
| 关键启动参数 | `-ngl 999 -c 262144 -np 1 -b 4096 -ub 1024 --mmproj f16 --context-shift --cache-idle-slots -cms 8192 --cache-ram 16384 --ctx-checkpoints 16 --metrics --host 0.0.0.0 --port 8080` | `ps` |
| MoE 专家缓存 | **未开**（无 `--moe-cache-mib`）→ 待优化 A1 | `ps` |
| 暴露面 | `--host 0.0.0.0`（A0 未收窄，连续 40+ 日） | `ps` |
| 18090 代理 | `mode=passthrough`，upstream=8080 OK；`npu_enabled=true`，`npu_upstream=http://127.0.0.1:8219`（8219 有进程，身份未明，延续监控） | `/health` |
| 模型 C（Qwen3.8-Flash-Next） | **未在线**（`/v1/models` 仅返回模型 A） | `/v1/models` |
| 本机实测 decode | **本次未重测速**（单 slot 避免扰动）；引用 11-04 固化值 **72.41 t/s**（Q5_K_P，短 prompt，temp0）｜`[历史值，待本机验证]` | 11-04 日报 |

---

## 3. minimax h3 专题（专项检查项逐条结论）

> 数据源：本机 `$HOME/drama-series-agent/config.json`（2026-11-12 04:03 修改）+ 进程/端口实测 + 社区共识（P2）。

| # | 检查项 | 实测 | 结论 |
|---|---|---|---|
| B0 | render.backend | `sdcpp` | ✅ 一致（非 ComfyUI） |
| B1 | 主 LLM 8080 与 sd.cpp 不冲突 | 8080 在线、sd-cli 当前空闲（无渲染进程） | ✅ 无冲突 |
| B2 | render 步数 / CFG（draft） | `render.steps=12`, `render.cfg_scale=1.0` | ⚠️ 漂移延续：draft 偏低（社区共识 20-30 步 / CFG 5-8，见 §4/§5） |
| B2' | quality / image 步数 | `image.steps=20`, `image.cfg_scale=4.0` | ✅ 对齐社区正式档（20 步 / CFG 4） |
| B3 | **llm.base_url / model** | `base_url=http://127.0.0.1:18090/v1`, `model=Qwen3.6-35B-A3B-Uncensored-Q5_K_P.gguf` | 🆕 **回退为本地 Qwen3.6 / 18090**（与 11-07~11-11「云端 MiniMax-M3.1-Flash via api.iamhc.cn」记录不符，本次 config 实测为本地） |
| B4 | 画布 / 母版 | `800x448` / `master 1920x1080`, 24fps, crf18, aac192k | ✅ 一致 |
| B5 | sd.cpp bin | `$HOME/sdcpp-git/build-vk4/bin/sd-cli`（84MB, Oct 20 构建）存在 | ✅ 一致（vk4 优于 vk2 6.8%） |
| B6 | 8000 API / 5173 前端 | 8000 监听（root 404，API 正常）、5173 HTTP 200 | ✅ 在线 |
| B7 | 8188 ComfyUI | `8188=000` 无监听 | ✅ 一致（已弃用） |
| B8 | `comfyui.comfyui_url` | `http://127.0.0.1:8188`（config 实测，非空） | ⚠️ 漂移延续（#8）：与 10-20「已清空」记录不符，8188 无监听仅噪音 |
| B9 | `SDCPP_EXTRA_ARGS` | 未在本次读取 `.env`（需复核） | ⏸️ 待复核：`--vae-tiling` 是否仍生效 |
| B10 | gpu.arbiter | `need_gib=64`, `instance_uuid=9770784bb1f940ada5c5890fd003efb3`, `auto_resume=true` | ✅ 一致（qwen 实例暂停/恢复护栏） |
| B11 | 驱动栈 / 后端 | Vulkan RADV STRIX_HALO，Mesa 26.0.8（apt-mark hold 钉死） | ✅ 一致（勿升 26.2.x） |

**专项小结**：9 项零漂移 + 2 项历史漂移（B2 draft 步数/CFG 偏低、B8 comfyui_url 回退 8188）；**今日新增 B3 漂移回退**（llm 从云端 MiniMax 回到本地 Qwen3.6/18090）。

---

## 4. 其他近期关键动态（事实 vs 他人实测值）

**【事实 · 一手源 GitHub】**
- `#32098`（merged 11-11）：`server: fix --cors-origins handling + protect against DNS rebinding` — **直接关联本机 A0（--host 0.0.0.0）暴露面修复**，建议尽快 cherry-pick / 升级。来源：https://github.com/ggml-org/llama.cpp/pull/32098
- `#31418`（merged 11-11）：`vulkan: support batched tensor copy API` — Vulkan 通用优化，利好本机 Vulkan 后端。来源：https://github.com/ggml-org/llama.cpp/pull/31418
- `#32043`（open）：`llama: avoid touching unused graph metadata pages`。来源：https://github.com/ggml-org/llama.cpp/pull/32043
- `#32108`（open）：`Feat/cuda fa kernel override`（CUDA 向，本机无关）。
- gufo v0.31 持续活跃（11-11 多条 serve 修复）→ 模型 C（Qwen3.8-Flash-Next）上游生态活跃。来源：https://github.com/gufo-org/gufo
- kingjones30/strix-halo-quant-lab 11-11 索引 **159 仓库**（同硬件 ROCmFP4 量化基准库，替代 404 的 kingjones777）。来源：https://github.com/kingjones30/strix-halo-quant-lab

**【事实 · HN P1】**
- 「Qwen3.8-27B MTP Q4S head on Q6 quant is faster than q6, f16 slower = acceptance」（11-08）— 佐证 MTP 草稿头量化/采样器对齐对接受率的决定性影响（坐实 #27950）。来源：https://hn.algolia.com/item（search: llama.cpp, 11-08）
- 「Swapping LLMs in Under Two Seconds: A Sleep Mode for Llama.cpp」（11-06）；「TokiRecur – KV-cache recycling launcher」（11-07）。

**【他人实测值 · P2 二手聚合，均待本机验证】**
- **modelfit.io**（Strix Halo 110GB usable 统一内存）：35B-A3B 估 ~50 t/s，120B MoE 估 ~32 t/s，dense 70B ~4 t/s；KV `q8_0` 约减半 fp16 占用。来源：https://modelfit.io/gpu/ryzen-ai-max-395 ｜`[他人实测，待本机验证]`
- **getrigbase / GitHub #31839**（Strix Halo 128GB，Windows，llama.cpp b11401 Vulkan，无 MTP）：Qwen3.6-35B-A3B **61.8 t/s**；Qwen3.5-122B 23.6 t/s。来源：https://github.com/ggml-org/llama.cpp/discussions/31839 ｜`[他人实测，待本机验证]`
- **llamaperf caa3f4f1**（Strix Halo 128GB，Gufo v0.31，Qwen3.8 Flash-Next UD-Q4_K_XL，**q8_0 KV，262144 ctx**）：**41 t/s gen / 1240-1335 t/s prefill / MTP 接受率 70-91%** — 模型 C 对标基准。来源：https://llamaperf.com/report/caa3f4f1 ｜`[他人实测，待本机验证]`
- **llamaperf ebe1134b**（Strix Halo 64GB，Windows，Flash-Next IQ1_M，q8_0 KV，131k）：25-45 t/s（MTP）。来源：https://llamaperf.com/report/ebe1134b ｜`[他人实测]`
- **lpqz.cn Halogen**（Strix Halo 64GB，MoE Q4_K_M）：ctx>8192 速度从 24 掉到 15 t/s，建议 8192 稳妥。来源：http://www.lpqz.cn/news/157158 ｜`[二手聚合]`
- **MiniMax H3 社区共识（多条独立源）**：steps **20-30 正式 / 10-15 草稿**；CFG **5-8**（hqwc 5-8、sheratonhq 5、lpqz 4-7、comfyui 指南 6-9）；VAE 保持 FP8/自带避免精度不匹配；画质词 `sharp focus` 优先；负向加 `text/watermark/logo`。来源：http://www.sheratonhq.com/news/149879、https://www.hqwc.cn/news/1482156.html 等 ｜`[二手聚合，非站内直采]`

---

## 5. 现状 vs 社区同硬件最优对比表

| 维度 | 本机（模型 A Q5_K_P, Vulkan） | 社区同硬件（Strix Halo 35B-A3B） | 社区模型 C 基准（Flash-Next, Gufo） | 差距 / 优先级 |
|---|---|---|---|---|
| decode t/s | 72.41（11-04 引用，temp0）`[历史]` | 61.8（无 MTP, b11401）`[他人]` | 41（含 MTP, 262k ctx）`[他人]` | 本机 35B 已优于社区 35B 无 MTP；**P2** 可试 n-max3 |
| prefill t/s | ~400（9-24 引用）`[历史]` | 未高报 | **1240-1335**`[他人]` | 相对模型 C 基准差 ~3×，**P0**（A2 prefill 短板闭环） |
| 上下文 | 262144（=训练） | 262144 | 262144 | ✅ 持平 |
| KV | q8_0 | q8_0（社区生产共识） | q8_0 | ✅ 已对齐 |
| GTT/显存 | 96 GiB（BIOS UMA） | 96-111 GiB usable | 96-98 GiB | ✅ 持平 |
| 驱动栈 | Mesa 26.0.8（钉死） | 26.2.x / 驱动 32.0.3 | Windows/Mesa 混合 | ⚠️ 本机刻意钉死防回归，**P0 稳定项** |
| build 版本 | b10824（commit 75147a27e） | b11401+ / b12292 上游 | gufo v0.31（≈上游最新） | **落后上游 ≈1468 build（+37/日）**，**P1**（C2 升级） |
| MTP 接受率 | 79.9%（n-max2） | 未报 | 70-91%（n-max7） | 可试 n-max3，**P2**（A4）+ #27950 人核 |
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

# B9 复核：确认 .env 仍含 SDCPP_EXTRA_ARGS="--vae-tiling"（VAE tiling 防 OOM）
grep -n "SDCPP_EXTRA_ARGS" $HOME/drama-series-agent/.env

# Mesa 钉死复核：确认 6 包仍 hold，防止 apt upgrade 升到 26.2.x
apt-mark showhold | grep -E "mesa|libgbm"   # 应列出 6 个包
```

### ③ 需重启或重建（cherry-pick / 升级二进制；先备 mesa deb 再动）
```bash
# C2 升级到上游 b12292（落后 1468 build，含 #32098 安全修复、#31418 vulkan 优化）：
#   前置（三步走，缺一不可）：
#   1) 备份当前可用 mesa deb：apt-get download mesa-vulkan-drivers libgl1-mesa-dri libglx-mesa0 libegl-mesa0 mesa-libgallium libgbm1
#   2) 升级后先用 vulkaninfo 验证枚举正常，再重启业务
#   3) 升级本机 fork 须 git pull + 重建（fork 落后多，建议先 git log 确认无本地未提交改动）
cd $HOME/llama-qwen4exp-rocmfpx && git status --short   # 确认干净后再 pull
cmake --build build-vk4 --target llama-server -j16          # 重建（fork 用此目标，避免 all 被 tests 拖垮）

# C1 cherry-pick 关键 PR（在升级前若只想取安全修复）：#32098(CORS/DNS)、#31418(vulkan batched copy)
#   用 mcp__github 或 git cherry-pick <合并 commit>； cherry-pick 后同样重建 build-vk4。
```

---

## 7. 风险与验证

- **🔴 MTP 输出质量需人工核对（llama.cpp #27950）**：本机接受率 79.9% 仅表征「目标模型接受草稿」比例，**不证明语义质量无损**。社区（deepu105）已验证采样器不对齐 drafter 时接受率 59.6%→45.7% 且墙钟 2.8×。建议：用固定 temp=0 跑 8K/32K/64K 三档中文续写，人工比对开启/关闭 MTP 的输出差异。**连续 30+ 日未做，优先级 P1。**
- **Vulkan NaN 监控（#31509）**：本机 Vulkan 后端，留意 `/metrics` 或渲染日志中 NaN/inf；出现即回退并检查上游修复。
- **Mesa 26.0.8 钉死**：26.2.x 在本机（gfx1151）会导致 Vulkan 完全不可用（已立硬约束）。任何系统级驱动升级必须先备 deb + vulkaninfo 验证。
- **暴露面 A0**：`--host 0.0.0.0` 已持续 40+ 日；上游 #32098 修了 CORS/DNS rebinding，但仍应收窄到 127.0.0.1。
- **模型 C 离线**：Qwen3.8-Flash-Next 未在线，社区基准（41 t/s / 1240-1335 prefill）仅作对标，本机未实测。

---

## 8. 今日相对昨日（11-11）的新增项

✅ **有实质增量，非注水：**

1. **8080 连续在线稳定**（11-11 在线 → 今日仍在线，模型 A Q5_K_P；非 11-05~07 离线态）。
2. **MTP 接受率回升**：79.4%（11-11）→ **79.9%**（今日，`/metrics` 158454/198228）。
3. **上游推进 +37 build**：b12255 → **b12292**（11-11），本机落后 ≈1468 build。
4. **🆕 新 PR #32098（merged）**：`server: fix --cors-origins + DNS rebinding` — 直接关联 A0 暴露面修复，建议纳入 C2 升级。
5. **🆕 B3 漂移回退**：config.json 实测 `llm` = **本地 Qwen3.6 / 18090**（model=Qwen3.6-35B-A3B-Uncensored-Q5_K_P.gguf），与 11-07~11-11「云端 MiniMax-M3.1-Flash」记录不符。
6. **P2 同硬件他人实测补充**：modelfit（110GB usable / 35B~50t/s）、getrigbase #31839（35B-A3B 61.8 t/s 无 MTP）、llamaperf Flash-Next（41 t/s + 1240-1335 prefill，模型 C 基准）。
7. **MiniMax H3 社区共识坐实**（多条独立源）：steps 20-30 / CFG 5-8，印证本机 draft（steps=12 / cfg=1.0）偏低（B2 漂移延续）。
8. **gufo 11-11 极活跃**（serve RFC9112 / JSON 16 位封顶）→ 模型 C 生态利好；kingjones30 11-11 索引 159 仓库。

**延续未解（不变）**：A0 host 收窄(40+日) / A1 MoE 缓存 / A2 prefill 短板 / A4 n-max3 + #27950 人核(30+日) / B2 draft 步数 CFG 偏低 / B8 comfyui_url 回退 / C2 升级 b12292（先备 mesa deb）/ Mesa 26.0.8 钉死 / #31509 Vulkan NaN 监控。
