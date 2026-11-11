#!/usr/bin/env bash
# 量化档位速度对比 v3 —— 真正独占（用面板 API stop，而非 kill）
#
# v1/v2 失败原因：直接 kill 进程会触发面板 autoRestart 立刻重拉，
#                导致测试期间 2 个实例并存（显存 53~58 GB），数据受干扰。
# v3 方案：用面板 API `stop` 停止实例 —— 实测不会触发 autoRestart
#          （稳定性观察 60 s，实例数保持 0）。
#
# 用法：nohup bash compare-quant-speed-v3.sh &

set -uo pipefail

BIN=$HOME/llama-qwen4exp-rocmfpx/build-vk4/bin/llama-server
DRAFT=$HOME/models/Qwen3.6-35B-A3B-MTP-ONLY-Q4_K_M.gguf
MMPROJ=$HOME/models/mmproj-Qwen3.6-35B-A3B-Uncensored-f16.gguf
PORT=8090
UUID=9770784bb1f940ada5c5890fd003efb3
RESULTS=/tmp/quant-compare-v3.txt
BENCH=$HOME/WorkBuddy/调试本地模型/tools/bench-server.py
PY=$HOME/.workbuddy/binaries/python/versions/3.13.12/bin/python3
TOOLS=$HOME/WorkBuddy/调试本地模型/tools
SUDO_PASS=$(cat "$HOME/.workbuddy/.docker-sudo")
PANEL_USER=amd
PANEL_PASS="${MCSM_PASS:?请设置 MCSM_PASS 环境变量}"

export VK_ICD_FILENAMES=/usr/share/vulkan/icd.d/radeon_icd.json
export VK_DRIVER_FILES=/usr/share/vulkan/icd.d/radeon_icd.json

: > "$RESULTS"

mcsm() { "$PY" "$TOOLS/mcsm-api.py" --user "$PANEL_USER" --password "$PANEL_PASS" "$@"; }

kill_all() {
    printf '%s\n' "$SUDO_PASS" | sudo -S -k pkill -x llama-server 2>/dev/null
    for i in $(seq 1 20); do
        pgrep -x llama-server >/dev/null 2>&1 || return 0
        sleep 1
    done
    printf '%s\n' "$SUDO_PASS" | sudo -S -k pkill -9 -x llama-server 2>/dev/null
    sleep 3
}

wait_ready() {
    for i in $(seq 1 90); do
        if curl -s -m 3 "http://127.0.0.1:$PORT/health" 2>/dev/null | grep -q ok; then
            return 0
        fi
        sleep 3
    done
    return 1
}

run_model() {
    local label="$1" model="$2"

    echo "" | tee -a "$RESULTS"
    echo "########## [$label] $(basename "$model") ##########" | tee -a "$RESULTS"
    [[ -f $model ]] || { echo "  [SKIP] 不存在" | tee -a "$RESULTS"; return 1; }

    local gb; gb=$(ls -l "$model" | awk '{printf "%.2f", $5/1024/1024/1024}')
    echo "  文件大小: ${gb} GiB" | tee -a "$RESULTS"

    kill_all
    rm -f /tmp/quant-v3-$PORT.log
    setsid nohup "$BIN" \
        -m "$model" -md "$DRAFT" \
        --spec-type draft-mtp \
        -ngl 999 -c 131072 -np 1 -b 4096 -ub 1024 \
        --mmproj "$MMPROJ" \
        --spec-draft-n-max 2 -ctk q8_0 -ctv q8_0 \
        --cache-idle-slots -cms 512 \
        --reasoning off \
        --metrics --host 0.0.0.0 --port "$PORT" \
        > /tmp/quant-v3-$PORT.log 2>&1 &

    if ! wait_ready; then
        echo "  [ERROR] 启动超时" | tee -a "$RESULTS"
        tail -8 /tmp/quant-v3-$PORT.log | tee -a "$RESULTS"
        return 1
    fi

    # 独占校验：连续 3 次采样实例数必须都是 1
    local n1 n2 n3 vram
    n1=$(pgrep -x llama-server | wc -l); sleep 4
    n2=$(pgrep -x llama-server | wc -l); sleep 4
    n3=$(pgrep -x llama-server | wc -l)
    vram=$(cat /sys/class/drm/card*/device/mem_info_vram_used 2>/dev/null | awk '{printf "%.2f", $1/1024/1024/1024}')
    echo "  独占校验: 实例数 ${n1}/${n2}/${n3}   显存 ${vram} GB" | tee -a "$RESULTS"
    if [[ "$n1$n2$n3" != "111" ]]; then
        echo "  [FATAL] 未能独占，本组作废" | tee -a "$RESULTS"
        kill_all
        return 1
    fi

    for w in 1 2; do
        curl -s -m 200 -X POST "http://127.0.0.1:$PORT/v1/chat/completions" \
            -H 'Content-Type: application/json' \
            -d '{"messages":[{"role":"user","content":"预热"}],"max_tokens":64,"stream":false}' \
            >/dev/null 2>&1
    done

    "$PY" "$BENCH" 7 "$PORT" 2>&1 | tee -a "$RESULTS"
    curl -s -m 5 "http://127.0.0.1:$PORT/metrics" 2>/dev/null \
        | grep -E 'spec_decode_num_(draft|accepted|drafts)_total' | grep -v '^#' | tee -a "$RESULTS"
    kill_all
}

# ===== 主流程 =====
echo "=== 停止面板实例（API stop，不触发 autoRestart）===" | tee -a "$RESULTS"
mcsm stop --uuid "$UUID" 2>&1 | tail -1 | tee -a "$RESULTS"
kill_all

run_model "Q4_K_P (当前)" $HOME/models/Qwen3.6-35B-A3B-Uncensored-Q4_K_P.gguf
run_model "Q5_K_P (新)"   $HOME/models/Qwen3.6-35B-A3B-Uncensored-Q5_K_P.gguf

echo "" | tee -a "$RESULTS"
echo "=== 恢复面板实例 ===" | tee -a "$RESULTS"
kill_all
mcsm start --uuid "$UUID" 2>&1 | tail -1 | tee -a "$RESULTS"
for i in $(seq 1 40); do
    if curl -s -m 3 http://127.0.0.1:8080/health 2>/dev/null | grep -q ok; then
        echo "  8080 已恢复（第${i}次探测）" | tee -a "$RESULTS"
        break
    fi
    sleep 3
done
echo "结果文件: $RESULTS" | tee -a "$RESULTS"
