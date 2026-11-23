#!/usr/bin/env bash
# 许可：CC0-1.0，公共领域贡献，无任何限制。
# ============================================================
# frps-audit.sh —— 在 frps 服务器（<公网服务器IP>）上运行
# 目的：记录「谁在连被穿透的模型端口」的真实公网 IP
#
# 为什么必须在 frps 上做：
#   frp 是 TCP 转发。流量到达被穿透那台机器时，源地址已经被换成 127.0.0.1
#   （因为连接由本机 frpc 发起）。所以本机侧的 ss / iptables / 应用日志
#   永远拿不到真实客户端 IP，只有 frps 这一跳能看到。
#
# 用法：
#   sudo bash frps-audit.sh            # 安装规则 + 独立日志 + 轮转
#   sudo bash frps-audit.sh status     # 看已记录多少、Top IP
#   sudo bash frps-audit.sh off        # 卸载（同目录 frps-audit-revert.sh 亦可）
#
# 回滚：sudo bash frps-audit-revert.sh
# ============================================================
set -euo pipefail

PORTS_CSV="${PORTS_CSV:-8080,18090,8219}"
CHAIN=MODEL_LOG
LOGPREFIX=MODELACCESS
LOGFILE=/var/log/model-access.log

need_root() { [[ $(id -u) -eq 0 ]] || { echo "[ERROR] 需 root -> sudo bash $0"; exit 1; }; }

show_status() {
    echo "=== 规则 ==="
    iptables -S "$CHAIN" 2>/dev/null || echo "  （未安装）"
    echo "=== 日志文件 ==="
    if [[ -f $LOGFILE ]]; then
        echo "  大小: $(du -h "$LOGFILE" | cut -f1)  行数: $(wc -l < "$LOGFILE")"
        echo "=== 来源 IP Top 15 ==="
        grep -oP 'SRC=\K[0-9.]+' "$LOGFILE" | sort | uniq -c | sort -rn | head -15
        echo "=== 最近 10 条 ==="
        tail -10 "$LOGFILE"
    else
        echo "  （无日志文件）"
    fi
}

uninstall_rules() {
    while iptables -C INPUT -j "$CHAIN" 2>/dev/null; do
        iptables -D INPUT -j "$CHAIN"
    done
    iptables -F "$CHAIN" 2>/dev/null || true
    iptables -X "$CHAIN" 2>/dev/null || true
    rm -f /etc/rsyslog.d/49-model-access.conf
    systemctl restart rsyslog 2>/dev/null || service rsyslog restart 2>/dev/null || true
    echo "[OK] 规则与 rsyslog 配置已移除（日志文件保留：$LOGFILE）"
}

case "${1:-install}" in
    status) need_root; show_status; exit 0 ;;
    off)    need_root; uninstall_rules; exit 0 ;;
esac

need_root

echo "[1/4] 清理旧规则"
uninstall_rules >/dev/null 2>&1 || true

echo "[2/4] 建链并挂到 INPUT（只记 NEW 连接，限速 120/min 防刷爆磁盘）"
iptables -N "$CHAIN"
iptables -A "$CHAIN" -p tcp -m multiport --dports "$PORTS_CSV" \
    -m conntrack --ctstate NEW \
    -m limit --limit 120/min --limit-burst 40 \
    -j LOG --log-prefix "${LOGPREFIX} " --log-level 4
iptables -I INPUT 1 -j "$CHAIN"

echo "[3/4] rsyslog 分流到独立文件（不污染 syslog）"
cat > /etc/rsyslog.d/49-model-access.conf <<'EOF'
# 模型端口访问审计（frps-audit.sh 生成）
:msg, contains, "MODELACCESS " -/var/log/model-access.log
& stop
EOF
systemctl restart rsyslog 2>/dev/null || service rsyslog restart 2>/dev/null || true

echo "[4/4] logrotate（保留 14 天，按天轮转）"
cat > /etc/logrotate.d/model-access <<EOF
$LOGFILE {
    daily
    rotate 14
    missingok
    notifempty
    compress
    delaycompress
    postrotate
        systemctl kill -s HUP rsyslog 2>/dev/null || true
    endscript
}
EOF

echo
echo "[OK] 审计已启用。监控端口: $PORTS_CSV"
echo "     日志: $LOGFILE"
echo "     查看: sudo bash $0 status"
echo "     卸载: sudo bash $0 off"
echo
echo "字段说明：SRC=x.x.x.x DST=... DPT=8080 中 SRC 即真实客户端 IP。"
echo "注意：若 frps 前面还有云厂商 SLB/NAT，SRC 会是 SLB 内网地址 —— 此时需在 SLB 侧开访问日志。"
