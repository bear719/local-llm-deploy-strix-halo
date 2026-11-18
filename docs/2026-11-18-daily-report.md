# 运行快照 · 2026-11-18（日报第 60 次）

来源：本机每日自动探测，2026-11-18 05:00 (GMT+8)。

本篇三条主结论：
① **decode 基线恢复有效：82.50 t/s**（35B-A3B Q5_K_P + MTP n=2），此前 11-15/11-16 的数据全部作废；
② **`GLIBC_TUNABLES=glibc.malloc.hugetlb=1` 是本机唯一「零代码、零 root、立即可测」的提速候选**，且前置条件已验证满足；
③ **「MoE 投机陷阱」不适用于内嵌 MTP**——社区那篇 -60% 的结论针对独立 draft 模型，不能拿来否定 MTP。

---

## 一、★ 基线刷新：82.50 t/s

| 项 | 值 | 判据 |
|---|---|---|
| decode | **82.50 t/s** | `/completion`，`n_predict=64`，`temp=0`，MTP 生效，`timings.predicted_per_second=82.502` |
| prefill | 89.02 t/s（**无效样本**） | `timings.prompt_per_second=89.023`，`prompt_n=5`，太短，不代表 pp512 |
| MTP 接受率 | **81.11%**（draft 485,287 / accepted 393,621） | `/metrics`，较 11-17 的 80.6% 微升 |
| GPU | 探测时 55 °C / use 1% / VRAM 51%；实测后 56 °C / use 47%；**无 `sd-cli`** | `rocm-smi` + `ps` |

**测速纪律（血的教训）**：11-15 那次的 17.28 t/s 是并发渲染污染，11-16 离线无数据。**任何 decode 数字在发布前必须 `pgrep -c sd-cli` 为 0**，且 prefill 在争用下会「显得更快」，单次测量一文不值。

> prefill 这一格仍空着：短 prompt 的 89 t/s 不能写进基线表。历史 `/metrics` avg 约 365 t/s 才是当前可引用值，标准复核要 `llama-bench -p 512`。

---

## 二、★ Huge pages：一个环境变量，值得立刻 A/B

社区实测（Tensward，2026-11-17，`https://tensward.com/blog/huge-pages-llama-cpp`）：

`GLIBC_TUNABLES=glibc.malloc.hugetlb=1` —— 一个 glibc 环境变量，零代码改动，让 malloc 走 hugetlb：

| 场景 | 增益 |
|---|---|
| H100 tool-calling | +21% RPS，首 token 快 22% |
| H100 plain chat | +14% |
| L4 tool-calling | +6.5% |
| L4 plain chat | +3.5% |
| 8B plain chat | 无增益 |
| 页错误 | ~124,000 → ~1,850 次/请求；L4 单快照 80 ms → 46 ms |

**本机前置条件已逐项验证满足**：glibc 2.43（≥2.35）、THP=`always [madvise] never`（madvise 生效）。生效验证方式：

```bash
grep AnonHugePages /proc/$(pidof -s llama-server)/smaps_rollup   # 应 > 0
```

启用方式：在面板实例启动命令最前面加环境变量（不改任何 flag）：

```
GLIBC_TUNABLES=glibc.malloc.hugetlb=1 <llama-server> <原参数不变>
```

**为什么本机可能有收益**：glibc malloc 的 host 侧分配（KV 主机卸载、prompt cache、mmap 元数据）页错误开销在 CPU 侧，而本机 decode 已到 82.5 t/s 档，**CPU 侧不再是完全免费的旁路**。收益与 GPU 速度正相关，本机预期中等，不会到 H100 的 +21%。

**必须 A/B，且必须按交错法做**：预热 2 次丢弃 → 加/不加各跑 3 轮交错 → 读 `timings.predicted_per_second`。分组跑（先全 A 再全 B）会被温升与后台任务污染，历史已吃过一次亏。

---

## 三、★ 「MoE 投机陷阱」不适用于本机 MTP（辨析留档）

社区有一篇流传较广的实测：Qwen3.6-35B-A3B UD-Q4，`--parallel 1` 无 draft 得 43.1 t/s，**加一个 1.5B 独立 draft 模型反降到 17.5 t/s（-60%）**，作者归因为「专家加载税」——verify 5 个 token 会触发全部 35B 专家的加载。

结论**对本机不成立**，理由是机制不同而不是数字不同：

| 维度 | 社区那篇 | 本机 |
|---|---|---|
| draft 来源 | **独立 1.5B 模型**（另一套权重，另一份内存） | **MTP heads 内嵌在主模型里**，`-md` 只是 heads 头 |
| 每 step 额外读取 | 1.5B 全量权重 | 极小 heads + 已加载的专家 |
| 实测结果 | 43.1 → 17.5 t/s | **82.50 t/s（MTP 开）** |

另一条反向证据：HN 11-14「RTX 3090 上 speculative decoding +55%」。所以「投机解码在 MoE 上普遍有害」是个**过度概括**，真正有害的是「独立 draft 模型 + 专家模型」这一组合。

同时要注意**另一侧的真实风险**（llama.cpp #27950）：采样器与 drafter 不对齐时，接受率会从 59.6% 掉到 45.7%、墙钟反而慢 2.8×。**接受率高 ≠ 输出无质量损失**，`n-max` 调整前后必须人工比对同一 prompt 的输出。

**社区 n-max 曲线（他人实测，M2 Ultra / Metal，Qwen3.6-35B-A3B UD-Q8_K_XL）**：

