# 本地大模型日报 · 2026-11-11

> 探测时间：2026-11-11 05:00 CST（Asia/Shanghai）
> 采集方式：全 API 免登录通道（GitHub REST / HN Algolia / 内置 WebSearch），无浏览器渲染
> 报告人：自动化任务（管家）

---

## 1. 抓取通道状态表

| 通道 | 状态 | 结果/原因 | 备注 |
|---|---|---|---|
| P0 GitHub · releases | ✅ 成功 | HTTP 200，5 条（b12250–b12255，均为 prerelease，11-10） | 上游最新 b12255 |
| P0 GitHub · pulls | ✅ 成功 | HTTP 200，15 条（含 #32044/#32045/#31185/#29791 等） | 详见第 4 节 |
| P0 GitHub · issues | ✅ 成功 | HTTP 200，15 条 | 与 PR 列表重叠（API 行为） |
| P0 仓库 commits（kyuz0） | ✅ 成功 | HTTP 200，11-07 活跃（Maya toolbox grammar patch） | 同硬件 ROCm 工具箱 |
| P0 仓库 commits（Nathanw1014） | ✅ 成功 | HTTP 200，最近 10-25（Mesa 26.2.4 打包，**本机不跟**） | 维持 Mesa 26.0.8 钉死 |
| P0 仓库 commits（drluoto） | ✅ 成功 | HTTP 200，最近 08-28（stale） | 非活跃 |
| P0 仓库 commits（gufo-org） | ✅ 成功 | HTTP 200，11-10 极活跃（nix HRX runtime / serve tool-call 修复） | 模型 C 上游友好 |
| P0 仓库 commits（kingjones777） | ⚠️ 失败→降级 | HTTP 404（持续多日） | 改用 kingjones30/strix-halo-quant-lab（153 仓库 ROCmFP4 基准） |
| P1 Hacker News（Algolia） | ✅ 成功 | HTTP 200，9 条（query=llama.cpp，%3E 正确转义） | 低 Strix 专项信噪比 |
| P2 WebSearch（中文二手聚合） | ✅ 成功 | 4 组查询 ×5 条，全部命中 | **二手聚合，非站内直采** |
| 抖音 / 小红书站内直采 | ⛔ 已停用 | 不恢复、不重试（headless 无 DOM / 需登录 / 无 Xvfb） | 仅取搜索引擎收录结果 |
| Reddit（r/LocalLLaMA） | ⛔ 已停用 | 本机网络层阻断 HTTP 000 | 不重试 |
| gh CLI | ⛔ 不可用 | 本机未安装 | 改用 curl + api.github.com |

---

## 2. 当前运行方案实测表（步骤 0，2026-11-11 05:00 CST）

> 8080 在线。**实际线上模型 = 模型 A 的 Q5_K_P 变体**，非清单中的 Q4_K_P，也**非主力模型 C（Qwen3.8-Flash-Next 仍离线未加载）**。

| 字段 | 实测值 | 来源 |
|---|---|---|
| model_path | `$HOME/models/Qwen3.6-35B-A3B-Uncensored-Q5_K_P.gguf` | `/props` + `ps` |
| model_ftype | Q5_K - Medium | `/props` |
| size | 28,016,404,992 ≈ **28.0 GB** | `/v1/models` meta |
| n_params | 34,660,610,688 ≈ **34.66B**（MoE，3B 激活） | `/v1/models` meta |
| n_embd | 2048 | `/v1/models` meta |
| n_vocab | 248320 | `/v1/models` meta |
| n_ctx | **262144** | `default_generation_settings.n_ctx` |
| n_ctx_train | **262144** | `/v1/models` meta（非 131072） |
| total_slots | 1 | `/props` |
| modalities | vision=✅ video=✅ audio=❌ | `/props` |
| build_info | **b10824-75147a27e**（2026-10-24） | `/props` |
| chat_format / reasoning | Content-only / none | `/props` |
| **speculative（/props）** | `"none"`（**已知谎言**） | `/props` |
| **speculative（/slots[0]）** | **True**（经 ps 交叉验证） | `/slots` |
| **speculative（/metrics）** | draft 216765 / accept 172059 → **接受率 79.4%**（昨日 77.1%） | `/metrics` |
| 启动命令（节选） | `-md ...MTP-ONLY-Q4_K_M.gguf --spec-type draft-mtp -ngl 999 -c 262144 --spec-draft-n-max 2 -ctk q8_0 -ctv q8_0 --mmproj ...f16.gguf --context-shift --cache-idle-slots -cms 8192 --cache-ram 16384 --ctx-checkpoints 16 --host 0.0.0.0 --port 8080` | `ps aux` |
| MoE 专家缓存 | **未启用**（无 `--moe-cache-mib`） | `ps aux` → A1 候选 |
| 代理 18090 | passthrough → 8080 OK；新增 `npu_enabled=true`、`npu_upstream=http://127.0.0.1:8219` | `/health` |
| NPU 8219 | 返回 `{"error":"Not Found"}`（有进程监听，非 llama） | 直连探测 |

