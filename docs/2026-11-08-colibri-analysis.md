# colibri 深度分析（本地推理引擎对照评估）

> 生成日期：2026-11-08
> 触发：周复盘 M-148 建议「Vulkan 构建对照 llama.cpp 测速」，本次做落地前技术评估
> 本机环境：AMD Ryzen AI MAX+ 395（Strix Halo）/ 96 GiB 统一内存（UMA carve-out）/ RADV STRIX_HALO Vulkan 1.4.354 / 主力 llama.cpp（8080 真模型 + 18090 docproxy 代理）

---

## 一、来源与基本事实（可回溯）

| 事实项 | 数值 / 描述 | 来源 |
|---|---|---|
| 仓库 | `JustVugg/colibri` | 本地 `LEARNINGS.md` M-148（首次发现 2026-11-03）+ WebSearch 多源 |
| 主语言 / 许可 | C / Apache-2.0 | WebSearch #1（one-man-company）、#2（mygit） |
| 创建 / 最近推送 | created 2026-07-01 / pushed 2026-11-02 | 本地 M-148（GitHub API 11-03 权威值） |
| Star 口径 | 46,482★（11-03, +655 日）/ 47.4k（11 月 CSDN, +802 日）/ 48,765★（archestack 11-07） | 本地 M-148；WebSearch #3、#5 |
| ⚠️ Star 增长 | 自 2026-07-01 起 4 个月累计 ~48.8k，曲线异常陡峭，v2.1.0(10-31)后爆拉 | WebSearch #5（archestack「0 on 4 Jul → 48,765 on 7 Nov」）；情报层警示，不影响技术判断 |
| 版本 | v2.1.0，released 2026-10-31 | WebSearch #1 |
| 引擎数 | 13 个（10 语言模型 + 1 画图 + 2 决策） | WebSearch #2（mygit） |
| Open issues | 154 个，含 Windows CUDA 文件与构建求助 | WebSearch #4（hu6） |
| 默认端口 / 接口 | 8000，暴露 OpenAI / Anthropic 风格端点 + MCP server | WebSearch #5（archestack） |

---

## 二、技术架构解析（范式层）

colibri 的核心范式 = **专家级分级存储（hierarchical expert storage）**，与 llama.cpp「整权重加载」路线根本不同：

- **route / union / place / overlap / learn**：routing 决定每 token 激活哪些专家；union 合并热路径；place 把专家分层放置（热→GPU、温→RAM、冷→NVMe 磁盘）；overlap 让磁盘读取与计算重叠；learn 是**学习型放置策略**（learned cache），而非简单 LRU。
- **LRU 热度缓存 + 多层放置**：高频专家常驻 GPU/内存，低频专家按需从磁盘流式读入（来源：本地 M-148 模式段）。
- **单文件每模型族**：一个模型家族对应一个引擎文件，结构比大模型框架易读（WebSearch #4）。
- **v2.1.0 关键升级**：① 原生 GGUF 导入 `coli import model.gguf`，接受任意 GGUF 无需转换/重量化（解锁 HuggingFace 全量量化）；② 跨平台 GPU：Linux/Windows **Vulkan** 后端（>VRAM 模型溢出专家到 RAM 池）、Windows CUDA archive（compute 8.0+）、Apple Silicon Metal（WebSearch #1）。
- **支持模型族**：GLM-5.2/5.3、Kimi K3、DeepSeek V4 Flash / V4.1 Flash、MiMo-V2.6 Flash、Qwen3.8-Flash-Next、**Qwen3.6（同时跑 Qwen3-Coder、dense Qwen3.8-27B、Flint、Muse Spark Open、LFM3-VL）**、OLMoE（WebSearch #2）。

---

## 三、与 llama.cpp 的对照（本机语义差异）

| 维度 | llama.cpp（本机主力） | colibri |
|---|---|---|
| 权重驻留 | 整权重加载到统一内存（96 GiB 全装下 35B-A3B Q4 ~20G + 27B Q4 ~13.6G） | 分层：稠密层常驻 RAM，routed experts 按热度流式（GPU/RAM/磁盘） |
| 本机 96 GiB 含义 | 充裕，无需磁盘流式 → 带宽墙是瓶颈（27B 22.4 t/s） | 磁盘流式卖点（跑装不下的超大模型）**对本机无意义**——我们装得下 |
| 成熟度 | 极成熟，已深度调优（MTP、262144 ctx、iGPU Vulkan 实测 35B-A3B 57.4 t/s） | 154 open issues，iGPU 实测缺失（archestack：「Discrete GPU path not measured」） |
| 部署形态 | 二进制 + MCSManager 托管（铁律） | 单文件零依赖，`make` 或 `start-here.sh` 一脚本体 |
| 接口 | OpenAI `/v1/chat/completions`（8080）+ docproxy(18090) | OpenAI/Anthropic 端点 + MCP server（8000） |
| 私有格式支持 | 支持本 fork 私有 ggml type 101（27B-ROCmFP4） | **仅标准 GGUF**，私有 type 101 不可读 |

**关键约束（现实阻断）**：本机两个主力模型中，`Qwen3.6-35B-A3B-Uncensored-Q4_K_P.gguf` 是**标准 Q4_K_P**，colibri 可读；但 `Qwen3.8-27B-ROCmFP4-FAST.gguf` 是**本 fork 私有 ggml type 101** 格式，colibri 的 GGUF 解析不认 → **colibri A/B 只能测 35B-A3B，27B 测不了**。

---

## 四、本机（Strix Halo）适配评估矩阵

