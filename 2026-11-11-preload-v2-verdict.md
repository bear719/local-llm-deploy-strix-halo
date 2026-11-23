# tools+system 前缀预加载：实测推翻上一轮结论，改判定为「默认不跑」

日期：2026-11-11 07:4x
环境：Qwen3.6-35B-A3B Q5_K_P，Vulkan，`-c 262144`，`--cache-ram 16384 --ctx-checkpoints 16`
取证：docproxy `DUMP_PROMPT=1` 快照（85 条真实/测试请求，05:09 → 07:34）

---

## 一、上一轮结论被推翻

上一轮我给出的判据是：**跨版本 tools JSON 字符级 LCP 只有 6045/76830，加 `sort_keys=True` 可恢复语义级收益（≈52,000 token / 113 s）**。

实测证明这条是错的，两处都错：

| 我的判断 | 实测 | 结论 |
|---|---|---|
| 加 `sort_keys` 能把 tools 全量命中 | 键顺序对 token 数影响 **< 0.2%**（40,210 → 40,164） | Jinja 的 `tools \| tojson` 已按键排序，**无需改动** |
| 预加载可省 113 s | 真实请求 `prompt_n = 40,210`，冷 prefill **52.7 s** | 「113 s」是按 463 t/s 硬算全量、且把 tools 与 system 相加重复计数 |

实测三组（同一条 `n_msg=2` 的新会话 bag，中间插入干扰请求把槽踢走）：

| 步骤 | prompt_n | cache_n | prefill | wall |
|---|---:|---:|---:|---:|
| 重放 bag 原样（冷） | 40,210 | **0** | 52.73 s | 53.7 s |
| 重放 bag，tools 键逆序（冷） | 40,164 | **0** | 52.00 s | 53.0 s |
| 再重放原样（cache-ram 恢复） | 4 | **40,206** | 0.75 s | 9.93 s |
| 紧接着再重放（槽内命中） | 4 | **40,206** | 0.74 s | **0.81 s** |

两条硬事实：

1. **键顺序无关**：逆序后 prompt_n 只差 46（−0.11%），说明 chat template 渲染前已排序。
2. **槽内命中只要 0.81 s**，cache-ram 恢复要 9.93 s（40K 条目含 checkpoints，反序列化体积远大于 KV 本体）。

---

## 二、为什么 preload 默认不该跑

关键推理：**tools + system 是每条真实请求都带的前缀**。所以只要槽里存在过任意一次真实请求，这 40K 就已经在槽内，新会话首请求会自动 LCP 命中 —— 不需要任何预加载。

槽里真正会「没有 40K 前缀」只有三种情况：

| 场景 | 触发方式 | preload 能否救 |
|---|---|---|
| llama-server 刚重启 | 面板重启、kill | ✅ 能 |
| 槽被 erase | `POST /slots/0?action=erase` | ✅ 能 |
| 槽被**不带 tools 的短请求**冲掉 | 探活、连通性测试、NPU 路由测试 | ✅ 能 |

而 preload 本身有代价：**覆盖一个 100K 活跃会话，要先 prompt_save 到 cache-ram**。实测这条 `wall = 80.4 s`（就是上面表格第一步那个 44-token 的干扰请求，耗时 80 s，全花在把 100K 会话写进 cache-ram）。

所以 v1（每分钟一次）的账：

```
收益  0 token（预热的是 disclosure catalog，与真实请求 LCP = 0）
代价  每分钟踢掉一次活跃会话；若会话是 100K，save 80 s + 回来 restore 12 s = 92 s
```

已停用（crontab 首行注释，备份 `backup/crontab.bak.20261111-preload`）。

---

## 三、快照暴露的两个真问题

### 1. tools 版本漂移

```
tools=8957afcbca5fcaec  sys=c7022493e3761180   37 次   tools_n=22  sys_chars=54321
tools=85fa5b117d078f9d  sys=92ab52cae8952846   28 次   tools_n=22  sys_chars=56427
tools=20245ddf9d2a1d8a  sys=c7022493e3761180    1 次   tools_n=23  sys_chars=54321
tools=8c0af49f6ea81b9b  sys=acc56b6696d165d5    1 次   tools_n=38  sys_chars=30193   ← OpenClaw
```

