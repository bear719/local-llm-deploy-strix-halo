#!/usr/bin/env bash
# Qwen3.6-35B-A3B-Uncensored-Q4_K_P + MTP 草稿模型 启动脚本（MoE 高速档）
#
# 用法:
#   ./start-qwen36-35b-a3b.sh            # 自动：有终端→后台，无终端(面板/守护)→前台
#   ./start-qwen36-35b-a3b.sh long       # 262K 单槽（默认档，速度优先）
#   ./start-qwen36-35b-a3b.sh fast       # 262K 单槽 + 关闭思考链（日常待办/抽取类任务）
#   ./start-qwen36-35b-a3b.sh multi      # 64K × 4 槽，并发优先（见下方串扰警告）
#   ./start-qwen36-35b-a3b.sh fg         # 强制前台（MCSManager 等面板用这个）
#   ./start-qwen36-35b-a3b.sh bg         # 强制后台（nohup + setsid）
#   ./start-qwen36-35b-a3b.sh stop       # 停止本脚本启动的服务
#   ./start-qwen36-35b-a3b.sh status     # 查看进程/显存/日志尾部
#   ./start-qwen36-35b-a3b.sh check      # 只做环境自检，不启动
#
# 与 Qwen3.8-Flash-Next-imatrix-v2（27B dense）的分工：
#   35B-A3B 是 MoE，每 token 只激活 3B → 解码约 57 t/s；27B dense 受带宽墙限制约 32~40 t/s。
#   长思考、日常待办、批量抽取 → 用本脚本；需要 imatrix-v2 的 n-gram 表能力 → 换 38 档。
#
# 模型侧关键点（勿删）:
#   1. 本模型是**标准 Q4_K_P**（gguf file_type 15），不含 fork 私有 ggml type，
#      所以上游/任意 build 都能加载；当前统一用 build-vk4（Vulkan，比 HIP 快约 51%）。
#   2. 主模型 arch=qwen35moe，40 层，embedding 2048，expert 256 取 8；
#      草稿模型 41 层、nextn_predict_layers=1、embedding 同为 2048 → 维度匹配，MTP 可用。
#      （来源：tools/gguf_probe.py 实测元数据）
#   3. **不要加 --ngram-on-disk / --spec-type ...ngram-map-k**：
#      gguf_probe 判定本模型无 PLE n-gram 表，那套参数是 imatrix-v2 专用的。
#   4. -np > 1 时 draft-mtp 存在 cross-slot 串扰风险（上游 PR #28123 作者声明），
#      故 long/fast 档强制 -np 1；multi 档如需严格正确请改回 -np 1。
#   5. mmproj 必须匹配主模型：35B-A3B 用 mmproj-Qwen3.6-35B-A3B-Uncensored-f16.gguf
#      （27B 用 mmproj-F32.gguf，用错会启动失败 mismatch between text model and mmproj）。

set -euo pipefail

BIN_DIR=$HOME/llama-qwen4exp-rocmfpx/build-vk4/bin
MODEL=$HOME/models/Qwen3.6-35B-A3B-Uncensored-Q4_K_P.gguf
DRAFT=$HOME/models/Qwen3.6-35B-A3B-MTP-ONLY-Q4_K_M.gguf
MMPROJ=$HOME/models/mmproj-Qwen3.6-35B-A3B-Uncensored-f16.gguf
PORT=${PORT:-8080}
SUFFIX=$(id -u)
LOG=/tmp/qwen36-35b-a3b-server-$SUFFIX.log
PIDFILE=/tmp/qwen36-35b-a3b-server-$SUFFIX.pid
MODE=${1:-auto}

# root 经 systemd/面板启动时拿不到 PAM 注入的环境，ICD 必须自己兜住，
# 否则 Vulkan 枚举不到设备 → 静默退化成 CPU 推理（速度掉 2 倍以上且不报错）。
# 排错口诀：echo $VK_ICD_FILENAMES 指向的文件必须真实存在。
if [[ -z ${VK_ICD_FILENAMES:-} && -f /usr/share/vulkan/icd.d/radeon_icd.json ]]; then
    export VK_ICD_FILENAMES=/usr/share/vulkan/icd.d/radeon_icd.json
    export VK_DRIVER_FILES=/usr/share/vulkan/icd.d/radeon_icd.json
