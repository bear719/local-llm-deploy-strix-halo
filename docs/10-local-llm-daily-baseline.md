# 本机大模型运行基线快照（起始 2026-11-06，持续更新至 2026-11-23）

来源：本机每日自动探测（无浏览器、全免登录 API 通道），起始 2026-11-06 05:00 (GMT+8)，随日报滚动修订。
本篇只保留**对部署有复用价值**的部分：实测基线表、参数漂移项、上游动态、优化候选清单、风险项、测速纪律、离线排障。
日报里的一次性条目（当日离线原因、逐条待办编号）已删；逐日明细见同目录 `2026-11-*-daily-report.md`。

> 修订原则：**结论被实测推翻时就地改写作废**，不并列保留两种说法。
> 已作废项：`--moe-cache-mib` 提速（见第五节）、「主 LLM 与渲染器无冲突」（见第八节）。

---

## 一、当日状态（重要：离线是常态而非故障）

| 现象 | 判定 |
|---|---|
| 8080 主推理端口无监听、无 `llama-server` 进程 | **预期行为**：出片前 GPU 仲裁器会暂停 MCSManager 面板的推理实例，渲染结束 `auto_resume` 自动恢复 |
| 18090 docproxy 在线但报 `upstream unreachable: Connection refused` | 上游 8080 被暂停时的正常连带表现 |
| 8000（导播台 API）、8081（localrouter，非推理本体）在线 | 与推理实例生命周期无关 |

**运维结论**：排障时先看「是否正在出片」。出片期间推理端口不通属设计内行为，不要误判为崩溃去重启实例。

---

## 二、当前运行方案实测基线

| 项 | 值 | 来源 |
|---|---|---|
| 模型 | `Qwen3.6-35B-A3B-Uncensored-Q5_K_P.gguf`（Q5_K_M，28 GB，34.66B 参数，MoE 激活 ≈3B） | `/props` + `ps` |
| `n_ctx` / `n_ctx_train` | 262144 / 262144（全量，未截断） | `default_generation_settings` |
| 并发槽位 | `total_slots = 1`（`-np 1`；早期快照曾为 2） | `/props` |
| 模态 | text + vision + video（mmproj f16） | `/props` |
| 投机解码 | `draft-mtp`，`--spec-draft-n-max 2`，MTP head 为 `Q4_K_M` | `/slots[0].params.speculative.types` + `ps` + `/metrics` 三处交叉验证 |
| KV 精度 | `-ctk/-ctv q8_0` | `ps` |
| decode 实测 | **68–88 t/s 区间**（2026-11-18~23 连续实测：82.50 / 81.88 / 82.33 / 81.6 / 81.69 / **87.75**；口径统一为 `n_predict=64`、temp 0、空闲态） | 本机实测，`timings.predicted_per_second` |
| MTP 接受率 | 80.6–81.6%（11-18~23 实测；**跨重启归零，仅同日可比**） | `/metrics` |
| 二进制 | b10824-75147a27e（上游已达 `b12633`，落后 ≈1809 build） | 本机 `/props` + releases API |
| 监听地址 | `0.0.0.0`（连续 46+ 日未收窄） | `ps` |

> 交叉验证方法值得复用：`/slots` 的 `speculative.types`、进程命令行参数、`/metrics` 里的 draft 计数三处若不一致，说明配置没真正生效。

---

## 三、参数漂移核查（config.json vs 旧记录）

出片侧配置与文档记录不一致时，**一律以 `config.json` 当日实际值为准**，并把旧记录作废。

| 项 | 旧记录 | 当日实际 | 判定 |
|---|---|---|---|
| 画布分辨率 | 576×1024 | `render 800×448`、`master 1920×1080`、`image 1024×576` | 旧记录过期 |
| `render.steps` | 20 | **12** | 低于社区质量档共识（20–30），建议回滚 20 |
| `cfg_scale` | 1.0（draft 档） | 1.0 | 一致 |
| `lora_scale` | draft 档须走环境变量 | `render.lora_scale = 0.0` + `SDCPP_LORA_SCALE=1.0` | 一致（config 内改 LoRA 无效是已知坑） |
| `SDCPP_EXTRA_ARGS` | `--vae-tiling` | `--vae-tiling` | 一致 |
| 仲裁器 `need_gib` | 64 | 64，`auto_resume=true` | 一致 |
| 附加核实 | — | sampler `res_multistep`、scheduler `simple`、fps 24、母版 libx264/crf18/veryfast、音频 `loudnorm I=-16:TP=-1.5:LRA=11` + 44100 Hz | 与质检修复结论一致 |

