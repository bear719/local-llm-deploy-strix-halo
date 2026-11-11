# KV 槽快照 + 冷槽自动恢复：本机部署可行性及预计收益分析

> ⛔ **本文部分结论已被 2026-11-09 11:1x 的真机实测推翻，请看 `2026-11-09-KV槽快照实测-否决结论与根因.md`。**
> 被推翻的：§三 KV 体量（实际 13.0 KiB/token 而非 42.5，模型是 30 SSM + 10 attention 的 hybrid）、
> §四 收益倍数（restore 实测 0× 有效）、§六 方案 1（`--cache-ram 3072` 实测无收益）。
> 仍然成立的：§二 参数与接口存在性、§五 5.1（/dev/shm 不可用）、5.2（只校 arch）、5.3（draft KV 不入快照）。
> 实测根因：hybrid/recurrent memory 必须靠 context checkpoint 才能复用，而 state 文件不含 checkpoints。

> 日期：2026-11-09
> 来源：llama-modchip `ARCHITECTURE.md` §3.8 Optimization 8（HARP-Cache / Slot 0 Disk Restore）
> 本机实测：`$HOME/llama-qwen4exp-rocmfpx` build 10824、8080 现役进程参数、`/proc/meminfo`、`/dev/shm` 与 NVMe 吞吐基准
> 结论口径：**技术上 100% 可行，但 modchip 的 `/dev/shm` 落点在本机必须换成 NVMe；单独做 ROI 低，必须先做 `--cache-ram` 扩容**

---

## 一、结论先行

| 项 | 判定 |
|---|---|
| 二进制能力 | ✅ 参数 `--slot-save-path`、接口 `POST /slots/:id?action=save\|restore\|erase` **全部存在**，无需重编 |
| 现役是否已启用 | ❌ 未启用（8080 命令行无 `--slot-save-path`）→ 现在调 save/restore 直接返回 `501 NOT_SUPPORTED` |
| 落 `/dev/shm`（modchip 做法） | ❌ **本机不可用**：tmpfs 吃 host RAM，而 host `MemAvailable` 仅 **7.49 GB**、swap 已用 6.3 GB |
| 落 NVMe | ✅ 可行：写 3.96 GiB/s、读 3.08 GiB/s，根分区剩 239 GB |
| 额外显存 | ✅ **零**。KV cache 在 `-c 262144` 启动时已按 10.62 GiB 全额预分配，快照只做填充/回读 |
| 单次收益（63.7K 前缀） | **97.3 s → 0.9–1.2 s（≈80–100×）** |
| 盈亏平衡点 | 前缀 ≥ **1,441 token** 才值得存（小于此值 restore 比 prefill 还慢） |
| 推荐次序 | **① `--cache-ram 3072`（零代码，解决进程内切换）→ ② `--slot-save-path`（解决重启）→ ③ 不要 /dev/shm** |

---

## 二、机制核实：本机已有的能力（带证据）

### 2.1 参数与接口

`./build-vk4/bin/llama-server --help`：

```
--slot-save-path PATH    path to save slot kv cache (default: disabled)      # 第 654 行
--slots, --no-slots      expose slots monitoring endpoint (default: enabled)  # 第 652 行
--cache-idle-slots       save idle slots to the prompt cache on new task      # 第 486 行
-cram, --cache-ram N     set the maximum cache size in MiB (default: 8192)    # 第 478 行
```

路由（`tools/server/server.cpp:285-286`）：

```cpp
ctx_http.get ("/slots",          ex_wrapper(routes.get_slots));
ctx_http.post("/slots/:id_slot", ex_wrapper(routes.post_slots));
```

动作分发（`tools/server/server-context.cpp:4824-4855`）：未设 `--slot-save-path` 时**直接拒绝**：

