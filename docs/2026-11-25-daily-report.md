# 运行快照 · 2026-11-25（日报第 67 次）

来源：本机每日自动探测，2026-11-25 06:50–07:05 (GMT+8)，全 API 通道。
数据纪律：本机 curl 实测为唯一「本机事实」；社区数值一律标注「他人实测，待本机验证」并附来源 URL。

本期有实质新增（非注水），四条主结论：

① **首次带 key 完成 `/props`+`/slots`+`/metrics` 全字段实测**（11-24 因 401 未探成）；
② **decode 三测 76.96 / 79.99 / 79.34 t/s，中位数 79.34**（n128、temp 0、cache=false、GPU 空闲），落 68–88 区间中部；
③ **MTP 接受率 84.78%**（draft 49,242 / accepted 41,741），较 11-23 的 80.65% +4.13pp（样本条件不同，非同条件对比）；
④ **`#27950` 状态修正**：该 issue 的 fix 已随上游 #27694 于 2026-10-12 落地本机 fork（commit `a515d6093`），历史「未解」表述作废 —— 判断方法见 §四。

> 带 key 调用的通用形式：`curl -H "Authorization: Bearer <本机key文件读取>" http://127.0.0.1:8080/props`；key 存 600 权限文件，命令中禁止出现明文。

---

## 一、平台实测（全字段）

探测 06:52–07:00，进程 uptime ≈1 天 9 小时。

| 项 | 值 |
|---|---|
| 8080 | `/health`=`{"status":"ok"}`；`/props`、`/v1/models`、`/slots`、`/metrics` 带 key 全部 200 |
| 18090 docproxy | passthrough → 8080，`npu_upstream`=8219，`npu_enabled`=true |
| model | `Qwen3.6-35B-A3B-Uncensored-Q5_K_P.gguf`（Q5_K_M，26.1 GiB，34.66B） |
| n_ctx / n_ctx_train | 262144 / 262144；n_embd=2048（与 mmproj-F32 5120 **不兼容**，勿混用） |
| slots / 模态 | 1；vision+video，audio 关 |
| MTP（/props） | `"none"` ← **不可信，勿据此判 MTP 关闭** |
| MTP（/slots） | `"none,draft-mtp"`，`speculative=true` |
| 启动交叉验证 | `-md ...MTP-ONLY-Q4_K_M.gguf --spec-type draft-mtp --spec-draft-n-max 2` |
| 采样链 | penalties → dry → top_n_sigma → top_k → typ_p → top_p → min_p → xtc → temperature |
| chat_format / reasoning | peg-native / deepseek（`reasoning_in_content=false`） |
| build | b10824-75147a27e（源码 HEAD 75147a27e） |
| KV / cache | `-ctk/-ctv q8_0`，`--cache-idle-slots -cms 8192 --cache-ram 16384 --ctx-checkpoints 16` |
| **decode** | **76.96 / 79.99 / 79.34，中位 79.34 t/s**（n128, temp0, cache=false, GPU 58°C/1% 空闲） |
| prefill | 短样本 prompt_n=4/11（89–360 ms），**不可比，基线仍缺失** |
| **MTP 接受率** | **84.78%**（draft 49,242 / accepted 41,741，11-23 21:40 重启后累计约 1.4 天） |
| 模型 C | 离线（`Qwen3.8-Flash-Next-ROCmFP4-FAST-v2` 未加载） |

端口拓扑：`8080`=200（/health）｜`8081`=404（localrouter）｜`8000`=404｜`8219`=404（flm 根路径 404 属正常）｜`8082/8010/8086/11434`=000。

**MTP 三处交叉验证结论：启用**。判据固定为 `/slots` 的 `none,draft-mtp` + 进程 `--spec-type draft-mtp -md ...MTP-ONLY... -n-max 2` + `/metrics` 非零计数；`/props` 的 `none` 是误导项。

**基线订正**：11-24 记「未实测、维持 68–88」，本轮实测中位 79.34 落该区间中部。接受率 84.78% 较 11-23 的 80.65% 上升，但累计起点不同、样本量不同，不视为趋势。

---

## 二、MiniMax-H3 配置核查

`config.json` mtime 11-19，sd.cpp 空闲。B0/B1/B3–B7/B9/B10/B11 零漂移（详见 11-24 快照核查表）。

