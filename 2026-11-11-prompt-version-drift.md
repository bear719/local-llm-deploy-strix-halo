# 版本漂移：逐源定性 + 实测判定 + 落地（不统一内容，改为全体预热）

日期：2026-11-11 08:2x–08:5x
环境：Qwen3.6-35B-A3B Q5_K_P，Vulkan，`-c 262144 -np 1`，`--mmproj` 已加载
数据：docproxy `DUMP_PROMPT` 快照 85 条请求（05:09 → 07:34）

---

## 结论先行

**"统一 tools / system 版本"这条路要放弃，但漂移问题已被更好的办法解决。**

三个漂移源里：一个**不需要统一**（顺序无关），两个**绝不能统一**（会破坏安全约束与工具调用）。真正的痛点是「每个新版本首次出现要 45 s 全量重算」，而它可以用「一次性全体预热」消除 —— 之后所有版本切换只要 **7.6 s**。

---

## 一、三个漂移源，逐一定性

### 源 1：tools 数组顺序 —— 不需要处理

A 版顺序（按使用频率）：`Read, Write, Edit, Bash, Glob, Grep, …`
C 版顺序（字母序）：`AskUserQuestion, Bash, DeferExecuteTool, Edit, …`

看起来是显著差异，但**实测证明它不影响 token**：

| 请求 | prompt_n | cache_n | prefill |
|---|---:|---:|---:|
| A 原顺序 | 4 | **36,847** | 0.80 s |
| A **逆序** | 4 | **36,847** | 0.81 s |
| A 按 name 排序 | 4 | **36,847** | 0.80 s |

原因在 `common/chat.cpp:576` `common_chat_tools_parse_oaicompat`：server 会把 tools 拆成 `common_chat_tool{name, description, parameters}` 向量，再由 `common_chat_tools_to_json_oaicompat` 重建。重建过程重排了内部结构，使顺序不再影响最终 token 序列。

> **推论：任何"给 tools 排序"的改造都是无用功。** 这条同时废掉了我上一轮提出的 `sort_keys` 方案和本轮原计划的排序方案。

（注：`/apply-template` 端点走的是另一条路径，同一组 tools 正序/逆序渲染 LCP 仅 124 字符 —— 但那条路径不参与实际推理，不能拿来当判据。）

### 源 2：tools 内容 —— 不能统一

`ToolSearch` 的 description 里嵌了 **deferred tools 清单**，B 版比 A 版多一行：

```
+LSP: Interact with Language Server Protocol (LSP) servers to get code intelligence features.
```

代价实测（system 完全相同，只差这一行）：

| 请求 | prompt_n | cache_n | prefill |
|---|---:|---:|---:|
| A（无 LSP） | 4 | 36,847 | 0.80 s |
| B（有 LSP） | 36,872 | **0** | **45.78 s** |
| A 回切 | 4 | 36,847 | 0.80 s |

**一行 = 45 s。** 因为 Qwen 的 template 把 tools 渲染在 system 之前，tools 一断，后面全废（不是部分命中，是整体 `cache_n=0`）。

但**这一行不能删也不能补**：它是模型发现 LSP 工具的唯一线索。删了模型永远不知道有 LSP；补了模型会去 `ToolSearch("LSP")` 然后失败。这是 LSP 插件启停的运行时状态，只能由客户端决定。

### 源 3：tools 集合 —— 不能统一

C 版比 A/B 多一个 `MultiEdit`（description 为空，体积很小）。实测：

| 请求 | prompt_n | cache_n | prefill |
|---|---:|---:|---:|
| C（23 个，含 MultiEdit） | 37,103 | **0** | **47.16 s** |

强删 MultiEdit = 新会话失去批量编辑能力；强补 MultiEdit = 旧会话的模型可能调用客户端没声明的工具。两边都有实际功能损失，**不做**。

### 源 4：system 模板 —— 绝对不能统一

两版差 **388 行 / 2,106 字符**，不是文字微调，是**两套不同的 system 模板**：

| 段落 | 54,321 版 | 56,427 版 |
|---|:---:|:---:|
| `<content_policy>` | ✗ | ✅ |
| `<personal_files_safety>` | ✗ | ✅（8 条强制规则，防误删用户文件） |
| `<regional_conventions>` | ✗ | ✅ |
| `<working_modes>` | ✗ | ✅ |
| `<agent_loop>` | ✗ | ✅ |
| `<result_presentation>` | ✗ | ✅ |

把旧版"升级"成新版 = 代理向 system 注入客户端没生成的指令；把新版"降级"成旧版 = **删掉 `personal_files_safety`，模型会真的去 `rm -rf` 用户目录**。

**否决。这是安全边界，不是性能问题。**

---

## 二、真正的痛点是「每次 45 s」，而它已经能被消除

上面所有跨版本测试都是 `cache_n=0`（45 s），但那只是**该版本第一次出现**的情况。版本一旦进过 cache-ram，代价立刻掉一个数量级：

