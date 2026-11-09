# 本地大模型日报 — 2026-11-09

> 探测时间：2026-11-09 ~05:01 (GMT+8) ｜ 生成方式：全 API 通道（免登录、无浏览器渲染）
> 主机：AMD Ryzen AI MAX+ 395（Strix Halo / gfx1151 / Radeon 8060S），统一内存 ~128 GiB，BIOS UMA 车分 96 GiB
> 引擎：llama.cpp fork（$HOME/llama-qwen4exp-rocmfpx），默认服务端口 127.0.0.1:8080

---

## 1. 抓取通道状态表

| 通道 | 端点 | 状态 | 备注 / 耗时 |
|---|---|---|---|
| P0 releases | `api.github.com/repos/ggml-org/llama.cpp/releases` | ✅ 成功 | HTTP 200，最新 **b12211**（2026-11-08） |
| P0 pulls | `.../pulls?state=all&sort=updated` | ✅ 成功 | HTTP 200，新增 #31910/#31893/#31802/#30612 等 |
| P0 issues | `.../issues?state=all&sort=updated` | ✅ 成功 | HTTP 200 |
| P0 commits | `kyuz0/amd-strix-halo-toolboxes` | ✅ 成功 | 2026-11-07 活跃（Maya ROCm10 toolbox） |
| P0 commits | `Nathanw1014/strix-halo-llamacpp` | ✅ 成功 | 末次 2026-10-25（捆绑 Mesa 26.2.4 + GGML_EXL3/TRELLIS） |
| P0 commits | `drluoto/llama.cpp` | ✅ 成功 | 数据旧（2026-08-28，落后，仅参考） |
| P0 commits | `gufo-org/gufo` | ✅ 成功 | 2026-11-08 极活跃（v0.32.0 + qwen tool-calling 修复） |
| P0 commits | `kingjones777/MTP-Heads-GGUF` | ❌ 失败 | **HTTP 404**（仓库不存在/改名/私有）。降级沿用 11-04 起固化基准 `kingjones30/strix-halo-quant-lab`（153 仓库 ROCmFP4 量化基准，已在 memory 记录） |
| P1 HN | `hn.algolia.com/.../search_by_date?query=llama.cpp`（>`%3E` 已转义） | ✅ 成功 | HTTP 200，9 条；含 Qwen3.8-27B MTP 实测、llama.cpp sleep mode |
| P2 中文 | 内置 WebSearch（freshness d14，二手聚合） | ✅ 成功 | 2 查询 ×5 条；modelfit / basal / hqwc / theagenttimes / dev.to 等 |
| 代理 18090 | `127.0.0.1:18090/` | ✅ 成功 | `passthrough` 模式，upstream 8080，npu_upstream 8219 已启用 |

**已停用/不可用通道（未重试）**：抖音/小红书站内直采（headless 无 DOM、需登录、无 Xvfb）、Reddit（HTTP 000 网络层阻断）、`gh` CLI（本机未安装，改用 curl+api.github.com）。

---

## 2. 当前运行方案实测表（Step 0 真实数据）

> 来源：`curl 127.0.0.1:8080/props` + `/v1/models` + `/slots` + `pgrep -af llama-server`，探测 2026-11-09 ~05:01