| 编号 | 检查项 | 结论 |
|---|---|---|
| B2 | steps=12、800×448 横屏、`cfg_scale=1.0` | ⚠️ 双漂移延续（steps/画布）；**本轮修正**：11-24 报「cfg 字段缺失」有误，`cfg_scale=1.0` 实际存在且值正确（蒸馏模型保持 1.0） |
| B8 | `comfyui_url`=`127.0.0.1:8188` | ⚠️ 漂移延续（8188 无监听，仅噪音；与早期「已清空」记录不符） |

**采集教训固化**：判定「字段缺失」前先核对字段实际路径与拼写 —— 11-24 的 cfg 误报即探查脚本字段路径写错所致。

---

## 三、上游动态（一手源）

- releases：**b12686**（11-24 22:45Z），较 11-24 的 b12655 +31 build；本机 b10824 落后 ≈**1862** build。来源 `api.github.com/repos/ggml-org/llama.cpp/releases?per_page=5`。
- 新 PR（均 open，11-24 22:00–22:50Z）：**#32839**（ggml-cuda HIP 用 readlane 替代 generic shuffle，AMD 相关）、**#31234**（CUDA/HIP flash_attn_tile 原生 q4_0/q8_0 KV，AMD 相关）、**#32936**（ggml 允许 axis-0 整行切分、single-token MQA，关联 issue #24015）、#32987（下载续传防混版本）、#32986/#32985（sampling adaptive-p clone）、#32984（CUDA FATTN combine 跳空）、#32983（TP 单设备分配）、#32971（OpenCL coopmat MoE）、#32081（batch invariance）、#32700（HRX 后端）、#31925（ERNIE 5.5）。
- issue：#24015（GGML_ASSERT axis-0 split，与 #32936 关联）、#32810（V100 1.0 prefill 回归，非本机）。
- gufo-org/gufo：11-24 五连（be751ce7 PNG 编码改 Rust 去 libpng、a3d7d934 递归 schema 语法检查、b572c240/b5ae75de CI 缓存、4203ab3a 递归 allOf）。
- kyuz0 11-18（00b6e5b）、Nathanw1014 10-25、drluoto 08-28 均无新提交；两个 MTP-Heads-GGUF 仓库持续 404。

## 四、★ PR 落地判断方法修正（重要）

历史用 `git merge-base --is-ancestor <PR号> HEAD` 判断上游 PR 是否在本机 —— **错误**：PR 号不是 git 对象，该命令报 `Not a valid object name` 且失败分支常被 `if` 静默吞掉。

正解：

```bash
git log --oneline --all --grep='#<PR号>' -i
```

本轮结果：

- **`#27950` 已修复落地** —— fork commit `a515d6093`（2026-10-12）cherry-pick 上游 #27694「Make the drafter probabilistic and the target verify by rejection sampling」，提交说明明确 `Fixes #27950 / closes #23335: draft-mtp changing deterministic output`。历史报告「#27950 未解」**作废**；输出质量抽检仍建议，但 n-max 调整后必须人工比对文本，禁止仅看 t/s。
- `#32839` / `#31234` / `#32936` 未落地（AMD 强相关，升级时优先 cherry-pick 评估）。

---

## 五、社区信息（他人实测，待本机验证）