```cpp
if (params.slot_save_path.empty()) {
    res->error(format_error_response("This server does not support slots action. "
               "Start it with `--slot-save-path`", ERROR_TYPE_NOT_SUPPORTED));
    return res;
}
if (action == "save")    return handle_slots_save(req, id_slot);
if (action == "restore") return handle_slots_restore(req, id_slot);
if (action == "erase")   return handle_slots_erase(req, id_slot);
```

### 2.2 现役 8080 真实参数（PID 3510531，属主 root）

```
-m $HOME/models/Qwen3.6-35B-A3B-Uncensored-Q5_K_P.gguf
-md $HOME/models/Qwen3.6-35B-A3B-MTP-ONLY-Q4_K_M.gguf --spec-type draft-mtp
-ngl 999 -c 262144 -np 1 -b 4096 -ub 1024
--mmproj .../mmproj-Qwen3.6-35B-A3B-Uncensored-f16.gguf
--spec-draft-n-max 2 -ctk q8_0 -ctv q8_0
--context-shift --cache-idle-slots -cms 512 --cache-ram 1024
--metrics --host 0.0.0.0 --port 8080
```

→ 缺 `--slot-save-path`；`--cache-ram` 只有 **1024 MiB**。

### 2.3 当前 slot 实况（`GET /slots`）

```json
[{"id":0,"n_ctx":262144,"is_processing":false,
  "n_prompt_tokens":63709,"n_prompt_tokens_processed":0,"n_prompt_tokens_cache":0}]
```

→ 单 slot 正缓存 **63,709 token 前缀**，KV 实占 **2.58 GiB**。

### 2.4 服务端累计指标（`GET /metrics`）

| 指标 | 值 |
|---|---|
| `prompt_tokens_total` | 1,590,860 |
| `prompt_seconds_total` | 2,429.44 s |
| **实测 prefill 有效速度** | **654.8 t/s** |
| `prompt_tokens_cached_total` | 11,435,200（LCP 复用已生效） |
| `tokens_predicted_total` | 235,978 |

---

## 三、KV 体量精算（决定一切数字）

GGUF 元数据（`Qwen3.6-35B-A3B-Uncensored-Q5_K_P.gguf`）：

```
qwen35moe.block_count             40
qwen35moe.attention.head_count_kv  2
qwen35moe.attention.key_length    256
qwen35moe.attention.value_length  256
```

每 token KV 元素数 = 40 层 × (K 2×256 + V 2×256) = **40,960 元素**
q8_0 编码 = 34 B / 32 元素 = 1.0625 B/元素

**⇒ 43,520 B/token = 42.50 KiB/token**（交叉验证：32,768 × 42.5 KiB = 1.328 GiB，与项目长期记录「KV(q8_0) 32K = 1.33 GiB」逐位吻合）

| 前缀长度 | KV 体积 | prefill 耗时 @654.8 t/s | 快照落盘体积 | restore 读盘耗时 @3.08 GiB/s |
|---:|---:|---:|---:|---:|
| 8,192 | 0.33 GiB | 12.5 s | 0.33 GiB | 0.11 s |
| 22,500（OpenClaw 40 工具头量级） | 0.91 GiB | 34.4 s | 0.91 GiB | 0.30 s |
| **63,709（当前实况）** | **2.58 GiB** | **97.3 s** | 2.58 GiB | **0.84 s** |
| 131,072 | 5.31 GiB | 200 s | 5.31 GiB | 1.72 s |
| 262,144（满载） | 10.62 GiB | 400 s | 10.62 GiB | 3.45 s |

---

## 四、收益测算

### 4.1 单次 save/restore 成本

| 环节 | 路径 | 估算 |
|---|---|---|
| save | VRAM → host | 2.58 GiB @ ~20 GB/s ≈ 0.13 s |
| save | host → NVMe | 2.58 GiB @ 3.96 GiB/s ≈ 0.65 s |
| **save 合计** | | **≈ 0.8 s**（占 slot 0.8 s，期间请求被 defer） |
| restore | NVMe → host | 2.58 GiB @ 3.08 GiB/s ≈ 0.84 s |
| restore | host → VRAM | ≈ 0.13 s |
| **restore 合计** | | **≈ 1.0 s** |