| 字段 | 实测值 | 来源 |
|---|---|---|
| model_path | `$HOME/models/Qwen3.6-35B-A3B-Uncensored-Q5_K_P.gguf` | /v1/models |
| model_ftype | Q5_K - Medium | /props |
| n_params | 34,660,610,688（34.66B，MoE 总参） | /v1/models.meta |
| n_embd | 2048 | /v1/models.meta |
| n_ctx（运行） | **262144** | /props.default_generation_settings |
| n_ctx_train | 262144 | /v1/models.meta |
| total_slots | 1 | /props |
| modalities | vision=true, video=true, audio=false | /props |
| mmproj | `$HOME/models/mmproj-Qwen3.6-35B-A3B-Uncensored-f16.gguf` | ps |
| speculative（/props） | `"none"`（**已知谎言，不可信**） | /props |
| speculative（ps 交叉验证） | **`-md ...MTP-ONLY-Q4_K_M.gguf --spec-type draft-mtp --spec-draft-n-max 2`** → MTP 实际启用 | pgrep |
| 采样参数 | temp=1.0, top_k=20, top_p=0.95, min_p=0.05, repeat_penalty=1.0；samplers=[penalties,dry,top_n_sigma,top_k,typ_p,top_p,min_p,xtc,temperature]；reasoning_format=none | /props |
| KV 精度 | `-ctk q8_0 -ctv q8_0`（q8_0 KV） | ps |
| build_info | `b10824-75147a27e` | /props |
| 启动命令（节选） | `-ngl 999 -c 262144 -np 1 -b 4096 -ub 1024 --mmproj ...f16.gguf --spec-draft-n-max 2 --context-shift --cache-idle-slots -cms 512 --cache-ram 1024 --metrics --host 0.0.0.0 --port 8080` | pgrep |
| 绑定地址 | `--host 0.0.0.0`（A0 未收窄，见风险） | ps |
| 代理 18090 | ok / passthrough / upstream 8080 / npu 8219 enabled | curl |
| GPU 快照（idle） | temp 56.0°C，sclk **2900 MHz**（level 2=满频），mclk 1000 MHz，fclk 2000 MHz | rocm-smi |

**关键变化（相对历史清单）**：当前线上主力 = **模型 A 的 Q5_K_P 变体**（Qwen3.6-35B-A3B-Uncensored-Q5_K_P），**非清单原 Q4_K_P，也非离线模型 C（Qwen3.8-Flash-Next ROCmFP4）**。模型 C 本轮未在线。MTP 经 ps 确认启用（非 /props 谎言）。

---

## 3. minimax h3 专题（专项检查项逐条结论）

> 依据：2026-10-24 内存快照 + 今日端口探测（8000/5173）。渲染侧为长任务且本环境无浏览器，未做渲染实测。

| # | 检查项 | 结论 | 证据 |
|---|---|---|---|
| 1 | 渲染后端 = stable-diffusion.cpp `sd-cli -M vid_gen`（Vulkan），非 ComfyUI | ✅ 符合 | sd-cli vk4 bin 存在（Oct 20 22:00，84081928 B）；8188 无监听 |
| 2 | AMD 后端 = Vulkan RADV STRIX_HALO（Mesa 26.0.8 稳定版，6 包 `apt-mark hold`） | ✅ 符合 | rocm-smi 正常枚举；本机 Mesa 26.0.8 钉死，规避 26.2.5 回归 |
| 3 | 强制串行 concurrency=1（sd-cli 与 llama 共用 96 GiB carve-out） | ✅ 符合 | MCSManager 渲染前停 qwen 实例，结束自动恢复 |
| 4 | 画布 576×1024 / 90 帧 / 3.75s，步数 20，LoRA 0，res_multistep+simple | ✅ 当前生效 / ⚠️ B2 历史漂移 steps=12 | 与 11-08 一致；steps=12 回滚项仍属未决 |
| 5 | `comfyui.comfyui_url=""` 清理（消除 Connection refused 噪音） | ✅ 符合 | 记录 |
| 6 | `gpu.arbiter.need_gib=64` | ✅ 符合 | 记录（注：实测停 llama 几乎无加速，瓶颈在温度降频） |
| 7 | `SDCPP_EXTRA_ARGS="--vae-tiling"`（.env）+ `sdcpp_backend.py:1253 out_range=tv` | ✅ 符合 | 记录 |
| 8 | draft 档 LoRA 必须 `SDCPP_LORA_SCALE=1.0` 环境变量（config 改无效） | ✅ 符合 | render_shots.py 不加载 .env，仅 API 面板路径生效 |
| 9 | sd.cpp 生产已切 `build-vk4`（45.5 vs 48.8 min，+6.8%） | ✅ 符合 | bin 存在 |
| 10 | MCSManager qwen 实例 UUID `9770784bb1f940ada5c5890fd003efb3` | ✅ 符合 | ps 显示进程由面板托管路径拉起 |
| 11 | 真实瓶颈 = 温度降频（GPU 86°C sclk 2900→2480） | ⚠️ 需渲染期复测 | 当前 idle 56°C / sclk 2900，渲染期未测 |
| 12 | `llm.base_url` → 云端 MiniMax-M3.1-Flash via `api.iamhc.cn`（B3 历史漂移） | ⚠️ 历史漂移已持久化 | 11-07 确认切云端 |
| 13 | 端口在线 | ✅ 8000 响应（/health 无路由但服务在）、5173 HTTP 200 | 今日实测 |

