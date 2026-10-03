#!/usr/bin/env bash
# Qwen3.8-Flash-Next-ROCmFP4-FAST-imatrix-v2 + --ngram-on-disk 启动脚本
#
# 用法:
#   ./start-qwen38-imatrix-v2.sh            # 自动：有终端→后台，无终端(面板/守护)→前台
#   ./start-qwen38-imatrix-v2.sh long       # 262K 单槽，速度优先（默认档）
#   ./start-qwen38-imatrix-v2.sh multi      # 64K × 4 槽，并发优先
#   ./start-qwen38-imatrix-v2.sh fg         # 强制前台（MCSManager 等面板请用这个）
#   ./start-qwen38-imatrix-v2.sh bg         # 强制后台（nohup + setsid）
#   ./start-qwen38-imatrix-v2.sh stop       # 停止服务
#   ./start-qwen38-imatrix-v2.sh status     # 查看进程/显存/日志尾部
#   ./start-qwen38-imatrix-v2.sh check      # 只做环境自检，不启动
#
# 面板（MCSManager）适配要点:
#   面板把"前台主进程退出"判定为实例停止，所以脚本里若 nohup 后台化，
#   面板立刻显示"已停止"，随后重启又会因端口被占而失败。
#   本脚本在 stdin 不是 tty 时自动改为前台 exec，且只在后台模式才落日志文件。
#   root/其他用户运行时，日志与 pid 文件带 uid 后缀，避免互相写不动。
#
# 模型侧关键点（勿删）:
#   1. --ngram-on-disk 是必须的。imatrix-v2 用 joined 布局，n-gram 表 22.4 GB
#      （per_layer_token_embd.weight, Q3_0_ROCMFPX, 320001536 行 × 70 B）。
#      不开的话这张表会常驻主机内存，本机 host 仅 30 GB → 直接进 swap
#      （fork 文档实测：21.1 GiB swapped，156 major faults/s）。
#   2. 只有 fork 分支 vulkan/qwen4exp-rocmfpx 编出的二进制能跑：
#      表量化类型是 fork 私有 ggml type 104（Q3_0_ROCMFPX），上游二进制不识别。
#      当前可用二进制：build-vk4（build 10820, commit b2cc77659）。
#   3. -np > 1 时 draft-mtp 存在 cross-slot 串扰风险（上游 PR #28123 作者声明），
#      故 long 档强制 -np 1；multi 档如需严格正确请改回 -np 1。

set -euo pipefail

BIN_DIR=$HOME/llama-qwen4exp-rocmfpx/build-vk4/bin
MODEL=$HOME/models/Qwen3.8-Flash-Next-ROCmFP4-FAST-imatrix-v2.gguf
DRAFT=$HOME/models/Qwen3.8-Flash-Next-MTP-ROCmFP4-FAST.gguf
PORT=${PORT:-8080}
SUFFIX=$(id -u)
LOG=/tmp/qwen38-imatrix-v2-server-$SUFFIX.log
PIDFILE=/tmp/qwen38-imatrix-v2-server-$SUFFIX.pid
MODE=${1:-auto}

# root 经 systemd/面板启动时拿不到 PAM 注入的环境，ICD 必须自己兜住，
# 否则 Vulkan 枚举不到设备 → 静默退化成 CPU 推理（速度掉 2 倍以上且不报错）
if [[ -z ${VK_ICD_FILENAMES:-} && -f /usr/share/vulkan/icd.d/radeon_icd.json ]]; then
    export VK_ICD_FILENAMES=/usr/share/vulkan/icd.d/radeon_icd.json
    export VK_DRIVER_FILES=/usr/share/vulkan/icd.d/radeon_icd.json
fi

port_busy() { ss -ltn 2>/dev/null | grep -q ":$PORT "; }

do_stop() {
    if [[ -f $PIDFILE ]] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
        kill "$(cat "$PIDFILE")" && echo "已停止 PID $(cat "$PIDFILE")"
        rm -f "$PIDFILE"
        return
    fi
    local pids; pids=$(pgrep -x llama-server 2>/dev/null || true)
    if [[ -n $pids ]]; then
        echo "[WARN] 发现未受本脚本管理的 llama-server：$pids"
        echo "       多半是面板孤儿进程（root 起的），本用户可能无权停止，用："
        echo "       sudo kill $pids"
    else
        echo "没有运行中的服务"
    fi
}

do_status() {
    local pids; pids=$(pgrep -x llama-server 2>/dev/null || true)
    [[ -n $pids ]] && echo "运行中 PID: $pids" || echo "未运行"
    command -v rocm-smi >/dev/null && rocm-smi --showmeminfo vram 2>/dev/null | grep "Used"
    [[ -f $LOG ]] && tail -n 5 "$LOG"
    return 0
}

case "$MODE" in
    stop)   do_stop; exit 0 ;;
    status) do_status; exit 0 ;;
    check)  : ;;
    fg|long|multi|auto|bg) : ;;
    *)      echo "[ERROR] 未知模式 '$MODE' -> 可用: long | multi | fg | bg | stop | status | check"; exit 1 ;;
esac

