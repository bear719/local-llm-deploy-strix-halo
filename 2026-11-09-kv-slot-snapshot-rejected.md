# KV 槽快照 + 冷槽自动恢复：**实测否决**、根因与订正

> ⚠️ **2026-11-09 13:00 重要订正（先读这一条）**：本文只否决了 **`--slot-save-path` 文件快照**这一半。
> 文中顺带得出的「`--cache-ram` 也无用」**是错的** —— 当时的对照实验用 `POST /slots/0?action=erase` 做基准，而 `erase` 直接清空 slot、**不触发 `prompt_save`**，cache 里从头没有条目，当然测不出效果。
> 用正确设计（A→B→A 切应用）复测：**`--cache-ram 3072` 生效，27.5K 前缀三应用轮转 29.6 s → 0.34 s（`cache_n=27,505`）**，现已设为生产值。
> 详见 `.workbuddy/memory/2026-11-09.md` 12:4x 段与下方 §7。
>
> 日期：2026-11-09 11:1x
> 前提：已按少爷授权执行 ①`--cache-ram 3072` ②`--slot-save-path $HOME/llama-slots`，并在真机做完 A/B 实测
> 结论：**`--slot-save-path` 无收益已回滚；`--cache-ram 3072` 有效已保留。** 见 §7。
> 前置分析：`2026-11-09-KV槽快照与冷槽自动恢复-本机可行性与收益分析.md`（其中 KV 体量与收益倍数**已被本次实测推翻**，见 §4）

---

## 一、一句话结论

`--slot-save-path` 的 restore **在本机这个模型上物理不可能生效**：本模型是 **30 层 SSM + 10 层 attention 的 hybrid**，llama.cpp 对 hybrid/recurrent memory 要求「必须存在 context checkpoint」才允许部分复用，而 **state 文件不含 checkpoints**。restore 成功后服务器仍会打印 `forcing full prompt re-processing`，把 `n_past` 归零，全量重算。

---

## 二、实测数据（真机，全部可复现）

测试负载：`/v1/chat/completions`，单条 user 消息 27,813 token（chat 模板渲染后）。

| 动作 | 结果 |
|---|---|
| 冷 prefill | 29.74 s / 27,813 token = **935 t/s**（`prompt_ms=29737`, 日志 `938.05 tokens per second`） |
| **save 快照** | **87–155 ms**，`n_written = 369,150,736 B`（352.0 MiB） |
| **restore 快照** | **45–112 ms**，`n_read = 369,248,908 B`，`n_restored = 27,813` |
| restore 后立刻 `/slots` | `n_prompt_tokens = 27813`（tokens 确实恢复了） |
| **restore 后首发请求** | **29.92 s / 27,813 token / `cache_n = 0`**（全量重算，零收益） |
| 同槽**连续**第二次请求 | **0.08 s / `prompt_n=4` / `cache_n=27,809`**（正常复用） |
| **KV 字节级还原验证** | save → restore → 再 save，两次文件 **md5 完全一致**（`32a4e629bf5fd86a7cad08fccfaaeba7`，369,248,908 B） |

→ **KV 和 tokens 都 100% 还原了，但服务器拒绝使用它。** 这不是配置问题。

对照实验（排除干扰项）：

| 实验 | 结果 |
|---|---|
| 关掉 `--cache-idle-slots` 后 restore | 仍 29.79 s / 全量 → **不是 idle 开关的问题** |
| `--cache-ram 3072` + erase 后发同 prompt | 仍 29.64 s / 全量 → **cache-ram 扩容无收益** |
| 强制 `id_slot=0` | 仍 29.81 s → **不是 slot 选择的问题** |

---

## 三、根因（源码 + 日志双证）

### 3.1 日志铁证

`--slot-save-path` 恢复后，首个请求的 launch 阶段：

```
0.36.151.128 I slot get_availabl: id 0 | checking sim = 1.000 (27813/27813) > 0.100
0.36.151.130 I slot get_availabl: id 0 | selected slot by LCP similarity, f_sim_best = 1.000, f_keep = 1.000
0.36.151.225 I slot   operator(): id 0 | cached n_tokens = 0, memory_seq_rm [0, end)
0.36.151.259 I slot   operator(): id 0 | forcing full prompt re-processing due to lack of cache data
                                        (likely due to SWA or hybrid/recurrent memory,
                                         see https://github.com/ggml-org/llama.cpp/pull/13194#issuecomment-2868343055)
```