**MiniMax-H3 参数社区共识**（用于校准，非本机实测）：

- 质量档：steps **20–30**、CFG 3–7
- 低显存 / ComfyUI 档：steps 14、CFG 5.0、736×416、8 帧
- Turbo LoRA（draft 档）：steps **4–8**、CFG 1.0–7.0、LoRA 权重 0.7–1.0 → 本机「4 步 + LoRA 1.0」获社区背书
- block cache / 上下文帧数 1–4 可降显存

---

## 四、现状 vs 社区同硬件最优（差距表）

| 维度 | 本机现状 | 社区同硬件参考 | 差距 / 动作 |
|---|---|---|---|
| decode（35B-A3B MoE） | **68–88 t/s 区间**（2026-11-18~23，MTP n=2） | 同模型 Q4_K_M + MTP **93 t/s**（同硬件 Vulkan）；无 MTP 62 t/s；UD-Q4 MTP n=4 约 77.7 t/s（Metal 另类硬件） | 已第一梯队；`--moe-cache-mib` 在 `-ngl 999` 下被自动禁用，**该候选作废**；n-max 3→4 或有 +3~6%（需质量人核） |
| prefill | 短样本无效；历史 `/metrics` avg 约 365 | pp512 414（27B Q4）；pp8192 1409（30B-A3B） | **本机短板**，标准复核须 `llama-bench -p 512`；勿引用短样本数字 |
| 上下文 | 262144 全量 | 社区多默认 128k 规避长 prefill；**实测长窗口会吃掉大部分 MTP 收益（空窗 3.1× → 256K 1.15×）** | 本机满配，长会话下需单测 MTP on/off |
| KV cache | q8_0 | 上游有 Vulkan Q4_0 KV fast path（未合并进本机 build） | 可 cherry-pick |
| MTP 加速 | n-max 2，接受率 80.6–81.6%（11-18~23） | n=2→73.0 / n=3→76.0 / n=4→77.7 / n=5→74.7 t/s（M2 Ultra 同模型）；**采样器必须与 drafter 对齐**，否则接受率 59.6%→45.7% 且墙钟慢 2.8× | 提 n-max 后需 A/B 质量人核；接受率下滑时优先试换 Q8 草稿头 |
| 上游版本 | b10824（11-23 落后 **1809** build） | b12633（2026-11-22 14:53Z） | 定制 fork **不可整包替换**，只做 cherry-pick 评估；先备 mesa deb |
| 驱动栈 | Mesa 26.0.8 **钉死 + apt-mark hold** | 新版本可用但曾致 Vulkan 全崩 | 稳定性优先，刻意不跟 |
| 出片 steps | 12 | 20–30 | 回滚 20 |

---

## 五、可立即执行的优化候选（含代价）

### 改启动参数即可（经面板重启实例，禁止裸跑二进制）

```bash
# 【P0，2026-11-18 新增】让 glibc malloc 走 huge pages：零代码、零 root、无需改任何 llama flag
#   前置：glibc >= 2.35（本机 2.43 ✅）、THP 含 madvise（本机 `always [madvise] never` ✅）
GLIBC_TUNABLES=glibc.malloc.hugetlb=1 <原启动命令，参数不变>
#   验证生效（非 0 才算生效）：
grep AnonHugePages /proc/$(pidof -s llama-server)/smaps_rollup
#   他人实测：H100 tool-calling +21% RPS / 首 token +22%；L4 +6.5%；8B plain chat 无增益；
#   页错误 ~124,000 → ~1,850 次/请求。收益与 GPU 速度正相关，本机 82.5 t/s 档预计中等。
#   ⚠️ 必须交错 A/B（预热 2 次丢弃 → 加/不加各 3 轮交替），分组跑会被温升污染。

# MTP draft 数从 2 提到 3（社区 n=3 拐点，但接受率 86%→78%、PP 掉约 17% + 质量人核）
--spec-draft-n-max 3

# 收窄监听地址（长期 0.0.0.0 属暴露面）
--host 127.0.0.1
```