**结论**：MTP（draft-mtp, n-max=2）确证启用，接受率回升至 79.4%；KV=q8_0；全量 -ngl 999；`--host 0.0.0.0` 连续 **40+ 日未收窄（A0 P0）**；二进制仍停在 b10824（落后上游 ≈1431 build）。模型 C 持续离线。

---

## 3. minimax h3 专题（专项检查项逐条）

> 数据源：`$HOME/drama-series-agent/config.json` + `.env` 直读（2026-11-11 05:00）+ 长期工作记忆

| # | 检查项 | 实测/设定 | 结论 |
|---|---|---|---|
| 1 | 渲染后端 | `render.backend=sdcpp`，`render.bin=$HOME/sdcpp-git/build-vk4/bin/sd-cli`（84081928 字节，10-20 构建） | ✅ 一致（Vulkan 原生推理，非 ComfyUI） |
| 2 | AMD 后端 | Vulkan RADV STRIX_HALO（gfx1151），Mesa 26.0.8 钉死 | ✅ 一致 |
| 3 | 权重路径 | `$HOME/models/minimax-h3`（57G） | ✅ 一致 |
| 4 | 并发模型 | `concurrency=1`（sd-cli 与 llama 共用车分池） | ✅ 一致 |
| 5 | 画布/帧数 | 工作记忆：576×1024 / 90 帧 / 3.75s（顶层 config 未直接带，走 `render_profile.sh`） | ✅ 对齐（旧 768×1344 39帧已弃） |
| 6 | 步数 | **`render.steps=12`（顶层 active 仍为 12 步）**；quality profile=20，draft profile=12 | ⚠️ **B2 漂移持续**：社区共识 20–30 步，成片建议走 quality=20 |
| 7 | CFG | 顶层 `render.cfg` 未设；draft profile `cfg=1.0` | ⚠️ **cfg=1.0 偏低**（11-10 已标记），建议抬至 3.0 |
| 8 | ComfyUI URL | **`comfyui.comfyui_url=http://127.0.0.1:8188`** | 🆕 **漂移**：与 10-20「已清空为 ""」记录不符，疑回退/展示层回落；8188 当前无监听，仅噪音回归，无害但需人工确认 |
| 9 | GPU 仲裁 | `gpu.arbiter.need_gib=64`；`kill_stray_llama` 未显式设（默认开） | ✅ 一致 |
| 10 | VAE tiling | `.env`：`SDCPP_EXTRA_ARGS="--vae-tiling"`；`sdcpp_backend.py` 已 `out_range=tv` | ✅ 一致（H3 已知 VAE bug 必开） |
| 11 | LLM 链路 | `llm.model=MiniMax-M3.1-Flash`，`llm.base_url=https://api.iamhc.cn/v1`（**云端**，非本地 8080/18090） | ⚠️ **B3 漂移持续**（11-07 起切云端，与本地推理架构分离） |
| 12 | 端口在线 | 8000=404（API 根路由正常）、5173=200（Vite 前端） | ✅ 无冲突 |

**专项小结**：12 项核实，9 项一致 + 3 项历史漂移（B2 步数 / B3 云端 LLM / draft cfg 偏低）+ **1 项新漂移（comfyui_url 回退 8188）**。sd.cpp/Vulkan/Mesa/need_gib/VAE tiling 全部稳定。sd-cli 当前空闲（无渲染任务占用）。

---

## 4. 其他近期关键动态（来源 URL + 日期；区分事实 / 他人实测）

