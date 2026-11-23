#!/usr/bin/env python3
# 许可：CC0-1.0，公共领域贡献，无任何限制。
# -*- coding: utf-8 -*-
"""
跨文档重复/矛盾排查（P0-2 的执行版）

做两件事：
  1. **近重复检测**：跨文件、同文件都算，用余弦找 cos >= 阈值 的段落对
     （不同文件的相同段落 = 结论被复制粘贴，应合并或交叉引用）
  2. **口径冲突检测**：抽取形如「关键词 + 数值 + 单位」的断言，
     同一关键词下出现多个不同数值 → 人工裁决谁过时

用法：
  python3 npu-dedup.py idx/root.json --cross --thr 0.95        # 跨文档近重复
  python3 npu-dedup.py idx/root.json --claims --out claims.md  # 口径冲突表
  python3 npu-dedup.py idx/root.json --all                     # 两者都跑

注意：--thr 0.95 只抓「几乎一模一样」的复制，0.90 起会有主题相近但不重复的假阳性。
"""

import argparse
import json
import math
import re
import sys
from collections import defaultdict


def load(path):
    with open(path, "r", encoding="utf-8") as f:
        d = json.load(f)
    vecs = d["vectors"] if "vectors" in d else [c["vector"] for c in d["chunks"]]
    chunks = d["chunks"] if "chunks" in d else [
        {"id": str(i), "source": "?", "title": "", "text": t} for i, t in enumerate(d["texts"])
    ]
    return chunks, vecs


def cos(x, y):
    s = sum(a * b for a, b in zip(x, y))
    nx = math.sqrt(sum(a * a for a in x)) or 1.0
    ny = math.sqrt(sum(b * b for b in y)) or 1.0
    return s / (nx * ny)


def norm(t):
    return re.sub(r"\s+", "", t)


# ---------------- 1. 近重复 ----------------

def find_dups(chunks, vecs, thr, cross_only):
    """先按指纹分组（前 80 字归一化），组内再算余弦，避免 O(n^2) 全量。"""
    buckets = defaultdict(list)
    for i, c in enumerate(chunks):
        buckets[norm(c["text"])[:80]].append(i)

    pairs = []
    for key, ids in buckets.items():
        if len(ids) < 2:
            continue
        for a in range(len(ids)):
            for b in range(a + 1, len(ids)):
                i, j = ids[a], ids[b]
                ci, cj = chunks[i], chunks[j]
                if cross_only and ci["source"] == cj["source"]:
                    continue
                s = cos(vecs[i], vecs[j])
                if s >= thr:
                    pairs.append((s, i, j))
    pairs.sort(key=lambda x: -x[0])
    return pairs


# ---------------- 2. 口径冲突 ----------------

# 只保留「有语义的指标名」：英文标识符或中文术语，排除列表编号（1. / 2.）与纯标点
_GOOD_NAME = re.compile(r"^(?:[A-Za-z][A-Za-z0-9_\-\. ]*|[\u4e00-\u9fff]{2,}[A-Za-z0-9_\-]*)")
# 关键词: 允许的中间分隔
CLAIM_PATTERNS = [
    # 指标 + 数值 + 单位
    (re.compile(r"([A-Za-z0-9_\u4e00-\u9fff][A-Za-z0-9_\-\.\u4e00-\u9fff ]{1,23}?)\s*[:：=＝]?\s*\**\s*(\d+(?:\.\d+)?)\s*(t/s|GB/s|GiB|GB|MiB|MB|W|ms|×)", re.I), "指标"),
]