1. **llamaperf**（11-24）：Qwen3.8 125B Flash-Next 在 4×R9700 + vLLM 0.29.3，MXFP4-FP8-GPTQ + FP8 KV + TP4 + MTP3，**248.5 t/s decode@concurrency1**、prefill 8.7k t/s —— 四卡数据中心配置，与本机单 APU 不可直接比。
2. **getrigbase AMD RDNA 实测表**：Flash-Next UD-IQ4_XS + 原生 MTP head + ngram-mod（ROCm）**31.7 t/s spec**，同配置无投机 16.8 t/s（+88%）；Q4_K_XL + KV q8_0 + EngramHalo.cpp 20.8 t/s。
3. **★ 1M ctx 来源核实（纠正原报告错误归属）**：`getrigbase.com/gpus/dgx-spark-gb10` 全文无 Strata 条目；1M/YaRN 条目全部属 DGX Spark（GB10）—— 2×DGX Spark vLLM Flash-Next 54.4 t/s（NVFP4, 262k·1M with YaRN）、单机 512k 48.7 t/s、27B 1M 58.3(TensorFold)/18.3(SGLang)。`llamaperf.com/report/027d02b5-...` 的 Strata 0.1.59 实测为 **181,072 ctx**（2×7900XTX, Q4_K_M, int8 KV, MTP~76%），**非 1M**。原「DGX Spark/Strata」并列表述已修正。
4. **modelfit.io**：Strix Halo Linux GTT 暴露约 110 GB 统一内存；35B-A3B est. 50 tok/s（±25%）、120B MoE 32、dense 70B 4；q8_0 KV 约减半。
5. **shattered.io**：PRO 495 Halo 192GB 可划 160GB 给 GPU；Max+ 395 128GB 典型 96GB（Windows）；128K 上下文显著吃内存，厂商标称参数上限仅短上下文有效。
6. **H3 参数共识（多篇独立教程）**：576×1024 竖屏 / steps 20–30（>70 收益极小）/ CFG 7–9（**蒸馏模型须 1.0**）/ 分块 VAE / 固定 seed / 8G 卡 12–16 步。
7. **HN**：llama.cpp 栏最新仍为 11-23 NariQ 帖（190 pts/36 评论），无新帖；local LLM 栏 11-24 新增 6 条（低分低相关，无 actionable 项）。

---

## 六、与社区同硬件对比

| 维度 | 本机（实测） | 社区同硬件（待验证） | 差距 / 优先级 |
|---|---|---|---|
| decode 35B-A3B | **79.34 t/s**（3 测中位，Q5_K_P+内嵌 MTP n=2） | 31.7（Flash-Next UD-IQ4_XS+MTP+ngram, ROCm）；50 est.（35B-A3B, modelfit） | 不同模型/量化非严格等价，P2 |
| decode 125B Flash-Next | 离线，无本机数据 | 90（2×7900XTX Strata, 181k ctx）；248.5（4×R9700 vLLM） | 未参与对比，P2 |
| prefill | **基线缺失** | 3200–5700（Strata 181k）；8656@2k（4×R9700 vLLM） | 长上下文短板，P1 |
| 上下文 | 262144 满训 | 1M 仅见 DGX Spark（YaRN）；**Strata 实测 181072，非 1M** | 未验证，P2 |
| KV | q8_0 | q4_0 KV（#31234 未落地，AMD 相关） | 等上游并 A/B 质量，P1 |
| MTP | n-max=2，接受率 **84.78%**，#27950 fix 已含 | n=2→73(86%)/n=3→76(78%)/n=4→77.7(67%)（他机）；Flash-Next MTP+11.5% | n=3 有余量但接受率递减，P1 |
| 驱动栈 | Mesa 26.0.8-1ubuntu0.3 hold（6 包） | Mesa 26.2.x 部分新特性，本机实测 Vulkan 初始化失败 | 钉死正确，P0 |
| huge pages | HugePages_Total=0、THP=madvise、glibc 2.43 | `GLIBC_TUNABLES=glibc.malloc.hugetlb=1`（他机 H100 +21%/L4 +6.5%） | 前置满足未启用，待 A/B，P1 |
| 安全 | `0.0.0.0` + 48 字符 key | 本地服务默认回环/带 auth | host 收窄 48+ 日未改，key 已补，P1 |

---

## 七、风险与验证

- **MTP 输出质量**：接受率 84.78% 为重启后累计（样本条件不同，不与前日比趋势）；#27950 fix 已落地，但 n-max 调整后仍须人工比对输出文本。
- **decode 基线**：79.34 为 3 次 n128 中位数，与 11-18 的 82.50、11-23 的 87.75 同区间抖动，不视为性能变化。复测须交错 A/B、GPU 空闲、带 key 调用。
- **API Key 保护**：无 key 访问 `/props` 返回 401 属鉴权正常；应用侧须确保代理链注入正确 key，18090 passthrough 当前可达。
- **上游差距扩大**：b10824 vs b12686（≈1862 build），本机为深度定制 fork，升级路径为 cherry-pick 评估。
- **数据校验**：P2 均为二手聚合（标注 URL），4×R9700 / 2×7900XTX 与单 APU 不可直接比较。

---

**许可**：CC0-1.0，公共领域贡献，无任何限制。
