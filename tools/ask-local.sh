#!/usr/bin/env bash
# 许可：CC0-1.0，公共领域贡献，无任何限制。
# 语义检索包装器 —— 一条命令查本地文档库
#
# 用法：
#   ./ask-local.sh "有效带宽是多少"
#   ./ask-local.sh "ASR 纠错方案" -k 8
#   ./ask-local.sh "为什么 cache-ram 不能用 -1" --full
#
# 依赖：idx/root.json（由 tools/npu-index.py 生成）
set -u

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PY:-/home/<user>/.workbuddy/binaries/python/versions/3.13.12/bin/python3}"
IDX="${IDX:-$DIR/idx/root.json}"
PUB="${PUB:-$DIR/idx/publish.json}"
TOPK=5
FULL=0
QUERY=()

# 默认跨库检索：root（工作区报告）+ publish（发布仓库 4 分支合并视图）
EXTRA=()
[ -f "$PUB" ] && EXTRA=(--extra "$PUB")

while [ $# -gt 0 ]; do
  case "$1" in
    -k|--topk) TOPK="$2"; shift 2 ;;
    --full)    FULL=1; shift ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *)         QUERY+=("$1"); shift ;;
  esac
done

if [ ${#QUERY[@]} -eq 0 ]; then
  echo "[ERROR] 缺少查询词 -> 用法: $0 \"你的问题\"" >&2
  exit 2
fi

if [ ! -f "$IDX" ]; then
  echo "[ERROR] 索引不存在: $IDX -> 先跑 tools/npu-index.py" >&2
  exit 2
fi

Q="${QUERY[*]}"

if [ "$FULL" -eq 1 ]; then
  # 打印命中块的完整正文（带来源与标题路径），跨库联合打分
  "$PY" - "$IDX" "$Q" "$TOPK" "$PUB" <<'PYEOF'
import json, sys, math, urllib.request
idx, q, k, pub = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
recs = []
for p in [idx, pub]:
    try:
        d = json.load(open(p, encoding="utf-8"))
    except Exception:
        continue
    if not d.get("vectors"):
        continue
    for i, v in enumerate(d["vectors"]):
        c = d["chunks"][i] if i < len(d.get("chunks", [])) else {"source": p, "title": "", "text": d["texts"][i]}
        recs.append((v, c))
if not recs:
    print("[ERROR] 无可检索索引", file=sys.stderr); sys.exit(2)
body = json.dumps({"model": "embed-gemma:300m", "input": [q]}).encode()
r = urllib.request.urlopen(urllib.request.Request(
    "http://127.0.0.1:8219/v1/embeddings", body, {"Content-Type": "application/json"}), timeout=120)
qv = json.load(r)["data"][0]["embedding"]
def cos(x, y):
    return sum(a*b for a, b in zip(x, y)) / (math.sqrt(sum(a*a for a in x))*math.sqrt(sum(b*b for b in y)) or 1)
sc = sorted(((cos(qv, v), i) for i, (v, _) in enumerate(recs)), reverse=True)[:k]
for s, i in sc:
    c = recs[i][1]
    print("\n=== %.4f  %s\n--- 章节：%s\n%s" % (s, c.get("source", "?"), c.get("title") or "-", c.get("text", "")))
PYEOF
else
  "$PY" "$DIR/tools/npu-sidecar.py" search "$IDX" "$Q" --topk "$TOPK" "${EXTRA[@]+"${EXTRA[@]}"}"
fi