### 4.2 净收益

| 场景 | 现状（prefill） | 快照方案 | 倍数 | 净省 |
|---|---:|---:|---:|---:|
| 换应用 / 重启后，63.7K 前缀 | 97.3 s | 1.0 s | **97×** | **96.3 s** |
| 同上，22.5K 前缀 | 34.4 s | 0.30 s | 115× | 34.1 s |
| 同上，8K 前缀 | 12.5 s | 0.11 s | 114× | 12.4 s |
| 短对话 1K 前缀 | 1.5 s | 0.02 s | 75× | 1.5 s（无感） |

**盈亏平衡**：`save(0.8) + restore(1.0) = 1.8 s` ⇔ **1,441 token** 的 prefill。
→ 低于 1.4K token 的前缀不要存，强制 save 反而是净亏。

### 4.3 真实年化收益（取决于触发频率）

| 触发频率 | 每日节省 | 备注 |
|---|---:|---|
| 每天重启 1 次 | 1.6 min | ROI 极低，不值得改造 |
| 每天换应用 5 次 | 8.0 min | 勉强 |
| 每天换应用 20 次（WorkBuddy / OpenClaw / 导播台 / Claude Code 轮转） | **32 min** | **这才是价值所在** |

⚠️ 现役 `-np 1` 是收益的根源也是风险：**只有一个 slot，任何应用切换都必然踢掉当前 63.7K 前缀**。

---

## 五、三个本机特有的否决点 / 风险（与 modchip 的关键分歧）

### 5.1 ❌ `/dev/shm` 落点在本机不成立

modchip 是 64 GB RAM 的纯 CPU 机器，KV 快照 85 MB 放 shm 毫无压力。本机：

```
MemTotal 31.2 GB   MemAvailable 7.49 GB   SwapUsed 6.3 / 16 GB
/dev/shm 16 G（tmpfs：占用计入 host RAM，不是独立池）
```

96 GiB 已被 BIOS UMA 划走（OS 不可寻址），host 只剩 31.2 GB 且已用 23.7 GB。往 shm 塞 2.58 GiB → available 掉到 ~4.9 GB，逼近历史 OOM 阈值（曾出现 avail 494 MiB 全局 OOM）。
**⇒ 快照必须落 NVMe**（`$HOME/llama-slots`），代价只是 save/restore 慢 2×（3–4 GiB/s vs 8 GiB/s），换来 host RAM 零占用。**这笔交换在本机是必做的**。

### 5.2 ⚠️ 状态文件只校验 arch 字符串，不校验模型

`src/llama-context.cpp:3342-3360`（`state_seq_save_file`）只写：

```cpp
file.write_u32(LLAMA_STATE_SEQ_MAGIC);
file.write_u32(LLAMA_STATE_SEQ_VERSION);
file.write_u32((uint32_t) n_token_count);
file.write_raw(tokens, ...);
state_seq_write_data(io, seq_id, 0);     // 内含 arch 字符串
```

`state_read_data` 的校验只有：

```cpp
if (cur_arch_str != arch_str)
    throw std::runtime_error("wrong model arch: ...");
```

**没有模型哈希、没有 `-c`、没有 `-np`、没有 KV 量化类型、没有 MTP draft 标识**。
→ 同为 `qwen35moe` arch 的不同量化/不同微调模型会**静默接受错 KV**，输出语义垃圾（不报错）。
**⇒ 快照文件名必须由外部脚本编码指纹**，例如 `q35b-q5kp-c262k-np1-ctkq8_0-<prefixhash>.bin`，restore 前比对，不匹配拒绝。

### 5.3 ⚠️ MTP draft 的 KV 不在快照内