**服务器认出了 100% 前缀（`f_keep = 1.000`），却仍然从 0 开始重算。**

### 3.2 代码路径

`tools/server/server-context.cpp:3369-3400`：

```cpp
if (pos_min >= pos_min_thold) {
    const auto it = std::find_if(slot.prompt.checkpoints.rbegin(),
                                 slot.prompt.checkpoints.rend(), ...);
    bool do_reset = it == slot.prompt.checkpoints.rend();
    if (!do_reset) {
        it->load_tgt(ctx_tgt, slot.id, ...);          // 只有 checkpoint 才能安全复用
        n_past = std::min(..., (size_t) it->n_tokens);
    }
    if (do_reset) {
        SLT_TRC(slot, "forcing full prompt re-processing due to lack of cache data "
                      "(likely due to SWA or hybrid/recurrent memory...)\n");
        pos_next = 0;
        n_past   = 0;                                  // ★ 归零
    }
}
```

`slot.prompt.checkpoints` 是 **server 层运行时对象**（`server_prompt::checkpoints`），
而 `--slot-save-path` 的 state 文件只写：

```cpp
// src/llama-context.cpp:3342 state_seq_save_file
file.write_u32(MAGIC); file.write_u32(VERSION); file.write_u32(n_token_count);
file.write_raw(tokens, ...);          // 只有 token id
state_seq_write_data(io, seq_id, 0);  // 只有 KV/SSM 张量
```

**→ 文件里没有 checkpoints。restore 后 `checkpoints.empty() == true` → `do_reset` → `n_past = 0`。**

### 3.3 为什么必须 checkpoint

本模型 40 层里 **30 层是 SSM（`ssm_a/ssm_alpha/ssm_beta/ssm_conv1d/ssm_dt/ssm_out`）**，只有 **10 层是真 attention**（`blk.3/7/11/15/19/23/27/31/35/39`）。

SSM 的 recurrent state 是**就地更新**的，无法像 GQA KV 那样用 `n_past` 指针回退 —— 必须先把状态快照成 checkpoint 才能安全截断。这就是源码注释里 `hybrid/recurrent memory` 的含义。

**这也是为什么同槽连续请求能命中（`cache_n=27,809`）**：那次 prefill 过程中已经按 `-cms 512` 生成了 checkpoint（日志 `created context checkpoint 2 of 32 (pos_min=27808, n_tokens=27809, size=117.764 MiB)`），第二次请求直接复用 checkpoint。

---

## 四、对前置报告的订正（两处硬错误）

| 项 | 前置报告（错） | 实测（对） |
|---|---|---|
| 模型结构 | 40 层全 attention | **10 层 attention + 30 层 SSM（hybrid）**，每 4 层一个 attention |
| 每 token KV | 42.5 KiB（按 40 层 ×1024 元素 ×q8_0） | **10,880 B/token**（10 层 ×1024 元素 ×1.0625）+ **固定 66.3 MB SSM 状态** |
| 27.8K 快照体积 | 1.10 GiB（推算） | **352.0 MiB（实测）** —— 公式 `66.3 MB + 10,880 × n_tokens` 与 369,150,736 B 吻合到 0.1% |
| 262K 满载 KV | 10.62 GiB | **≈ 2.92 GiB**（66.3 MB + 2.85 GB） |
| prefill 速度 | 654.8 t/s（来自 /metrics 历史均值） | **935–940 t/s**（单次实测，短前缀更快） |
| restore 收益 | 97 s → 1.0 s（≈97×） | **0×（不可用）** |
| `--cache-ram 3072` 收益 | 进程内切换 97 s→1 s | **0×（实测 erase 后仍全量重算）** |

**唯一没被推翻的**：save/restore 本身很快（87 ms / 45-112 ms），KV 字节级完美还原，`/dev/shm` 落点确实该否决（tmpfs 吃 host RAM）。机制没问题，是**上层拒绝使用**。