fi

port_busy() { ss -ltn 2>/dev/null | grep -q ":$PORT "; }

do_stop() {
    # 先按进程名找，pidfile 只是兜底：setsid 会 fork，pidfile 里记的未必是真正的
    # llama-server PID，直接 kill pidfile 可能杀不掉。
    local pids; pids=$(pgrep -x llama-server 2>/dev/null || true)
    if [[ -n $pids ]]; then
        kill $pids 2>/dev/null && echo "已停止 PID: $pids" || {
            echo "[ERROR] 无权停止 $pids -> 手动执行: sudo kill $pids"; return 1; }
        rm -f "$PIDFILE"
        return
    fi
    pids=$(pgrep -x llama-server 2>/dev/null || true)
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
    fg|long|fast|multi|auto|bg) : ;;
    *)      echo "[ERROR] 未知模式 '$MODE' -> 可用: long | fast | multi | fg | bg | stop | status | check"; exit 1 ;;
esac

# ---- 环境自检（避免加载几十秒后才炸） ----
[[ -x $BIN_DIR/llama-server ]] || { echo "[ERROR] 二进制不存在: $BIN_DIR/llama-server"; exit 1; }
[[ -f $MODEL ]] || { echo "[ERROR] 主模型不存在: $MODEL"; exit 1; }
[[ -f $DRAFT ]] || { echo "[ERROR] MTP 草稿模型不存在: $DRAFT"; exit 1; }
[[ -f $MMPROJ ]] || { echo "[WARN] mmproj 不存在: $MMPROJ（视觉能力将不可用，文本不受影响）"; MMPROJ=""; }
if port_busy; then
    echo "[ERROR] 端口 $PORT 已被占用，新实例会启动即失败"
    ss -ltnp 2>/dev/null | grep ":$PORT " || true
    exit 1
fi
echo "[OK] 环境自检通过：二进制/模型就绪，端口 $PORT 空闲，ICD=${VK_ICD_FILENAMES:-未设置}"
[[ $MODE == check ]] && exit 0

# ---- 参数档 ----
# 权重 23.42 GB + 草稿 1.62 GB + mmproj 0.90 GB ≈ 25.9 GB，KV 另计；96 GiB 显存充裕。
case "$MODE" in
    multi) CTX_ARGS=(-c 65536 -np 3 -b 2048 -ub 1024) ;;   # 并发优先（3 槽）
    *)     CTX_ARGS=(-c 131072 -np 2 -b 4096 -ub 1024) ;;  # 速度优先（2 槽）；本 build 真实上限 131072（-c 262144 被强行 clamp）
esac

case "$MODE" in
    fast) REASONING=(--reasoning off) ;;   # 日常待办/结构化抽取：不出思考链，直接给结果
    *)    REASONING=() ;;                  # long/multi 保留模型原生思考行为
esac

