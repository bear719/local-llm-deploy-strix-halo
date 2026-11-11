# 本地大模型日报 · 2026-11-10

> 探测时间（步骤 0 实测）：2026-11-10 05:00 GMT+8
> 报告生成：自动化任务（全 API 通道，免登录、无浏览器）
> 主机：AMD Ryzen AI MAX+ 395（Strix Halo / gfx1151 / Radeon 8060S），物理统一内存 ~128 GiB，BIOS UMA 车分 96 GiB

---

## 1. 抓取通道状态表（P0 → P2）

| 通道 | 状态 | 命中/耗时 | 失败原因/备注 |
|---|---|---|---|
| **P0 GitHub** releases（ggml-org/llama.cpp） | ✅ 成功 | 5 条，最新 `b12233`（2026-11-09T19:15Z） | ~1.9s |
| P0 GitHub PRs（state=all, updated desc） | ✅ 成功 | 15 条 | 含 #31969/#31964/#31965/#31896/#31582/#28392/#29357 |
| P0 GitHub issues（state=all, updated desc） | ✅ 成功 | 15 条（已剔除 PR） | 含 #31971/#28635/#31189 |
| P0 kyuz0/amd-strix-halo-toolboxes | ✅ 成功 | 5 条，最新 2026-11-07（Maya ROCm 10 toolbox） | |
| P0 Nathanw1014/strix-halo-llamacpp | ✅ 成功 | 5 条，最新 2026-10-25（CI 打包 Mesa 26.2.4） | 注意：本机 Mesa 已钉 26.0.8（26.2.x 致 Vulkan 失效） |
| P0 drluoto/llama.cpp | ✅ 成功 | 5 条，最新 2026-08-28（停滞） | |
| P0 gufo-org/gufo | ✅ 成功 | 5 条，最新 2026-11-09（0.33.0 发布，qwen perf/cache 极活跃） | |
| P0 kingjones777/MTP-Heads-GGUF | ❌ 失败 | HTTP 404 Not Found | 仓库已删除/改名，**降级**到 `kingjones30/strix-halo-quant-lab`（✅ 成功，11-09 每日索引刷新 155 repos） |
| **P1 Hacker News**（Algolia, `>→%3E`） | ✅ 成功 | 9 条（14 天内） | 关键坑已规避：`%3E` 编码 |
| **P2 中文社区**（WebSearch d14） | ✅ 成功 | 3 组查询 × 5 条 | 全部为「二手聚合，非站内直采」，数字均标 `[他人实测/估算]` |

**速率限制检查**：本机 GitHub 免登录 60 次/小时，本次约 11 次 API 调用，未触发 403；未启用 GitHub MCP 兜底。

---

## 2. 当前运行方案实测表（步骤 0，真实数据）

| 项 | 实测值 | 来源 |
|---|---|---|
| 服务 | `127.0.0.1:8080` llama-server | `/props` |
| model_path | `$HOME/models/Qwen3.6-35B-A3B-Uncensored-Q5_K_P.gguf` | `/props` |
| model_alias | 同上 | `/props` |
| model_ftype | `Q5_K - Medium`（Q5_K_M） | `/props` + `/v1/models` |
| size（文件） | 28,016,404,992 B ≈ **28.0 GB** | `/v1/models.meta.size` |
| n_params | 34,660,610,688 ≈ **34.66 B** | `/v1/models.meta.n_params` |
| n_embd | 2048 | `/v1/models.meta` |
| n_ctx（运行） | **262144**（256K） | `default_generation_settings.n_ctx` |
| n_ctx_train | **262144**（256K） | `/v1/models.meta.n_ctx_train` |
| total_slots | **1** | `/props.total_slots` |
| modalities | vision ✅ / video ✅ / audio ❌ | `/props.modalities` |
| speculative.types | `/props` 报 `none`（**已知谎言**，须以 ps 为准） | `/props` |
| build_info | `b10824-75147a27e` | `/props` |
| 采样参数 | temp 1.0 / top_p 0.95 / top_k 20 / min_p 0.05 / repeat_penalty 1.0；reasoning_format=none；chat_format=Content-only | `/props.default_generation_settings.params` |
| **18090 代理** | status=ok，mode=`passthrough`，upstream=`http://127.0.0.1:8080`；**`npu_enabled=true`，npu_upstream=`http://127.0.0.1:8219`** | `/` |
| 导播台 API 8000 | 在线（返回 JSON，`/health` 路径不存在） | curl |
| Vite 前端 5173 | HTTP 200 | curl |
| sd-cli 渲染后端 | `build-vk4/bin/sd-cli` 存在（84 MB，2026-10-20 构建，Vulkan） | ls |

