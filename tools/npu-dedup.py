#!/usr/bin/env python3
# 许可：CC0-1.0，公共领域贡献，无任何限制。
# -*- coding: utf-8 -*-
"""
文本去重 / 聚类工具 —— 基于 NPU embedding（8219）

适用：病历段落去重、管线输出查重、语料近重复清理、日志聚类。
实测（2026-11-23）：近重复对 cos 0.93~0.99，无关对 0.31 → 阈值 0.90 安全。

用法：
  python3 npu-dedup.py texts.txt                    # 每行一条，输出保留项
  python3 npu-dedup.py texts.txt --thr 0.92 --json  # 输出 JSON（含被删项与相似度）
  python3 npu-dedup.py texts.txt --cluster          # 只做聚类，不删
  cat x.txt | python3 npu-dedup.py - --thr 0.9
"""

import argparse
import json
import math
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])


def _load_embed():
    # 动态导入同目录的 npu-sidecar.py（文件名含连字符，不能直接 import）
    import importlib.util
    import os
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "npu-sidecar.py")
    spec = importlib.util.spec_from_file_location("npu_sidecar", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.embed_texts


def cos(x, y):
    s = sum(a * b for a, b in zip(x, y))
    nx = math.sqrt(sum(a * a for a in x)) or 1.0
    ny = math.sqrt(sum(b * b for b in y)) or 1.0
    return s / (nx * ny)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input", help="文本文件（每行一条），- 表示 stdin")
    ap.add_argument("--thr", type=float, default=0.90, help="判为重复的余弦阈值，默认 0.90")
    ap.add_argument("--cluster", action="store_true", help="只聚类，不删除")
    ap.add_argument("--json", action="store_true", help="JSON 输出")
    a = ap.parse_args()

    embed = _load_embed()
    if a.input == "-":
        lines = [ln.strip() for ln in sys.stdin.read().splitlines() if ln.strip()]
    else:
        with open(a.input, "r", encoding="utf-8") as f:
            lines = [ln.strip() for ln in f if ln.strip()]

    if not lines:
        print("[ERROR] 输入为空", file=sys.stderr)
        return 2

    vecs, dt = embed(lines)
    print("[INFO] %d 条 / %.2fs" % (len(lines), dt), file=sys.stderr)

    clusters = []  # [[idx,...], ...]
    assigned = [False] * len(lines)
    for i in range(len(lines)):
        if assigned[i]:
            continue
        members = [i]
        assigned[i] = True
        for j in range(i + 1, len(lines)):
            if assigned[j]:
                continue
            if cos(vecs[i], vecs[j]) >= a.thr:
                members.append(j)
                assigned[j] = True
        clusters.append(members)

    keep = [c[0] for c in clusters]
    dropped = [(j, c[0], round(cos(vecs[j], vecs[c[0]]), 4))
               for c in clusters for j in c[1:]]

    if a.cluster:
        for c in clusters:
            print("[簇 %d] %d 条" % (len(c), len(c)))
            for i in c:
                print("   %s%s" % ("*" if i == c[0] else " ", lines[i][:100]))
    elif a.json:
        print(json.dumps({
            "total": len(lines), "kept": len(keep), "dropped": len(dropped),
            "threshold": a.thr,
            "clusters": [{"keep": lines[c[0]], "dups": [lines[j] for j in c[1:]]} for c in clusters if len(c) > 1],
        }, ensure_ascii=False, indent=2))
    else:
        with open(a.input + ".dedup", "w", encoding="utf-8") as f:
            for i in keep:
                f.write(lines[i] + "\n")
        print("[OK] %d -> %d 条（去重 %d），写入 %s.dedup"
              % (len(lines), len(keep), len(dropped), a.input))
        for j, k, s in dropped[:10]:
            print("  - cos=%.3f  %s" % (s, lines[j][:60]))
    print("[OK] 保留 %d / 删除 %d / 阈值 %.2f" % (len(keep), len(dropped), a.thr), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