`node: 22 个工具` 与 `23 个工具` 交替出现（07:34:04 那条新会话是 23）。**工具集合一变，LCP 就在 tools 段内断掉**，40K 前缀整体失效 → 冷算 52.7 s。这是新会话首请求慢的真实原因，不是缺预热。

system prompt 也有两版（54,321 / 56,427 字符，差 2,106，差异在 `# Runtime Isolation Rules` 之后），同样会断前缀。

### 2. 短请求冲槽

18 条 `tools_n=0, sys_chars=0, n_msg=1` 的请求，05:31:34 → 05:40:56 每 30 s 一条，model 字段填的是文件路径 `$HOME/models/Qwen3.6-35B-A3B-Uncensored-Q5_K_P.gguf`，内容是 `Translate: The weather is nice today.`（NPU 连通性测试残留）。每条都会把槽清成几十 token。

**这类请求是唯一值得用 preload 兜底的场景**。目前已无常驻污染源（07:10 后未再出现）。

---

## 四、交付：preload v2

`tools/preload_system_prompt.py` 已重写（v1 备份 `tools/preload_system_prompt.py.bak.20261111-v1`）。

行为变化：

| 项 | v1 | v2 |
|---|---|---|
| prompt 来源 | 硬编码 disclosure catalog（2671 tok） | 从 `DUMP_PROMPT` 快照提取**真实请求形态** |
| 命中对象 | 与真实请求 LCP = 0 | tools + system（40,210 tok） |
| 槽守卫 | 无，无条件覆盖 | **忙 / 有真实会话 → 一律跳过** |
| 默认行为 | cron 每分钟跑 | 不挂 cron，手动按需 |
| 附加能力 | — | `--stats` / `--dry-run` / `--force` / `--profile mode` |

守卫判定（`decide()`）：

```
槽 is_processing        → 跳过
n_prompt_tokens == 0    → 预热（槽为空，可安全补位）
n_prompt_tokens ≈ 上次预热长度（±8） → 跳过（已是自己）
其余                     → 跳过（槽内有真实会话，绝不覆盖）
```

用法：

```bash
P=$HOME/.workbuddy/binaries/python/versions/3.13.12/bin/python3
$P tools/preload_system_prompt.py --stats      # 看快照形态分布 + 短请求清单
$P tools/preload_system_prompt.py --dry-run    # 只看决策
$P tools/preload_system_prompt.py             # 守卫通过才预热
$P tools/preload_system_prompt.py --force     # 服务重启后手动补位
```

建议只在 **llama-server 重启后** 手动跑一次（此时槽真空，守卫会放行）。

---

## 五、若要继续优化，只有一条路

`tools` / `system` 版本漂移才是 52.7 s 冷算的根因。可行方案：在 docproxy 里对 tools 数组按 `function.name` 稳定排序并统一序列化（capsule: 语义不变，仅归一化顺序）。这样只要工具**集合**相同，前缀就一致。

但集合本身会变（22 / 23 / 38 三种），归一化只能解决「同集合不同序」，解决不了「集合变化」。收益上限有限，且要动转发主链路。

我的建议：**不动**。现状下每轮对话只有首次请求可能吃 52.7 s，同一会话后续全部槽内命中（0.8 s 级）。这个代价远小于改造风险。

---

## 六、当前状态

| 项 | 值 |
|---|---|
| crontab | 首行已注释停用 |
| 槽 | `n_prompt_tokens = 40,210`（tools=22 + sys 54,321 + heartbeat，正好匹配 190 轮会话前缀） |
| 8080 / 18090 | ok / ok（passthrough） |
| VRAM | 51,704,860,672 B = 48.15 GiB |
| GPU 侧无残留 | 槽空闲，`is_processing=false` |

回滚：

```bash
cp tools/preload_system_prompt.py.bak.20261111-v1 tools/preload_system_prompt.py
crontab $HOME/WorkBuddy/调试本地模型/backup/crontab.bak.20261111-preload   # 恢复每分钟 preload（不建议）
```

---

> 许可：CC0-1.0，公共领域贡献，无任何限制。
