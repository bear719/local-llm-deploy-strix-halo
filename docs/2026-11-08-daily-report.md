# 本地大模型日报 · 2026-11-08

> 探测时间：2026-11-08 05:00 (GMT+8) ｜ 采集通道：GitHub API(P0) + HN Algolia(P1) + WebSearch(P2)，全部免登录、无浏览器渲染。
> 本日最大状态变化：**主 LLM 服务 8080 恢复在线**（11-05~11-07 连续离线后，今日 18:13 重启恢复）。

---

## 1. 抓取通道状态表

| 通道 | 目标 | 状态 | 原因 / 备注 |
|---|---|---|---|
| P0 GitHub releases | api.github.com/repos/ggml-org/llama.cpp/releases | ✅ 成功 | 最新 b12189 (2026-11-07) |
| P0 GitHub PR | pulls?state=all&sort=updated&per_page=15 | ✅ 成功 | 最新 15 条已解析 |
| P0 GitHub issue | issues?state=all&sort=updated&per_page=15 | ✅ 成功 | 已过滤 PR |
| P0 kyuz0/amd-strix-halo-toolboxes | commits?per_page=5 | ✅ 成功 | 11-07 活跃 |
| P0 Nathanw1014/strix-halo-llamacpp | commits?per_page=5 | ✅ 成功 | 10-25 后 stale |
| P0 drluoto/llama.cpp | commits?per_page=5 | ✅ 成功 | 08-28 后 stale |
| P0 gufo-org/gufo | commits?per_page=5 | ✅ 成功 | 11-07 极活跃 |
| P0 kingjones777/MTP-Heads-GGUF | commits?per_page=5 | ❌ 失败 | HTTP 404（仓库不存在/已移）→ 改用 kingjones30/strix-halo-quant-lab（历史已定） |
| P1 Hacker News | hn.algolia.com search_by_date llama.cpp | ✅ 成功 | 14d 9 条，低信噪比 |
| P2 WebSearch | 4 组关键词 | ✅ 成功 | 二手聚合，非站内直采 |
| 抖音/小红书站内直采 | — | ⛔ 已停用 | 历史决议，不恢复 |
| Reddit (r/LocalLLaMA) | — | ⛔ 已停用 | 本机 HTTP 000 网络层阻断 |

---

## 2. 当前运行方案实测表（步骤 0 真实数据，探测 05:00）

来源：`curl 127.0.0.1:8080/props` + `/v1/models` + `ps` 进程参数交叉验证。

| 字段 | 实测值 | 来源 / 说明 |
|---|---|---|
| 服务状态 | **在线**（PID 2628535，启动 11-07 18:13） | `ps` / `curl /v1/models` |
| model_path | `$HOME/models/Qwen3.6-35B-A3B-Uncensored-Q5_K_P.gguf` | `/v1/models` meta |
| model_alias | 同上（Q5_K_P 变体） | `/props` |
| model_ftype | Q5_K - Medium | `/props` |
| size | 28,016,404,992 B（≈28.0 GB） | `/v1/models` size |
| n_params | 34,660,610,688（≈34.66B，35B-A3B） | `/v1/models` n_params |
| n_embd | 2048 | `/v1/models`（印证 35B-A3B 架构） |
| n_ctx | 262144 | `default_generation_settings.n_ctx`（全量） |
| n_ctx_train | 262144 | `/v1/models` n_ctx_train |
| total_slots | 1 | `/props` |
| modalities | vision=true, video=true, audio=false | `/props` |
| 多模态 | mmproj `...-f16.gguf` 已挂 | `ps --mmproj` |
| speculative.types | `/props` 报 `none`（**不可信**） | 须看下方三处交叉验证 |
| **MTP 实际** | **启用**：`-md ...MTP-ONLY-Q4_K_M.gguf --spec-type draft-mtp --spec-draft-n-max 2` | `ps` 命令行（权威） |
| KV 量化 | `-ctk q8_0 -ctv q8_0` | `ps` |
| GPU offload | `-ngl 999 -fa on` | `ps` |
| 批处理 | `-np 1 -b 4096 -ub 1024` | `ps` |
| 缓存 | `--cache-idle-slots -cms 512 --cache-ram 1024` | `ps` |
| 监听 | `--host 0.0.0.0 --port 8080` | `ps`（⚠️ A0 未收窄，连续 40+ 日） |
| 二进制 build | b10824-75147a27e（10-24 构建） | `/props` build_info |
| 采样参数 | temp 1.0 / top_k 20 / top_p 0.949 / min_p 0.05 / repeat_penalty 1.0 / DRY on | `/props` default_generation_settings.params |
| 代理 18090 | status ok, mode passthrough, upstream 8080 | `curl 18090/health` ✅ |
| MoE 专家缓存 | **未启用**（ps 无 `--moe-cache-mib`） | ⚠️ A1 优化候选 |