### 4.1 上游 llama.cpp（ggml-org）— 事实（PR/状态）
- **#32044**（open，2026-11-10）fix embeddings on DeepSeek V4 and Qwen4-Exp by dedicated NextN hidden state width → 关联本机 qwen4exp fork / 模型 C 的 NextN 隐藏层结构。来源：https://github.com/ggml-org/llama.cpp/pull/32044
- **#32045**（open，2026-11-10）fix: roll back draft KV cache for rejected positions in DFlash accept() → **直接关联 MTP/spec-decode 质量（#27950）**，DFlash 拒收位置 KV 回滚修正。来源：https://github.com/ggml-org/llama.cpp/pull/32045
- **#31185**（merged，2026-11-09）feat: external PLE file loading → 外部 PLE 文件加载，利好模型 C 的 `ple16` 外挂加载路线。来源：https://github.com/ggml-org/llama.cpp/pull/31185
- **#29791**（open）vulkan: add fp8 and scaled matmul support → AMD Vulkan 后端 FP8。来源：https://github.com/ggml-org/llama.cpp/pull/29791
- **#30190**（open）vulkan: fold verify tokens and GQA heads into one FA row tile → Vulkan 推理融合，AMD 利好。来源：https://github.com/ggml-org/llama.cpp/pull/30190
- **#28392**（open）FP8 KV cache。来源：https://github.com/ggml-org/llama.cpp/pull/28392
- 上游版本：**b12255**（11-10），本机 **b10824** → **落后 ≈1431 build**（+22 vs 昨日 1409）。
- gufo-org/gufo 11-10 极活跃（v0.32.x，nix HRX runtime、serve tool-call 数值修复）→ 模型 C 上游工具链持续友好。

### 4.2 Hacker News（P1）— 事实 / 讨论
- **Qwen3.8-27B MTP Q4S head on Q6 quant**（2026-11-08，2 分）：MTP 头量化（Q4S 头快于 q6、f16 慢），与我们 Q4_K_M MTP 头做法呼应。来源：https://github.com/alainnothere/llama.cpp/commit/77b124a7ab56e0f1c33c025344a9c63465a9a87f
- **TokiRecur**（2026-11-07，3 分）：llama.cpp launcher with KV-cache recycling（KV 缓存回收）。来源：https://github.com/lhadzic377-netizen/TokiRecur
- **Sleep Mode for llama.cpp**（2026-11-06，1 分）：<2s 热切换模型休眠模式。来源：https://zaage.it/writing/llama-sleep/
- **llama.cpp 团队桌面 App**（2026-11-04，3 分）：llama.app 跨平台客户端。来源：https://llama.app/models

### 4.3 中文社区（P2，二手聚合，非站内直采）— 他人实测 / 共识
- **modelfit.io**：Strix Halo 128GB 统一内存 ~110GB 可寻址；35B MoE 估算 **50 tok/s**；实测带宽约 **215 GB/s**（理论 256）。[估算+他人实测，待本机验证] 来源：https://modelfit.io/gpu/ryzen-ai-max-395/
- **getrigbase**（2026-11-08 他人实测）：GMKtec EVO-X3 Strix Halo 128GB，stock llama.cpp **b11401 Vulkan**，Qwen3.6-35B-A3B UD-Q4_K_XL **61.8 tok/s（无 MTP）**、Qwen3.5-122B 23.6。来源：https://getrigbase.com/builds/gmktec-evo-x3-strix-halo-128gb-windows-vulkan-31839
- **CSDN BigMoeOnEdge**（中文，他人实测）：Qwen3.6-35B-A3B MTP draft 2/3/4 接受率 **71.4% / 60.1% / 52.4%**，相对关闭 +7.6% / +15.1%；独立 GPU +35%；手机端因专家读盘延迟反而变慢。来源：https://blog.csdn.net/gitblog_00307/article/details/156579781
- **dev.to deepu105**（他人实测，质量红线）：Qwen3.8 MTP n=5 达 2.3–3.1×；但**采样器不对齐 drafter → 接受率 59.6%→45.7%、墙钟 2.8×**（验证 #27950 + 采样器必须与 drafter 对齐）。27B ROCmFP4-FAST 需 julianmb/q38rocm fork。来源：https://dev.to/deepu105/can-qwen-38-running-on-your-laptop-really-replace-claude-opus-for-agentic-coding-51gk
- **ssdnodes**（他人实测）：Qwen3.8-Flash-Next n-gram 28.8GB shard + `--lazy-mode`；MI355X MXFP4；PLE 默认 CPU offload。来源：https://www.ssdnodes.com/learn/what-it-takes-to-self-host-qwen-3-8-flash-next
- **libosmos**（8 天前项目，他人实测）：DeepSeek-V4.1-Flash 768B 单 Strix Halo，**UD-IQ1_S 草稿 40.8 tok/s / 纯解码 19.3**（64K 上下文，greedy）。来源：https://singularitybyte.com/tools/libosmos-deepseek-v4-1-flash-strix-halo.html
- **MiniMax H3 社区共识**（多源）：steps **20–30**、CFG **6–8**（或 4–7）、**VAE tiling 必开**（H3 已知 VAE bug）、分辨率 480–720p、单段 4–8s。来源：http://www.sheratonhq.com/news/171560 、http://www.hqwc.cn/a/1860548.html 、https://www.hqwc.cn/a/1534165.html 、http://www.sheratonhq.com/news/120613 、http://www.lpqz.cn/news/59898

