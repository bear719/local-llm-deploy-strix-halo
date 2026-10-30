# MCSManager 35B 实例旧启动参数存档

- 实例文件：`/opt/mcsmanager/daemon/data/InstanceConfig/9770784bb1f940ada5c5890fd003efb3.json`
- 原昵称：`llamacpp Qwen3.6-35B-A3B-Uncensored-Q4_K_P`
- 备份文件：`9770784bb1f940ada5c5890fd003efb3.json.bak.20261002`（同目录，改写前生成）
- 存档时间：2026-10-02
- 存档原因：该命令行指向的二进制 `$HOME/rocmfp4-llama/build-strix-rocmfp4/bin/llama-server` 已不是当前主力构建
  （现役为 `$HOME/llama-qwen4exp-rocmfpx/build-vk4`，build 10821 / commit 925c32a20），
  且含多个 fork 私有参数，直接照搬到 build-vk4 有启动失败风险，故整体换成脚本化启动。

## 旧命令行（原文，勿丢）

```
$HOME/rocmfp4-llama/build-strix-rocmfp4/bin/llama-server -m $HOME/models/Qwen3.6-35B-A3B-Uncensored-Q4_K_P.gguf -md $HOME/models/Qwen3.6-35B-A3B-MTP-ONLY-Q4_K_M.gguf --mmproj $HOME/models/mmproj-Qwen3.6-35B-A3B-Uncensored-f16.gguf --host 0.0.0.0 --port 8080 -c 262144 -cram 65536 -ngl 999 --device Vulkan0 --n-cpu-moe 0 --cache-type-k q8_0 --cache-type-v q8_0 --mlock --temp 0.6 --top-p 0.9 --top-k 40 --min-p 0.3 --presence-penalty 0.0 --repeat-last-n 512 --repeat-penalty 1.0 -fa on -np 1 --jinja -t 16 --reasoning-format auto --reasoning-budget 2048 -b 8192 -ub 512 --cache-reuse 256 --kv-unified --cache-ram 8192 -lv 4 -fit off --no-mmap --spec-type draft-mtp --spec-draft-ngl 999 --spec-draft-n-max 3 --spec-draft-p-min 0.3 -cpent 8192 -ctxcp 8 --log-verbosity 3
```

## 逐项备注（哪些值值得日后回捞）

| 参数 | 旧值 | 处理 |
|---|---|---|
| `--spec-draft-n-max` | 3 | 新脚本用 2。来源：2026-09-27 三轮网格实测，n-max=2 最优（34.75），3 掉到 33.08 |
| `--spec-draft-p-min` | 0.3 | 新脚本不设（实测在噪声内：0→32.80 / 0.3→33.71 / 0.6→32.16） |
| `-b / -ub` | 8192 / 512 | 新脚本 long 档 4096 / 1024；旧值可回测 |
| `--cache-type-k/v` | q8_0 / q8_0 | 新脚本已保留（等价 `-ctk/-ctv q8_0`） |
| `--mlock` / `--no-mmap` | 开 / 开 | 新脚本未设。`--no-mmap` 会显著延长加载时间，imatrix-v2 档用 `--ngram-on-disk` 替代思路 |
| `-t 16` | 16 线程 | 新脚本未设，走默认（16 核 32 线程） |
| 采样 `--temp 0.6 --top-p 0.9 --top-k 40 --min-p 0.3` | — | 新脚本不锁采样，交给客户端传参 |
| `--reasoning-budget 2048` | 2048 | 新脚本 fast 档用 `--reasoning off`；long 档保留原生 |
| `-cram 65536 --cache-ram 8192 --kv-unified --cache-idle-slots --cache-reuse 256 -fit off -cpent 8192 -ctxcp 8 --spec-draft-ngl 999` | fork 私有/版本相关 | **未迁移**，build-vk4 是否支持未验证，需要时逐项试 |

## 回滚

```bash
sudo cp /opt/mcsmanager/daemon/data/InstanceConfig/9770784bb1f940ada5c5890fd003efb3.json.bak.20261002 \
        /opt/mcsmanager/daemon/data/InstanceConfig/9770784bb1f940ada5c5890fd003efb3.json
sudo systemctl restart mcsm-daemon
```
