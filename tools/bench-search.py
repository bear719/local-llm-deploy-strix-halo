#!/usr/bin/env python3
# 许可：CC0-1.0，公共领域贡献，无任何限制。
# -*- coding: utf-8 -*-
"""
检索效果基准：单塔向量 vs 仅 BM25 vs 融合（供索引/参数调整后复测）

评测口径（必须说清，否则数字无意义）：
  - 用例是**本机真实问题**，目标文档是人工确认过的正确答案所在文件。
  - 指标：Hit@3 / Hit@5 / MRR@5（命中排名倒数均值）。
  - 只衡量「能不能把对的文档捞进 top-k」，不衡量 LLM 读到之后的回答质量。

2026-11-23 首次基线（1431 块全量索引，6 条用例）：
  融合    Hit@3 100%  MRR 0.833
  仅向量  Hit@3  67%  MRR 0.559
  仅BM25  Hit@3  33%  MRR 0.417

用法：
  python3 tools/bench-search.py
  python3 tools/bench-search.py --topk 10 --verbose
"""

import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SEARCH = os.path.join(HERE, "npu-search.py")
ROOT = os.path.dirname(HERE)

# (查询, 正确答案所在文件名子串)
CASES = [
    ("cache-ram -1 为什么不行", "2026-11-09-cache-ram-100K定档"),
    ("coopmat2 对 RDNA3 有没有用", "2026-11-23-B1B2B3"),
    ("ASR 拼音纠错 CER 下降", "2026-11-08-ASR中文识别"),
    ("gpu arbiter 显存护栏 kill stray llama", "02-gpu-arbiter"),
    ("spec-draft-n-max 取值与接受率", "2026-09-27-imatrix-v2"),
    ("prompt cache 落显存 Vulkan_HostDL", "2026-11-09-prompt-cache落显存"),
    ("KV 槽快照为什么否决", "2026-11-09-KV槽快照实测"),
    ("Wan2.2 cfg-scale 必须 5.0", "video"),
]

MODES = [("融合", []), ("仅向量", ["--vec-only"]), ("仅BM25", ["--bm25-only"])]


def run(query, extra, topk):
    r = subprocess.run([sys.executable, SEARCH, query, "--topk", str(topk), "--json"] + extra,
                       capture_output=True, text=True, cwd=ROOT, timeout=180)
    if r.returncode != 0:
        return None, r.stderr[-300:]
    try:
        return json.loads(r.stdout), None
    except Exception as e:
        return None, str(e)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--topk", type=int, default=5)
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()

    print("%-46s %s" % ("查询 → 目标", "  ".join("%-8s" % m[0] for m in MODES)))
    print("-" * 90)
    agg = {m[0]: [] for m in MODES}
    for q, tgt in CASES:
        row = []
        for mname, extra in MODES:
            hits, err = run(q, extra, a.topk)
            if hits is None:
                row.append("ERR")
                agg[mname].append(99)
                print("  [%s] %s" % (mname, err), file=sys.stderr)
                continue
            rank = next((i + 1 for i, h in enumerate(hits) if tgt in h["source"]), 0)
            agg[mname].append(rank if rank else 99)
            row.append("第%d" % rank if rank else "未命中")
            if a.verbose and rank != 1:
                got = [os.path.basename(h["source"])[:34] for h in hits[:3]]
                print("  [%s] top3=%s" % (mname, got), file=sys.stderr)
        print("%-46s %s" % ((q[:30] + " → " + tgt[:12]), "  ".join("%-8s" % x for x in row)))

    print("-" * 90)
    n = len(CASES)
    for mname in agg:
        rs = agg[mname]
        print("%-8s Hit@3=%3.0f%%  Hit@%d=%3.0f%%  MRR@%d=%.3f"
              % (mname,
                 100 * sum(1 for r in rs if r <= 3) / n,
                 a.topk, 100 * sum(1 for r in rs if r <= a.topk) / n,
                 a.topk, sum(1.0 / r if r <= a.topk else 0 for r in rs) / n))
    return 0


if __name__ == "__main__":
    sys.exit(main())