`server-context.cpp:2582` 只对 **target ctx** 调 `llama_state_seq_save_file(ctx_tgt, ...)`。`ctx_dft`（MTP-ONLY-Q4_K_M）的 KV 不保存。
→ restore 后 target 侧前缀已就绪，但 draft 侧 `n_past = 0`，首个请求需重建 draft 前缀。draft 只有 1 层量级，估 22K 前缀 1–3 s。
**结论：收益打折但仍在 30× 以上，可接受；不可接受的是把它当 0 成本宣传。**

### 5.4 ⚠️ `--context-shift` 与快照 pos 的潜在错位（未实测）

`server_tokens::serialize()`（`server-common.cpp:553`）**只存 token id，不存 pos**；restore 后 `slot->prompt.tokens` 的 pos 被重建为 0..n-1，而 KV cell 的 pos 按文件原值写回。
现役开了 `--context-shift`：一旦 262,144 用完触发 shift，cell pos 已环移 → 与重建的 0..n-1 错位。
**⇒ 263K 上下文下实际很难触发，但必须专门验一次；预案是 restore 失败/上下文接近满载时禁用快照。**

### 5.5 ⚠️ 单 slot 抢占：不能盲 restore

`server-context.cpp:2592`：slot `is_processing()` 时 save/restore 任务被 **defer**，不报错、不排队保证顺序。
两个客户端并发时互相覆盖 KV = 把 97 s 变成 2 × 97 s。
**⇒ docproxy 侧必须：① 前缀指纹命中才 restore；② 全局互斥锁串行化 restore + 首个请求；③ restore 后立即发出该请求，不给别人插队窗口。**

### 5.6 其它工程约束

- `fs_validate_filename()` 禁止路径分隔符 → 快照只能平铺在 `--slot-save-path` 目录下，不能分子目录。
- 快照**无自动清理**（llama.cpp 不做 GC）→ 需外部 LRU（建议上限 20 GiB，按 mtime 淘汰）。
- 面板 `startCommand` 属主 root → 加参数只能走面板 API（`tools/mcsm-api-update-instance.py`）或面板 UI；**重启一次会清空当前 63.7K 前缀 = 一次性 97 s 成本**。

---

## 六、方案对比与推荐

### 方案 1：`--cache-ram 3072`（零代码，先做）

**问题根因**：`--cache-ram 1024` 意味着 prompt cache 上限 1 GiB，而当前 63.7K 前缀序列化后 **2.58 GiB** → `--cache-idle-slots` 想存存不下，**直接丢弃**。这就是「换个应用就重算 97 s」的直接原因。

| 项 | 值 |
|---|---|
| 改动 | 面板参数 `--cache-ram 1024` → `3072` |
| 收益 | 进程内换应用：97 s → ~1 s（纯内存命中，无磁盘 IO） |
| 代价 | host RAM +2 GiB（available 7.49 → 约 5.5 GB） |
| 局限 | **不解决进程重启**（进程没了 cache 也没了） |
| 风险 | host 内存本已紧张，需盯 `MemAvailable`；建议同时加水位告警 |

### 方案 2：`--slot-save-path $HOME/llama-slots`（解决重启）

| 项 | 值 |
|---|---|
| 改动 | 面板加参数 + docproxy 挂 save/restore 钩子 |
| 收益 | 重启/系统重启后 97 s → 1.0 s；且能与方案 1 叠加（进程内走 cache，跨进程走快照） |
| 代价 | 每次 save 写 2.58 GiB（NVMe 磨损 ≈ 每天 5 次 × 2.58 = 13 GB/天） |
| 局限 | 需客户端/代理配合，否则零收益 |
| 风险 | 5.2–5.5 四条 |

### 方案 3：`/dev/shm` 落点 —— ❌ 不采用

唯一优势是快 2×（8 vs 3.96 GiB/s），代价是把 2.58 GiB 压进只剩 7.49 GB 的 host RAM。**收益 0.3 s，风险是整个系统 OOM。** 不划算。

### 推荐路径

```
第 1 步（今天可做，零代码）：--cache-ram 1024 → 3072，面板重启一次
第 2 步（观察 3 天）：盯 MemAvailable 与 /metrics 的 prompt_tokens_cached_total 增量
第 3 步（若重启仍频繁）：加 --slot-save-path + docproxy 钩子
```