| n-max | decode | 接受率 |
|---:|---:|---:|
| 2 | 73.04 t/s | 86.2% |
| 3 | 76.00 t/s | 78.3% |
| 4 | 77.68 t/s | 76.7% |
| 5 | 74.68 t/s | 68.0% |

规律：**n=3~4 是拐点，n=5 回落**；且 MTP 会让 prefill 掉约 17%（1015 → ~840 t/s）。本机 `n-max=2` 偏保守，`n=3` 可能有 3~4% 空间，但要连带接受率下降与 prefill 损失一起算。

---

## 四、上游与社区动态

**事实（GitHub API，11-18 采集）**：
- release 到 **b12483**（11-17 20:05Z），本机 `b10824` 落后约 **1659 build**（较昨日 +38）。
- 新 PR（均 open）：#32501（kv-cache: guard DeepSeek attn_rot_k against zero n_embd_head_k_all）、#32502（ggml SSM_CONV backward）、#32434（server slot_sched: fix lora and recurrent）、#32439（Hexagon Nemotron MoE on HTP）、#32500（cuda MROPE/IMROPE + rms_norm_mul_rope 调优）、#32413（mtmd kokoro tts）、#31274（Save host memory for scheduler context sizing）。
- issue #22847（closed）：`http client error: Failed to read connection`。
- 同硬件仓库 gufo 11-17 密集提交：`f6346864`（server: share session state when sessions > files）、`10c578aa`（asr: accept FLAC/MP3/Ogg）、`842295e4`（perf: map session state on demand + lend to RAM cache）——**「按需 mmap + 借给 RAM cache」正是本机 prompt cache 落显存路线的同构思路**，值得跟踪。

**他人实测（待本机验证）**：
- MTP 在 Strix Halo 上 **对 27B 有效**（15k 单轮 87.44 s → 77.39 s，-11.5%；no_think 模式接受率 40~90%，thinking 模式降到 ~76%），但在 **35B-A3B 某些后端翻车**（Metal issue #23011：26.23 → 1.93 t/s，接受率却 95.6%）。**翻车与接受率无关，是后端实现问题**；本机 Vulkan/RADV 实测 82.5 t/s，不属该场景。
- H3 量化档：Q4_K_M 在 32 GiB 机器含加载 57~62 s、Q8_0 约 94 s；蒸馏档推荐 `--cfg-scale 1.0 --steps 8`。

---

## 五、基线对照表（本机 vs 社区同硬件）

| 维度 | 本机（实测） | 社区最优（他人实测） | 差距/动作 |
|---|---|---|---|
| decode | **82.50 t/s**（35B Q5_K_P + MTP n=2） | 35B UD-Q4 MTP n=4 77.7（Metal）；27B UD-Q4 12.82（无 MTP） | 已第一梯队，n=3~4 或 +3~6% |
| prefill | 短样本 89（无效）；历史 avg 365 | pp512 414（27B Q4）；pp8192 1409（30B-A3B） | **本机短板**，待 `llama-bench` 复核 |
| 上下文 | 262144 实跑 | 社区多为 8k~32k | 规格领先，KV 内存需配套 |
| KV | q8_0 + 131072 checkpoint 窗 + 16 GiB cache-ram | 非对称 Q8_0 K/V 为 MoE 推荐 | 已对齐 |
| 显存 | 96 GiB UMA carve-out，`-ngl 999` 全 offload | Vulkan 可寻址约 112 GB | 健康 |
| 驱动 | Mesa **26.0.8**（6 包 hold） | 26.2.5-arch 正常 | **勿升**，本机 26.2.x 回归崩溃 |
| 内存页 | **未启用 huge pages**，glibc 2.43 / THP=madvise 满足前置 | H100 +21% / L4 +6.5% | **P0，立即可 A/B** |

---

## 六、可执行清单（按风险分级）

**一级 · 改启动环境（低风险，面板改命令即生效）**
1. 【P0】加 `GLIBC_TUNABLES=glibc.malloc.hugetlb=1`，A/B 后决定保留 → 见第二节。
2. 【P1】`--spec-draft-n-max 2 → 3`，配合输出质量人核（#27950）→ 见第三节曲线。

**二级 · 改配置（零重启）**

3. 【P1】导播台画质档复位：`steps 12 → 20`、`800×448 → 576×1024`；`cfg=1.0` 保持不变。
4. 【P2】清空 `comfyui_url`（8188 无监听，只是日志噪音；渲染后端已是 sdcpp）。
5. 【P2】`apt-mark showhold | grep -E 'mesa|libgbm|libgl1|libglx|libegl'` 确认 6 包仍 hold。

**三级 · 需重建**

6. 【P2】**本轮不建议升级到 b12483**。理由：已稳定跑 82.5 t/s，落后 1659 build 的收益（Vulkan/MoE 修复）无法在本机预先量化，而 v1.0.x 有 ABI 破坏（废弃函数删除、NextN 头迁移、RPC v9），drama 应用链自研代码需同步检查。真要升，先 `apt-get download` 备份 6 个 mesa deb，升级后 `vulkaninfo | grep STRIX_HALO` 不通过就退回。

---

## 七、风险

- **接受率不等于质量**：81.11% 很高，但 `n-max` 调整仍须人工比对（重点看 JSON/结构化输出与长推理链）。
- **huge pages 因机而异**：原作者自述同型号机器间增益有差异、最长只测了半小时。本机必须 A/B。
- **累计计数器跨重启归零**，别把归零当回归。
- **`/props` 的 `speculative.types` 不可信**（见 `docs/2026-11-17-daily-report.md` 第一节），判 MTP 只认 `ps` + `/slots` + `/metrics`。

---

*许可：CC0-1.0，公共领域贡献，无任何限制。*
