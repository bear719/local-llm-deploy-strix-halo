#!/usr/bin/env bash
# llama-server 内存监控 + 阈值触发重启
#
# 用法:
#   ./monitor-and-restart.sh              # 单次检查（cron 用这个）
#   ./monitor-and-restart.sh --daemon     # 守护模式（每 5 分钟轮询）
#
# 阈值（可环境变量覆盖）:
#   MEM_THRESHOLD=85    系统内存使用率超过此值触发
#   SWAP_THRESHOLD=10   Swap 已用超过此 GB 触发
#   RESTART_SCRIPT=     重启脚本路径
#   SUDO_PASS=          sudo 密码

set -uo pipefail

MEM_THRESHOLD=${MEM_THRESHOLD:-85}
SWAP_THRESHOLD=${SWAP_THRESHOLD:-10}
RESTART_SCRIPT=${RESTART_SCRIPT:-$HOME/WorkBuddy/调试本地模型/start-qwen36-35b-a3b.sh}
LOG=/tmp/llama-monitor.log
SUDO_PASS=${SUDO_PASS:-密码}

log() {
    local msg
    msg="$(date '+%Y-%m-%d %H:%M:%S') $*"
    echo "$msg" | tee -a "$LOG"
}

check_and_restart() {
    local mem_total mem_avail mem_used mem_pct
    local swap_total swap_free swap_used_kb swap_used_gb

    mem_total=$(grep MemTotal /proc/meminfo | awk '{print $2}')
    mem_avail=$(grep MemAvailable /proc/meminfo | awk '{print $2}')
    swap_total=$(grep SwapTotal /proc/meminfo | awk '{print $2}')
    swap_free=$(grep SwapFree /proc/meminfo | awk '{print $2}')

    mem_used=$((mem_total - mem_avail))
    mem_pct=$((mem_used * 100 / mem_total))
    swap_used_kb=$((swap_total - swap_free))
    swap_used_gb=$((swap_used_kb / 1024 / 1024))

    log "内存: ${mem_pct}% | Swap: ${swap_used_gb}GB (阈值: ${SWAP_THRESHOLD}GB)"

    local triggered=0

    if (( mem_pct >= MEM_THRESHOLD )); then
        log "[TRIGGER] 内存使用率 ${mem_pct}% >= ${MEM_THRESHOLD}%，触发重启"
        triggered=1
    fi

    if (( swap_used_gb >= SWAP_THRESHOLD )); then
        log "[TRIGGER] Swap 已用 ${swap_used_gb}GB >= ${SWAP_THRESHOLD}GB，触发重启"
        triggered=1
    fi

    if (( triggered )); then
        local pids
        pids=$(pgrep -x llama-server 2>/dev/null || true)
        if [[ -n "$pids" ]]; then
            for pid in $pids; do
                log "停止 PID $pid"
                echo "$SUDO_PASS" | sudo -S -k kill -9 "$pid" 2>/dev/null
            done
            sleep 3
        fi

        echo 1 | sudo -S -k sysctl -w vm.drop_caches=1 2>/dev/null

        log "启动新实例..."
        bash "$RESTART_SCRIPT" >/dev/null 2>&1
        log "启动完成"
    else
        log "正常，无需重启"
    fi
}

case "${1:-}" in
    --daemon)
        log "守护模式启动，每 5 分钟检查一次"
        while true; do
            check_and_restart
            sleep 300
        done
        ;;
    *)
        check_and_restart
        ;;
esac
