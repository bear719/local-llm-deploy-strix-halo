#!/usr/bin/env bash
# 本机两个 llama-server 模型档位的一键切换器（分时复用同一张卡 / 同一端口 8080）
#
# 用法:
#   ./switch-model.sh 36 [long|fast|multi]   # 切到 Qwen3.6-35B-A3B（MoE，约 57 t/s）
#   ./switch-model.sh 38 [long|multi]        # 切到 Qwen3.8-Flash-Next-imatrix-v2（27B dense + n-gram）
#   ./switch-model.sh status                 # 看当前跑的是哪个 + 显存 + MTP 是否真的启用
#
# 为什么必须切换而不能并存（2026-10-02 实测）:
#   VRAM 上限 96.00 GiB。38 档加载后占 81.67 GB，只剩 19.3 GB；
#   36 档权重 23.42 + 草稿 1.62 + mmproj 0.90 = 25.04 GB > 19.3 GB → 装不下，
#   硬开会被 Vulkan 以 ErrorDeviceLost 踢掉（不是 OOM，容易误判）。
#
# 切换代价：停服 → 启动 → 加载。36 档约 20~30 秒，38 档约 55 秒。

set -euo pipefail

PORT=${PORT:-8080}
BASE_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PID36=/tmp/qwen36-35b-a3b-server-$(id -u).pid
PID38=/tmp/qwen38-imatrix-v2-server-$(id -u).pid
WAIT_MAX=${WAIT_MAX:-180}

health_ok() { curl -sf --max-time 3 "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; }
port_busy() { ss -ltn 2>/dev/null | grep -q ":$PORT "; }

current_model() {
    curl -sf --max-time 3 "http://127.0.0.1:$PORT/props" 2>/dev/null \
        | sed -n 's/.*"model_path":"\([^"]*\)".*/\1/p' || true
}

do_status() {
    local pids; pids=$(pgrep -x llama-server 2>/dev/null || true)
    if [[ -z $pids ]]; then
        echo "llama-server 未运行（端口 $PORT 空闲）"
    else
        echo "运行中 PID: $pids"
        echo "当前模型: $(current_model)"
        # 判断 MTP 是否真启用：/props 顶层 speculative.types 恒为 none 不可信，
        # 必须看 /slots[0].params.speculative.types
        curl -sf --max-time 3 "http://127.0.0.1:$PORT/slots" 2>/dev/null \
            | grep -o '"speculative.types":"[^"]*"' | head -1 || echo "  (slots 端点不可用)"
    fi
    command -v rocm-smi >/dev/null && rocm-smi --showmeminfo vram 2>/dev/null | grep "Used"
    exit 0
}

# 停掉当前在跑的 llama-server（不管是谁起的）
stop_current() {
    local pids; pids=$(pgrep -x llama-server 2>/dev/null || true)
    [[ -z $pids ]] && { echo "[INFO] 无运行中的 llama-server"; return 0; }

    echo "[INFO] 停止现有服务 PID: $pids"
    kill $pids 2>/dev/null || true
    for ((i = 0; i < 30; i++)); do
        sleep 1
        pgrep -x llama-server >/dev/null 2>&1 || break
    done

    if pgrep -x llama-server >/dev/null 2>&1; then
        echo "[ERROR] 30 秒内未退出 -> 多半是 MCSManager 面板（root）起的进程，本用户无权 kill"
        echo "        方式①（推荐）: 在面板里停止对应实例，再跑本脚本"
        echo "        方式②        : sudo kill $(pgrep -x llama-server | tr '\n' ' ')"
        exit 1
    fi
    for ((i = 0; i < 15; i++)); do
        port_busy || break
        sleep 1
    done
    rm -f "$PID36" "$PID38"
    echo "[OK] 已停止，端口 $PORT 已释放"
}

wait_ready() {
    local waited=0
    while (( waited < WAIT_MAX )); do
        if health_ok; then
            echo "[OK] 服务就绪（等待 ${waited}s），模型: $(current_model)"
            return 0
        fi
        sleep 2; waited=$((waited + 2))
    done
    echo "[ERROR] ${WAIT_MAX}s 内未就绪 -> 查看日志: /tmp/qwen*-server-$(id -u).log"
    exit 1
}

TARGET=${1:-}
MODE=${2:-}

case "$TARGET" in
    status) do_status ;;
    36|35b|qwen36)
        stop_current
        echo "[INFO] 启动 Qwen3.6-35B-A3B（模式=${MODE:-long}）"
        "$BASE_DIR/start-qwen36-35b-a3b.sh" "${MODE:-long}" >/dev/null
        # 上面的脚本在 MODE 非空时不会走 auto 前台分支，但 auto 分支遇非 tty 会 exec 前台，
        # 因此这里显式指定模式确保它走 bg。
        wait_ready
        ;;
    38|27b|qwen38)
        stop_current
        echo "[INFO] 启动 Qwen3.8-Flash-Next-imatrix-v2（模式=${MODE:-long}）"
        "$BASE_DIR/start-qwen38-imatrix-v2.sh" "${MODE:-long}" >/dev/null
        wait_ready
        ;;
    *)
        echo "[ERROR] 未知目标 '$TARGET' -> 可用: 36 | 38 | status"
        exit 1
        ;;
esac
