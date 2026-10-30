#!/usr/bin/env bash
# Qwen3.6-35B-A3B 提速网格（2026-10-07）
# 目的：在 3.6-35B 上实测 --spec-draft-n-max / KV 量化 / FA / mmproj 四项的影响
# 基线：decode 90.61 t/s，接受率 77.8%，每步接受 1.55 token，GPU 已满频 2900MHz
#
# 重要：脚本用 8090 端口起独立实例，不碰面板 8080。
#       但独立实例会与 8080 争显存和带宽 → 必须先停 8080 实例才能得到干净数据。
#       故本脚本会：停 8080 → 逐组启动测试 → 结束后由面板自动重拉 8080。

set -uo pipefail

BIN=$HOME/llama-qwen4exp-rocmfpx/build-vk4/bin/llama-server
MODEL=$HOME/models/Qwen3.6-35B-A3B-Uncensored-Q4_K_P.gguf
DRAFT=$HOME/models/Qwen3.6-35B-A3B-MTP-ONLY-Q4_K_M.gguf
MMPROJ=$HOME/models/mmproj-Qwen3.6-35B-A3B-Uncensored-f16.gguf
PORT=8090
RESULTS=/tmp/specgrid-35b-20261007.txt
SUDO_FILE=$HOME/.workbuddy/.docker-sudo
SUDO_PASS=$(cat "$SUDO_FILE")
BENCH=$HOME/WorkBuddy/调试本地模型/tools/bench-server.py
PY=$HOME/.workbuddy/binaries/python/versions/3.13.12/bin/python3

export VK_ICD_FILENAMES=/usr/share/vulkan/icd.d/radeon_icd.json
export VK_DRIVER_FILES=/usr/share/vulkan/icd.d/radeon_icd.json

[[ -f $RESULTS ]] || echo "Qwen3.6-35B-A3B 提速网格  2026-10-07" > "$RESULTS"

stop_panel() {
    printf '%s\n' "$SUDO_PASS" | sudo -S -k pkill -x llama-server 2>/dev/null
    for i in $(seq 1 20); do
        pgrep -x llama-server >/dev/null 2>&1 || return 0
        sleep 1
    done
    printf '%s\n' "$SUDO_PASS" | sudo -S -k pkill -9 -x llama-server 2>/dev/null
    sleep 3
}

wait_ready() {
    for i in $(seq 1 40); do
        if curl -s -m 3 "http://127.0.0.1:$PORT/health" 2>/dev/null | grep -q ok; then
            return 0
        fi
        sleep 3
    done
    return 1
}

run_case() {
    local name="$1" desc="$2"; shift 2
    local extra=("$@")

    echo "" | tee -a "$RESULTS"
    echo "=========== [$name] $desc ===========" | tee -a "$RESULTS"

    stop_panel
    # 抢先占端口，防面板重拉
    rm -f /tmp/grid-instance-$PORT.log
    setsid nohup "$BIN" \
        -m "$MODEL" -md "$DRAFT" \
        --spec-type draft-mtp \
        -ngl 999 -c 131072 -np 1 -b 4096 -ub 1024 \
        "${extra[@]}" \
        --cache-idle-slots -cms 512 \
        --metrics --host 0.0.0.0 --port "$PORT" \
        > /tmp/grid-instance-$PORT.log 2>&1 &

    if ! wait_ready; then
        echo "  [ERROR] 启动失败，日志尾部：" | tee -a "$RESULTS"
        tail -5 /tmp/grid-instance-$PORT.log | tee -a "$RESULTS"
        return 1
    fi

    # 预热 1 次，排除 shader 编译 / 冷 cache
    curl -s -m 120 -X POST "http://127.0.0.1:$PORT/v1/chat/completions" \
        -H 'Content-Type: application/json' \
        -d '{"messages":[{"role":"user","content":"预热"}],"max_tokens":16,"stream":false}' \
        >/dev/null 2>&1

    "$PY" "$BENCH" 5 "$PORT" 2>&1 | tee -a "$RESULTS"

    # MTP 指标
    curl -s -m 5 "http://127.0.0.1:$PORT/metrics" 2>/dev/null \
        | grep -E 'spec_decode_num_(draft|accepted)_tokens_total' | tee -a "$RESULTS"

    local pids; pids=$(pgrep -x llama-server 2>/dev/null || true)
    [[ -n $pids ]] && kill $pids 2>/dev/null
    sleep 3
}

# ---------- 网格定义 ----------
# 变量：mmproj(有/无) / ctk,ctv / fa / n-max
run_case "A-基线" "mmproj + q8_0 KV + n-max2（当前线上配置）" \
    --mmproj "$MMPROJ" --spec-draft-n-max 2 -ctk q8_0 -ctv q8_0

run_case "B-KV-q4_0" "去 mmproj + q4_0 KV + n-max2（测底带宽压力）" \
    -ctk q4_0 -ctv q4_0 --spec-draft-n-max 2

run_case "C-noMMproj" "去 mmproj + q8_0 KV + n-max2（隔离 mmproj 影响）" \
    --spec-draft-n-max 2 -ctk q8_0 -ctv q8_0

run_case "D-nmax3" "去 mmproj + q8_0 KV + n-max3（验证位置1接受率69%是否有余量）" \
    --spec-draft-n-max 3 -ctk q8_0 -ctv q8_0

run_case "E-nmax1" "去 mmproj + q8_0 KV + n-max1（skill 结论：1 略逊 2）" \
    --spec-draft-n-max 1 -ctk q8_0 -ctv q8_0

echo "" | tee -a "$RESULTS"
echo "=== 网格结束，恢复面板实例 ===" | tee -a "$RESULTS"
stop_panel
echo "结果：$RESULTS"