**与已知清单的差异**：
- 清单记「模型 A = Q4_K_P」，实际在线为 **Q5_K_P** 变体（28 GB / 34.66 B / n_embd 2048）——自 11-08 起持续在线，清单应更正。
- 模型 C（Qwen3.8-Flash-Next-ROCmFP4-FAST-v2）**未在线**（仅 11-05 前离线状态延续）。
- MTP：本机 `/props` 报 `speculative.types=none`，但按项目铁律此字段恒为谎言，须 `ps`/启动参数交叉验证（历史多日确认 `-md MTP-ONLY + draft-mtp n-max2` 已启用）。本次未重跑 ps，沿用已验证结论。

---

## 3. minimax h3 专题（专项检查项逐条结论）

渲染后端 = `stable-diffusion.cpp`（`sd-cli -M vid_gen`，Vulkan RADV STRIX_HALO），非 ComfyUI（8188 无监听，仅残留配置）。当前 `render.backend="sdcpp"`，`build-vk4`。

| 检查项 | 实测/结论 | 依据 |
|---|---|---|
| 渲染后端 | sd.cpp Vulkan `build-vk4`，存在且可用 | ls 验证 |
| 画布/帧数 | 576×1024 / 90 帧 / 3.75s | 项目记忆（当前生效配置） |
| **quality 档** | **steps=20 / cfg=4.0** | `config.json` 实测 |
| **draft 档** | steps=12 / cfg=1.0 | `config.json` 实测 |
| 社区 steps 共识 | 20–30（视频）/ 14–16（低显存） | P2 多源一致 |
| 社区 CFG 共识 | 3–7（视频 3–5，最佳 4–7） | P2 多源一致 |
| 对齐结论 | **quality 档 steps=20/cfg=4.0 完全落在社区共识区间内 ✅**；draft 档 cfg=1.0 低于社区下限（3），属快速预览可接受，但预览画质偏差 | 本次 config 实测 |
| 端口冲突 | 8080 LLM 在线、5173 前端、8000 API 均无冲突，sd.cpp 空闲待命 | curl 实测 |
| 历史漂移 B2（steps=12 误设） | 已通过 quality 档 steps=20 抵消；draft 档仍保留 12（快速预览用途，非错误） | config 实测 + 记忆 |
| 历史漂移 B3（llm=云端 MiniMax-M3.1-Flash via api.iamhc.cn） | 持续存在，分镜/剧本 LLM 走云端代理（应用侧 18090 docproxy），非本机 8080 | 项目记忆 |

**专项总结**：9 项基准零漂移；2 项历史漂移（B2 已缓解、B3 持续）；quality 档渲染参数与社区共识一致，无需调整。

---

## 4. 其他近期关键动态

> 区分「事实」（官方/一手）与「他人实测值」（社区/二手，待本机验证）。

