#!/usr/bin/env bash
# Open WebUI 启动脚本（Strix Halo 本机）
# 用途：一键（重）建 Open WebUI 容器，接入 llama.cpp(8080) + FLM NPU(8219) 双端点
# 作者：管家  日期：2026-10-07
#
# 依赖：Docker + 本机 sudo 凭据文件 ~/.workbuddy/.docker-sudo（600 权限）

set -euo pipefail

# ---------- 可调参数 ----------
PORT=3000                                   # 宿主映射端口
DATA_DIR="$HOME/WorkBuddy/调试本地模型/openwebui-data"
IMAGE="ghcr.io/open-webui/open-webui:main"
CONTAINER="open-webui"
SECRET_KEY="${WEBUI_SECRET_KEY:-change-me}"      # 会话加密密钥，换掉需重新登录
SUDO_FILE="$HOME/.workbuddy/.docker-sudo"
# -------------------------------

SUDO() { cat "$SUDO_FILE" | sudo -S -k "$@"; }

echo "[1/4] 检查 sudo 凭据与 Docker"
[ -f "$SUDO_FILE" ] || { echo "[ERROR] 缺少 $SUDO_FILE -> 先写入 sudo 密码"; exit 1; }
SUDO docker version >/dev/null

echo "[2/4] 清理旧容器（保留数据目录）"
SUDO docker rm -f "$CONTAINER" 2>/dev/null || true

echo "[3/4] 启动容器"
mkdir -p "$DATA_DIR"
SUDO docker run -d \
  -p "${PORT}:8080" \
  --add-host=host.docker.internal:host-gateway \
  -v "${DATA_DIR}:/app/backend/data" \
  -e WEBUI_SECRET_KEY="$SECRET_KEY" \
  -e HF_ENDPOINT=https://hf-mirror.com \
  -e ENABLE_OPENAI_API=true \
  -e OPENAI_API_BASE_URL=http://host.docker.internal:8080/v1 \
  -e OPENAI_API_KEY=sk-no-key \
  -e ENABLE_SEARCH_QUERY_GENERATION=true \
  -e "SEARCH_SEARXNG_ENGINE_QUERY_URL=http://host.docker.internal:8888/search?q=<query>" \
  --name "$CONTAINER" \
  --restart always \
  "$IMAGE" >/dev/null

echo "[4/4] 等待健康检查"
for i in $(seq 1 30); do
  code=$(curl -s -o /dev/null -w '%{http_code}' -m 5 "http://127.0.0.1:${PORT}/health" || true)
  if [ "$code" = "200" ]; then
    echo "[OK] Open WebUI 已就绪 -> http://127.0.0.1:${PORT}"
    exit 0
  fi
  sleep 5
done

echo "[ERROR] 健康检查超时 -> sudo docker logs $CONTAINER"
exit 1