> ⚠️ **`--moe-cache-mib 8192` 已被判定作废（2026-11-16）**，别再照抄。
> 机制：缓存只服务于**留在主机内存**的专家权重，必须配合 `-cmoe` / `-ncmoe` / `-ot` 让部分专家层不上显存，
> 且只对 **≤32 token batch（decode）**生效；`-ngl 999` 全 offload 时"没有任何层的专家留在主机内存"，
> llama.cpp 会**警告并自动禁用缓存**。要做就必须先搭 A/B（A 组全 offload 基线 / B 组用 `-ncmoe` 留层后再开缓存），
> 且作者在 RTX 5090 上的 2.2×、双卡测试者反而变慢 —— **不可跨硬件外推**。

### 出片侧

```bash
# 回到社区质量档基线（编辑出片工作台 config.json）
# render.steps: 12 -> 20
```

### 需要重启或重建

```bash
# 升级 llama.cpp 前先备份 Vulkan 驱动包（升级破坏 Radv 是高频事故）
apt-get download mesa-vulkan-drivers libgl1-mesa-dri libglx-mesa0 libegl-mesa0 mesa-libgallium libgbm1

# fork 分支重建（上游 master 不认私有量化类型）
cd $HOME/llama-qwen4exp-rocmfpx && git pull && cmake --build build-vk4 --target llama-server -j16

# Mesa 维持 apt-mark hold，任何系统级升级后先 vulkaninfo 验证再上生产
```

> `--mlock --no-mmap` + tmpfs 承载模型可把写放大从 6:1 降到 1:1，但前提是 tmpfs 容量 ≥ 模型体积，host RAM 不足时不可用。

---

## 六、风险清单

| 等级 | 风险 | 处置 |
|---|---|---|
| 高 | **MTP 输出质量**：接受率回落（85.8% → 77.1%）；社区实测采样器与 drafter 不一致时接受率 59.6%→45.7%、墙钟耗时 2.8× | 保持 `--temperature 0.0` + `--spec-draft-p-min 0.0` 对齐 drafter；提 n-max 后必须人核输出 |
| 中 | 8080 离线被误判为崩溃 | 先确认是否在出片；仲裁器 `auto_resume` 会在渲染结束后恢复 |
| 中 | 上游 HIP MoE prefill 回退 15–50% | 升级前在长 prefill 场景做对照，避免引入回退 |
| 低 | Vulkan 驱动栈漂移 | Mesa 26.0.8 钉死有效，26.2.x 曾致 Vulkan 全崩；升级前备 deb + `vulkaninfo` |

---

## 七、社区结论采纳原则（怎么读别人的数字）

| 结论 | 原文要点 | 本机怎么用 |
|---|---|---|
| MTP 数并非越大越好 | 某 Strix Halo 128 GB 实测 n=5 最佳、MTP 带来 2.3–3.1×；`--temperature 0.0` 时接受率 59.6%，官方采样降到 45.7% | 取「采样器对齐 drafter」这条方法论，不取绝对值 |
| n-gram 表不占权重 | 176B 模型里有 51B 是 n-gram 查表（非权重），故 85 GB 量化可在 64 GB 机器上以 36 t/s 跑，表常驻 SSD | 解释了 Flash-Next 的 `--ngram-on-disk` 收益来源 |
| 自动 fit 会误分配 | llama.cpp 自动 fit 在超大模型上会误分配导致 OOM，须 `-fit off` | 加载 Flash-Next 类超大模型时必填 |
| 同硬件 27B Vulkan 横评 | Q4_K_M 16.8 / Q6_K 14.2 / Q8_0 11.3 t/s | 仅作旁证，与 MoE 35B-A3B 不可比 |
| 低可信度内容 | 有文称 176B 模型 BF16 仅 8.6 GB，与体量严重矛盾 | `[UNVERIFIED]`，只采信其中可独立验证的部分（如「Vulkan 后端须自行编译」） |
| 「MoE 投机陷阱」-60% | 35B-A3B UD-Q4 无 draft 43.1 t/s，加 1.5B **独立 draft 模型**降到 17.5 t/s，归因「专家加载税」 | **不适用于内嵌 MTP**：本机 draft 是主模型自带的 MTP heads（`-md` 只加载 heads），实测 80–88 t/s。该文的结论边界是「独立 draft 模型 + 专家模型」组合，**不要拿来否定 MTP** |
| 判断「上游 PR 是否已在本机」 | — | **禁用 `git merge-base --is-ancestor <PR号> HEAD`**（PR 号不是 git 对象，报 `Not a valid object name` 且失败分支常被 `if` 静默吞掉）。正解：`git log --oneline --all --grep='<PR号>' -i` |

