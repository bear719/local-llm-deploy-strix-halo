# 运行快照 · 2026-11-24（日报第 66 次）

来源：本机每日自动探测，2026-11-24 07:11 (GMT+8)，全 API 通道（免登录、无浏览器渲染）。
数据纪律：本机 curl 实测为唯一「本机事实」；社区数值一律标注「他人实测，待本机验证」并附来源 URL；本轮无新实测不编造数字。

本期三条主结论：

① **8080 现需 API Key**：无 key 访问 `/props`、`/v1/models` 返回 401（`/health` 仍 ok），配置 `--api-key-file` 已生效 —— 这是公网暴露面处置后的新常态，排障时须带 key 才能拿到全字段；
② **上游推进到 b12655**（11-23 23:18Z），本机 b10824 落后 ≈1831 build（较昨日 1809 扩大 +22）；
③ **本机配置零变更、无架构级新增、无性能新实测** —— decode 基线维持 **68–88 t/s** 区间，不引用单值。

---

## 一、平台实测（来自当日配置探查）

| 项 | 值 |
|---|---|
| 8080 | `/health` ok；`/props`、`/v1/models` 需 key（401 = 鉴权正常拦截，非故障） |
| 18090 docproxy | `/`、`/health` 均 `{"status":"ok"}`，passthrough → 8080，`npu_upstream`=8219 在线 |
| model_path | `Qwen3.6-35B-A3B-Uncensored-Q5_K_P.gguf`（Q5_K_M，26.1 GiB，34.66B ≈35B-A3B MoE） |
| n_ctx / n_ctx_train | 262144 / 262144（全量，无 clamp） |
| slots | 1（`-np 1`）；模态 vision+video，audio 关 |
| build | b10824-75147a27e |
| MTP 三处交叉验证 | `/props` default=`none`（**不可信，忽略**）；`/slots[0].params`=`none,draft-mtp` ✅；进程 `--spec-type draft-mtp --spec-draft-n-max 2` ✅ |
| KV | `-ctk q8_0 -ctv q8_0` + `--cache-idle-slots -cms 8192 --cache-ram 16384 --ctx-checkpoints 16` |
| 采样链 | penalties → dry → top_n_sigma → top_k → typ_p → top_p → min_p → xtc → temperature |
| decode | 本轮未实测；基线维持 68–88 t/s（昨日单次 87.75） |
| prefill | 基线缺失（有效样本需 ≥4k prompt） |
| 模型 C | `Qwen3.8-Flash-Next-ROCmFP4-FAST-v2`（93.47 GB / 176.94B）仍离线，无切换 |

**MTP 判据复用**：判断投机解码是否真的启用，只看 `/slots` 参数 + 进程命令行 + `/metrics` draft 计数三处；`/props` 的 `speculative.types=none` 是已知误导项。

端口拓扑：`8080`=llama-server（需 key）｜`18090`=docproxy｜`8000`=非 llama（404）｜`8081/8082/8010/8086/11434`=无监听（000）。

---

## 二、MiniMax-H3 出片配置核查（B0–B11）

配置源 `config.json`（mtime 11-19，自 11-12 未变），sd.cpp 空闲，无渲染任务。

| 编号 | 检查项 | 结论 |
|---|---|---|
| B0 | 渲染后端 `sdcpp` / build-vk4 | ✅ 零漂移 |
| B1 | llama 恢复链路（8080 + 18090） | ✅ 闭环 |
| B2 | steps=**12**、画布 **800×448 横屏** | ⚠️ 双漂移延续（社区共识 steps 20–30 / 竖屏 576×1024）；本轮记录「cfg 字段缺失」**次日被证伪**，见 11-25 快照 |
| B3 | LLM 后端走本地 18090、模型与 8080 一致 | ✅ |
| B4–B7 | 母版合成 / 音色绑定 / 语音限幅 / 拼接过渡 | ✅ 延续（xfade 0.292 + trim_head 0.3 配置层已落地，成片未复测） |
| B8 | `comfyui_url`=`127.0.0.1:8188` | ⚠️ 漂移延续（8188 无监听，仅 Connection refused 噪音） |
| B9 | `--vae-tiling` | ✅ |
| B10 | Mesa 6 包 `apt-mark hold @ 26.0.8-1ubuntu0.3` | ✅ 防升至致 Vulkan 失效的 26.2.5 |
| B11 | `gpu.arbiter.need_gib=64`、build-vk4 存在 | ✅ |

