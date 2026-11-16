# 运行快照 · 2026-11-15（日报第 57 次 · 全 API 通道）

来源：本机每日自动探测，2026-11-15 05:00 (GMT+8)。

本篇的核心是**一条被推翻的旧结论**：并发渲染期间测出的速度不能当基线，而旧文档里"主 LLM 与渲染器无冲突"的说法只在空闲态成立。

---

## 一、★ 并发渲染会真实压垮 llama（旧结论修正）

探测窗口内 `sd-cli -M img_gen` 正在并发渲染（qwen-image 2.1，800×448 / 20 步），此时：

| 指标 | 并发渲染窗口内 | 空闲态基准 | 判定 |
|---|---|---|---|
| decode | **17.28 t/s** | 72.41 t/s（11-04，temp0） | **-76%** |
| prefill | **621 t/s**（4001 tok / 6.44 s） | ~400 t/s（09-24） | 数值偏高但**不可作基线**（抖动大） |
| 8080 端口 | 在线 | 在线 | 服务层无端口冲突 |

**结论修正**：
- 端口层面确实"无冲突"（两者都只是 GPU 后端争用，不是抢端口）；
- 但**负载层面争用真实存在**，且幅度极大（decode 掉四分之三以上）；
- 根因：`gpu_arbiter` 对 image 档（800×448 / 20 步）判定在预算内，**不会暂停 llama**。

**方法论纪律**：
1. 测速前必须 `pgrep -c sd-cli` 确认返回 0；有渲染进程在场，任何数字作废。
2. 反过来，prefill 在争用下反而"看起来更快"（621 vs 400）—— **单次测量不可信，须看多次均值与方差**。
3. 若需保主 LLM 响应：临时提高 `arbiter.need_gib` 让 image 档也触发暂停，或错峰调度渲染任务。

---

## 二、运行态实测

| 项 | 值 |
|---|---|
| 模型 | Qwen3.6-35B-A3B Q5_K_P（28,016,404,992 B；34.66B 参数；`n_embd` 2048 / `n_vocab` 248320） |
| `n_ctx` / `n_ctx_train` | 262144 / 262144 |
| 槽位 | 1 |
| 投机解码 | MTP 启用；`-md ...MTP-ONLY-Q4_K_M.gguf --spec-type draft-mtp --spec-draft-n-max 2` |
| MTP 接受率 | 累计快照 68.2%（draft 5170 / accepted 3524）；单请求抽样 59%（234 / 138） |
| KV | q8_0 |
| 采样默认 | temp 1.0、top_k 20、top_p 0.95、min_p 0.05、repeat_penalty 1.0；samplers 含 dry / top_n_sigma / typ_p / xtc |
| build | `b10824-75147a27e` |
| MoE 专家缓存 | 未开 |
| 暴露面 | `--host 0.0.0.0`（连续 41+ 日） |

> ⚠️ **`/props` 的 `default_generation_settings.params.speculative.types = "none"` 是本 fork 的已知不可信字段**。
> 判定 MTP 是否生效，只认 `ps` 命令行 + `/metrics` 计数器两处；`/slots[0].params.speculative.types` 的 `None` 只是 per-request 缺省，不代表服务端没开。

---

## 三、出片侧参数核查（10 项零漂移 + 2 项历史漂移）

| 项 | 实测 | 结论 |
|---|---|---|
| `render.backend` | `sdcpp` | ✅ 非 ComfyUI |
| `render.steps` / `cfg_scale` | **12** / **1.0** | ⚠️ 漂移延续：社区 draft 档 8–15 / CFG 4–8，本机步数偏低 |
| `render` 画布 | **800×448**（16:9 横屏） | ⚠️ 偏离短剧竖屏 **576×1024** 共识 |
| `image.steps` / `cfg_scale` | 20 / 4.0，1024×576 | ✅ 对齐社区正式档 |
| `llm.base_url` / `model` | `http://127.0.0.1:18090/v1` / 本地 Qwen3.6 Q5_K_P | ✅ 连续三日坐实（应用侧一律 18090） |
| 母版 | 1920×1080 / 24 fps / crf18 / aac192k | ✅ |
| sd.cpp bin | `build-vk4` 版本 | ✅ vk4 优于 vk2 约 6.8% |
| 8188 ComfyUI | 无监听 | ✅ 已弃用 |
| `comfyui.comfyui_url` | 仍为 `http://127.0.0.1:8188` | ⚠️ 与"已清空"的历史记录不符，仅日志噪音 |
| `SDCPP_EXTRA_ARGS` | `--vae-tiling` | ✅ 已确认生效（防 VAE OOM） |
| `gpu.arbiter` | `need_gib=64`、`limit_gib=80.5`、`margin_gib=1.0`、`auto_resume=true` | ✅ |
| 驱动栈 | Vulkan RADV STRIX_HALO，Mesa 26.0.8（6 包 hold） | ✅ 勿升 26.2.x |

**方法纪律**：出片侧参数与文档记录不一致时，一律以 `config.json` 当日实际值为准，旧记录当场作废 —— 不要"以文档为准去解释代码"。

---

## 四、上游动态（一手 GitHub）

- 上游 `b12366`（11-13）→ **`b12387`（11-14）**，单日 +21；本机落后 ≈**1563 build**。
- `#27788`（open）：**把多序列投机解码与 MTP 暴露到公共 C API** —— 本机 MTP 路线获上游背书。
- `#32281`（open）：为投机解码相关 PR 建 CI 测试 —— 质量保障增强。
- `#26348`（open）：ggml-cpu x86 VNNI Q2_0 点积 3× 提速（非 AMD GPU 路径，参考价值有限）。
- `#32291`（open）：OpenVINO Qwen3.5 mask。

---

**许可**：CC0-1.0，公共领域贡献，无任何限制。
