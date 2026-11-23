#!/usr/bin/env python3
# 许可：CC0-1.0，公共领域贡献，无任何限制。
# -*- coding: utf-8 -*-
"""
文档分块 + NPU 向量化建索引

规则（依据 2026-11-23 长度实验，见 `2026-11-23-NPU非推理用途.md` §1.1）：
  - 分块 800 字 / 重叠 100 字（embedding 在 4518 字内不报错，但语义会稀释）
  - 按 Markdown 标题先切节，节内再按窗口滑切；每块带来源与标题路径
  - 可选 --dedup 前置余弦去重（阈值 0.95），减少索引体积

输出：
  <out>.json      {"model","dim","chunks":[{id,source,title,text,vector}]}
  <out>.meta.json 建索引参数与耗时

用法：
  python3 npu-index.py docs/ --out idx/docs.json
  python3 npu-index.py . --glob "*.md" --out idx/root.json --dedup
  python3 npu-index.py a.md b.md --out idx/x.json
"""

import argparse
import glob as globmod
import hashlib
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import importlib.util

_p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "npu-sidecar.py")
_spec = importlib.util.spec_from_file_location("npu_sidecar", _p)
_sidecar = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_sidecar)

embed_texts = _sidecar.embed_texts
EMBED_MODEL = _sidecar.EMBED_MODEL

CHUNK = 800
OVERLAP = 100


def split_sections(text):
    """按 Markdown 标题切节，返回 [(标题路径, 正文, 起始行号)]

    起始行号为 1-based，供检索结果做「文件:行」精确定位（2026-11-23 新增）。
    """
    lines = text.splitlines()
    out, buf, path = [], [], []  # buf 元素为 (行号, 行文本)

    def flush():
        if buf:
            body = "\n".join(t for _, t in buf).strip()
            if body:
                out.append((" > ".join(path) if path else "", body, buf[0][0]))
            buf.clear()

    for i, ln in enumerate(lines, start=1):
        m = re.match(r"^(#{1,4})\s+(.*)$", ln)
        if m:
            flush()
            lvl = len(m.group(1))
            path[:] = path[: lvl - 1]
            path.append(m.group(2).strip())
        else:
            buf.append((i, ln))
    flush()
    return out


def window(text, size=CHUNK, step=None):
    """按窗口滑切，尽量在句末断开"""
    step = step or (size - OVERLAP)
    if len(text) <= size:
        return [text]
    chunks, i = [], 0
    while i < len(text):
        seg = text[i:i + size]
        if i + size < len(text):
            cut = max(seg.rfind("。"), seg.rfind("\n"), seg.rfind("；"), seg.rfind("！"), seg.rfind("？"))
            if cut > size * 0.6:
                seg = seg[: cut + 1]
        chunks.append(seg.strip())
        if len(seg) < step:
            break
        i += len(seg) if seg is not text else step
    return [c for c in chunks if c]


