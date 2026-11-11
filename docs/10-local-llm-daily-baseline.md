# 本机大模型运行基线快照（2026-11-06 日报）

来源：本机每日自动探测（无浏览器、全免登录 API 通道），2026-11-06 05:00 (GMT+8)。
本篇只保留**对部署有复用价值**的部分：实测基线表、参数漂移项、上游动态、优化候选清单、风险项。
日报里的一次性条目（当日离线原因、逐条待办编号）已删。

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
| 并发槽位 | `total_slots = 2` | `/slots` |
| 模态 | text + vision + video（mmproj f16） | `/props` |
| 投机解码 | `draft-mtp`，`--spec-draft-n-max 2`，MTP head 为 `Q4_K_M` | `/slots[0].params.speculative.types` + `ps` + `/metrics` 三处交叉验证 |
| KV 精度 | `-ctk/-ctv q8_0` | `ps` |
| decode 实测 | **72.41 t/s**（256 token，temp 0.6） | 本机实测 |
| MTP 接受率 | 77.1%（前一日 85.8%，有回落） | `/metrics` |
| 二进制 | b10824-75147a27e | 本机 |
| 监听地址 | `0.0.0.0`（连续 40+ 日未收窄） | `ps` |

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
| decode（35B-A3B MoE） | 72.41 t/s（MTP n=2） | MoE 专家缓存开启 + MTP n=3 可再提；缓存默认 OFF 时吞吐近减半 | 未开 `--moe-cache-mib`、n-max 偏低 |
| prefill | 169 t/s | gufo / 特定量化可到 ~1261 t/s；另有 HIP MoE prefill 回退 15–50% 的上游 issue | 本机 prefill 是短板，评估引擎而非只调参 |
| 上下文 | 262144 全量 | 社区多默认 128k 规避长 prefill | 一致 |
| KV cache | q8_0 | 上游有 Vulkan Q4_0 KV fast path（未合并进本机 build） | 可 cherry-pick |
| MTP 加速 | n-max 2，接受率 77.1% | n=3–5 可达 2.3–3.1×，但**采样器必须与 drafter 对齐** | 提 n-max 后需 A/B 质量人核 |
| 上游版本 | b10824 | 当日上游 HEAD 已领先约 1300 个 build | 含多个 MTP / ReBAR 性能 PR |
| 驱动栈 | Mesa 26.0.8 **钉死 + apt-mark hold** | 新版本可用但曾致 Vulkan 全崩 | 稳定性优先，刻意不跟 |
| 出片 steps | 12 | 20–30 | 回滚 20 |

---

## 五、可立即执行的优化候选（含代价）

### 改启动参数即可（经面板重启实例，禁止裸跑二进制）

```bash
# MoE 专家缓存（默认 OFF，开启后 MoE 解码可显著提速，需实测）
--moe-cache-mib 8192

# MTP draft 数从 2 提到 3（社区有翻倍案例，但接受率须重新测 + 质量人核）
--spec-draft-n-max 3

# 收窄监听地址（长期 0.0.0.0 属暴露面）
--host 127.0.0.1
```

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

> 通用纪律：任何外部速度数字先核对**模型量级、量化格式、窗口长度、后端**四要素，缺一项不得直接与本站基线比较。

---

**许可**：CC0-1.0，公共领域贡献，无任何限制。
