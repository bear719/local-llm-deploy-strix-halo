# Qwen3.6-35B-A3B 实测与验证记录

# 35B-A3B 压力测试 + docproxy(18090) 修复后验证

- 时间：2026-10-02 21:45–21:46（Asia/Shanghai）
- 执行人：管家（WorkBuddy）
- 脚本：`tools/bench-stress-35b.py`，默认 `CONCURRENCY=5`
- 原始日志：`/tmp/bench-8080-214518.log`、`/tmp/bench-18090-214518.log`
- 代理日志：`/opt/mcsmanager/daemon/data/InstanceLog/d81ea6096b1c46709f9d9b43fc8137f7.log`

## 被测对象

| 项 | 值 |
|---|---|
| 推理服务 | `llama-server` :8080，`-np 1 -c 262144 -b 4096 -ub 1024` |
| 模型 | `Qwen3.6-35B-A3B-Uncensored-Q4_K_P.gguf` |
| 投机解码 | `--spec-type draft-mtp -md Qwen3.6-35B-A3B-MTP-ONLY-Q4_K_M.gguf --spec-draft-n-max 2` |
| 代理 | `docproxy.py` :18090 → :8080，`PROXY_MODE=passthrough`，`INJECT_NO_THINK=1` |
| 代理版本 | 2026-10-02 21:35 补丁版（chunked 终止 + 上游状态码转发 + 心跳 + 访问日志） |

两轮串行执行：**8080 直连作基线，18090 经代理作对照**。

## 结果

### 1. 并发（5 请求同时发，`max_tokens=16`）

| 指标 | 8080 直连 | 18090 经代理 |
|---|---|---|
| 成功率 | 5/5 (100%) | 5/5 (100%) |
| 总耗时 | 0.56 s | 0.54 s |
| 总生成 token | 10 | 10 |
| 吞吐量 | 17.7 t/s | 18.5 t/s |

注：`-np 1` 单槽，5 个请求是串行处理，此处的"并发"只验证排队与成功率，不代表并行吞吐。

### 2. 长上下文生成（`max_tokens=1024`）

| 用例 | 8080 直连 | 18090 经代理 |
|---|---|---|
| 用例 1 | 12.35 s / 1024 token / **82.9 t/s** | 10.16 s / 783 token / **77.0 t/s** |
| 用例 2 | 12.10 s / 1024 token / **84.6 t/s** | 4.95 s / 374 token / **75.6 t/s** |

差异来源：18090 默认注入 `enable_thinking=false`，答案更短、自然停止（783/374 token）；
8080 直连带思考链，1024 上限被打满。同口径下解码速度均在 **75–85 t/s**。

### 3. 多轮对话（4 轮，`max_tokens=128`）

| 轮次 | 8080 直连 | 18090 经代理 |
|---|---|---|
| 1 | 1.51 s | 1.89 s |
| 2 | 1.55 s | 1.98 s |
| 3 | 1.60 s | 1.84 s |
| 4 | 1.69 s | 2.00 s |

每轮累积上下文，延迟随轮次缓慢上升，符合预期。

### 4. 流式 vs 非流式（`max_tokens=64`）

| 提示 | 8080 非流式 / 流式 | 18090 非流式 / 流式 |
|---|---|---|
| 只回复两个字：收到 | 0.73 s / 0.72 s | 0.16 s / 0.09 s |
| 1+1 等于几？ | 0.78 s / 0.79 s | 0.25 s / 0.11 s |
| 荒原狼讲了什么？（一句话） | 0.73 s / 0.73 s | 0.81 s / 0.91 s |

**关键**：修复后流式请求全部正常结束，无一例悬挂（修复前读流式 20 s 必然 `TimeoutError`）。
流式与非流式耗时在同一量级，chunked 编码未引入可测开销。

### 5. 投机解码（MTP）

| 指标 | 本次（累计，自服务启动） | 参考（2026-10-02 上午） |
|---|---|---|
| 接受率 | **80.4%** (8062/10029) | 74.4% (457/614) |
| 每步平均接受 | 1.61 token | 1.99 token |

数据来源：`/metrics`（`spec_decode_num_accepted_tokens_total` / `spec_decode_num_draft_tokens_total`）。
该端点仅 8080 提供，18090 不转发（代理只透传 `/v1/*`），故只有基线轮有值。

### 6. 代理侧健康度

压测期间 `docproxy` 累计 228 条请求记录，无 `转发异常`，无新增 4xx/5xx
（日志中 2 条 500 为压测前手动构造的空 `messages` 错误用例）。

## 结论

1. **修复有效**：18090 流式响应正常终止（HTTP/1.1 + chunked + `0\r\n\r\n`），
   压测 0 悬挂、0 错误，并发成功率 100%。
2. **代理开销可忽略**：并发 0.54 s vs 基线 0.56 s；解码 77 t/s vs 83 t/s（跨口径，含思考链差异）。
3. **模型健康**：解码 75–85 t/s，MTP 接受率 80.4%。

