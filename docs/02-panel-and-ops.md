# 面板与运维（MCSManager）

本机用 MCSManager（web 23333 / daemon 24444）托管 llama-server 与 docproxy 实例。以下经验偏运维，
与具体模型无关，单独成篇。

## 为什么面板化

- 两档模型**分时复用同一张卡**（96 GiB 装不下两个），用 `scripts/switch-model.sh` 切换；
  面板便于启停与看日志

## 关键坑

- **前台化**：面板把「前台主进程退出」判为实例停止。脚本若 `nohup &` 后台化，面板立刻显示
  「已停止」，随后重启因端口占用失败 → 脚本在**非 tty 时自动改前台 `exec`**，日志直出面板控制台；
  桌面终端里仍是后台 + 日志留存
- **ICD 自建**：root 经面板启动拿不到 PAM 注入的环境，脚本自行兜 `VK_ICD_FILENAMES`
- **uid 后缀**：日志与 pid 文件带 uid 后缀（`/tmp/qwen*-server-<uid>.log`），避免 root/lc 互相写不动
- **面板实例日志不落盘**：面板 PTY 的 fd/1、fd/2 指向 socket。查真实日志读
  `/opt/mcsmanager/daemon/data/InstanceLog/<uuid>.log`（需 sudo）；
  先 `sudo grep -l <关键字> /opt/mcsmanager/daemon/data/InstanceConfig/*.json` 反查 uuid
- **面板孤儿进程（root 起）本用户无权 kill**：用 `sudo kill <pid>`。本机已可用 sudo 凭据自主重启；
  注意 `-k` 忽略缓存票，且同一命令里不要出现 heredoc（会占 stdin 让 sudo 读不到密码）。
  面板 `autoRestart` 会自动重拉，kill 后无需手动重启
- **多实例**：docproxy 单独一个面板实例（:18090），上游指向 :8080；它不转发 `/metrics`，
  压测基线请走 :8080

## 两档切换

- VRAM 上限 96 GiB：38 档加载后占 ~82 GiB，剩 ~19 GiB；36 档权重 23.4+草稿 1.6+mmproj 0.9 ≈ 25 GiB
  > 19 GiB → 装不下，硬开会以 `ErrorDeviceLost` 踢掉（不是 OOM，易误判）
- 切换代价：停服 → 启动 → 加载。36 档 ~20–30s，38 档 ~55s
- 详见 `scripts/switch-model.sh`
