# 运行快照 · 2026-11-17（日报第 59 次 · 全 API 通道）

来源：本机每日自动探测，2026-11-17 05:00 (GMT+8)；抓取通道为 GitHub REST API + HN Algolia + 二手聚合，**全部免登录**。

本篇三条值得留档的东西：
① **如何证明 MTP 真的在跑**——`/props` 给出的 `speculative.types="none"` 是假话，必须三处交叉验证；
② **完整启动命令行首次被逐条捕获**（含 prompt cache / context checkpoint 全套参数）；
③ **8080 从离线自愈**：上一轮判定的「面板实例未拉起」自行恢复，说明它不是持久故障。

---

## 一、★ MTP 三处交叉验证（可复用判据）

`/props` 与 `/slots` 对同一件事给出相反答案。实测结论：**`/props...params.speculative.types` 是 fork 已知不可信字段**，返回 `"none"` 时 MTP 可能正在满速工作。

| # | 判据 | 本次实测值 | 可信度 |
|---|---|---|---|
| 1 | `/slots[0].speculative` + `params."speculative.types"` | `true` / `none,draft-mtp` | 高（槽位实际生效参数） |
| 2 | `ps` 命令行是否带 `--spec-type draft-mtp --spec-draft-n-max N -md ...MTP-ONLY...gguf` | 三项齐全 | 最高（进程真相） |
| 3 | `/metrics` 的 `spec_decode_num_draft_tokens_total` / `_accepted_tokens_total` | draft 221,051 / accepted 178,117 = **80.6%**；per-pos pos0=96,010 / pos1=82,107 | 最高（计数器在动，非静态配置回显） |

三条全绿才能下「MTP 生效」的结论。只查 `/props` 会得到相反的假答案。

**附带的两个坑**：
- 计数器是**累计值，跨重启归零**，所以「接受率下降」在重启后必然出现，不能当回归信号；
- per-pos 分解（pos0 / pos1）才能看出 `n-max` 的实际消耗结构——本次 pos0 占 54%、pos1 占 46%，说明第二草稿确实被大量验证，`n-max=3` 理论上还有空间但边际递减。

---

## 二、★ 完整启动命令行（首次逐条落档）

```
-ngl 999 -c 262144 -np 1 -b 4096 -ub 1024
--mmproj $HOME/models/mmproj-...-f16.gguf
-ctk q8_0 -ctv q8_0
--context-shift --cache-idle-slots -cms 8192 --cache-ram 16384 --ctx-checkpoints 16
--metrics --host 0.0.0.0 --port 8080
-md $HOME/models/Qwen3.6-35B-A3B-MTP-ONLY-Q4_K_M.gguf --spec-type draft-mtp --spec-draft-n-max 2
```

要点：
- `-cms 8192 × --ctx-checkpoints 16` = **131072 的 checkpoint 覆盖窗口**，这是长上下文换槽后能秒回的前提；
- `--cache-ram 16384` 是 MiB 而非 token，正数会**顶高**驻留条数上限（`-1` 反而最严格，见 `MEMORY` 的语义反直觉记录）；
- 抓到的参数与此前记忆一致，**无法确认是否本轮新增**，只记「已确认在跑」。

`/props` 另有一处版本差异：props 报 `chat_format=Content-only / reasoning_format=none`，而 slots 实际是 `peg-native / deepseek`。**以 slots 为准**——props 是模板默认值，slots 是请求侧实际注入。

---

## 三、8080 离线自愈：说明「实例未拉起」是非持久态

| 日期 | 05:00 状态 | 判定 |
|---|---|---|
| 11-16 | 离线 | 面板实例未拉起（无进程、显存 0%） |
| 11-17 | **在线** | 自愈，无需人工干预 |

意义：11-16 那条「auto_resume 未触发」的结论应弱化为**偶发**，而不是需要改配置的缺陷。排障顺序仍按三态表走（仲裁暂停 / 实例未拉起 / 代理层独立故障），不要因为一天离线就去改 `auto_resume`。