**采集教训**：B2 的「cfg 字段缺失」是**探查脚本字段路径写错**导致的误报，不是配置缺失 —— 见 11-25 快照 §二 B2 修正。这类「字段缺失」结论必须先核对字段实际路径再下判断。

---

## 三、上游动态（一手源）

- llama.cpp releases：**b12655**（11-23 23:18Z）、b12651（11-23 08:52Z）。本机 b10824，落后 ≈1831 build。来源 `api.github.com/repos/ggml-org/llama.cpp/releases`。
- PR/issue 最新 #32582（hexagon int-hmx、f32→f16 lowering，open）。`#31802`（CUDA KV 反量化）是 PR 号非 git 对象，禁用 `git merge-base`，本机未落地。
- gufo-org/gufo：11-23 两连（#1360 ext 互相依赖链接、#1365 CI 等待 rate limit）。
- kyuz0/amd-strix-halo-toolboxes 最新 11-18（00b6e5b）；Nathanw1014 10-25；drluoto 08-28（停滞）。
- kingjones777 / kingjones30 MTP-Heads-GGUF 两仓库均 404，持续失效，不重试。

## 四、社区信息（他人实测，待本机验证）

- **HN 新帖**：NariQ 发布 Qwen3.8-27B 3-bit / 2.5-bit / 2-bit 量化（约 10 GB，宣称近 BF16 质量），需 nari-labs/nari-llama.cpp fork；DeepSWE 39.8/41.0/41.9/28.6。来源 `hn.algolia.com/api/v1/search_by_date?query=llama.cpp`（HN 查询的 `>` 须写成 `%3E`，否则 400）。
- **aidaily.fyi Strix Halo 话题页**：Flash-Next 获 Strata 官方实验性支持（Linux only）；halogen 0.12.0 使 1M ctx decode 27.3→38.3 t/s；LemonSeed R9700 eGPU 159 t/s vs Strix Halo 64.4。
- **hqwc.cn APU 128 GB 双后端记录**：Flash-Next-125B Q4_K_M（68 GB）全驻留；LPDDR5X-8000 256-bit 理论带宽 256 GB/s；MoE 每 token 激活 ~6B，理论解码上限 ≈21 t/s。
- **llamaperf**（11-18）：Flash-Next IQ3_S，Strata 27.60 vs llama.cpp 22.16 t/s（24842 ctx、MTP off）；Strata 开 MTP 后 56.7 t/s。
- **getrigbase**：Strix Halo Vulkan fork Flash-Next 31–39 t/s @32k；EngramHalo.cpp Q4_K_XL 20.8→36.1（+MTP）。

> 来源均已标注；与本机架构（Qwen3.6 内嵌 MTP head、单 APU Vulkan）差异处不直接套用。

---

## 五、与社区同硬件对比（本机现状 vs 他人实测）

| 维度 | 本机 | 社区同硬件（待验证） | 差距 / 优先级 |
|---|---|---|---|
| decode 35B-A3B | 68–88 t/s 区间（Q5_K_P + 内嵌 MTP n=2） | 93 t/s（Q4_K_M + MTP）| 量化档不同非严格等价，P2 |
| prefill | 基线缺失 | 1603（Flash-Next @131072, halogen）| 长上下文公认短板，P1 |
| 上下文 | 262144 满训 | 社区多 131072，主动封顶规避长 prefill 衰减 | 满窗 MTP 收益需单测，P1 |
| KV | q8_0 | q8_0 甜点（混合注意力 ~20 KB/token）| 一致 |
| MTP | n-max=2，接受率 80.65% | n=5/n=6（他机 3.1×/2.3×），接受率 73–95% | 架构不同不可直接套，P1 |
| 引擎版本 | b10824 | b12655（落后 ≈1831 build）| cherry-pick 评估而非整包替换，P1 |

---

**许可**：CC0-1.0，公共领域贡献，无任何限制。