def extract_claims(chunks):
    claims = defaultdict(list)  # 归一后的指标名 -> [(值, 来源, 摘要)]
    for c in chunks:
        text = c["text"]
        for pat, kind in CLAIM_PATTERNS:
            for m in pat.finditer(text):
                raw = m.group(1).strip().strip("*|` ")
                raw = re.split(r"[|`（(）)]", raw)[-1].strip(" -*：:，,")
                if not _GOOD_NAME.match(raw) or len(raw) < 2:
                    continue
                if re.fullmatch(r"\d+\.?", raw):
                    continue
                # 只保留最后一个「词」（去掉前面的数值与符号，避免 "pp4096 709–840" 这类串）
                name = re.split(r"[\s，,、；;/]+", raw)[-1].strip(" -*：:")
                if len(name) < 2 or re.fullmatch(r"[\d\.]+", name):
                    continue
                claims[(name.lower(), m.group(3).lower())].append(
                    (float(m.group(2)), c["source"],
                     text[max(0, m.start() - 20):m.end() + 20].replace("\n", " "))
                )
    return claims


def report_claims(claims, min_files=1):
    rows = []
    for (name, unit), items in claims.items():
        vals = {round(v, 4) for v, _, _ in items}
        srcs = {s for _, s, _ in items}
        if len(vals) >= 2 and len(srcs) >= min_files:
            rows.append((name, unit, sorted(vals), sorted(srcs), len(items)))
    rows.sort(key=lambda r: (-len(r[2]), r[0]))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("index", help="npu-index.py 产出的 JSON")
    ap.add_argument("--cross", action="store_true", help="跨文档近重复")
    ap.add_argument("--claims", action="store_true", help="口径冲突")
    ap.add_argument("--all", action="store_true", help="两者都跑")
    ap.add_argument("--thr", type=float, default=0.95)
    ap.add_argument("--topk", type=int, default=40)
    ap.add_argument("--out", help="把结果写成 Markdown")
    a = ap.parse_args()
    if not (a.cross or a.claims or a.all):
        a.all = True

    chunks, vecs = load(a.index)
    lines = ["# 跨文档重复与口径冲突排查", "", "> 索引：`%s`，%d 块" % (a.index, len(chunks)), ""]

    if a.cross or a.all:
        # 只做跨文件，同文件重复意义不大（窗口重叠所致）
        pairs = find_dups(chunks, vecs, a.thr, cross_only=True)
        lines += ["## 一、跨文档近重复（cos ≥ %.2f）" % a.thr, "",
                  "共 **%d** 对。" % len(pairs), ""]
        if pairs:
            lines += ["| cos | 来源 A | 来源 B | 重复内容 |", "|---:|---|---|---|"]
            for s, i, j in pairs[: a.topk]:
                lines.append("| %.3f | %s | %s | %s |" % (
                    s, chunks[i]["source"], chunks[j]["source"],
                    chunks[i]["text"][:60].replace("|", "/").replace("\n", " ")))
        else:
            lines.append("**无**：本库各文件之间没有近乎逐字复制的内容。")

        # 同文件内部：只报窗口重叠导致的正常重复之外的真重复
        own = find_dups(chunks, vecs, 0.995, cross_only=False)
        own = [(s, i, j) for s, i, j in own if chunks[i]["source"] == chunks[j]["source"]]
        lines += ["", "### 同文件内 cos ≥ 0.995 的块对：%d 对（窗口重叠通常会产生，可忽略）" % len(own)]

    if a.claims or a.all:
        claims = extract_claims(chunks)
        rows = report_claims(claims)
        lines += ["", "## 二、口径冲突（同一指标出现多个数值）", "",
                  "共 **%d** 组。" % len(rows), "",
                  "| 指标 | 单位 | 出现的值 | 涉及文件数 | 提及次数 |", "|---|---|---|---:|---:|"]
        for name, unit, vals, srcs, n in rows[: a.topk]:
            lines.append("| %s | %s | %s | %d | %d |" % (
                name, unit, " / ".join("%g" % v for v in vals[:6]), len(srcs), n))
        lines += ["", "> 说明：同名指标多值 **不一定是错误**（可能是不同量化档、不同版本、不同上下文）。",
                  "> 需要人工判断哪条已过时，然后在 `MEMORY.md` 里留唯一口径。"]

    text = "\n".join(lines) + "\n"
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text)
        print("[OK] -> %s" % a.out)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
