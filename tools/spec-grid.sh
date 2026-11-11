#!/usr/bin/env bash
# --spec-draft-n-max / --spec-draft-p-min 网格实验
#
# 原理：改 start-qwen38-imatrix-v2.sh 的 TUNING 行 -> 杀掉面板实例 -> 立刻自己起服务占住 8080
#       -> 等 /health 就绪 -> 跑 bench-server.py 5 次，结果追加到 RESULT
# 注意：面板(MCSManager)会在实例进程退出后自动重启并抢端口，所以 kill 后必须在数秒内
#       把端口占住，否则自己的实例必定 couldn't bind（2026-09-27 踩过）。
set -uo pipefail

START=$HOME/WorkBuddy/调试本地模型/start-qwen38-imatrix-v2.sh
BENCH=$HOME/WorkBuddy/调试本地模型/tools/bench-server.py
PY=$HOME/.workbuddy/binaries/python/versions/3.13.12/bin/python3
RESULT=/tmp/specgrid3-results.txt
BASE="--spec-type draft-mtp -ctk q8_0 -ctv q8_0 --spec-draft-n-max 1"

# 名称|描述|TUNING 内容
CASES=(
  "M|纯MTP n-max=1|--spec-type draft-mtp -ctk q8_0 -ctv q8_0 --spec-draft-n-max 1"
  "N|纯MTP n-max=2|--spec-type draft-mtp -ctk q8_0 -ctv q8_0 --spec-draft-n-max 2"
  "O|纯MTP n-max=3|--spec-type draft-mtp -ctk q8_0 -ctv q8_0 --spec-draft-n-max 3"
)

kill_all() {
    printf '%s\n' "${SUDO_PASS:-}" | sudo -S -k pkill -x llama-server 2>/dev/null || true
    for i in $(seq 1 30); do
        pgrep -x llama-server >/dev/null 2>&1 || return 0
        sleep 1
    done
    printf '%s\n' "${SUDO_PASS:-}" | sudo -S -k pkill -9 -x llama-server 2>/dev/null || true
    sleep 3
}

wait_ready() {
    for i in $(seq 1 200); do
        if curl -s -m 2 http://127.0.0.1:8080/health 2>/dev/null | grep -q '"ok"'; then
            return 0
        fi
        sleep 2
    done
    return 1
}

echo "=== spec-decoding 网格实验 $(date '+%F %T') ===" | tee -a "$RESULT"

for case in "${CASES[@]}"; do
    IFS='|' read -r name desc tuning <<< "$case"
    echo "" | tee -a "$RESULT"
    echo "----- 组 $name: $desc -----" | tee -a "$RESULT"

    # 1) 改脚本里的 TUNING 行
    sed -i "s|^TUNING=(.*|TUNING=($tuning)|" "$START"
    grep -n "^TUNING=" "$START"

    # 2) 杀掉现有实例（面板会自动重启，所以要抢端口）
    kill_all
    sleep 2

    # 3) 自己起服务（bg 模式，占住 8080）
    "$START" bg >/tmp/grid-launch.log 2>&1
    sleep 3
    if ! pgrep -x llama-server >/dev/null 2>&1; then
        # 端口可能被面板抢了，等等看是否别人的实例起来了
        sleep 20
        if ! pgrep -x llama-server >/dev/null 2>&1; then
            echo "[ERROR] 组 $name 未能启动，跳过" | tee -a "$RESULT"
            tail -3 /tmp/grid-launch.log | tee -a "$RESULT"
            continue
        fi
    fi

    # 4) 等加载完成（93 GB 模型约 55~70 秒）
    if wait_ready; then
        echo "[OK] 服务就绪 $(date '+%T')" | tee -a "$RESULT"
    else
        echo "[ERROR] 组 $name 等待就绪超时" | tee -a "$RESULT"
        continue
    fi

    # 5) 预热 1 次（排除首次编译 shader / 冷 cache 的干扰）
    curl -s -m 120 http://127.0.0.1:8080/v1/chat/completions \
        -H "Content-Type: application/json" \
        -d '{"messages":[{"role":"user","content":"你好"}],"max_tokens":32}' >/dev/null 2>&1

    # 6) 正式测速
    $PY "$BENCH" 12 2>&1 | tee -a "$RESULT"
    echo "VRAM: $(rocm-smi --showmeminfo vram 2>/dev/null | grep 'Total Used' | awk '{print $NF}') B" | tee -a "$RESULT"
done

# 收尾：恢复基线参数并交还面板
echo "" | tee -a "$RESULT"
echo "----- 恢复基线 -----" | tee -a "$RESULT"
sed -i "s|^TUNING=(.*|TUNING=($BASE)|" "$START"
kill_all
sleep 10
echo "实验结束 $(date '+%F %T')，面板应在数秒内自动重启实例" | tee -a "$RESULT"
