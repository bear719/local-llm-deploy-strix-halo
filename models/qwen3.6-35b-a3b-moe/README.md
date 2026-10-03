# Qwen3.6-35B-A3B-Uncensored (MoE 档)

本机**速度档**：MoE 架构，每 token 只激活 ~3B，decode 约 57–92 t/s。

## 模型侧关键点（勿删）

1. **标准 Q4_K_P**（gguf file_type 15），**不含 fork 私有 ggml type** → 上游 / 任意 build 都能加载；
   本机统一用 build-vk4（Vulkan，比 HIP 快约 51%）
2. 主模型 arch=qwen35moe，40 层，embedding 2048，expert 256 取 8；
   草稿模型 41 层、`nextn_predict_layers=1`、embedding 同为 2048 → 维度匹配，MTP 可用
   （来源：`tools/gguf_probe.py` 实测元数据）
3. **不要加 `--ngram-on-disk` / `--spec-type ...ngram-map-k`**：本模型无 PLE n-gram 表，
   那套参数是 imatrix-v2（dense 27B）专用的
4. `-np > 1` 时 draft-mtp 存在 cross-slot 串扰风险（上游 PR #28123 作者声明），
   故 long/fast 档强制 `-np 1`；multi 档如需严格正确请改回 `-np 1`
5. **mmproj 必须匹配主模型**：35B-A3B 用 `mmproj-Qwen3.6-35B-A3B-Uncensored-f16.gguf`
   （27B 用 `mmproj-F32.gguf`，用错启动失败 `mismatch between text model and mmproj`）

## 用法

```
./start.sh            # 自动：有终端→后台，无终端(面板/守护)→前台
./start.sh long       # 262K 单槽（默认档，速度优先）
./start.sh fast       # 262K 单槽 + 关闭思考链（日常待办/抽取类任务）
./start.sh multi      # 64K × 3 槽，并发优先（有串扰风险，见上）
./start.sh fg|bg|stop|status|check
```

- long 档：`-c 131072 -np 2 -b 4096 -ub 1024`（本 build 上限 131072，`-c 262144` 被 clamp）
- fast 档：叠加 `--reasoning off`，直出答案不吐思考链

## 实测（2026-10-02 ~ 10-03）

| 指标 | 值 |
|---|---|
| decode | **83–92 t/s**（中位 90.14） |
| 长 prefill | **~520 t/s**（89K tok / ~171s） |
| 显存 | **~31 GiB**（对比 38 档 ~86 GiB，一半不到） |
| MTP（n-max=2）接受率 | 77–80%，每步平均接受 1.55–1.99 token |
| 对比 38 档（dense 27B） | 快约 2.2 倍 |

## 调优固化

```
--spec-draft-n-max 2 -ctk q8_0 -ctv q8_0 --cache-idle-slots -cms 512
```

- `--cache-reuse` 在 mmproj 下被自动禁用（已移除）；多轮加速靠 `--cache-idle-slots` + LCP 前缀复用
- `-ctk/-ctv q8_0` 省显存、速度不降

详见同目录 `benchmarks.md`（压测 + 速度复测）、`legacy-params.md`（旧面板参数存档与回滚参考）。