---

## 七、若做方案 2：落地参数与植入点

### 7.1 面板参数增量

```
--slot-save-path $HOME/llama-slots
```

前置：`mkdir -p $HOME/llama-slots && chmod 755`（llama-server 以 root 跑，目录需可写）。
**不动** `-c / -np / -ctk / -ctv`，否则已有快照全部失效。

### 7.2 docproxy 植入点（`tools/docproxy.py`）

| 位置 | 动作 |
|---|---|
| `do_POST` 分派前（第 698 行后） | 若命中前缀指纹 → `POST 8080/slots/0?action=restore {"filename":"<fp>.bin"}` |
| `forward_to_upstream` 流的 `[DONE]` 之后 | 异步 `POST /slots/0?action=save`，节流：前缀增长 ≥ 4,096 token 或空闲 ≥ 30 s 才存 |
| 启动时 | 若快照存在且模型指纹匹配 → 先 restore 再对外服务 |

**关键：restore 必须与紧随其后的首个请求在同一次互斥内完成**，否则 `--cache-idle-slots` 会在新任务到来时清空 slot，restore 白做。

### 7.3 指纹构造（必须，见 5.2）

```
fp = sha1(模型文件名 + 量化 + n_ctx + n_parallel + ctk + ctv + 系统提示前缀 token 的前 2048 个)[:16]
filename = f"{fp}.bin"
```

---

## 八、验证清单（需授权才能执行的部分单独标注）

| # | 项目 | 方法 | 是否需授权 |
|---|---|---|---|
| 1 | 接口存在性 | `curl -X POST 8080/slots/0?action=save -d '{"filename":"t.bin"}'` 应返回 `501 Start it with --slot-save-path` | 只读，已可由代码证据确认 |
| 2 | save 真实耗时 | 加参数重启后，slot 有空档时实测 | **需重启 8080** |
| 3 | restore 真实耗时 + KV 正确性 | save → erase → restore → 发同前缀请求，比对首 token 与 prefill 时间 | **需重启 8080** |
| 4 | MTP draft 重建成本 | restore 后首个请求的 `timings.prompt_ms` | **需重启 8080** |
| 5 | context-shift 错位 | 需要 >262K 负载，成本高，建议改为代码审查结论 | 暂缓 |
| 6 | `--cache-ram 3072` 的 host 压力 | 重启后 `free -m` 连续观察 24 h | **需重启 8080** |

**一次重启可同时验证 2/3/4/6，成本 = 当前 63.7K 前缀丢失一次（97 s）。**

---

## 九、最终判定

1. **可行，但不是照抄。** modchip 的 `/dev/shm` 做法与本机 host 内存约束正面冲突，必须改落 NVMe。
2. **收益真实但取决于频率。** 单 slot + 63.7K 前缀的现实下，每次前缀失效代价 97 s，快照能压到 1 s；但如果每天只重启一次，改造投入不划算。
3. **真正的低垂果实不是快照，是 `--cache-ram 1024 → 3072`。** 当前配置下 2.58 GiB 的前缀连内存都留不住，这是「换应用必重算」的直接原因，改一个数字就能吃掉 80% 的痛感。
4. **不要相信状态文件的兼容性校验。** 它只认 arch 字符串，换模型会静默喂错 KV —— 指纹必须自己加。

---

## 十、本次执行声明

**零生产变更**：未加参数、未重启任何服务、未创建快照目录、未修改 `docproxy.py`、未下载任何模型。仅只读排查（`--help`、`/proc/<pid>/cmdline`、`GET /slots`、`GET /metrics`、源码阅读）+ 两项基准（`/dev/shm` 1 GiB 读写、NVMe 1.5 GiB 读写，均在临时文件上完成后删除）。

---

> 许可：CC0-1.0，公共领域贡献，无任何限制。