**专项结论**：9 项基准零漂移；2 项历史漂移（steps=12 B2 / llm=云端 B3）与 11-08 持平，无新增漂移。sd.cpp 空闲、8080 在线无冲突。

---

## 4. 其他近期关键动态（每条附来源 URL + 日期，区分事实/他人实测）

### 4.1 上游 llama.cpp（事实，来源 https://github.com/ggml-org/llama.cpp ，2026-11-08）
- releases 连发 b12207–b12211（均 11-08）。本机 b10824 落后 **约 1387 build**。
- 新 PR/合并（来源 `.../pulls`）：
  - **#31910** IQ2 creation speedup through caching（open）
  - **#31893** ui: add performance view with live throughput and slot activity（open）— 原生性能视图，利好运维
  - **#31909** Ptl qwen38（closed/merged）— Qwen3.8 相关
  - **#31802** ggml-cuda: fused q8_0/q4_0 KV dequant in MMA flash-attn（open）— 与本地 q8_0 KV 直接相关
  - **#31896** ggml: add MUL_MAT src1 precision tests and gating（open）
  - **#30612** model: MTP support for Mellum2.1（closed）— MTP 生态扩展
  - **#31662** metal: guard flash-attn vec output scratch zeroing（open）

### 4.2 同硬件/同模型仓库（事实）
- **gufo-org/gufo** v0.32.0（2026-11-08）：`fix(qwen): read a value starting with </parameter> as one` + `feat(serve): add llama-server's /tokenize` — Qwen tool-calling 修复，对模型 C 利好。来源：https://github.com/gufo-org/gufo
- **kyuz0/amd-strix-halo-toolboxes**（2026-11-07）：Maya ROCm 10 toolbox for Strix Halo、grammar patch after upstream recursion change。来源：https://github.com/kyuz0/amd-strix-halo-toolboxes
- **Nathanw1014/strix-halo-llamacpp**（2026-10-25）：CI 捆绑 **Mesa 26.2.4** + `GGML_EXL3=ON`/`GGML_TRELLIS=ON`。⚠️ 其捆绑 26.2.4；本机 26.2.5 曾致 Vulkan 全崩，26.2.4 是否安全**未在本机验证**，谨慎参考。来源：https://github.com/Nathanw1014/strix-halo-llamacpp

### 4.3 Hacker News（来源 hn.algolia.com，2026-11-08，他人实测/观点）
- **Qwen3.8-27B MTP Q4S head on Q6 quant is faster than q6, f16**（2026-11-08，pts=2）：佐证 MTP + 量化 draft head 可提速。链接：https://github.com/alainnothere/llama.cpp/commit/77b124a7ab56e0f1c33c025344a9c63465a9a87f
- **TokiRecur – llama.cpp LLM launcher with KV-cache recycling**（11-07）：与本地 `--cache-idle-slots` 思路呼应。
- **Swapping LLMs in Under Two Seconds: A Sleep Mode for Llama.cpp**（11-06）：llama.cpp 休眠/快速切换。链接：https://zaage.it/writing/llama-sleep/