| 序列 | cache_n | prefill | wall |
|---|---:|---:|---:|
| C 第 2 次 | 37,099 | 0.80 s | 7.61 s |
| A 回切 | 36,847 | 0.80 s | 7.57 s |
| C 第 3 次 | 37,099 | 0.80 s | 7.70 s |
| A 回切 2 | 36,847 | 0.80 s | 7.66 s |

**A↔C 四个来回全部命中，wall 稳定 7.6 s。** 也就是说：漂移的真实代价 = `版本数 × 45 s`（一次性），而不是每次都 45 s。

于是解法就明确了：**服务重启后，把所有已知版本一次性灌进 cache-ram。**

---

## 三、落地：`--warm-all`

`tools/preload_system_prompt.py` 新增 `--warm-all`：枚举快照里每一个 `(tools_sha, sys_sha)` 组合，依次预热，按出现次数降序。

首次执行（4 个版本，2 个已缓存 / 2 个新灌入）：

```
[WARM-ALL] 共 4 个版本，按出现次数降序处理
  [1/4] tools=8957afcb sys=c7022493 tools_n=22 sys_chars=54321 → cache_n=35,823 prefill=2.7s wall=2.7s
  [2/4] tools=85fa5b11 sys=92ab52ca tools_n=22 sys_chars=56427 → cache_n=0      prefill=46.2s wall=57.0s
  [3/4] tools=8c0af49f sys=acc56b66 tools_n=38 sys_chars=30193 → cache_n=0      prefill=24.4s wall=30.5s
  [4/4] tools=20245ddf sys=c7022493 tools_n=23 sys_chars=54321 → cache_n=36,075 prefill=2.7s wall=10.4s
[WARM-ALL] 完成：2 个已命中 / 2 个新灌入 / 0 个失败，总耗时 100.6s
```

二次执行（全部命中）：

```
  [1/4] → cache_n=36,844 prefill=0.8s wall=11.7s
  [2/4] → cache_n=37,074 prefill=0.8s wall=7.5s
  [3/4] → cache_n=23,211 prefill=0.6s wall=6.5s
  [4/4] → cache_n=37,096 prefill=0.8s wall=6.8s
[WARM-ALL] 完成：4 个已命中 / 0 个新灌入 / 0 个失败，总耗时 32.6s
```

一次投入 100 s，之后**任何版本切换都是 6–12 s**（含 save+restore）。

用法：

```bash
P=$HOME/.workbuddy/binaries/python/versions/3.13.12/bin/python3
$P tools/preload_system_prompt.py --stats       # 看有哪些版本
$P tools/preload_system_prompt.py --warm-all    # 服务重启后跑一次
```

不挂 cron。只在 llama-server 重启后跑，因为：
- 重启后 cache-ram 清空 → 所有版本都要重新灌
- 平时跑没有收益（条目还在），反而会触发无谓的 save

---

## 四、能力边界（为什么不做更多）

| 想法 | 判定 | 原因 |
|---|---|---|
| 给 tools 排序统一顺序 | ✗ 无用 | 实测逆序 `cache_n` 相同，server 内部已归一化 |
| 裁剪 tools 描述缩短 prefill | ✗ 不做 | tools 占 20,009 token（54%），裁描述会降低工具调用准确率 |
| 开启 `--cache-reuse` 抢救断点后内容 | ✗ 不可用 | 已加载 `--mmproj`，llama-server 启动即打印 "cache_reuse is not supported by multimodal, it will be disabled"（脚本 135–136 行已记录） |
| `-np 2` 双槽隔离不同版本 | ✗ 不可用 | 脚本 27–28 行：`-np > 1` 时 draft-MTP 存在 cross-slot 串扰（上游 PR #28123），long 档强制 `-np 1` |
| 代理层统一 system / tools 内容 | ✗ 否决 | 删 `personal_files_safety` = 真会误删文件；删 LSP 声明 = 模型找不到工具 |

---

## 五、当前状态

| 项 | 值 |
|---|---|
| cache-ram | 16 GiB 预算，已容纳 4 个版本 |
| 版本切换 | 6–12 s（全部 cache_n 命中） |
| VRAM | 50,904,784,896 B = **47.40 GiB** / 96 |
| GTT | 2.07 GiB（未动） |
| 8080 / 18090 | ok / ok |
| crontab | preload 行保持注释 |

补充：`--cache-ram 16384` 实测可同时驻留 4 个 40K 版本 + 若干 100K 会话条目，暂不需要上调。若日后版本数超过 6 个，可升到 24576。

---

## 六、回滚

```bash
cp tools/preload_system_prompt.py.bak.20261111-v1 tools/preload_system_prompt.py
```

（本轮只改了 `tools/preload_system_prompt.py`，未改 docproxy、未改启动脚本、未重启任何服务。）

---

> 许可：CC0-1.0，公共领域贡献，无任何限制。
