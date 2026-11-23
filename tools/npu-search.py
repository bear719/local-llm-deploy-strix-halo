#!/usr/bin/env python3
# 许可：CC0-1.0，公共领域贡献，无任何限制。
# -*- coding: utf-8 -*-
"""
本机文档库混合检索（向量 + BM25 + RRF 融合 + MMR 去重）

为什么需要它（2026-11-23 立项，见 `2026-11-23-提升本地Qwen能力方案清单.md` C1）：
  原 `npu-sidecar.py search` 只有单塔向量召回，两个已知缺陷：
    ① 专有名词/参数名/文件名类查询失准 —— 向量对 `--cache-ram`、`bf16`、`IQ1_S`
       这类字面串不敏感，而 BM25 恰好擅长；
    ② 同一文档相邻块在向量空间近乎重合，top-k 常被一篇文档占满。
  本脚本用「向量 + BM25(bigram) 双路召回 → RRF 融合 → MMR 去重」解决这两点。
  全程 CPU + NPU，不占 iGPU 显存，不影响 8080 decode。

中文切词策略：不引入 jieba 依赖，用 **CJK 二元组（bigram）**。
  CJK 无空格分词，bigram 是信息检索里的标准无监督做法，
  对「内镜」「吻合口」「淋巴结」这类固定搭配召回率高于单字。

用法：
  python3 tools/npu-search.py "cache-ram 上限"                 # 默认 top8
  python3 tools/npu-search.py "Child-Pugh" --topk 5 --full
  python3 tools/npu-search.py "arbiter 显存" --index idx/all.json --json
  python3 tools/npu-search.py "MTP 接受率" --bm25-only           # 跳向量，最快
  python3 tools/npu-search.py "npu" --source "*.md"             # 来源过滤
"""

import argparse
import glob as globmod
import importlib.util
import json
import math
import os
import pickle
import re
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

_spec = importlib.util.spec_from_file_location("npu_sidecar", os.path.join(HERE, "npu-sidecar.py"))
_sidecar = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_sidecar)
embed_texts = _sidecar.embed_texts

# BM25 参数（Lucene 常用取值）
K1 = 1.2
B = 0.75
# RRF 平滑常数（原论文 60）
RRF_K = 60


# ---------------------------------------------------------------- 切词

_ASCII = re.compile(r"[a-z0-9][a-z0-9_.\-:]*")
_CJK = re.compile(r"[\u4e00-\u9fff]+")


def tokenize(s):
    """英文/数字保留整词，中文切 bigram。返回 token 列表（保留重复，供词频统计）"""
    s = s.lower()
    out = _ASCII.findall(s)
    for seg in _CJK.findall(s):
        n = len(seg)
        if n == 1:
            out.append(seg)
        else:
            out.extend(seg[i:i + 2] for i in range(n - 1))
    return out


# ---------------------------------------------------------------- 加载

def load_index(path):
    """返回 (chunks, vectors)。兼容 dict 与 list 两种布局"""
    with open(path, "r", encoding="utf-8") as f:
        d = json.load(f)
    if isinstance(d, dict):
        chunks = d.get("chunks") or []
        vecs = d.get("vectors") or []
        if not chunks and d.get("texts"):
            chunks = [{"source": d.get("source", path), "title": "", "text": t}
                      for t in d["texts"]]
        return chunks, vecs
    return d, [r["vector"] for r in d]