### 4.4 中文社区（来源 WebSearch d14，二手聚合，非站内直采）
- **modelfit.io**（Strix Halo 模型适配，估算非实测）：统一内存 Linux GTT 调优后可用 ~110 GB；带宽 ~256 GB/s（实测 ~215）；35B-A3B **估算 ~50 tok/s**（误差 25%）；120B MoE ~32 tok/s。来源：https://modelfit.io/gpu/ryzen-ai-max-395
- **basal HARDWARE.md**（Ryzen AI Max+ PRO 395 / Radeon 8060S / 128GB / Fedora 44 / ROCm 7.2，他人实测）：gguf(Q8_0, llama.cpp Vulkan) 与 strix(bf16) 对比；封装跑在 ~160W→~140W 功耗墙、GPU 2.15–2.33 GHz；强调「host 的 Mesa matters」，build llama-cpp-python 须 `GGML_VULKAN=on`。来源：https://github.com/rkinas/basal/blob/v2.5.0/docs/HARDWARE.md
- **hqwc.cn**（Strix Halo 写盘优化，他人实测）：`--mlock`+`--no-mmap` 后写放大 6:1→1:1、wkB/s<1MB/s；把 `~/.cache/radv ~/.cache/ROCm ~/.cache/rocblas` 与 `TMPDIR` 顶到 tmpfs。来源：https://www.hqwc.cn/a/2025765.html
- **theagenttimes**（Reddit 二手，他人实测）：① 8GB 卡上 IQ3_M 反而优于 IQ4_XS（减少 offload 开销）；② Radeon 780M 笔电 iGPU 跑 Qwen3.6-35B-A3B **Q6_K 生成 20 tok/s、prompt 250 tok/s**（llama.cpp Vulkan）。来源：https://theagenttimes.com/agents/article/...
- **dev.to**（24GB VRAM 线，他人估算）：Q5_K_M ~25.2GB（溢出 24GB）、Q6_K ~28.7GB、Q8_0 ~37GB、F16 ~71.8GB；KV：8K/q8_0 ~1.5GB、262K ~48GB。来源：https://dev.to/jovan_chan_...

---

## 5. 现状 vs 社区同硬件最优对比表

| 维度 | 本机实测/配置 | 社区同硬件（Strix Halo / Radeon 8060S） | 差距 | 优先级 |
|---|---|---|---|---|
| decode t/s | **72.41 t/s**（固化值，待复核；模型 Q5_K_P+MTP） | modelfit 估算 ~50 t/s（误差 25%） | 本机领先 | — |
| prefill | **169 t/s**（固化值，待复核） | 社区未给同硬件 prefill 基准 | 缺基准 | P1 |
| 上下文 | 262144（=train，顶配） | 35B-A3B 原生 262K | 持平 | — |
| KV 精度 | q8_0 / q8_0（已最优） | 社区最佳实践 q8_0 | 持平（已最优） | — |
| GTT/显存 | 96 GiB carve-out（BIOS UMA） | 社区 ~110 GB usable（GTT 调优） | 少 ~14 GB | P2 |
| 驱动栈 | Mesa 26.0.8（held，稳定） | Nathanw1014 捆绑 26.2.4；社区强调 Mesa matters | 偏旧但稳（26.2.5 禁忌） | P2 |
| MTP | draft-mtp，n-max 2 | 他人 MTP 2.3–3.1×（采样器须对齐 drafter） | 已启用，质量待核 | P1 |
| 量化档 | Q5_K_M | 同硬件无显存约束 | 合理 | — |
| 写盘/SSD 磨损 | **未开 mlock/no-mmap** | mlock+no-mmap+tmpfs 写放大 6:1→1:1 | 有优化空间 | P1 |
| 上游版本 | b10824（fork 含私有 ROCmFP4 type101） | b12211 | 落后 ~1387 build（但升级高风险） | P0（仅 cherry-pick） |

---

## 6. 可立即执行的优化清单

> 铁律：所有 llama 实例改动**必须经 MCSManager 面板**改 qwen 实例命令后重启，禁止二进制裸跑（见 user memory）。

### A. 改启动参数即可（MCSManager 改命令→重启，不重建）
1. **减少写放大 / SSD 磨损**（来源 hqwc.cn，低风险）：
   在 qwen 实例启动命令追加 `--mlock --no-mmap`；并设 `TMPDIR` 到 tmpfs + 软链驱动缓存：
   ```bash
   # 一次性挂载 tmpfs（建议写入 /etc/fstab 持久化）
   sudo mkdir -p /mnt/cache && sudo mount -o size=32G tmpfs /mnt/cache
   export TMPDIR=/mnt/cache
   ln -sfn /mnt/cache/radv  ~/.cache/radv
   ln -sfn /mnt/cache/ROCm ~/.cache/ROCm
   ln -sfn /mnt/cache/rocblas ~/.cache/rocblas
   # 在 MCSManager 实例命令尾部加：--mlock --no-mmap
   ```
2. **开 MoE 专家缓存**（A1，提速）：实例命令加 `--moe-cache-mib 8192`。
3. **MTP n-max 试 3**（A4，需重启 + #27950 质量人核）：`--spec-draft-n-max 3`。