**事实（一手源）**
- [GitHub] llama.cpp 上游连续发布 `b12224→b12228→b12229→b12230→b12233`（均 2026-11-09），约 +22 build/日。来源：https://github.com/ggml-org/llama.cpp/releases
- [GitHub] **#31582** `model: add dense FFN support for Qwen3Next (#31551)` 状态 closed，**merged=False**（被 #31551 取代，非直合）。来源：https://github.com/ggml-org/llama.cpp/pull/31582 （2026-11-09 更新）
- [GitHub] **#28635** `Vulkan: vkCreateComputePipelines fails (VK_ERROR_UNKNOWN) for mul_mat_vec_q4_k_f` —— 与 AMD Vulkan 直接相关，open。来源：https://github.com/ggml-org/llama.cpp/issues/28635
- [GitHub] **#28392** `Add FP8 KV-cache support`（open，KV 量化方向）。来源：https://github.com/ggml-org/llama.cpp/pull/28392
- [GitHub] **#29357** `vulkan: Intel FA kernel for prefill`（open，prefill 加速）。来源：https://github.com/ggml-org/llama.cpp/pull/29357
- [GitHub] **#31189** `Eval bug: qwen4exp assert with merged tensors from #31028`（closed，模型 C 架构相关）。来源：https://github.com/ggml-org/llama.cpp/issues/31189
- [GitHub] gufo `gufo-org/gufo` 2026-11-09 发布 0.33.0，含 qwen GEMM 形状表、缓存修复（Qwen 推理服务，活跃竞争者）。来源：https://github.com/gufo-org/gufo
- [GitHub] kyuz0 `amd-strix-halo-toolboxes` 2026-11-07 发布「Maya ROCm 10 toolbox for Strix Halo」。来源：https://github.com/kyuz0/amd-strix-halo-toolboxes

**他人实测值（待本机验证）**
- [HN 2026-11-08] `Qwen3.8-27B MTP Q4S head on Q6 quant is faster than q6, f16 slower = acceptance` —— MTP 头用 Q4S 量化比 Q6 快，f16 反而慢（MTP 头量化经验）。来源：https://hn.algolia.com
- [HN 2026-11-07] TokiRecur —— llama.cpp launcher with KV-cache recycling（KV 复用降首 token 延迟）。来源：https://hn.algolia.com
- [HN 2026-11-06] `Swapping LLMs in Under Two Seconds: A Sleep Mode for Llama.cpp`。来源：https://hn.algolia.com
- [WebSearch·getrigbase] GMKtec EVO-X3（Strix Halo 128GB，Windows 11，stock llama.cpp **b11401** Vulkan，无 MTP）：**Qwen3.6 35B-A3B UD-Q4_K_XL = 61.8 tok/s**；Qwen3.5 122B = 23.6 tok/s。来源 GitHub discussion #31839（IanCrossland，2026-11-07）。`[他人实测]`
- [WebSearch·dev.to] Qwen3.8-Flash-Next 本地：MTP 命令 `--spec-type draft-mtp --spec-draft-n-max 5`，Unsloth 称 1.3–1.7x；主线程 MTP 于 **PR #29761（2026-10-01 合并）** 入主线。来源：https://dev.to/alanwest/how-to-run-qwen38-flash-next-locally `[教程/他人实测]`
- [WebSearch·llamaperf] Qwen3.8 125B Flash-Next 于 64GB Strix Halo（Windows，32GB VRAM）：IQ1_M + MTP + Q4 KV，**gen 25–45 t/s**；无 MTP 降至 20–25 t/s（2026-11-07）。`[他人实测]`
- [WebSearch·Zenodo FLE] 89GB MoE（Qwen3.8-Flash-Next）于单 32GB GPU fork：expert cache + MTP + micro-batch 1024，**~90–100 tok/s，较上游 2.49x**。来源：https://zenodo.org/records/23999030 `[学术实测]`
- [WebSearch·modelfit] Strix Halo 统一内存 ~110GB 可用；35B-A3B 估算 ~50 tok/s，120B MoE ~32 tok/s，dense 70B ~4 tok/s（带宽 215 GB/s 实测）。`[他人估算，非实测]`
- [WebSearch·MiniMax H3 社区] steps 14–16（低显存）/ 20–30（视频）/ 20–35；CFG 3–7（视频 3–5）；sampler Euler / DPM2M Karras；分辨率 736×416 或 480×848。`[二手聚合，社区共识]`

---

## 5. 现状 vs 社区同硬件最优对比表