def collect(args):
    # ★ 坑：glob.glob("dir/*.md") 不递归；要扫子目录必须显式 **/*.md
    pattern_used = args.glob
    if args.recursive and not args.glob.startswith("**/"):
        pattern_used = "**/" + args.glob
    files = []
    for target in args.targets:
        if os.path.isdir(target):
            pattern = os.path.join(target, pattern_used)
            files.extend(sorted(globmod.glob(pattern, recursive=True)))
        else:
            files.extend(globmod.glob(target))
    seen, uniq = set(), []
    excl = list(getattr(args, "exclude", None) or [])
    for f in files:
        rp = os.path.realpath(f)
        rel = os.path.relpath(rp, os.getcwd())
        if excl and any(globmod.fnmatch.fnmatch(rel, pat) for pat in excl):
            continue
        if rp not in seen and os.path.isfile(rp):
            seen.add(rp)
            uniq.append(rp)
    return uniq


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("targets", nargs="+", help="目录或文件，可多个")
    ap.add_argument("--glob", default="*.md", help="目录下的匹配模式，默认 *.md（含子目录需用 **/*.md）")
    ap.add_argument("--recursive", action="store_true", help="目录递归：等价于把 --glob 自动补成 **/<模式>")
    ap.add_argument("--out", required=True)
    ap.add_argument("--chunk", type=int, default=CHUNK)
    ap.add_argument("--overlap", type=int, default=OVERLAP)
    ap.add_argument("--dedup", action="store_true", help="建索引前按全文 hash 去重（跨库副本消除）")
    ap.add_argument("--exclude", action="append", default=None,
                    help="路径 glob 排除，可重复，如 'publish/*' '.workbuddy/*'")
    ap.add_argument("--min-len", type=int, default=20, help="短于此长度的块丢弃")
    a = ap.parse_args()

    files = collect(a)
    if not files:
        print("[ERROR] 未找到匹配文件", file=sys.stderr)
        return 2

    t0 = time.time()
    chunks = []
    for f in files:
        try:
            with open(f, "r", encoding="utf-8") as fh:
                text = fh.read()
        except UnicodeDecodeError:
            print("[SKIP] 非 UTF-8: %s" % f, file=sys.stderr)
            continue
        rel = os.path.relpath(f, os.getcwd())
        for title, body, start_line in split_sections(text):
            for seg in window(body, a.chunk, a.chunk - a.overlap):
                if len(seg) < a.min_len:
                    continue
                cid = hashlib.md5((rel + "|" + title + "|" + seg).encode()).hexdigest()[:12]
                # 块在文件中的起始行：节内字符偏移换算成行偏移
                off = body.find(seg)
                line = start_line + (body[:off].count("\n") if off > 0 else 0)
                chunks.append({"id": cid, "source": rel, "title": title,
                               "line": line, "text": seg})

    print("[INFO] %d 文件 -> %d 块（%.1f 字/块均值）"
          % (len(files), len(chunks),
             sum(len(c["text"]) for c in chunks) / max(len(chunks), 1)), file=sys.stderr)

    if a.dedup and chunks:
        # ★ 全文 hash 去重（2026-11-23 改）：publish/ 是根目录文档的完整镜像，
        #   旧实现按前 200 字做 key，长文档分块后同一起点会被误删；
        #   改为全文 md5，只删「整块完全相同」的副本。先遍历到的路径优先保留
        #   （collect 按 targets 顺序 + 排序输出，所以根目录会排在 publish 前面）。
        seen, uniq = set(), []
        for c in chunks:
            k = hashlib.md5(c["text"].encode()).hexdigest()
            if k in seen:
                continue
            seen.add(k)
            uniq.append(c)
        print("[INFO] 全文去重 %d -> %d（删 %d 个副本）"
              % (len(chunks), len(uniq), len(chunks) - len(uniq)), file=sys.stderr)
        chunks = uniq

    vecs, dt = embed_texts([c["text"] for c in chunks])
    for c, v in zip(chunks, vecs):
        c["vector"] = v

    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    payload = {
        "model": EMBED_MODEL,
        "dim": len(vecs[0]) if vecs else 0,
        "chunk": a.chunk,
        "overlap": a.overlap,
        "files": len(files),
        "count": len(chunks),
        "chunks": chunks,
        "texts": [c["text"] for c in chunks],
        "vectors": vecs,
    }
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    meta = {
        "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "model": EMBED_MODEL, "dim": payload["dim"],
        "files": [os.path.relpath(f, os.getcwd()) for f in files],
        "chunks": len(chunks), "embed_s": round(dt, 2),
        "total_s": round(time.time() - t0, 2),
        "speed_chunks_per_s": round(len(chunks) / dt, 2) if dt else 0,
    }
    with open(a.out + ".meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print("[OK] %d 块 / 向量化 %.2fs（%.1f 块/s）/ 总 %.2fs -> %s"
          % (len(chunks), dt, meta["speed_chunks_per_s"], meta["total_s"], a.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