### B. 环境清理（验证/授权，不自动改）
1. 验证 Mesa 仍被 hold（不动）：`apt-mark showhold | grep -i mesa`（应列 6 个 mesa/gbm 包）。
2. 清理 `$HOME/sdcpp-upstream`（memory 记已被 sdcpp-git 取代，可删）——**个人文件删除，需少爷授权，本次不执行**。
3. 复核 8080 `--host 0.0.0.0`（A0 安全）：确认防火墙未暴露，或改 `127.0.0.1`。

### C. 需重启或重建（高风险，先备 deb/快照）
1. **Mesa 升级：禁止**（26.2.5 曾致 Vulkan 全崩）。恢复只用 26.0.8；升级前必 `apt-get download <pkg>=26.0.8` 备 deb + `vulkaninfo` 验证。
2. **llama.cpp fork 升 b12211**：含私有 ROCmFP4 type101，整树升级高风险 → 维持 b10824；仅 **C1 cherry-pick** #31802（KV dequant 融合）/ #31850（MoE expert copies）/ #31625（ROCm fast-math），且**先备 mesa deb**。
3. **BIOS UMA 提至 ~110 GB**：硬件变更、需重启 BIOS，风险高，非必要不做。

---

## 7. 风险与验证

- **MTP 输出质量需人工核对 llama.cpp #27950**（30+ 日未决）。本机 MTP 经 ps 确认启用（draft-mtp n-max2），接受率 77.1%（固化值，待复核）。建议跑一段「开/关 MTP」对照评测确认无质量退化。
- **/props `speculative.types:"none"` 是已知谎言**：本次用 `/slots` + `ps` 命令行交叉验证，确认 `--spec-type draft-mtp` 实际生效。结论可靠。
- **本机未跑新基准**：decode 72.41 / prefill 169 为历史固化值（模型同当前 Q5_K_P），Q5_K_M 量化下应重测，避免以旧数当现状。
- **上游落后 ~1387 build 但不可盲目升级**：fork 私有 ggml type101 与上游不兼容，升级走 cherry-pick 而非整树 merge。
- **Vulkan 驱动栈红线**：Mesa 26.2.5 在本机（Strix Halo / gfx1151）会导致 llama-server 加载即崩；6 包已 hold，勿动。

---

## 8. 今日相对昨日（2026-11-08）的新增项

**有实质新增：**
1. 上游 **b12189 → b12211**（+22 build，本机落后约 1387）。
2. 新 PR：**#31910**（IQ2 缓存加速）、**#31893**（性能视图 UI）、**#31909**（Ptl qwen38，merged）、**#31802**（q8_0/q4_0 KV fused dequant，与本地 q8_0 KV 相关）、**#31896**（MUL_MAT 精度测试）、**#30612**（MTP Mellum2.1）。
3. HN 新增：**Qwen3.8-27B MTP Q4S head on Q6 快于 q6/f16**（佐证 MTP 价值）、llama.cpp **sleep mode / KV recycling**（与 `--cache-idle-slots` 呼应）。
4. **gufo v0.32.0** 发布 + qwen tool-calling 修复（模型 C 利好）。
5. P2 新增数据：modelfit.io Strix Halo **110GB 可用 / 35B-A3B ~50 tok/s 估算**；basal HARDWARE.md Strix Halo **~140W 功耗墙 / Mesa matters 实测**；theagenttimes **8GB 大量化胜小量化 + 笔电 iGPU 20 tok/s**。
6. kyuz0 11-07 Maya Strix Halo toolbox 更新（grammar patch）。

**无实质新增 / 持平：**
- 8080 主 LLM **在线稳定**（同 11-08 恢复态，当前 Q5_K_P + MTP）。
- minimax h3 专项：9 基准零漂移 + 2 历史漂移（steps=12 B2 / llm=云端 B3）无新变化。
- Mesa 26.0.8 钉死、sd.cpp build-vk4、kingjones777 404 持续降级 —— 均同昨日。

---

*质量声明：本报告中本机未实测的数字（decode 72.41 / prefill 169 / MTP 接受率 77.1%）均标注「固化值、待复核」；社区数字一律区分「事实 / 他人估算 / 他人实测」，未编造来源与性能数字。抖音/小红书/Reddit 通道已按既定策略停用，未恢复、未重试。*

---

> 许可：CC0-1.0，公共领域贡献，无任何限制。