## 遗留风险

- **单槽串行（`-np 1`）未解**：压测流量与 agent 自身推理请求抢同一槽位，
  叠加长上下文 prefill，仍会出现"前端长时间无输出"。压测请走独立实例/端口，
  或把输出重定向到文件只给模型看摘要。
- 不建议为并发改 `-np > 1`：MTP 在 `-np > 1` 下存在 cross-slot contamination
  （上游 PR #28123 作者明确声明），需专项验证后再动。

---

# 35B-A3B 速度复测（2026-10-03）

- 时间：2026-10-03 14:55–15:00（Asia/Shanghai）
- 执行人：管家（WorkBuddy）
- 脚本：`tools/bench-35b-20261003.py`（纯文本，每条请求 prefix 带随机 uuid，规避 `--cache-idle-slots` 的 LCP 前缀复用秒回）
- 被测实例：`llama-server` :8080（同 `start-qwen36-35b-a3b.sh` long 档，`-c 131072 -np 2`，MTP n-max=2，mmproj 多模态）

## 实测数据

### 1. 短上下文 decode（3 次，短 prompt + max_tokens=256）

| 次 | prefill (t/s) | decode (t/s) | 生成 token | wall |
|---|---|---|---|---|
| 1 | 150.36 | 83.12 | 256 | 3.88s |
| 2 | 205.60 | 92.26 | 256 | 3.10s |
| 3 | 215.41 | 90.14 | 256 | 3.04s |

- decode 中位 **90.14 t/s**（区间 83.12~92.26）
- prefill 中位 205.60 t/s（小 prompt 含启动开销，仅供参考，不代表长 prefill 速率）

### 2. 长上下文 prefill（2 次，~308KB 纯文本 prompt，带随机 uuid 前缀）

| 次 | prompt_tokens | prefill (t/s) | wall |
|---|---|---|---|
| 1 | 89144 | 521.51 | 171.27s |
| 2 | 89140 | 519.59 | 172.34s |

- 长 prefill 稳定 **~520 t/s**（89K tokens / ~171s）

### 3. MTP（投机解码）

| 口径 | 接受率 | draft / accepted / steps | 每步接受 |
|---|---|---|---|
| 本次短测增量 | 79.1% | 592 / 468 / 297 | 1.58 token |
| 自服务启动累计 | **77.4%** | 100385 / 77648 / 50197 | 1.55 token |

## 对比历史（2026-10-02 上线验证）

| 指标 | 2026-10-02 | 2026-10-03 | 变化 |
|---|---|---|---|
| decode 中位 | 85.46 t/s（82.66~91.46） | 90.14 t/s（83.12~92.26） | ↑ 略升，正常波动 |
| prefill 小 prompt 中位 | 152.85 t/s | 205.60 t/s | ↑ 方差内 |
| prefill 长上下文 | 无记录 | 520 t/s（89K tok） | 新增 |
| MTP 接受率（累计） | 74.4%（457/614） | 77.4%（100385/77648） | ↑ 2.9pp |
| MTP 每步接受 | 1.99（n-max=2 满载） | 1.55（短请求未打满） | ↓ 口径差异 |

## 结论

1. **模型健康**：decode 83~92 t/s，长 prefill ~520 t/s，MTP 接受率 77.4%，无退化。
2. **与 38 档对比**：35B-A3B（MoE）decode ~90 t/s，38 档 imatrix-v2（dense 27B）32~40 t/s，本档快约 2.2 倍（来源：`start-qwen36-35b-a3b.sh` 注释）。
3. **异常记录**：memory 中「308KB 请求体 → prefill ≈ 26s」与本次 171s 不符。本次为带 `--cache-idle-slots` + MTP 的实测值，以本次 520 t/s 为准；memory 旧记录疑似口径不同（小规模或不同 token 密度），待核。

## 关联事件（本机 400 错误）

测速前少爷报告 `400 Failed to tokenize prompt` + `mtmd_tokenize: error: number of media markers in text (1) exceeds number of bitmaps (0)`。

- 根因：本次对话请求（task 30257 之后新请求，75K tokens）由 WorkBuddy 客户端构造，消息文本含 **1 个 media marker**（`<__media_...__>` 或 `<|vision_start|>...<|vision_end|>`），但**未附任何图片**（bitmaps=0）。
- 当前实例 `modalities.vision=true`（带 mmproj），`media_marker=<__media_GJYdua2Gvoq3jFek9IJonb87mQYUuKfK__>`，纯文本请求不应带该占位符。
- 修复：开新对话（不带历史图片上下文）即可绕过；中期需查 docproxy `X-Trim-Prompt` 裁剪是否误留 marker，或客户端纯文本请求不应注入 `<__media_...__>`。
- 该错误与模型性能无关：task 30257 本身正常跑完（draft acceptance 90.4%，75969 tokens）。
