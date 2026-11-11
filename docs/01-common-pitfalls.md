# 通用踩坑清单

跨模型、跨工具的共性坑。按模型专属的坑见各 `models/<x>/` 目录。

## 反代 / SSE（以 `tools/docproxy` 为例）

- **SSE 反代严禁把短心跳值赋给 `socket.settimeout`**：超时后 CPython 把 socket 永久置 `timed_out`，
  此后任何 read 抛 `OSError("cannot read from timed out object")`（**普通 OSError，不被
  `socket.timeout` / `TimeoutError` 捕获**）→ 漏到外层 → 502 / 客户端 aborted。
  **正解**：socket 用长超时兜底（如 600s），心跳用 `select.select([fd],[],[],HEARTBEAT_SEC)` 轮询发
  SSE 注释 `: keep-alive\n\n`。**永远不要**写 `sock.settimeout(心跳秒数)`。
- **必须手动解码 chunked 上传**：大 body（如 WorkBuddy 注入 40K+ tokens）走
  `Transfer-Encoding: chunked` 且无 Content-Length，反代只认 Content-Length 会读空 body → 上游 500。
  需自行解码 chunked。

## 缓存与多轮

- `--cache-reuse` 在 `--mmproj`（多模态）下被**自动禁用**（日志
  `cache_reuse is not supported by multimodal`），仅纯文本档有效
- 多轮加速真正来源 = `--cache-idle-slots` + slot 内置 LCP 前缀复用
  （同会话轮次间实测 18~202×）；**不是** `--cache-reuse`
- `-cms` = `--checkpoint-min-step`（短选项；长选项 `--cms` 本 build 不支持，启动即退出）；
  超长上下文续写更稳，保留在长上下文档

## 投机解码（MTP）

- `-np > 1` 时 `draft-mtp` 存在 **cross-slot contamination**（上游 PR #28123 作者声明）：
  请求间内容串扰。开多槽前必须专项验证
- `--spec-draft-n-max` **越小越快**：1~2 最优；≥8 直接崩塌 65~74%（接受率暴跌 +
  草稿模型 `nextn_predict_layers=1` 走串行循环，draft N 个 token 要跑 N 次前向，成本线性叠加）。
  `--spec-draft-p-min` 在噪声内，保持默认不设
- `/props.params.speculative.types` **恒为 `none`（假象）**；真凭据说
  `/slots[0].params.speculative.types` 与 `ps` 命令行里的 `-md` / `--spec-type`

## 量化 / 二进制

- 私有量化 type 101/104（ROCmFP4_FAST / Q3_0_ROCMFPX）只有 `vulkan/qwen4exp-rocmfpx`
  分支二进制能加载；上游任何构建一律 `invalid ggml type`
- mmproj 必须匹配主模型 embedding 维度（35B-A3B 用 `*-f16.gguf`；27B 用 `mmproj-F32.gguf`），
  用错启动即 `mismatch between text model and mmproj`

## 客户端报错

- `400 Failed to tokenize prompt` + `media markers ... exceeds number of bitmaps`：
  纯文本请求被注入 `<__media_...__>` 占位符却未附图片。新开对话绕过；
  中期查代理 `X-Trim-Prompt` 裁剪是否误留 marker，或客户端纯文本请求不应注入 media marker

## prompt cache 吃 host RAM（2026-10-08 定位，最容易误判）

- 参数 `--cache-ram N`（短 `-cram`），**默认 8192 MiB = 8 GiB**
- `--cache-idle-slots` 依赖它：新任务到达时把空闲 slot 的 KV **序列化进 host RAM**，
  再清空 device KV → 本质是「用 host RAM 换显存」
- 症状：llama-server 用久了 host 内存上涨、重启就变小；`RssAnon ≈ 8.37 GiB ≈ 8192 MiB + 基础开销`
- 日志特征：反复 `making room for prompt cache entry, removing oldest entry (size = ~126 MiB)`
- 本机 carve-out 余 52 GiB、host 仅 30 GiB → **方向相反**，应降到 `--cache-ram 1024`（省约 7 GiB）；
  完全禁用用 `0`，但 `--cache-idle-slots` 要求 cache-ram > 0，须一并去掉
- 交叉验证：Vulkan 的权重/KV/计算缓冲全落 carve-out，GTT 稳定 1.69 GiB 零增长