---

## 五、有没有绕过的办法

| 方案 | 可行性 | 说明 |
|---|---|---|
| 给 state 文件加 checkpoint 段 | 需改 llama.cpp 源码 | 要把 `server_prompt::checkpoints`（含 `data_tgt`/`data_dft`/`data_spec`）序列化进 .bin。工作量中等，但会与上游格式分叉，此后每次同步都要 rebase |
| 用 `--cache-ram` 的 prompt cache 路径跨进程 | ❌ | prompt cache 在 host RAM，进程死即消失 |
| 靠 `--cache-idle-slots` 在进程内换应用 | ❌ | 单 slot 下实测无收益（erase 后仍全量） |
| **多 slot 常驻（`-np N`）** | ✅ **唯一可行** | 每个应用占独立 slot，KV 互不清空。代价：每 slot 独立 KV（10.9 KiB/token）+ SSM 状态 66 MB；且 `-np>1` 时 draft-mtp 有 cross-slot 串扰风险（脚本注释引上游 PR #28123） |
| 缩短上下文换速度 | ✅ 低成本 | `-c 131072` 时单次全量 prefill 从 30 s 降到 15 s，KV 减半 |

**推荐**：若「换应用重算 30 s」确实是痛点，改 `-np 2`（`-c 262144` 总量不变，每槽 131072）。**不要**在 draft-mtp 下用 `-np > 1` 做严格正确性任务（串扰风险已知）。

---

## 六、变更与回滚记录（已全部还原）

| 动作 | 状态 |
|---|---|
| `start-qwen36-35b-a3b.sh`：`--cache-ram 1024→3072` | ✅ 已还原为 1024 |
| `start-qwen36-35b-a3b.sh`：加 `--slot-save-path` | ✅ 已移除（参数计数 = 0） |
| `start-qwen36-35b-a3b.sh`：关 `--cache-idle-slots` | ✅ 已还原为开启 |
| `start-qwen36-35b-a3b.sh`：加 `-v --log-file` 诊断 | ✅ 已移除 |
| `$HOME/llama-slots/*.bin`（1.07 GB 测试快照） | ✅ 已删除 |
| 备份脚本 | `start-qwen36-35b-a3b.sh.bak.20261109-kvslot`（保留） |
| 面板实例重启次数 | 5 次（含最后回滚一次），当前生产参数：`-c 262144 -np 1 --cache-idle-slots --cache-ram 1024 --context-shift -cms 512` |
| 服务状态 | 8080 `{"status":"ok"}`；18090 `npu_enabled:true`；host `MemAvailable 12.8 GB` |

**遗留**：`/tmp/llama-debug.log`（root 所有，516 KB）由 root 创建，lc 无权删除；下次重启会被截断覆盖，无害。

---

## 七、方法论教训（已写入记忆）

1. **GGUF 元数据里的 `attention.head_count_kv` 不代表「每层都有 KV」**。必须按张量名逐层统计（`ssm_*` vs `attn_k/attn_v`），否则 KV 体积会算错 3.3 倍。
2. **`/metrics` 的 `prompt_tokens_seconds` 是历史加权均值**，含大量小请求开销，不能当单次 prefill 速度；单次实测 935 t/s，指标显示 655 t/s。
3. **接口返回 200 ≠ 功能生效**。restore 返回 `n_restored=27813` 且文件 md5 一致，但仍然零收益 —— 必须以「后续请求的 `cache_n`」作为验收口径。
4. **hybrid 模型的 checkpoint 才是复用单位**，不是 KV 字节。`-cms`（checkpoint 间隔）与 `--checkpoints` 数量是这类模型的关键参数。

---

## 八、本次执行声明

按少爷「1+2」授权执行了参数变更与重启；实测发现方案零收益后**主动回滚到原始生产配置并验证**（参数、端口、健康检查、host 内存全部核对）。未修改 `docproxy.py`（钩子未实施，因为底层机制已否决，加了等于空转）。所有测试文件已清理。

---

> 许可：CC0-1.0，公共领域贡献，无任何限制。