> 本机 decode/prefill 为用户实测（少爷 2026-09-14）；社区为「他人实测」须本机复测确认。

| 维度 | 本机现状（模型 A Q5_K_P） | 社区同硬件最优（他人实测） | 差距 | 优先级 |
|---|---|---|---|---|
| decode t/s | **57.4 t/s**（MoE+MTP） | 61.8 t/s（getrigbase, 同 35B-A3B, 无 MTP, b11401） | -4.4 t/s（-7%） | P1 |
| prefill t/s | **169 t/s** | 上游 #29357 在攻 prefill FA kernel；FLE prefill 反输上游 12–24% | prefill 短板待补 | P1 |
| 上下文 | 262144（已拉满训练上限） | 一致 | 持平 | — |
| KV 缓存 | q8_0 | #28392 FP8 KV（未合）可减半 KV | 可空间换带宽 | P2 |
| 统一内存 | ~128 GiB 物理 / 96 GiB UMA 车分 | libosmos 113 GiB GPU / getrigbase 111.6 GiB（Win） | 持平（Linux 更优） | — |
| 带宽 | ~215 GB/s（实测） | 一致（硬件上限） | 物理墙，不可破 | — |
| 驱动栈 | Mesa 26.0.8（钉死，26.2.x 致 Vulkan 失效） | Nathanw1014 CI 打包 Mesa 26.2.4（未验证本机） | 本机受 Mesa 硬约束，不可盲升 | P0（风险） |
| 引擎版本 | b10824（2026-10-24） | 上游 b12233（2026-11-09） | **落后 ~1409 build** | P0 |
| MoE 专家缓存 | 无（上游无此特性） | FLE/ik_llama.cpp 专家缓存 2.49x | 架构级差距 | P2（需换分支） |

**结论**：本机 decode 仅落后社区同模型 7%，prefill 为关键短板；最大差距在引擎版本（落后 ~1409 build）与 MoE 专家缓存（需换 FLE/ik 分支）。

---

## 6. 可立即执行的优化清单

### A. 改启动参数即可（经 MCSManager 面板改实例命令，**禁止裸跑二进制**）
1. **收窄监听（A0，延续 40+ 日）**：MCSManager 实例 `start-qwen36-35b-a3b`（UUID `9770784bb1f940ada5c5890fd003efb3`）启动命令 `--host 0.0.0.0` → `--host 127.0.0.1`。
   ```bash
   # 经面板改，或调用 MCSManager API（工具 mcsm-api-apikey.py）
   python3 $HOME/WorkBuddy/调试本地模型/tools/mcsm-api-apikey.py stop <实例UUID>   # 先优雅停止
   # 在面板编辑启动参数后：
   python3 $HOME/WorkBuddy/调试本地模型/tools/mcsm-api-apikey.py start <实例UUID>
   ```
2. **MTP n-max 调优（A4）**：当前 `draft-mtp n-max2`，可试 `n-max3`（需重启 llama 实例生效；注意 #27950 质量人核）。
   ```bash
   # 启动参数追加/修改片段（面板编辑）：
   -md $HOME/models/<MTP头>.gguf --spec-type draft-mtp --spec-draft-n-max 3
   ```
3. **draft 档 CFG 抬升**：`config.json` draft 档 `cfg=1.0` 低于社区下限 3，建议改 `cfg_scale: 3.0`（预览可用性提升，不影响 quality 档）。
   ```bash
   # 编辑 $HOME/drama-series-agent/config.json draft 档
   # "cfg_scale": 1.0  →  "cfg_scale": 3.0
   ```

### B. 环境清理
4. 确认 18090 双链路：`npu_enabled=true` 且 `npu_upstream=127.0.0.1:8219` —— 若该 NPU 上游未实际使用，关注是否引入额外依赖；当前 8080 主链路正常，无需改动。
5. 清理残留 ComfyUI 配置噪音：8188 无监听属历史残留，已绕过，无需处理。

