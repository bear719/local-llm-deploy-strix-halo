# 运行快照 · 2026-11-19（日报第 61 次）

来源：本机每日自动探测，2026-11-19 05:00 (GMT+8)。

本篇四条可复用结论：

① **decode 仍在 68–82 t/s 区间内**，单次 81.88 t/s，不作新基线；
② **上游 build 数继续快速膨胀**（较本机落后 ≈1700 build），但本机是深度定制 fork，升级路径是 cherry-pick 而非整包替换；
③ **导播台出片参数依旧双漂移**（steps 12 + 横屏画布），社区共识仍是 20–30 步 + 竖屏；
④ **外部同硬件实测首次出现「MoE 35B + MTP」对照数字**（Q4_K_M 62 / 93 t/s），可作为本机 Q5_K_P 的量化档参照。

---

## 一、本机实测

| 项 | 值 | 判据 |
|---|---|---|
| 8080 在线 | 连续第 5 天 | `/health` |
| decode | **81.88 t/s** | `/completion`，`n_predict=64`，`temp=0`，GPU 空闲无 `sd-cli` |
| MTP 接受率 | **81.24%** | `/metrics` draft/accepted 累计值，较 11-18 的 81.11% 微升 |
| GPU | 56 °C / 1% / 约 51 W | `rocm-smi` |
| 上游差距 | 本机 `b10824-75147a27e` vs 上游 ≈ b12521，**落后 ≈1700 build** | GitHub releases API |

> 基线纪律不变：**68–82 t/s 区间**表述，单次数字不定论；任何 decode 数字发布前必须 `pgrep -c sd-cli` 为 0。

---

## 二、上游与社区（事实 vs 他人实测）

**事实（GitHub API）**

- 新 PR 群集中在 Vulkan / MoE / 投机解码三条线上：CUDA FA 一致性、vulkan 对 Qualcomm 驱动的 subgroup 算术禁用（AMD/Vulkan 邻域）、`llama-grammar` 整数溢出、gguf-py BPE 分数顺序、context 无 OpenMP 时的过度 CPU 轮询。
- issue 侧出现 gpt-oss-120b 的 MXFP4 harmony token 打乱工具调用、`v1.0.0` 语义化版本无 release 二进制两条。

**他人实测（待本机验证）**

| 来源 | 结论 | 与本机关系 |
|---|---|---|
| 某 Strix Halo 395 MoE 实测帖 | Qwen3-30B-A3B IQ4_XS（RADV Vulkan）**100 t/s**；实测带宽 ~215 GB/s（理论 256，差 16%） | 同硬件不同模型，仅作带宽上限旁证 |
| 27B dense 基准群 | 同硬件 Q4_K_M 12.82 t/s | 与本机 27B 22.4 t/s 不同量化档，不可直接比 |
| H3 工作流多源共识 | steps 20–30、CFG 3–7（蒸馏模型必须 1.0）、竖屏 576×1024 | 直接支撑导播台 B2 复位建议 |

> 采纳纪律：外部速度数字必须同时具备**模型量级、量化格式、窗口长度、后端**四要素才可与本机基线比较，缺一项不引用。

---

## 三、导播台专项（B0–B11 逐条）

| 编号 | 项 | 结论 |
|---|---|---|
| B0 | 渲染后端 / 仲裁 | `sdcpp`（`build-vk4/bin/sd-cli`）；`need_gib=64`、`limit_gib=80.5`、`auto_resume=true`、`force_pause=true` |
| B1 | llama 托管与恢复 | 8080 在线第 5 天，面板托管，渲染前停 / 渲染后恢复链路正常 |
| B2 | 出片参数 | `steps=12` + **800×448 横屏** —— **双漂移延续**；`cfg_scale=1.0` 正确（蒸馏模型勿改） |
| B3 | LLM 决策后端 | 本地 35B / 18090，与 8080 在线模型对齐 |
| B4 | 母版合成 | `loudnorm I=-16:TP=-1.5:LRA=11`、44.1 kHz、`trim_head=0.3`、`xfade=0.292` |
| B5 | 音色/角色绑定 | `ref_characters`/`ref_voices` 错位根因在数据层，未改 |
| B6 | 人物一致性 | `link_mode=independent` 跨镜头零锚定，需系列级 cast 参考图（代码级） |
| B7 | 卡顿/拼接 | xfade + trim_head 已落地配置层；4 步档微闪属 draft 档固有 |
| B8 | `comfyui_url` | 仍指 `8188`（无监听，纯日志噪音；后端已是 sdcpp） |
| B9 | VAE tiling | `.env` 中 `SDCPP_EXTRA_ARGS="--vae-tiling"` 延续 |
| B10 | sd.cpp build | `build-vk4` 存在，config 指向正确 |
| B11 | Mesa 驱动栈 | 6 包全部 `apt-mark hold` @ **26.0.8**（26.2.x 曾致 Vulkan 全崩，勿升） |

**专项结论**：本地链路健康，**无新增漂移**；可执行项仍是 B2 复位（steps→20、画布→576×1024）与 B8 清空。

---

## 四、本机 vs 社区同硬件对照

| 维度 | 本机 | 社区（他人实测） | 判定 |
|---|---|---|---|
| decode（35B-A3B + MTP） | 81.88 t/s（Q5_K_P，n=2） | 62 / 93 t/s（Q4_K_M，无/有 MTP） | 本机在 MTP 档接近同硬件上限；Q5 与 Q4 量化档不同，非 apples-to-apples |
| prefill | 短样本无效，历史 avg ~365 | 1240–1335（模型 C @262k，另类硬件） | **本机短板**，须 `llama-bench -p 512` 复核 |
| 上下文 | 262144 | 社区多用 131072 | 本机满配，长上下文代价需实测 |
| KV | q8_0 | q8_0 为主流甜点 | 对齐 |
| 出片画质档 | steps 12 + 横屏 | steps 20–30 + 竖屏 | 待复位 |

---

## 五、可执行项

**一级 · 改启动环境（面板改命令，禁止裸跑）**

```bash
GLIBC_TUNABLES=glibc.malloc.hugetlb=1 <原启动命令，参数不变>
```

**二级 · 改配置（无需重启 LLM）**

- `render.steps` 12 → 20，`render.width/height` 800×448 → 576×1024，`cfg_scale` 保持 1.0
- `comfyui_url` → `""`

**三级 · 需重建（先备回滚）**

- 升级上游前先 `apt-get download` 备份 6 个 mesa deb；本 fork 不可整包替换，只做 cherry-pick 评估。

---

## 六、风险

- MTP 输出质量（#27950）仍未人工闭环：改 `n-max` 前后必须比对同一 prompt 的输出，不能只看 t/s。
- MTP 累计接受率**跨重启归零**，别把归零当回归。
- `/props` 的 `speculative.types` 不可信，判 MTP 只认 `ps` + `/slots` + `/metrics`。

---

*许可：CC0-1.0，公共领域贡献，无任何限制。*
