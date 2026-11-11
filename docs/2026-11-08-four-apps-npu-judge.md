# 四应用接入 NPU 旁路 + judge 链路优化（2026-11-08 22:00–22:25）

> 起因：少爷点名 `openclaw / workbuddy / claude code / 导播台` 四个应用要接 NPU。
> 结论先行：**三个接上了（含导播台零代码），Claude Code 协议不通接不了；
> 但顺手挖出两个真实性能坑，收益远大于 NPU 分流本身。**

---

## 一、结论摘要

| 应用 | 接入结果 | 实际路径 |
|---|---|---|
| **WorkBuddy** | ✅ 已加可选条目 | `models.json` 新增 `lfm2.5-it:1.2b` → 18090，默认模型未变（仍 20+1 条，[0] 仍是 Flash-Next-imatrix-v2） |
| **OpenClaw** | ✅ 已加 provider + 白名单 | `npu` provider → 18090；`modelPolicy.allow` 已含 `npu/lfm2.5-it:1.2b`；默认仍是 `llamacpp/…Q5_K_P` |
| **导播台** | ✅ **零代码继承** | `openclaw_bridge.py` 自动把 OpenClaw providers 翻成预设，已实测出现 `OpenClaw · npu` |
| **Claude Code** | ❌ 接不了 | flm 无 `/v1/messages`（实测 404），且 1.2B 扛不住代码任务 |

**关键判断：没有任何一个应用被改成「默认走 NPU」。** 全部是「多一个可选项」。
把 Claude Code 或导播台的默认模型换成 1.2B 会直接毁掉它们的能力，这不在讨论范围。

---

## 二、四个应用的真实接入点

### 2.1 WorkBuddy
- 配置：`~/.workbuddy/models.json`（数组，2 空格缩进）
- 新增条目追加到**末尾**（不插开头，避免改变「第 0 条 = 默认模型」的既有行为）
- `maxInputTokens` 标 **8192**（按 flm `--ctx-len 8192` 实配），没有沿用 262144 —— 标大了会骗客户端塞长上下文进去然后爆
- `supportsToolCall: false`，`supportsImages: false`，`supportsReasoning: false`

### 2.2 OpenClaw —— 三处，缺一不可
| 文件 | 改动 | 作用 |
|---|---|---|
| `~/.openclaw/openclaw.json` → `models.providers.npu` | 新增 provider | 定义模型来源 |
| 同上 → `agents.main.models["npu/lfm2.5-it:1.2b"]` | 新增条目 | 让 agent 能看见 |
| 同上 → `agents.main.modelPolicy.allow` | 追加一条 | **这才是真正的白名单** |

> `agents/main/agent/models.json` 也加了同样的 provider，但**它是无效的** —— 见 2.5 的 schema 问题。

### 2.3 导播台 —— 零代码
`src/drama_series_agent/openclaw_bridge.py` 的 `load_openclaw_presets()` 会遍历
`~/.openclaw/openclaw.json` 的 `models.providers`，每家取 `_first_model_id()` 作为 model。
所以**改 OpenClaw 一处，导播台自动多一个选项**。实测 11 条预设：

```
OpenClaw · llamacpp   http://127.0.0.1:18090/v1   Qwen3.6-35B-A3B-Uncensored-Q5_K_P.gguf
OpenClaw · npu        http://127.0.0.1:18090/v1   lfm2.5-it:1.2b     ← 新增，自动出现
```

注意 bridge 是**只读**的，不会回写 OpenClaw。

### 2.4 Claude Code —— 为什么接不了
链路：`settings.json` → `ANTHROPIC_BASE_URL=http://127.0.0.1:8099` →
`~/.workbuddy/skills/local-agent-orchestrator/scripts/anthropic-fix-proxy.py`
（只做 system 消息合并，`UPSTREAM = http://127.0.0.1:8080`，**绕过 18090**）→ llama.cpp `/v1/messages`。

三个硬障碍：
1. **协议不通**：flm 只提供 OpenAI 端点。实测 `POST 8219/v1/messages` → **404**。
2. **没有 header 通道**：Claude Code 不能发 `X-Backend: npu`；只能靠换 base_url 或换 model 名。
3. **能力不匹配**：Claude Code 的活是代码编辑 + 多轮工具调用，1.2B 做不了。
   即便打通协议，也只会得到一个「能返回文字但不可用」的模型。