> 通用纪律：任何外部速度数字先核对**模型量级、量化格式、窗口长度、后端**四要素，缺一项不得直接与本站基线比较。

---

## 八、测速纪律：并发渲染会污染一切数字（2026-11-15 实测）

| 指标 | 空闲态基准 | 渲染并发窗口内 | 幅度 |
|---|---|---|---|
| decode | 72.41 t/s（11-04，temp0） | **17.28 t/s** | **-76%** |
| prefill | ~400 t/s（09-24） | 621 t/s（4001 tok / 6.44 s） | 数值反而更高，**同样不可用** |

根因：`gpu_arbiter` 对 image 档（800×448 / 20 步）判定在预算内，**不会暂停 llama**，
于是主 LLM 与 sd.cpp 在同一 GPU 后端上硬争抢。端口层面确实"无冲突"，**负载层面冲突极严重**。

**三条铁律**：

1. 测速前先 `pgrep -c sd-cli`，**返回非 0 则本次数字全部作废**，不做解释性辩护。
2. prefill 在争用下会"看起来更快"，单次测量完全不可信 → 必须多次均值 + 方差，且与无干扰对照跑。
3. 要保主 LLM 响应质量，要么提高 `arbiter.need_gib` 让 image 档也触发暂停，要么错峰调度渲染。

> 反过来说：**旧文档里"主 LLM 与渲染器无冲突"的表述只在空闲态成立**，已在本条作废。

---

## 九、离线排障：三种"不通"必须分清（2026-11-16）

| 现象组合 | 判定 | 处置 |
|---|---|---|
| 8080 不通 + 有渲染进程 + 显存占用高 | 仲裁器**按设计**暂停了推理实例 | 等渲染结束 `auto_resume`，**不要重启** |
| 8080 不通 + 无渲染进程 + **显存占用 0%** | **实例根本没被拉起**（非崩溃、非争用） | 经面板 API 拉起实例，别去翻崩溃栈 |
| 8080 通但 18090 报 `upstream unreachable` | 代理与模型是**独立进程**，一个通 ≠ 另一个通 | 先修 8080 再验 18090 |

**端口指纹**（根路径 404 不等于服务坏了）：

| 端口 | 身份 | 健康形态 |
|---|---|---|
| 8080 | llama-server 真模型 | `/props`、`/v1/models` 返回正常 JSON |
| 18090 | docproxy 代理 | `{"status":"ok","proxy":"docproxy","mode":"passthrough",...}` |
| 8219 | flm NPU 微服务（翻译/ASR/embedding） | 根路径 404 属正常 |
| 8000 | 导播台 API（FastAPI） | 根路径 404 `{"detail":"Not Found"}` 属正常 |
| 8081 | localrouter 路由层 | 根路径 404 属正常 |
| 5173 | 导播台前端 | HTTP 200 |
| 8188 | ComfyUI（已弃用） | 000 无监听 |

> 另一类隐性坑：**MTP 累计接受率跨重启不可比**。`/metrics` 计数器随服务重启归零，
> 比较接受率前先看进程 `lstart`；若当日有重启，前一日的稳态值直接作废。

---

## 十、配置类修复的验证纪律（2026-11-23）

典型复发案例：`comfyui_url` 在某个时间点「已清空」，几天后巡检又发现指回 `127.0.0.1:8188`。

原因不是没改，而是**改完没回读**——写盘失败、被默认值回填、或被另一次配置写入覆盖，都能让改动在无人察觉时消失。

三条纪律：

1. **改完立即回读**，打印关键字段实际值（不是打印「已改为 X」）；
2. **改动前 `cp -a config.json config.json.bak.$(date +%Y%m%d-%H%M%S)`**，备份才允许回滚；
3. **配置类修复与文本类修复分开记账**，配置是「状态」，会漂移，需要每轮巡检复核；文档是「快照」，不需要。

> 同理适用于启动参数：面板改完要从 `ps` 命令行回读一遍，确认新参数真的进了进程。

---

**许可**：CC0-1.0，公共领域贡献，无任何限制。