def build_bm25(chunks, index_path, cache_path):
    """构建（或复用缓存）倒排表。返回 (df, doc_len, avgdl, postings, N)

    ★ 缓存失效判据用**索引文件本身的 mtime**，不是 cache 名反推
      （`x.json.bm25.pkl`.rsplit 会得到 `x.json.bm25`，路径不存在 → 崩）。
    """
    if cache_path and os.path.exists(cache_path) and os.path.exists(index_path):
        if os.path.getmtime(cache_path) >= os.path.getmtime(index_path):
            try:
                with open(cache_path, "rb") as f:
                    return pickle.load(f)
            except Exception:
                pass

    tf = []           # 每块的 Counter（用 dict）
    doc_len = []
    for c in chunks:
        toks = tokenize(c.get("text", ""))
        cnt = defaultdict(int)
        for t in toks:
            cnt[t] += 1
        tf.append(dict(cnt))
        doc_len.append(len(toks))

    df = defaultdict(int)
    for cnt in tf:
        for t in cnt:
            df[t] += 1

    postings = defaultdict(list)  # token -> [(doc_idx, term_freq)]
    for i, cnt in enumerate(tf):
        for t, v in cnt.items():
            postings[t].append((i, v))

    data = (dict(df), doc_len, (sum(doc_len) / max(len(doc_len), 1)), dict(postings), len(chunks))
    if cache_path:
        try:
            with open(cache_path, "wb") as f:
                pickle.dump(data, f, protocol=4)
        except Exception:
            pass
    return data


def bm25_rank(query, bm, topn):
    df, doc_len, avgdl, postings, N = bm
    q = set(tokenize(query))
    if not q:
        return []
    scores = defaultdict(float)
    for t in q:
        plist = postings.get(t)
        if not plist:
            continue
        n_t = df.get(t, 0)
        idf = math.log(1 + (N - n_t + 0.5) / (n_t + 0.5))
        for i, f in plist:
            dl = doc_len[i] or 1
            denom = f + K1 * (1 - B + B * dl / avgdl)
            scores[i] += idf * (f * (K1 + 1)) / denom
    return sorted(scores.items(), key=lambda x: -x[1])[:topn]


# ---------------------------------------------------------------- 融合

def cosine(a, b):
    s = 0.0
    na = nb = 0.0
    for x, y in zip(a, b):
        s += x * y
        na += x * x
        nb += y * y
    if na <= 0 or nb <= 0:
        return 0.0
    return s / math.sqrt(na * nb)


def rrf(rank_lists, k=RRF_K):
    """倒数排名融合：score = Σ 1/(k + rank)"""
    agg = defaultdict(float)
    for lst in rank_lists:
        for rank, idx in enumerate(lst, start=1):
            agg[idx] += 1.0 / (k + rank)
    return sorted(agg.items(), key=lambda x: -x[1])


def mmr(order, vectors, topk, lam=0.75):
    """最大边际相关去重：λ 越大越偏相关性，越小越偏多样性"""
    picked, cand = [], list(order)
    while cand and len(picked) < topk:
        best, best_i = -1e9, None
        for pos, (idx, _) in enumerate(cand):
            rel = 1.0 / (1 + pos)          # 用融合后的排名当相关性
            div = 0.0
            if picked:
                div = max(cosine(vectors[idx], vectors[p]) for p in picked)
            val = lam * rel - (1 - lam) * div
            if val > best:
                best, best_i = val, pos
        picked.append(cand.pop(best_i)[0])
    return picked


# ---------------------------------------------------------------- 主流程