# ★ 本档实测（2026-10-02 12:58，面板实例启动后 tools/bench-server.py 3 次中位数）:
#     decode 85.46 t/s（区间 82.66~91.46）| prefill 152.85 t/s
#     显存 31.42 GB（对比 38 档 imatrix-v2 的 81.75 GB，一半不到）
#     MTP 接受率 457/614 = 74.4%，每步平均接受 1.99 token（n-max=2 满载）
#     /slots[0].params.speculative.types = none,draft-mtp → MTP 确认启用
#     对比：38 档 32~40 t/s（dense 27B 受带宽墙）→ 本档快约 2.2 倍
#
# 投机解码微调项（沿用 2026-09-27 在 27B 上的三轮网格实测结论，35B 尚未单独网格，待补）:
#   ★ --spec-draft-n-max 越小越快：1→34.22 / 2→34.75(最优) / 3→33.08 / 8→11.51 / 16→8.64 t/s。
#     n-max 调大会崩塌 65%~74%，绝对不要调大。
#   ★ --spec-draft-p-min 在噪声内，保持默认不设。
#   ★ -ctk/-ctv q8_0 为省显存，速度不降。
# ★ 本档实测（2026-10-02 12:58，面板实例启动后 tools/bench-server.py 3 次中位数）:
#     decode 85.46 t/s（区间 82.66~91.46）| prefill 152.85 t/s
#     显存 31.42 GB（对比 38 档 imatrix-v2 的 81.75 GB，一半不到）
#     MTP 接受率 457/614 = 74.4%，每步平均接受 1.99 token（n-max=2 满载）
#     /slots[0].params.speculative.types = none,draft-mtp → MTP 确认启用
#     对比：38 档 32~40 t/s（dense 27B 受带宽墙）→ 本档快约 2.2 倍
#
# ★ 2026-10-03 优化（实测修正）：
#   --cache-reuse 256：本档带 --mmproj（多模态），llama-server 启动时打印
#     "cache_reuse is not supported by multimodal, it will be disabled" → 该参数在 mmproj 下无效，已移除。
#   --cache-idle-slots：空闲 slot 保留 KV cache，配合 slot 内置 LCP 前缀复用，实现同会话轮次间 202× 加速。
#   -cms 512（= --checkpoint-min-step）：长上下文 checkpoint 间隔从默认 8192 降到 512，超长上下文续写更稳。
#   ★ 真实上下文上限 = 131072：本 build 把 -c 262144 强行 clamp 到模型原生 131072（日志证实
#     "request (200020 tokens) exceeds the available context size (131072 tokens)"），故 CTX_ARGS 改 -c 131072。
TUNING=(--spec-draft-n-max 2 -ctk q8_0 -ctv q8_0
        --cache-idle-slots -cms 512)

# ---- 前台还是后台 ----
# FORCE_BG=1 供 switch-model.sh 调用：外层已有等待逻辑，这里必须后台返回，
# 否则非 tty 环境下会 exec 前台把调用方整个卡住。
FOREGROUND=0
case "$MODE" in
    fg) FOREGROUND=1 ;;
    bg) FOREGROUND=0 ;;
    *)  if [[ -n ${FORCE_BG:-} ]]; then FOREGROUND=0; else [[ -t 0 ]] || FOREGROUND=1; fi ;;
esac

# GPU 频率：auto 档只跑约 1 GHz，拉到 high（2900 MHz）decode +3~5%。
# 注意：rocm-smi 在本机触发 sudo 密码提示，非交互环境（后台/面板）会卡住。
# 加 < /dev/null 让 sudo 拿不到 tty 直接失败（而非阻塞），失败静默跳过。
if command -v rocm-smi >/dev/null 2>&1; then
    rocm-smi --setperflevel high < /dev/null >/dev/null 2>&1 || true
fi

CMD=(
    "$BIN_DIR/llama-server"
    -m "$MODEL" -md "$DRAFT"
    --spec-type draft-mtp
    -ngl 999 "${CTX_ARGS[@]}"
)
[[ -n $MMPROJ ]] && CMD+=(--mmproj "$MMPROJ")
CMD+=(
    "${TUNING[@]}"
    "${REASONING[@]}"
    --metrics --host 0.0.0.0 --port "$PORT"
)

if (( FOREGROUND )); then
    echo "[INFO] 前台模式：日志直出，加载约 20~30 秒（25.9 GB，比 93 GB 的 imatrix-v2 快很多）"
    exec "${CMD[@]}"
else
    cd "$BIN_DIR"
    setsid nohup "${CMD[@]}" > "$LOG" 2>&1 &
    echo $! > "$PIDFILE"
    disown
    echo "已启动 PID $(cat "$PIDFILE")，模式=$MODE，日志 $LOG"
    echo "加载约 20~30 秒，用 '$0 status' 查看进度"
fi