**MTP 三处交叉验证结论**：`/props` 的 `speculative.types` 恒为 `none`（已知不可信）；以 `ps` 命令行（`--spec-type draft-mtp --spec-draft-n-max 2` + `-md MTP-ONLY`）为准 → **MTP 已启用**。接受率昨日实测 77.1%，冷启动 `/metrics` 计数低不采信。

> ⚠️ **已知清单更正**：实际在线的"模型 A"是 **Q5_K_P（Q5_K_M）变体，28GB**，非清单所写的 Q4_K_P；主力模型 C（Qwen3.8-Flash-Next-ROCmFP4）当前**未加载**（离线）。清单需更新。

---

## 3. minimax h3 专题（专项检查项逐条结论）

核查文件：`$HOME/drama-series-agent/config.json` + `.env` + 进程/端口/权重目录。

| # | 专项项 | 实测 | 结论 |
|---|---|---|---|
| 1 | render.backend | `sdcpp` | ✅ 一致 |
| 2 | render.bin | `$HOME/sdcpp-git/build-vk4/bin/sd-cli`（84MB, 10-20 构建） | ✅ 一致 |
| 3 | SDCPP_EXTRA_ARGS | `--vae-tiling`（.env 已确认） | ✅ 一致 |
| 4 | COMFYUI_URL | `""`（清理逻辑跳过，消除 8188 Connection refused 噪音） | ✅ 一致 |
| 5 | 端口 8000 | `404`（导播台 API 在线，根路由无） | ✅ 一致 |
| 6 | 端口 8188（ComfyUI） | `000`（未监听） | ✅ 一致（残留配置，无害） |
| 7 | 权重目录 | `$HOME/models/minimax-h3` = 59G | ✅ 一致 |
| 8 | gpu.arbiter.need_gib | `64` | ✅ 一致 |
| 9 | arbiter.auto_resume | `true`（8080 今日恢复在线佐证其生效） | ✅ 一致 |
| 🔺10 | **render.steps** | **`12`**（基线 20） | ⚠️ **漂移 B2**（持续，无新增） |
| 🔺11 | **llm.model / base_url** | `MiniMax-M3.1-Flash` / `https://api.iamhc.cn/v1`（云端） | ⚠️ **漂移 B3**（由 18090 兜底升级为云端，持续） |
| 12 | out_range | `sdcpp_backend.py:1253` 已改 `tv`（色彩范围瑕疵修复） | ✅ 历史已落实 |
| 13 | 当前渲染状态 | 无 sd-cli 进程（空闲），8080 在线无冲突 | ✅ 正常 |

**结论**：9 项基准零漂移 + 2 项历史漂移（steps=12、llm 云端）持平，无新增漂移。sd.cpp 当前空闲，未渲染。

---

## 4. 其他近期关键动态

> 区分「事实」与「他人实测值〔待本机验证〕」。