def main():
    ap = argparse.ArgumentParser(description="本机文档库混合检索")
    ap.add_argument("query")
    ap.add_argument("--index", action="append", default=None,
                    help="索引文件，可重复；默认自动找 idx/all.json，否则 root+publish")
    ap.add_argument("--topk", type=int, default=8)
    ap.add_argument("--candidates", type=int, default=50, help="每路召回条数")
    ap.add_argument("--bm25-only", action="store_true", help="跳过向量召回（NPU 忙时用）")
    ap.add_argument("--vec-only", action="store_true")
    ap.add_argument("--lam", type=float, default=0.75, help="MMR 相关性权重")
    ap.add_argument("--source", default=None, help="来源 glob 过滤，如 'publish/*'")
    ap.add_argument("--full", action="store_true", help="输出完整块而非摘要")
    ap.add_argument("--json", action="store_true", help="JSON 输出")
    ap.add_argument("--no-cache", action="store_true", help="不读写 BM25 缓存")
    a = ap.parse_args()

    idx_paths = a.index
    if not idx_paths:
        allp = os.path.join(HERE, "..", "idx", "all.json")
        if os.path.exists(allp):
            idx_paths = [allp]
        else:
            idx_paths = []
            for n in ("root.json", "publish.json"):
                p = os.path.join(HERE, "..", "idx", n)
                if os.path.exists(p):
                    idx_paths.append(p)
    if not idx_paths:
        print("[ERROR] 找不到索引文件 -> 先跑 tools/npu-reindex.sh", file=sys.stderr)
        return 2

    chunks, vectors = [], []
    for p in idx_paths:
        c, v = load_index(p)
        chunks.extend(c)
        vectors.extend(v)
    if len(vectors) != len(chunks):
        print("[ERROR] 索引块数与向量数不一致 (%d vs %d) -> 重建索引"
              % (len(chunks), len(vectors)), file=sys.stderr)
        return 2

    # 来源过滤
    if a.source:
        keep = [i for i, c in enumerate(chunks)
                if globmod.fnmatch.fnmatch(c.get("source", ""), a.source)]
        chunks = [chunks[i] for i in keep]
        vectors = [vectors[i] for i in keep]

    # ★ source 过滤后 chunk 下标会重排，缓存里的 posting 索引不再对应当前列表 -> 禁用缓存
    cache = None if (a.no_cache or a.source) else os.path.abspath(idx_paths[0]) + ".bm25.pkl"
    bm = build_bm25(chunks, os.path.abspath(idx_paths[0]), cache)

    rank_lists = []
    bm_hits = bm25_rank(a.query, bm, a.candidates)
    if not a.vec_only:
        rank_lists.append([i for i, _ in bm_hits])

    vec_hits = []
    if not a.bm25_only:
        try:
            qv, _ = embed_texts([a.query])
            qv = qv[0]
            scored = [(cosine(qv, v), i) for i, v in enumerate(vectors)]
            scored.sort(key=lambda x: -x[0])
            vec_hits = scored[: a.candidates]
            rank_lists.append([i for _, i in vec_hits])
        except Exception as e:
            print("[WARN] 向量召回失败（%s）-> 退化为 BM25-only" % e, file=sys.stderr)

    if not rank_lists:
        print("[ERROR] 两路召回均失败", file=sys.stderr)
        return 2

    fused = rrf(rank_lists)
    order = mmr(fused, vectors, max(a.topk, 1), a.lam)

    bm_map = {i: s for i, s in bm_hits}
    vec_map = {i: s for s, i in vec_hits}
    bm_rank = {i: r for r, (i, _) in enumerate(bm_hits, 1)}
    vec_rank = {i: r for r, (_, i) in enumerate(vec_hits, 1)}

    results = []
    for idx in order:
        c = chunks[idx]
        results.append({
            "score": round(dict(fused).get(idx, 0.0), 6),
            "source": c.get("source", ""),
            "line": c.get("line"),
            "title": c.get("title", ""),
            "bm25_rank": bm_rank.get(idx),
            "vec_rank": vec_rank.get(idx),
            "bm25": round(bm_map.get(idx, 0.0), 3),
            "cos": round(vec_map.get(idx, 0.0), 4),
            "text": c.get("text", ""),
        })

    if a.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return 0

    print("查询: %s" % a.query)
    print("索引: %s | %d 块 | 融合=%s"
          % (", ".join(os.path.basename(p) for p in idx_paths), len(chunks),
             "+".join(["bm25"] * (not a.vec_only) + ["vec"] * (not a.bm25_only))))
    print("-" * 72)
    for n, r in enumerate(results, 1):
        loc = "%s:%s" % (r["source"], r["line"] if r["line"] else "?")
        print("%d. [%.5f] %s" % (n, r["score"], loc))
        if r["title"]:
            print("   § %s" % r["title"][:80])
        print("   bm25#%-3s cos=%-7s" % (r["bm25_rank"] or "-", r["cos"]))
        txt = r["text"] if a.full else r["text"][:220].replace("\n", " ")
        for ln in txt.split("\n"):
            print("   " + ln)
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