---

## 5. 现状 vs 社区同硬件最优对比表

| 维度 | 本机现状 | 社区同硬件/同模型最优（他人实测） | 差距 | 优先级 |
|---|---|---|---|---|
| decode t/s（模型 A 35B-A3B Q5_K_P + MTP n=2） | **≈72.4 t/s**（2026-10-28 实测，今日未复测） | Strix Halo Vulkan 无 MTP 61.8（getrigbase）；1×RTX3090 CUDA+MTP 113（N卡不可比） | 本机已优于同硬件无 MTP 基线；n=3（A4）仍有空间 | P1 |
| MTP 接受率 | **79.4%**（n=2） | CSDN n=3 60.1% / n=4 52.4%；dev.to 对齐采样器后更高 | n 升会降接受率，需 A/B | P1 |
| prefill t/s | **≈169 t/s**（Vulkan，MoE+MTP，2026-09-14） | SpecPicks：35B **ROCm prefill +45~67%** 优于 Vulkan（A2 短板） | 纯 Vulkan prefill 为已知短板 | P0 |
| 上下文 | 262144（全量） | 同硬件可达 1M（lazy-mode） | 已全量，无差距 | — |
| KV 量化 | q8_0（ctk/ctv） | zimaspace 256K + KV q4 | q4 更省显存，质量需核 | P2 |
| 显存/统一内存车分（GTT） | 96 GiB UMA，模型 A 28GB，余量充足 | hyperpc：96GB 上限即 3× RTX5090 容量 | 容量无差距，带宽 215 vs 1792 GB/s 是物理上限 | — |
| 驱动栈（Mesa） | **26.0.8 钉死（apt hold）** | Nathanw1014 打包 26.2.4（本机不跟，26.2.5 致 Vulkan 全崩） | 维持钉死即最优稳定态 | P0 |
| 构建版本 | b10824（2026-10-24） | b12255（11-10），落后 **1431** | 缺失 #31185/#29791/#32045 等 | P1（C2 升级） |
| MoE 专家缓存 | 未开（A1） | savrn/moefast：默认 OFF 约减半吞吐 | 零成本候选，待 A/B | P1 |
| 模型 C（Flash-Next）在线 | **离线** | libosmos/ssdnodes 多路线可跑 768B/176B | 离线则无对标 | P2 |
| 导播台 render.steps | 12（draft） | 社区 20–30 | B2 漂移，成片偏激进 | P1 |
| 导播台 llm | 云端 MiniMax-M3.1-Flash | 本地 8080 可承载（若切回） | B3 与本地推理架构分离 | P2 |

---

## 6. 可立即执行的优化清单

### 6.1 改启动参数即可（无需重建，重启 llama-server 生效）
```bash
# A0【P0】收窄监听地址（连续 40+ 日 0.0.0.0，暴露面过大）
# 改启动参数 --host 127.0.0.1（仅本机），经 MCSManager 面板改实例命令后重启

# A1【P1】开启 MoE 专家缓存（b10824 已含 #29887 能力，默认 OFF 约减半吞吐）
# 在现有启动命令追加：--moe-cache-mib 8192
# 完整增量参数示例（追加到现有 ps 命令）：
#   --moe-cache-mib 8192
# 验证：重启后 /metrics 观察 throughput；与现状 72.4 t/s A/B

# A4【P1】MTP n-max A/B（当前 n=2 接受率 79.4%；社区 n=3 接受率回落但+15%）
# 改 --spec-draft-n-max 3，对比接受率与墙钟 t/s
```

### 6.2 环境清理（不改二进制）
```bash
# 清理无用监听噪音：18090 docproxy 的 comfyui.url 回退 8188（专项 #8 新漂移）
# 确认 config.json 中 comfyui.comfyui_url 应维持 ""（清理逻辑跳过），
# 若确需写回："sudo rocm-smi" 无关，直接 Edit config.json 该字段为 ""
# 注意：8188 当前无监听，仅日志噪音，非阻塞

# 本机 8219（npu_upstream）身份未明：若非预期服务，排查监听进程
ss -ltnp | grep 8219
```