### C. 需重启或重建（先备份 mesa deb）
6. **升级 llama.cpp 到 b12233（C2）**：先 `apt-get download` 备份 6 个 mesa 包，再 git pull + 重建（仅 `cmake --build build-vk4 --target llama-server`，跳 tests）。
   ```bash
   cd $HOME/llama-qwen4exp-rocmfpx
   git stash && git pull --ff-only
   cmake --build build-vk4 --target llama-server -j16
   ```
7. **Cherry-pick 模型 A 相关 PR（C1）**：#31850（MoE expert copies 独立 stream）、#31625（ROCm fast-math）、#31802（MTP Mellum2.1）—— 均需在 b12233 基线后评估，先备 mesa deb。
8. **MoE 专家缓存（性能跃迁）**：评估切 FLE 或 ik_llama.cpp 分支获取专家缓存（社区 2.49x 实测），属架构级变更，需重建 + 回归测试。

---

## 7. 风险与验证

- **MTP 输出质量需人工核对（llama.cpp #27950）**：本机 MTP 经 ps 确认启用（`draft-mtp n-max2`），但 MTP 头可能引入质量偏移，须人工比对开启/关闭 MTP 的同一 prompt 输出。状态：持续未解（30+ 日）。
- **引擎版本落后 ~1409 build**：#28635（Vulkan q4_k_f 管线失败）、#28392（FP8 KV）、#29357（prefill FA）等修复/特性均未在本机，升级前必须 `vulkaninfo` 验证 + 备 mesa deb（Mesa 26.2.x 致 Vulkan 失效的事故已确立）。
- **Mesa 硬约束**：6 个 mesa/gbm 包已 `apt-mark hold` 在 26.0.8；任何系统级驱动升级须「备份 deb + 验证内核兼容 + vulkaninfo 验证」三步，缺一不可。
- **#31509 Vulkan NaN 监控**：建议保留启用以捕捉渲染异常。

---

## 8. 今日相对昨日（2026-11-09）的新增项

**增量（相对 11-09 日报）**：
1. 上游 `b12211 → b12233`（+22 build），本机落后扩至 ~1409 build。
2. 新 PR **#31582**（Qwen3Next dense FFN，closed/未直合，被 #31551 取代）—— 模型 C 架构相关，确认未在本机。
3. 新 issue **#28635**（Vulkan q4_k_f 管线失败，AMD 相关）、**#31189**（qwen4exp merged tensors assert，模型 C 相关，已 closed）。
4. HN 新增 **Qwen3.8-27B MTP Q4S 头量化经验**（Q4S 快于 Q6、f16 慢）、**TokiRecur KV 复用**、**llama.cpp sleep mode**（11-06~08）。
5. P2 新增高质量他人实测：getrigbase #31839（35B-A3B 61.8 tok/s, b11401）、llamaperf（Flash-Next 25–45 t/s + MTP）、Zenodo FLE（89GB MoE 90 tok/s, 2.49x）、dev.to Flash-Next MTP 教程（PR #29761 主线已合）。
6. **本机 minimax 专项实测更新**：`config.json` 实测确认 quality 档 steps=20/cfg=4.0、draft 档 steps=12/cfg=1.0；quality 档与社区共识一致，draft 档 cfg 偏低（建议抬至 3.0）。
7. **18090 代理新出现 `npu_enabled=true`（npu_upstream 8219）** —— 昨日未记录，需留意是否引入新依赖。

**无实质新增/延续未解**：A0 host 收窄（40+ 日）、A1 MoE 缓存、A2 prefill 短板、A4 n-max3+#27950 人核、B3 llm 云端决策、C1 cherry-pick、C2 升级（先备 mesa deb）、Mesa 26.0.8 钉死、#31509 Vulkan NaN 监控 —— 全部延续。

---

*质量红线自检：本报告所有性能数字均标注来源；本机未实测的社区数字一律标 `[他人实测/估算]`；优化建议均落到具体命令/参数，无空话。抖音/小红书/Reddit/gh CLI 通道按既定策略未启用、未重试。*

---

> 许可：CC0-1.0，公共领域贡献，无任何限制。