# ---- 环境自检（避免加载 55 秒后才炸） ----
[[ -x $BIN_DIR/llama-server ]] || { echo "[ERROR] 二进制不存在: $BIN_DIR/llama-server"; exit 1; }
[[ -f $MODEL ]] || { echo "[ERROR] 主模型不存在: $MODEL"; exit 1; }
[[ -f $DRAFT ]] || { echo "[ERROR] MTP 草稿模型不存在: $DRAFT"; exit 1; }
if port_busy; then
    echo "[ERROR] 端口 $PORT 已被占用，新实例会启动即失败"
    ss -ltnp 2>/dev/null | grep ":$PORT " || true
    exit 1
fi
echo "[OK] 环境自检通过：二进制/模型就绪，端口 $PORT 空闲，ICD=${VK_ICD_FILENAMES:-未设置}"
[[ $MODE == check ]] && exit 0

# ---- 参数档 ----
case "$MODE" in
    multi) CTX_ARGS=(-c 65536 -np 4 -b 2048 -ub 512) ;;   # 79.2 GB，26~33 t/s
    *)     CTX_ARGS=(-c 131072 -np 2 -b 4096 -ub 1024) ;; # 90.6 GB，35~39 t/s；np=2 支持缓存复用；本 build 上限 131072
esac

# 投机解码微调项（2026-09-27 三轮网格实测，temperature 0.7，12 次中位数）
#   ★ --spec-draft-n-max 是最强杠杆，且**越小越快**：
#       n-max=1 → 34.22 t/s | n-max=2 → 34.75（最优）| n-max=3（默认）→ 33.08
#       n-max=8 → 11.51 t/s | n-max=16 → 8.64 t/s   ← 崩塌 65%~74%，绝对不要调大
#     机制：草稿模型 nextn_predict_layers=1，源码 common/speculative.cpp 走串行循环，
#     draft N 个 token 就要对草稿模型跑 N 次前向，成本线性叠加；同时接受率随 n-max 增大
#     暴跌（67.8% → 53.3% → 44.5% → 19.9% → 10.6%），每步有效产出仅从 0.68 涨到 1.66 token，
#     收益远不抵成本。（旧注释写的"nextn=1 所以 n-max 无效"是错的，已订正。）
#   ★ --spec-draft-p-min 无实质影响：0（默认）32.80 / 0.3 → 33.71 / 0.6 → 32.16，全在噪声内。
#     它确实能抬高接受率（43% → 63%），但 draft 总数同步减少，净速度不变 → 保持默认不设。
#   ★ --spec-draft-adaptive 只能把 n-max=8 从 11.51 救回 30.42，仍不如直接把 n-max 设小。
#   ★ -ctk/-ctv q8_0 的目的是省显存：262K 上下文从 90.99 GB 降到 86.84 GB（-4.16 GB），速度不降。
# ★ 2026-10-03 优化（纯文本档，cache-reuse 生效）：
#   --cache-reuse 256：复用 256+ token 连续缓存块（本档无 --mmproj，cache-reuse 有效）
#   --cache-idle-slots：空闲 slot 保留 KV cache，配合 slot LCP 复用实现多轮加速
#   注：本 build 不支持长选项 --cms；-cms（checkpoint-min-step）对本档长上下文收益有限，故不加
TUNING=(--spec-type draft-mtp,ngram-map-k -ctk q8_0 -ctv q8_0 --spec-draft-n-max 2
        --cache-reuse 256 --cache-idle-slots)

# ---- 前台还是后台 ----
# FORCE_BG=1 供 switch-model.sh 调用：外层已有等待逻辑，这里必须后台返回，
# 否则非 tty 环境下会 exec 前台把调用方整个卡住。
FOREGROUND=0
case "$MODE" in
    fg) FOREGROUND=1 ;;
    bg) FOREGROUND=0 ;;
    *)  if [[ -n ${FORCE_BG:-} ]]; then FOREGROUND=0; else [[ -t 0 ]] || FOREGROUND=1; fi ;;
esac

# GPU 频率：auto 档只跑 970 MHz，实测拉到 high（2900 MHz）decode +5.3%
# （31.96 → 33.70 t/s）。需要 root/权限，失败静默跳过。
# 注意：rocm-smi 本机触发 sudo 提示，非交互环境（后台/面板）会卡住，加 < /dev/null 规避。
if command -v rocm-smi >/dev/null 2>&1; then
    rocm-smi --setperflevel high < /dev/null >/dev/null 2>&1 || true
fi

CMD=(
    "$BIN_DIR/llama-server"
    -m "$MODEL" -md "$DRAFT"
    --spec-type draft-mtp
    --ngram-on-disk --ngram-cache 512 --ngram-io-threads 64
    -ngl 999 "${CTX_ARGS[@]}"
    "${TUNING[@]}"
    --reasoning off          # 2026-09-28 关闭思考链：+16.3% decode（A/B 实测 34.94→40.65 t/s）
    --metrics --host 0.0.0.0 --port "$PORT"
)

if (( FOREGROUND )); then
    echo "[INFO] 前台模式：日志直出，加载约 55 秒，Ctrl+C 或面板停止按钮退出"
    exec "${CMD[@]}"
else
    cd "$BIN_DIR"
    setsid nohup "${CMD[@]}" > "$LOG" 2>&1 &
    echo $! > "$PIDFILE"
    disown
    echo "已启动 PID $(cat "$PIDFILE")，模式=$MODE，日志 $LOG"
    echo "加载 93 GB 模型约需 55 秒，用 '$0 status' 查看进度"
fi