### 6.3 需重启或重建（谨慎，含 mesa 备份）
```bash
# C2【P1】升级 llama.cpp 到 b12255（落后 1431 build，缺失 #31185/#29791/#32045）
# 前置（Mesa 硬约束）：先备份当前可用 deb，再升级，升级后必 vulkaninfo 验证
apt-get download mesa-vulkan-drivers libgl1-mesa-dri libglx-mesa0 libegl-mesa0 mesa-libgallium libgbm1
# 然后 git pull 上游 + 重建（本 fork 用 --target llama-server 避测试拖累）：
cd $HOME/llama-qwen4exp-rocmfpx
git fetch origin && git merge b12255   # 或 cherry-pick #31185/#29791/#32045
cmake --build build-vk4 --target llama-server -j16

# B2【P1】导播台成片步数回滚 20（对齐社区 20–30，当前 draft 12 偏激进）
# 改 config.json / render_profile.sh 的 quality steps=20（draft 可保留 12 仅作草稿）

# B3【P2】导播台 llm 一致性决策：本地 8080（Qwen3.6）或云端 MiniMax-M3.1-Flash，二选一并固化
```

---

## 7. 风险与验证

- **MTP 输出质量必须人工核对（llama.cpp #27950）**：本机接受率 79.4% 看似健康，但 dev.to deepu105 实测证明**采样器不对齐 drafter 会使接受率从 59.6% 塌到 45.7%、墙钟 2.8×**——本机 `--temperature 1.0 / top_p 0.95 / top_k 20` 与 MTP 头训练分布是否对齐未验证。**建议**：固定 seed 跑同一长文，逐 token 比对开启/关闭 MTP 的输出差异。新增 **#32045（DFlash 拒收位置 KV 回滚）** 正是该质量问题的上游修复，升级（C2）后应复测接受率与输出一致性。
- **`/props` 的 `speculative.types="none"` 是已知谎言**：永远以 `/slots[0].speculative` + `ps` 命令行 + `/metrics` 三处交叉验证为准（今日三处一致=True）。
- **构建版本滞后 1431 build**：缺失 #31185（外部 PLE）、#29791（Vulkan FP8）、#32045（MTP 质量），升级前务必按 Mesa 三步走（备份 deb → 验证内核兼容 → vulkaninfo 验证）。
- **Mesa 26.2.5 回归风险**：当前 26.0.8 已 `apt-mark hold`；任何系统级驱动升级前必须先备份 deb，升级后 vulkaninfo 验证再重启业务。
- **18090 新增 npu_upstream=8219**：身份未明，建议 `ss -ltnp | grep 8219` 确认是否为预期 NPU 代理，避免未知进程参与推理链路。

---

## 8. 今日相对昨日的新增项

> 昨日（2026-11-10）基线：`本地大模型/2026-11-10-本地大模型日报.md`

**增量（与昨日相比）：**
1. 🆕 **专项新漂移 #8**：`config.json` 实测 `comfyui.comfyui_url=http://127.0.0.1:8188`，与「10-20 已清空」记录不符（疑回退/展示层回落），需人工确认（8188 无监听，仅噪音）。
2. 🆕 **上游新 PR**：#32044（Qwen4-Exp/DeepSeek V4 NextN 隐藏层宽度，关联模型 C）、#32045（DFlash 拒收位置 KV 回滚，直接修复 #27950 MTP 质量）。
3. 🆕 **上游推进 +22 build**：b12233 → **b12255**（落后 1409 → **1431**）。
4. 🆕 **MTP 接受率回升**：77.1%（11-10）→ **79.4%**（今日 /metrics）。
5. 🆕 **P2 新增同硬件他人实测**：getrigbase Strix Halo 61.8 t/s（无 MTP，量化基线）；libosmos 768B 单 Strix Halo 40.8 t/s 草稿；CSDN MTP 接受率随 n 衰减曲线。
6. 🆕 **18090 代理新增 `npu_upstream=8219` / `npu_enabled=true`**（昨日仅记录 npu_enabled，今日确认上游地址 8219 有进程监听）。
7. 无实质新增：模型 C 仍离线、A0 host 未收窄、B2/B3 漂移持续、Mesa 钉死、#27950 人核待办均延续。

**待办延续（未解）**：A0 host 收窄(40+日) / A1 MoE 缓存 / A2 prefill 短板 / A4 n-max3+#27950 人核 / B2 steps 回滚20 / B3 llm 决策 / C2 升级 b12255(先备 mesa deb) / #27950 MTP 质量人核 / Mesa 26.0.8 钉死 / #31509 Vulkan NaN 监控 / 专项 #8 comfyui_url 回退确认。

---

*来源声明：本报 P0 数据来自 api.github.com（免登录，60 次/小时限额内）；P1 来自 hn.algolia.com；P2 来自内置 WebSearch（中文社区二手聚合，非站内直采）。所有性能数字均标注来源，本机未实测者标注「他人实测，待本机验证」。* 

---

> 许可：CC0-1.0，公共领域贡献，无任何限制。