| 项目 | 判定 | 依据 |
|---|---|---|
| 35B-A3B 能否加载 | ✅ 可（标准 Q4_K_P GGUF） | WebSearch #2 列 Qwen3.6 engine 原生支持 |
| iGPU Vulkan 加速是否覆盖 | ✅ 覆盖（Qwen3.6 在 iGPU 加速列表） | WebSearch #1：「iGPU only for models measured faster there (Qwen3.6, Qwen3-Coder, Qwen3.8-Flash-Next)」 |
| 27B-ROCmFP4 能否加载 | ❌ 否（私有 type 101） | 用户记忆「27B = fork 私有 ggml type 101」 |
| 统一内存语义 | ⚠️ 需注意：无独立 VRAM，「专家溢出到 RAM 池」在 UMA 下与 llama.cpp 整权重加载趋同，磁盘流式优势归零 | 架构推论 |
| 构建可行性 | ✅ Linux Vulkan 路径相对成熟（start-here.sh 自动检测构建） | WebSearch #2、#4（Windows CUDA 问题多，Linux 较少） |
| 端口冲突 | ✅ 8000 不冲突（llama.cpp 8080 / docproxy 18090） | 端口分配核对 |

---

## 五、风险与红旗

1. **Star 增长异常**：4 个月 4.8 万、v2.1.0 后爆拉，存在 star 操纵疑云（archestack 曲线）。情报价值需打折，但技术范式本身成立。
2. **成熟度不足**：154 open issues 且含构建问题，远低于 llama.cpp。作为「对照引擎」可接受，作为「主力替换」风险高。
3. **iGPU 实测缺失**：作者未测离散 GPU，仅 1 例用户报告；Strix Halo iGPU 路径无公开 t/s 数据 → **不能假设比 llama.cpp 快，必须实测**。
4. **大模型极慢**：GLM-5.2 744B cold 仅 0.05–0.1 tok/s（25GB 笔记本），印证其卖点是「跑得下」而非「跑得快」——与本机需求（快）错位。
5. **私有格式不兼容**：无法直接吃我们调优过的 27B-ROCmFP4。

---

## 六、落地 A/B 测速方案（命令级）

> 目标：用 35B-A3B Q4 在 colibri-Vulkan 与 llama.cpp（57.4 t/s 基准）对比 prefill + decode t/s。
> 前提：`$HOME/models/Qwen3.6-35B-A3B-Uncensored-Q4_K_P.gguf` 已存在（标准 GGUF）。

**1. 系统依赖（无头 Linux）**
```bash
sudo apt install -y git build-essential libvulkan-dev vulkan-tools
vulkaninfo | grep -i "STRIX_HALO"   # 确认 RADV Vulkan 设备枚举正常
```

**2. 获取与构建（优先 git clone，禁用 tarball——参考本机 sd.cpp 教训）**
```bash
git clone https://github.com/JustVugg/colibri
cd colibri
make            # 或查看 Makefile 中 Vulkan target；start-here.sh 为交互式，无头环境用手动 make
```

**3. 导入标准 GGUF（v2.1.0 原生，免转换）**
```bash
./coli import $HOME/models/Qwen3.6-35B-A3B-Uncensored-Q4_K_P.gguf
```

**4. 启动 Vulkan 后端，避开端口冲突（8001）**
```bash
./coli run Qwen3.6-35B-A3B-Uncensored-Q4_K_P --backend vulkan --port 8001
```

**5. 等价负载测速对比（400 token 生成，3 次取中值）**
```bash
# colibri（8001）
curl -s http://127.0.0.1:8001/v1/chat/completions -H 'Content-Type: application/json' \
  -d '{"model":"Qwen3.6-35B-A3B-Uncensored-Q4_K_P","messages":[{"role":"user","content":"用一句话解释 MoE"}],"max_tokens":400}' &

# llama.cpp 基准（8080，已开 MTP）
curl -s http://127.0.0.1:8080/v1/chat/completions -H 'Content-Type: application/json' \
  -d '{"model":"Qwen3.6-35B-A3B-Uncensored-Q4_K_P","messages":[{"role":"user","content":"用一句话解释 MoE"}],"max_tokens":400}'
```

**判定阈值**：colibri-Vulkan decode t/s ≥ llama.cpp 的 57.4（±10%）且 prefill 不显著落后 → 才考虑把「临时测新模型 / 轻量本地推理」场景切到 colibri（单文件零依赖优势）；**主力 27B + 35B 服务仍留在 llama.cpp**（私有格式 + 调优深度 + MCSManager 托管铁律）。若 colibri < 40 t/s，则仅作「架构借鉴」，不部署。

---

## 七、结论与判定

1. **范式确认成立**：专家级分层存储（learned placement + 磁盘流式）是对 llama.cpp 整权重路线的有效对照，且 v2.1.0 原生 GGUF 导入降低了试用门槛（M-148 记录准确）。
2. **本机价值错位**：96 GiB 统一内存使 colibri 的「跑装不下的超大模型」卖点归零；其潜在价值只剩「单文件零依赖 + MoE 专家调度提速」，**且需实测验证提速是否成立**。
3. **硬约束**：27B-ROCmFP4（私有 type 101）colibri 不可读 → 对照仅限 35B-A3B。
4. **风险可控但需警惕**：star 异常增长 + 154 issues + iGPU 实测缺失 → 定位为「对照 / 候选」，**不构成 llama.cpp 替换理由**。
5. **可执行判定**：下周跑第六节 A/B，以 57.4 t/s 为基准线。未实测前，colibri 维持「本地推理直接候选（M-148）」状态，不进生产。

---
*数据来源：本地 `项目雷达/LEARNINGS.md` M-148（2026-11-03）；WebSearch 2026-11-08 实时核实（one-man-company / mygit / CSDN / hu6 / archestack 共 5 源）。所有数值可回溯至上述文件与 URL。*

---

> 许可：CC0-1.0，公共领域贡献，无任何限制。