**要做的话**得写一个 anthropic↔openai 双向转换层，且只值得给 Haiku 位的后台小任务用。
这是新增失败点，不做。

### 2.5 一个既有配置问题（不是我引入的）
OpenClaw 启动日志：
```
[agents/model-registry] model catalog load issue: Invalid models.json schema:
  - providers.247.apiKey: must be string
  - providers.550.apiKey: must be string
  ... 全部 9 家都报，含未改动的
```
`agents/main/agent/models.json` 里 `apiKey` 写成了 `{"source":"env","id":"..."}` 对象，
而当前 OpenClaw（2026.9.4）的 zod schema 要求字符串 → **整份文件被忽略**。

**已核实是既有问题**：13:40 首次启动就报，14:25 也报过。所以：
- 我往这个文件加的 npu provider 实际不生效（但也没害）
- OpenClaw 真正生效的配置源是 `openclaw.json`（上面 2.2 的三处）
- 修它需要把 apiKey 改成字符串字面量，会动到 9 家既有 provider → **未擅自处理**

---

## 三、judge 迁移 NPU：被数据否决

### 3.1 为什么先试这个
OpenClaw 的分层路由链路：

```
OpenClaw → 8081(router.py) → judge.choice 定档 → cheap(18090) / reasoning(DeepSeek 云端)
```

judge 是**高频、短输入、只输出一个 JSON、要确定性**的调用 —— 教科书级的 NPU 小模型场景。
而 cheap 档承接「日常对话/改写/摘要」，绝不能用 1.2B 替换。

### 3.2 实验（`tools/bench-judge-npu.py`，20 条样本，A/B 交错）
| 指标 | 35B @8080 | 1.2B @8219 |
|---|---|---|
| 档位一致率 | — | **0/20 = 0%** |
| 单次延迟中位 | 13.24 s | 0.79 s |
| 解析失败 | 2/20 | **20/20** |

失败原因不是超时，而是**不遵守枚举约束**：
```
choice 非法: '简单问答'
choice 非法: 'simple question'
```
它把「从 cheap/reasoning 里选一个」理解成了「自由回答这是什么类型」，
而且 `probabilities` 恒定输出 0.30/0.30。

### 3.3 判定
**judge 不迁 NPU。** 理由不是慢，是**不准**：
- 误判「复杂请求 → cheap」会把该上云端的难题压给本地 35B，质量不够
- 误判「简单请求 → reasoning」会白烧云端 token 和钱

一个 0 一致率的路由器比没有路由器更危险。

---

## 四、★ 意外收获：judge 慢 18.6 倍的真因

做上面那个实验时发现 35B 每次要 12–16 秒，远高于生成 30 token 应有的时间。
抓真实返回体，根因是 **思考链**：

| 方式 | 延迟 | 生成 token | `reasoning_content` 字符 | 合法 JSON |
|---|---|---|---|---|
| 直连 8080（原状） | 5.89 / **12.23 / 12.55** s | 475 / 1024 / 1024 | 1396 / 2909 / 2983 | 2/3 |
| 显式传 `chat_template_kwargs.enable_thinking=false` | **0.71 / 0.63 / 0.63** s | 30 / 29 / 30 | **0** | **3/3** |
| 经 docproxy 18090（代理本就注入） | **0.62 / 0.63 / 0.63** s | 30 / 29 / 30 | **0** | **3/3** |

**1024 token 预算里 965 个烧在思考，真正的 JSON 只有 72 字符。**

### 修法（已上生产）
`jev-local/judge.py` 两处：
1. `ENDPOINT`：`http://127.0.0.1:8080` → **`http://127.0.0.1:18090`**（由 docproxy 注入关思考）
2. `MAX_TOKENS`：`1024` → **`128`**（关思考后实际只输出约 30 token）
3. 额外：请求体里**显式**带 `chat_template_kwargs.enable_thinking=false`，
   作为双保险 —— 将来有人把 ENDPOINT 改回直连也不会退化

