#!/usr/bin/env bash
# docproxy 启动脚本（供 MCSManager 通用实例 / systemd 使用）
# 关键：前台阻塞运行，MCSManager 靠前台主进程判定实例存活，切勿后台化（nohup &）。
set -u
PORT="${PORT:-18090}"
UPSTREAM="${UPSTREAM:-http://127.0.0.1:8080}"
PROXY_MODE="${PROXY_MODE:-passthrough}"   # passthrough=兼容客户端透传; disclosure=非流式走渐进式披露
# 默认给转发请求注入 chat_template_kwargs.enable_thinking=false。
# 2026-10-02 实测：35B-A3B（Qwen3.6 模板）默认吐思考链，OpenClaw 这类通用 OpenAI 客户端
# 不会关思考，结果 token 全进 reasoning_content、content 为空。注入后默认直出答案；
# 客户端显式传 enable_thinking 时以其为准。设为 0 可关闭注入。
INJECT_NO_THINK="${INJECT_NO_THINK:-1}"

# ---- NPU 旁路分流（2026-11-08 上生产）----
# 只有「显式标记」的请求才会被送去 NPU：X-Backend: npu 头，或 model 命中别名白名单。
# 绝不按 prompt 内容猜测，主模型流量 100% 仍走 $UPSTREAM(8080)。
#
# ★ 回滚口径：这里刻意用 ${VAR-默认}（单横线）而非 ${VAR:-默认}。
#   单横线只在「变量未设置」时取默认值；把 NPU_UPSTREAM 显式设为空串即可
#   完整关闭分流，无需改代码、无需回滚补丁。
NPU_UPSTREAM="${NPU_UPSTREAM-http://127.0.0.1:8219}"
NPU_MODEL_TAG="${NPU_MODEL_TAG-lfm2.5-it:1.2b}"
# host RAM 水位线（MiB）：NPU 吃 30.47 GiB host RAM，与 Vulkan 的 96 GiB carve-out
# 不是同一个池子。2026-10-08 实测 avail 掉到 494 MiB 时全局 OOM，故必须设闸门。
NPU_MIN_MEMAVAIL_MIB="${NPU_MIN_MEMAVAIL_MIB-4096}"
# sidecar：/v1/embeddings 与 /v1/audio/* 自动走 NPU，不需要客户端加任何头。
# 前置条件是 8219 已用 --embed / --asr 启动（见 flm-npu.conf）。
# 同样用单横线：显式设空串即关闭，退回「仅按 X-Backend / model 别名分流」。
NPU_SIDECAR="${NPU_SIDECAR-1}"
# ASR 文本拼音层纠错（确定性层，零额外延迟）；设为空串即关闭
NPU_ASR_FIX="${NPU_ASR_FIX-1}"

PY="/home/<user>/.workbuddy/binaries/python/envs/default/bin/python"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="$SCRIPT_DIR/tools/docproxy.py"   # 与 start-docproxy.sh 同目录

# ---- 等待上游就绪（最多 120s，避免比 llama-server 先起时自检失败）----
for i in $(seq 1 24); do
  if curl -s -m 3 "$UPSTREAM/health" >/dev/null 2>&1; then break; fi
  echo "[等待] 上游 $UPSTREAM 未就绪，5s 后重试 ($i/24)"
  sleep 5
done
if ! curl -s -m 3 "$UPSTREAM/health" >/dev/null 2>&1; then
  echo "[ERROR] 上游 $UPSTREAM 在 120s 内未就绪，请先在面板启动模型实例（35B-A3B 档或 start-qwen38-imatrix-v2，二者分时复用 8080）" >&2
  exit 1
fi

# ---- 端口占用检查 ----
if ss -ltn 2>/dev/null | grep -q ":$PORT "; then
  echo "[ERROR] 端口 $PORT 已被占用，请先停止占用进程" >&2
  exit 1
fi

export PROXY_MODE
export INJECT_NO_THINK
export NPU_UPSTREAM
export NPU_MODEL_TAG
export NPU_MIN_MEMAVAIL_MIB
export NPU_SIDECAR
export NPU_ASR_FIX
echo "[OK] 启动 docproxy :$PORT -> $UPSTREAM  mode=$PROXY_MODE"
if [ -n "$NPU_UPSTREAM" ]; then
  echo "[OK] NPU 旁路已启用 -> $NPU_UPSTREAM  tag=$NPU_MODEL_TAG  mem水位=${NPU_MIN_MEMAVAIL_MIB}MiB"
  echo "[OK] ASR 纠错=${NPU_ASR_FIX:-0}  sidecar=${NPU_SIDECAR:-0}"
else
  echo "[OK] NPU 旁路已关闭（NPU_UPSTREAM 为空），全部流量走 $UPSTREAM"
fi
exec "$PY" "$SCRIPT" serve --port "$PORT" --upstream "$UPSTREAM"

# 许可：CC0-1.0，公共领域贡献，无任何限制。
