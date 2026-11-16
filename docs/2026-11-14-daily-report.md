# 运行快照 · 2026-11-14（日报第 56 次 · 全 API 通道）

来源：本机每日自动探测，2026-11-14 05:00 (GMT+8)。主机：AMD Ryzen AI MAX+ 395（Strix Halo / gfx1151 / Radeon 8060S），统一内存 128 GiB，BIOS UMA 车分 96 GiB；引擎 llama.cpp fork（Vulkan RADV STRIX_HALO，Mesa 26.0.8 钉死）。

本篇只留对部署有复用价值的部分。一次性抓取条目（逐条 PR 编号、离线原因复述）已删。

---

## 一、运行态实测

| 项 | 值 | 来源 |
|---|---|---|
| 模型 | Qwen3.6-35B-A3B **Q5_K_P**（28.0 GB，34.66B 参数，MoE 激活 ≈3B） | `/props` + `/v1/models` |
| `n_ctx` | 262144（= `n_ctx_train`，未截断） | `/props` |
| 槽位 | `total_slots = 1` | `/props` |
| 模态 | vision=true, video=true, audio=false | `/props` |
| 投机解码 | `--spec-type draft-mtp`，`--spec-draft-n-max 2`，draft 为 `MTP-ONLY-Q4_K_M` | `ps` + `/slots` |
| KV | `q8_0`（`-ctk/-ctv q8_0`） | `ps` |
| build | `b10824-75147a27e` | `/props` |
| 启动参数 | `-ngl 999 -c 262144 -np 1 -b 4096 -ub 1024 --mmproj f16 -ctk/-ctv q8_0 --context-shift --cache-idle-slots -cms 8192 --cache-ram 16384 --ctx-checkpoints 16 --metrics --host 0.0.0.0 --port 8080` | `ps` |
| MoE 专家缓存 | **未开**（无 `--moe-cache-mib`） | `ps` |
| 暴露面 | `--host 0.0.0.0`（连续 40+ 日未收窄） | `ps` |
| 18090 docproxy | `mode=passthrough`，upstream 8080 OK；`npu_enabled=true`，`npu_upstream=http://127.0.0.1:8219` | `/health` |
| 上游落后 | 当日 `v1.0.0`（11-13）+ `b12366`；本机 b10824 落后 ≈**1542 build** | releases API |

**今日 00:08 重启** → `/metrics` 的 MTP 累计计数器清零，前一日的稳态接受率（79.99%）随之失效。**累计计数器跨重启不可比**，这是读 MTP 接受率的第一个坑。

---

## 二、当日可复用结论

1. **MTP 累计计数器不是稳态指标** —— 服务重启即归零；跨日比较接受率必须先看 `lstart`。
2. **面板托管实例必须经面板改参**：所谓"改启动参数"= 改面板 `startCommand` 再经面板重启，**不得裸跑二进制**（外部 arbiter 会 kill 非托管进程）。
3. **Mesa 钉死要复核**：`apt-mark hold` 的 6 个包在每次 `apt upgrade` 后都要确认仍在 hold 状态，否则悄悄升到 26.2.x 会致 Vulkan 全崩。
4. **基线老化是隐性风险**：decode 自 11-04、prefill 自 09-24 未重测。
   固定 2K / 8K / 32K 三档 prompt 各跑一次取均值，才能刷新可比基线；单点临时测速不可作数。

---

## 三、上游动态（一手 GitHub）

- `v1.0.0` 正式发布（2026-11-13T10:20Z），随后滚动 `b12366`。
- 新的 PR（open）：`#31274`（scheduler host mem）、`#31912`（backend grammar sampling）、`#31802`（cuda fused KV dequant）、`#32098`（**CORS / DNS rebinding 安全修复**）。
- 新的 issue：`#32231`（Gemma4 tool bug）、`#32229`（CUDA mmvq fusion 在 Pascal 慢 20–36%）、`#31947`（GLM-5.3 OOM）。
- 同硬件量化库 `kingjones30/strix-halo-quant-lab` 仍在线（原 `kingjones777/MTP-Heads-GGUF` 连续 404）。

> 采信纪律：PR 标题只能证明"有人在做"，不能证明"本机可受益"。AMD / Vulkan 路径是否受惠，须看 diff 与实机 A/B。

---

## 四、优化候选（当日判定）

| 编号 | 动作 | 判定 |
|---|---|---|
| A0 | `--host 0.0.0.0` → `127.0.0.1` | 安全项，直接影响面；18090 仍在 127.0.0.1，应用侧不受影响 |
| A1 | 追加 `--moe-cache-mib 8192` | **暂缓**（详见 2026-11-16 快照：`-ngl 999` 下必然被自动禁用） |
| A4 | `--spec-draft-n-max 3` | 需人核输出质量后再定 |
| B2 | 出片 draft 档 `steps 12→20`、`cfg 1.0→4.0` | 与社区正式档下限对齐 |
| B8 | `comfyui.comfyui_url` 仍回填 8188（无监听） | 仅日志噪音，可置空 |
| C1 | cherry-pick `#32098` / `#31274` / `#31802` / `#31912` | 只想取安全修复时走这条，不必整体升级 |
| C2 | 升级到 `v1.0.0` / `b12366` | 须先备份 mesa deb → `vulkaninfo` 验证 → 重启业务 |

---

**许可**：CC0-1.0，公共领域贡献，无任何限制。