### 实测结果
```
judge.py choice ... → 0.66s / 0.68s / 0.68s，判定全部正确
```
**12.5 s → 0.67 s，约 18.6 倍。**

---

## 五、★ 第二个坑：router 非流式响应卡满 120 秒

修完 judge 做端到端验证时，`curl -m 120` 整整卡满 120 s 才退出，而响应体早已到齐。

根因（`router.py` 原 166–181 行）：
```python
self.send_response(resp.status)
for k, v in resp.headers.items():
    if k.lower() in ("content-type", "cache-control"):
        self.send_header(k, v)
self.end_headers()          # ← 此时还没给 Content-Length
...
self.wfile.write(resp.read())
```
`protocol_version = "HTTP/1.1"`（keep-alive），既无 `Content-Length` 也无 chunked 编码
→ 客户端无法判断响应边界，只能等连接关闭 → 一直等到超时。
**所有经 8081 的非流式调用都受此影响。**

### 修法（已上生产）
非流式分支先 `resp.read()` 拿到全量，再补 `Content-Length` 后 `end_headers()`；
流式分支保持不变（靠 `data: [DONE]` 自行界定）。

### 实测
```
修复前：HTTP 200，wall 120.00s（curl exit 28）
修复后：HTTP 200，wall 1.08s
```
**120 s → 1.08 s。** 这一条对 OpenClaw 的体感改善比 NPU 分流大得多。

---

## 六、改动清单

| 文件 | 改动 | 备份 |
|---|---|---|
| `~/.workbuddy/models.json` | 追加 `lfm2.5-it:1.2b` 条目（20→21） | `.bak.20261108-npu` |
| `~/.openclaw/openclaw.json` | +`npu` provider、+agent models 条目、+modelPolicy.allow | `.bak.20261108-npu` |
| `~/.openclaw/agents/main/agent/models.json` | +`npu` provider（因 schema 问题实际不生效） | `.bak.20261108-npu` |
| `jev-local/judge.py` | ENDPOINT→18090、MAX_TOKENS→128、显式关思考 | `.bak.20261108-thinking` |
| `jev-local/router.py` | 非流式补 `Content-Length` | `.bak2` |
| `tools/bench-judge-npu.py` | 新增，judge 一致性对比工具 | — |

重启：`localrouter.service`、`openclaw-gateway.service`（均 user 级，**不是** system 级）。

---

## 七、回滚

| 目标 | 操作 |
|---|---|
| 撤销 WorkBuddy 条目 | 删 `models.json` 末条，或 `cp models.json.bak.20261108-npu models.json` |
| 撤销 OpenClaw | `cp openclaw.json.bak.20261108-npu openclaw.json` → `systemctl --user restart openclaw-gateway` |
| 撤销 judge 优化 | `cp judge.py.bak.20261108-thinking judge.py` → 重启 localrouter |
| 撤销 router 修复 | `cp router.py.bak2 router.py` → 重启 localrouter |
| 关掉 NPU 分流（最轻） | `start-docproxy.sh` 里把 `NPU_UPSTREAM` 设为空 → 面板重启 18090 |

---

## 八、待办

| 项 | 状态 |
|---|---|
| **8219 收敛到 `127.0.0.1`** | 仍未做。flm 绑 `0.0.0.0:8219` 且无认证，局域网可直调。18090 已是回环 |
| OpenClaw `utilityModel` | 仍为 `""`（disabled）。它只服务 `session-companion-ask` 一个功能，不是通用辅助位，价值有限，未设 |
| `agents/main/agent/models.json` schema | 9 家 provider 的 `apiKey` 格式过时，整份被忽略。修需动既有密钥 → 待定 |
| Claude Code 走 18090 | 可选：把 `anthropic-fix-proxy.py` 的 `UPSTREAM` 改 18090，让它享受 media marker 修复。与 NPU 无关 |
| 1.2B 做 judge 的替代方案 | 已否决。若仍想用 NPU 做分类，需换成「固定选项 + response_format 强约束 + 只做二分类」重测 |

---

> 许可：CC0-1.0，公共领域贡献，无任何限制。