**事实（一手源）**
- [GitHub] llama.cpp 最新 release **b12189**（2026-11-07）→ 本机 b10824，**落后约 1365 build**。来源：https://github.com/ggml-org/llama.cpp/releases
- [GitHub PR #31850] `llama: upload expert copies on a separate stream with an event-lifetime fix`（open, 11-07）→ MoE 专家缓存路线演进，直接利好模型 A。来源：https://github.com/ggml-org/llama.cpp/pull/31850
- [GitHub PR #31625] `HIP: Enable fast-math on HIP without regressions`（open, 11-07）→ ROCm 路线。来源：https://github.com/ggml-org/llama.cpp/pull/31625
- [GitHub PR #30826/#30824] Vulkan rms_norm / subgroup 调整（open）→ Vulkan 后端维护。来源：https://github.com/ggml-org/llama.cpp/pull/30826
- [GitHub issue #31560] Vulkan KHR_coopmat 在 Intel Arc Pro B70 给出错误结果（open）→ 非本机架构，但 Vulkan 一致性需持续监控。来源：https://github.com/ggml-org/llama.cpp/issues/31560
- [gufo-org/gufo] 11-07 极活跃：text providers 声明 speculation 默认值、prefill 可见整 prompt、可选 hidden-state 编码 → 模型 C 利好。来源：https://github.com/gufo-org/gufo/commits
- [kyuz0/amd-strix-halo-toolboxes] 11-07 `Fix grammar patch after upstream recursion changes` + Maya ROCm 10 toolbox。来源：https://github.com/kyuz0/amd-strix-halo-toolboxes/commits

**他人实测值〔待本机验证〕**
- [runaihome, Strix Halo 同硬件] Qwen3-30B-A3B IQ4_XS RADV Vulkan **100 t/s**；GPT-OSS 120B 55 t/s；实测带宽 ~215 GB/s（理论 256）；GPU 可取 96GB；**优先 MoE**。来源：http://www.runaihome.com/blog/ryzen-ai-max-395-strix-halo-local-llm-2026 〔二手聚合，非站内直采〕
- [GitCode, 模型 C] 自适应 MTP `--spec-draft-adaptive --spec-draft-n-min 2 --spec-draft-n-max 4`，Strix Halo **最高 40 t/s**；长上下文 131072 深度 prefill 137.7 / gen 19.70(无 MTP)。来源：https://blog.gitcode.com/... 〔二手聚合〕
- [ima.qq.com 微信文章, 模型 C] 启动 `-ngl 999 -fa on -dio --jinja -fit off --spec-draft-n-max 4`；实测 Prefill 1997tok/7.8s=256 t/s，Decode 7495tok/4m33s=27.40 t/s。来源：ima.qq.com（微信文章，二手聚合）
- [kingjones777 HF, 模型 C 量化路线重大修正] STRIX(105) tier **只保 attn K/V 不保 LM head** → 现改偏好 **tier 102 COHERENT + `--output-tensor-type q6_K --token-embedding-type q6_K`**；`-fit off` 必填。来源：https://huggingface.co/kingjones777/DeepSeek-V4-Flash-0731-ROCmFP4 〔二手聚合〕
- [MiniMax H3 社区共识] steps **20-30**（本机 12 偏激进）、CFG **4-7**（视频比图像保守）、分辨率 768x432/960x544 起步。来源：CSDN blog.csdn.net/weixin_42628941、blog.csdn.net/weixin_33139275、hqwc.cn 等〔二手聚合，非站内直采〕
- [HN 11-07] TokiRecur（llama.cpp KV-cache recycling）、Swapping LLMs <2s sleep mode、Hob on-device（10-26, 180p/44c）。来源：https://hn.algolia.com 〔无 Strix 专项〕

---

## 5. 现状 vs 社区同硬件最优对比表

维度 | 本机实测 | 社区同硬件最优 | 差距 | 优先级
---|---|---|---|---
decode (t/s) | 模型 A +MTP n2 ≈ **72.41**（10-28 实测） | Vulkan 无-spec 62.6 / +MTP **93**（vitorpontual/RigBase） | 落后 +MTP 档 ~22% | P0(A4)
prefill (t/s) | 未实测长 prompt（短板） | vitorpontual prefill **1380@10K**；runaihome 带宽 215GB/s | 最大短板，未闭环 | **P0(A2)**
上下文 | **262144** 全量 | 同档 | 持平 | —
KV 量化 | **q8_0** | 社区共识 q8_0 安全 | 持平 | —
MoE 专家缓存 | **未启用**（默认 OFF 约减半吞吐） | savrn/moefast 指出应开启 | 零成本优化空间 | **P0(A1)**
GTT / 显存车分 | **96 GiB carve-out** | 同档（BIOS 已设） | 持平 | —
驱动栈 | **Mesa 26.0.8-1ubuntu0.3**（钉死 6 包 hold）/ RADV Vulkan 1.4 | Nathanw1014 用 Mesa 26.2.4（本机不跟，回归风险） | 保守但稳定 | P0(维持)
MTP 接受率 | 77.1%（昨日） | nosistech 单 slot 63→90% | 有提升空间 | P1
量化路线(模型 C) | ROCmFP4 FAST v2 ple16 | kingjones777 建议 102 COHERENT + q6_K 输出/嵌入（STRIX105 只保 K/V 不保 head） | 路线待校正 | P1(C2)
服务监听 | `--host 0.0.0.0`（暴露） | 应 `127.0.0.1` | 安全风险 | **P0(A0)**
二进制版本 | b10824（落后 1365 build） | b12189 | 落后多，关键修复未含 | P1(C2)

---

## 6. 可立即执行的优化清单

### A 组 · 改启动参数即可（仅改 llama-server 命令行参数，经 MCSManager 重启实例生效，无需重建二进制）
- **A0 收窄监听**（安全）：把 qwen 实例启动命令 `--host 0.0.0.0` 改为 `--host 127.0.0.1`。改后重启实例：
  ```bash
  # 在 MCSManager 面板编辑「start-qwen36-35b-a3b」实例启动命令，将 --host 0.0.0.0 改为 --host 127.0.0.1，保存后重启
  python3 $HOME/WorkBuddy/调试本地模型/tools/mcsm-api-apikey.py stop  9770784bb1f940ada5c5890fd003efb3
  # （编辑实例命令后）
  python3 $HOME/WorkBuddy/调试本地模型/tools/mcsm-api-apikey.py start 9770784bb1f940ada5c5890fd003efb3
  ```
- **A1 启用 MoE 专家缓存**（零成本吞吐提升，b10824 已含 #29887 能力）：在启动命令追加 `--moe-cache-mib 8192`，重启实例做 A/B（对比 decode t/s 与接受率）。
- **A4 提升 MTP 深度**（参考 victoralcazardev n=3 翻倍）：`--spec-draft-n-max 2` 改为 `--spec-draft-n-max 3`，重启后**必须人工核对输出质量（#27950 风险）**。

### B 组 · 环境清理（不改二进制）
- **B0 确认 Mesa 钉死**：`apt-mark showhold` 应列出 6 个 mesa/gbm 包；`vulkaninfo 2>/dev/null | head -3` 应枚举 `AMD Radeon Graphics (RADV STRIX_HALO)`。若异常立即回退。
- **B1 清理陈旧构建**：`$HOME/sdcpp-src/build-vk2/bin/sd-cli`（85MB, 10-08，已被 build-vk4 取代）可删（先 `cp -a` 备份到 /tmp）。
- **B2 导播台 steps 回滚**：`config.json` 内 `render.steps` 由 **12 → 20**（社区共识 20-30，当前 12 偏激进易出伪影）。改后重启 render 服务（API 在 18000）。
  ```bash
  # 编辑 $HOME/drama-series-agent/config.json 第 28 行 "steps": 12 -> 20，保存后重启 run_api
  ```
- **B3 llm.model 一致性决策**：当前 `llm.model=MiniMax-M3.1-Flash` 走云端 `api.iamhc.cn`，与本地 8080 架构无关（导播台只用其做分镜/剧本 LLM）。若需离线，改回 `base_url=http://127.0.0.1:18090/v1`、`model=...`。**需少爷决策**，自动化不改。

### C 组 · 需重启或重建（编译/升级）
- **C2 重建 build-vk4 含上游修复**：cherry-pick 或合入 #31850（MoE expert copies 独立 stream）、#31625（ROCm fast-math），从源码 `$HOME/llama-qwen4exp-rocmfpx` 重建：
  ```bash
  cd $HOME/llama-qwen4exp-rocmfpx && git fetch && git merge-base --is-ancestor <commit> HEAD  # 先验证是否已含
  cmake --build build-vk4 --target llama-server -j16   # 避免全量 all（tests 不同步会拖垮）
  ```
  ⚠️ 升级前**必须先备份 mesa deb**（`apt-get download <pkg>=26.0.8-1ubuntu0.3` 6 包），升级后 `vulkaninfo` 验证再重启业务。
- **C3 升级到 b12189**：落后 1365 build，含大量 MoE/Vulkan/ROCm 修复。同 C2 流程，**先备 mesa 回退包**。

---

## 7. 风险与验证

- **MTP 输出质量（#27950）**：本机已含 #27694（概率化拒绝采样）+ #29797（temp-zero greedy）修复（10-25 重建落地），但仍需在 A4 调 n-max 后**人工核对**长文本/代码生成质量，确认无语义退化。
- **Vulkan NaN 监控（#31509）**：本机走 RADV Vulkan，同后端曾报 all-NaN。每次渲染/推理前 `vulkaninfo | head -3` 正常即安全；异常立即 `rocm-smi --gpureset -d 0` 后复查。
- **Mesa 维持 26.0.8 钉死**：6 包 `apt-mark hold`，**严禁** `apt upgrade` 升到 26.2.x（曾致 Vulkan 完全不可用）。任何驱动升级须「备 deb + 验内核兼容 + vulkaninfo 验证」三步走。
- **服务托管的铁律**：llama 实例一律经 MCSManager 启停（UUID `9770784bb1f940ada5c5890fd003efb3`），**禁止裸跑二进制**；arbiter 已内置 `kill_stray_llama` 兜底。

---

## 8. 今日相对昨日（2026-11-07）的新增项

- 🟢 **8080 主 LLM 恢复在线**（最大状态变化，11-05~07 连续离线 → 今日 18:13 重启）。引用固化配置校验通过：模型 A Q5_K_P / b10824 / n_ctx 262144 / MTP n2 / KV q8_0。
- 🔺 **已知清单更正**：在线"模型 A"实为 **Q5_K_P（28GB）**，非 Q4_K_P；模型 C（Flash-Next）仍离线未加载。
- 📈 **上游推进 +10 build**：b12179 → **b12189**，落后 1355 → **1365 build**。
- 🆕 **新 PR #31850**（MoE expert copies 独立 stream，模型 A 直接相关）、#31625（ROCm fast-math）待 cherry-pick 评估。
- 🆕 **gufo 11-07 极活跃**（spec defaults / prefill 整 prompt / hidden-state 编码）→ 模型 C 利好。
- 🆕 **kingjones777 量化路线修正信号**：STRIX(105) tier 只保 attn K/V 不保 LM head → 改偏好 **102 COHERENT + q6_K 输出/嵌入**（模型 C 重建参考）。
- 🆕 **P2 同硬件实测补充**：runaihome Strix Halo MoE 100 t/s、GitCode 模型 C 自适应 MTP 最高 40 t/s —— 坐实 MoE 路线正确 & 为 C2 设提速目标。
- ➖ minimax h3 专项：无新增漂移（steps=12 / llm 云端两项持续）。

**延续未解项**（自动带入，非今日新增）：A0 host 收窄(40+日)、A1 MoE 缓存、A2 prefill 短板闭环、A4 n-max3 A/B+质量人核、B2 steps 回滚 20、B3 llm 一致性决策、C2 #31850/#31625 cherry-pick 重建、#27950 MTP 质量人核(30+日)、Mesa 26.0.8 钉死、#31509 Vulkan NaN 监控。

---

> 许可：CC0-1.0，公共领域贡献，无任何限制。
