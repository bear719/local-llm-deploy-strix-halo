#!/usr/bin/env bash
# 许可：CC0-1.0，公共领域贡献，无任何限制。
# 文档库索引夜间全量重建 —— 供 cron 调用
#
# 设计要点（2026-11-23 改版：单库合并 + 全文去重 + 行号定位）：
#   1. 先过 GPU 空闲门控（NPU 满负荷会让 GPU decode 掉 12.7%）
#   2. **只产出一份 idx/all.json**：旧版 root.json + publish.json 双库导致
#      「单查一库永远检索不到另一库」（0.287 vs 0.358 的安静错命中）。
#      publish/ 是根目录文档的镜像，合并后按全文 hash 去重，实测 1977 → 1431 块。
#   3. 全量重建而非增量 diff：1431 块的规模约 7 分钟，增量逻辑的复杂度不值得
#   4. 排除 .workbuddy（记忆文件）、openwebui-data（模型缓存）、backup（备份）
#   5. 先写 .tmp 再 mv，失败不覆盖旧索引
#
# 用法：
#   ./tools/npu-reindex.sh              # 手动跑一次
#   crontab: 30 3 * * * /path/tools/npu-reindex.sh >> /tmp/npu-reindex.log 2>&1
#
# 环境变量：
#   IDLE_WAIT     等空闲的最长秒数，默认 3600
#   MIN_MEMAVAIL  门控要求的 host 可用内存 MiB，默认 4096
set -u

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${PY:-/home/<user>/.workbuddy/binaries/python/versions/3.13.12/bin/python3}"
IDLE_WAIT="${IDLE_WAIT:-3600}"
MIN_MEMAVAIL="${MIN_MEMAVAIL:-4096}"
STAMP="$(date '+%Y-%m-%d %H:%M:%S')"

echo "[$STAMP] === 索引更新开始 ==="

# NPU 服务存活检查：挂了就别白等
if ! curl -sf -m 5 http://127.0.0.1:8219/v1/models -o /dev/null; then
  echo "[ERROR] NPU 8219 无响应 -> 跳过本次更新" >&2
  exit 1
fi

cd "$DIR" || exit 1

# GPU 空闲门控
if ! "$PY" tools/npu-idle-gate.py --wait "$IDLE_WAIT" --idle 10 --min-mem "$MIN_MEMAVAIL" --quiet; then
  echo "[WAIT] 未等到 GPU 空闲窗口（${IDLE_WAIT}s）-> 跳过本次更新" >&2
  exit 1
fi

mkdir -p idx
TMP="idx/all.json.tmp"
if "$PY" tools/npu-index.py . --glob "*.md" --recursive \
      --exclude ".workbuddy/*" --exclude "openwebui-data/*" --exclude "backup/*" \
      --out "$TMP" --dedup 2>&1 | tail -3; then
  mv -f "$TMP" idx/all.json
  mv -f "$TMP.meta.json" idx/all.json.meta.json
  # BM25 倒排缓存随索引失效，删掉让 npu-search 重建
  rm -f idx/all.json.bm25.pkl
  echo "[OK] 索引已更新 -> idx/all.json"
else
  rm -f "$TMP" "$TMP.meta.json"
  echo "[ERROR] 建索引失败 -> 保留旧索引" >&2
  exit 1
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] === 完成 ==="