---

## 四、上游与社区动态（区分事实 / 他人实测）

**事实（GitHub API，11-17 采集）**：
- 上游 release 到 **b12445**（11-16 20:44Z），本机 `b10824-75147a27e` 落后约 1621 build。
- PR **#27897**（11-16 20:28Z，open）：`speculative: fix combined draft-mtp + external draft (-md) init crash`。本机配置正好是「`-md` MTP-ONLY 头 + `--spec-type draft-mtp`」，属标准 MTP 路径，**未命中**该「MTP + 独立 draft 模型」组合崩溃场景，但 draft 初始化存在边界 crash 这件事本身值得记一笔。
- issue **#32336**：`timings.cache_n` 会泄露同 slot 他人 prompt 的匹配量——共享 slot 部署下有信息泄露面，与「`--host 0.0.0.0` 收窄」属同一类风险。
- issue **#32424**：deepseek4 无 CSA 层时 KV 构造除零崩溃（与本机 35B-A3B 无关，但 284B 级 deepseek4 部署前需确认已修）。
- 其他 AMD 相关 PR：#32266 `ggml-cuda: hip few mmq on non-wmma arch`、#32172 `ggml-openvino: NPU/GPU 内存优化`。

**他人实测（待本机验证）**：
- Strix Halo AXB35 128GB，Flash-Next IQ4_XS 在 halogen 0.18.23 上 **68.8 t/s**；27B ROCmFP4-FAST 走 ROCmFPX fork(b12501)+MTP 4 草稿 **38.6 t/s**、prefill 353@12k。
- Strix Halo + Gufo v0.31（125B 级 UD-Q4_K_XL、q8_0 KV、MTP 7 草稿）：41 t/s@55–67K，prefill 1240–1335，MTP 接受 70–91%。
- 社区共识（H3 蒸馏模型）：steps 20–30（25 为甜点），**cfg 必须 1.0**，画布 576×1024 竖屏起步，tiled VAE 是降显存关键。

**一条容易踩的对照陷阱**：Framework Desktop 395 128GB 上 27B UD-Q4_K_M 只有 **12.82 t/s**，但其 Mesa 是 26.2.5-arch；本机 26.2.x 会崩、钉死在 26.0.8。**同类基准不能跨 Mesa 版本外推**。

---

## 五、导播台 config 逐项核对（无新增漂移）

`config.json` 自 11-12 未变。本轮 11 项检查中唯一实质变化是 **B1 关注点闭环**（8080 在线，应用 LLM 链路可用）。

| 编号 | 项 | 实测 | 判定 |
|---|---|---|---|
| B0 | 渲染后端 | `backend=sdcpp`，`sd-cli` 存在（build-vk4） | ✅ sd.cpp Vulkan 原生，非 ComfyUI |
| B1 | 仲裁 | `need_gib=64`、`limit_gib=80.5`、`auto_resume=true`、`force_pause=true` | ✅ 本轮闭环 |
| B2 | 步数/CFG/画布 | `steps=12`、`cfg=1.0`、`800×448` 横屏 | ⚠️ 双漂移（步数低于共识、画布非竖屏）；cfg=1.0 正确**勿改** |
| B4 | 母版合成 | 1920×1080 / crf18 / loudnorm I=-16 TP=-1.5 / xfade 0.292 | ✅ |
| B5 | 并发 | `1` | ✅ sd-cli 与 llama 共用同一显存池，必须串行 |
| B8 | comfyui_url | 仍填 `127.0.0.1:8188`（无监听） | ⚠️ 仅日志噪音，建议置空 |
| B11 | Mesa | 6 包 hold 在 26.0.8 | ✅ 勿升 |

**长期未决项本轮仍无进展**：`--host 0.0.0.0` 收窄（42+ 日）、`--moe-cache-mib` A/B（全 offload 下自动禁用）、prefill 短板、`n-max=3` 与 #27950 质量人核。

---

*许可：CC0-1.0，公共领域贡献，无任何限制。*
