#!/usr/bin/env bash
# 许可：CC0-1.0，公共领域贡献，无任何限制。
# frps-audit-revert.sh —— 在 frps 服务器（<公网服务器IP>）上运行
# 一键回滚 frps-audit.sh 的全部改动：删自定义链、删 INPUT 跳转、删 rsyslog 分流、删 logrotate
# 日志文件 /var/log/model-access.log 保留（如需删：sudo rm -f 该文件）
set -euo pipefail
[[ $(id -u) -eq 0 ]] || { echo "[ERROR] 需 root -> sudo bash $0"; exit 1; }

CHAIN=MODEL_LOG

while iptables -C INPUT -j "$CHAIN" 2>/dev/null; do
    iptables -D INPUT -j "$CHAIN"
done
iptables -F "$CHAIN" 2>/dev/null || true
iptables -X "$CHAIN" 2>/dev/null || true

rm -f /etc/rsyslog.d/49-model-access.conf /etc/logrotate.d/model-access
systemctl restart rsyslog 2>/dev/null || service rsyslog restart 2>/dev/null || true

echo "[OK] 已回滚。残留检查："
iptables -S "$CHAIN" 2>/dev/null && echo "  ⚠ 链仍存在" || echo "  ✓ 自定义链已删"
ls /etc/rsyslog.d/49-model-access.conf 2>/dev/null && echo "  ⚠ rsyslog 配置仍在" || echo "  ✓ rsyslog 配置已删"
echo "日志文件保留在 /var/log/model-access.log（含历史客户端 IP，可留作证据）"
