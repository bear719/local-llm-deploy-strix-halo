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
PY="$HOME/.workbuddy/binaries/python/envs/default/bin/python"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="$SCRIPT_DIR/docproxy.py"   # 与 start-docproxy.sh 同目录

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
echo "[OK] 启动 docproxy :$PORT -> $UPSTREAM  mode=$PROXY_MODE"
exec "$PY" "$SCRIPT" serve --port "$PORT" --upstream "$UPSTREAM"
