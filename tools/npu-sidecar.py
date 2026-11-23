#!/usr/bin/env python3
# 许可：CC0-1.0，公共领域贡献，无任何限制。
# -*- coding: utf-8 -*-
"""
NPU 侧车（sidecar）工具集 —— XDNA2 / FastFlowLM / 端口 8219

定位：NPU 只做「短、无状态、可延迟、不要求判断力」的活。
     判断力型任务（judge / 质量评估）已实测否决，勿再迁移。

四个子命令：
  embed   <文本文件|->            向量化，输出 JSON（可 --out）
  search  <索引.jsonl> <查询>      语义检索 top-k（余弦）
  translate <文件|->              中英互译（自动判向，长文自动分段）
  extract  <schema.json> <文本>    按 JSON Schema 约束抽取/分类（xgrammar 强制格式）

通用约定：
  - 每条请求显式发 think:false / presence_penalty:0（flm 参数粘滞，跨客户端共享）
  - 结构化输出一律走 response_format=json_schema，不靠 prompt 求它
  - NPU 全局串行：并发无意义，脚本内一律顺序调用

依赖：仅标准库。
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.request

NPU = os.environ.get("NPU_URL", "http://127.0.0.1:8219")
EMBED_MODEL = os.environ.get("NPU_EMBED_MODEL", "embed-gemma:300m")
MT_MODEL = os.environ.get("NPU_MT_MODEL", "hy-mt2-flash:1.8b")
TIMEOUT = int(os.environ.get("NPU_TIMEOUT", "600"))


# ---------------- 基础调用 ----------------

def _post(path, payload, timeout=TIMEOUT):
    req = urllib.request.Request(
        NPU + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _read(path):
    if path == "-":
        return sys.stdin.read()
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def embed_texts(texts):
    """返回 (向量列表, 耗时秒)。NPU 逐条串行，batch 参数不提升吞吐。"""
    t0 = time.time()
    r = _post("/v1/embeddings", {"model": EMBED_MODEL, "input": texts})
    data = sorted(r["data"], key=lambda x: x.get("index", 0))
    return [d["embedding"] for d in data], time.time() - t0


def chat(prompt, model=MT_MODEL, schema=None, max_tokens=1024):
    """单次非流式对话；schema 非空时用 json_schema 约束解码。"""
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "think": False,
        "presence_penalty": 0,
        "temperature": 0,
    }
    if schema is not None:
        body["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "out", "schema": schema},
        }
    r = _post("/v1/chat/completions", body)
    return r["choices"][0]["message"]["content"], r.get("usage", {})


# ---------------- embed ----------------

def cmd_embed(a):
    texts = json.loads(_read(a.input)) if a.json_input else [
        ln.strip() for ln in _read(a.input).splitlines() if ln.strip()
    ]
    if not texts:
        print("[ERROR] 输入为空", file=sys.stderr)
        return 2
    vecs, dt = embed_texts(texts)
    out = {
        "model": EMBED_MODEL,
        "dim": len(vecs[0]) if vecs else 0,
        "count": len(vecs),
        "elapsed_s": round(dt, 3),
        "vectors": vecs,
        "texts": texts,
    }
    _emit(out, a.out)
    print("[OK] %d 条 / %.2fs / %.1f 条/s / dim=%d"
          % (len(vecs), dt, len(vecs) / dt if dt else 0, out["dim"]), file=sys.stderr)
    return 0


def cmd_search(a):
    """索引格式兼容两种：
       ① npu-index.py / npu-sidecar.py embed 产出的单文件 JSON（{"vectors":[[..]],"texts":[..]}）
       ② 每行一条的 jsonl（{"id":..,"text":..,"vector":[..]}）
    ★ 跨库检索用 --extra（可重复）：把 root.json 与 publish.json 一起打分，
      否则单库永远检索不到另一库的内容。
    """
    qvec, _ = embed_texts([a.query])
    qvec = qvec[0]

    def load_one(path):
        recs = []
        if path.endswith(".json"):
            with open(path, "r", encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict) and "vectors" in d:
                for i, v in enumerate(d["vectors"]):
                    recs.append({"id": d.get("ids", [str(i)])[i] if d.get("ids") else str(i),
                                 "source": (d.get("chunks") or [{}] * len(d["vectors"]))[i].get("source", path)
                                 if i < len(d.get("chunks") or []) else path,
                                 "text": d["texts"][i], "vector": v})
            elif isinstance(d, list):
                recs = d
        else:
            with open(path, "r", encoding="utf-8") as f:
                for ln in f:
                    ln = ln.strip()
                    if ln:
                        recs.append(json.loads(ln))
        return recs

    records = []
    for p in [a.index] + list(a.extra or []):
        records.extend(load_one(p))

    scored = []
    for rec in records:
        s = sum(x * y for x, y in zip(qvec, rec["vector"]))
        scored.append((s, rec))
    scored.sort(key=lambda x: -x[0])
    for s, rec in scored[: a.topk]:
        src = rec.get("source") or "-"
        print("%.4f\t%s\t%s\t%s" % (s, rec.get("id", "-"), src, rec.get("text", "")[:120]))
    return 0


# ---------------- translate ----------------

_CJK = re.compile(r"[\u4e00-\u9fff]")


def _split_long(text, limit=1200):
    """按句末标点切段，控制单段长度（NPU ctx 8192，但长段 TTFT 会明显变长）。"""
    parts = re.split(r"(?<=[。！？!?；;\n])", text)
    buf, out = "", []
    for p in parts:
        if len(buf) + len(p) > limit and buf:
            out.append(buf)
            buf = p
        else:
            buf += p
    if buf:
        out.append(buf)
    return out or [text]


def cmd_translate(a):
    text = _read(a.input)
    zh = len(_CJK.findall(text))
    to_en = a.to_en if a.to_en else (zh / max(len(text), 1) < 0.05)
    header = "Translate into English: " if to_en else "Translate into Chinese: "
    segs = _split_long(text)
    outs, t0 = [], time.time()
    for i, seg in enumerate(segs, 1):
        c, u = chat(header + seg, model=a.model, max_tokens=2048)
        outs.append(c.strip())
        if a.verbose:
            print("[%d/%d] %.2fs dec=%.0f" % (i, len(segs), time.time() - t0,
                                             u.get("decoding_speed_tps", 0)), file=sys.stderr)
    res = "\n".join(outs)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(res + "\n")
        print("[OK] %d 段 / %.2fs -> %s" % (len(segs), time.time() - t0, a.out), file=sys.stderr)
    else:
        print(res)
    return 0


# ---------------- extract ----------------

def cmd_extract(a):
    schema = json.loads(_read(a.schema))
    text = _read(a.input) if a.input != "-" else sys.stdin.read()
    prompt = (a.prompt + "\n\n" if a.prompt else "按 JSON Schema 抽取下列文本中的字段：\n\n") + text
    c, u = chat(prompt, model=a.model, schema=schema, max_tokens=a.max_tokens)
    try:
        obj = json.loads(c)
        print(json.dumps(obj, ensure_ascii=False, indent=2))
        if a.verbose:
            print("[OK] dec=%.0f t/s" % u.get("decoding_speed_tps", 0), file=sys.stderr)
        return 0
    except Exception as e:
        print("[ERROR] 输出非合法 JSON -> %s\n原文: %s" % (e, c[:200]), file=sys.stderr)
        return 1


def _emit(obj, path):
    if path:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False)
    else:
        json.dump(obj, sys.stdout, ensure_ascii=False)


# ---------------- CLI ----------------

def main():
    ap = argparse.ArgumentParser(description="NPU 侧车工具集（8219）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("embed", help="向量化，输出 JSON")
    p.add_argument("input", help="文本文件，- 表示 stdin（每行一条）")
    p.add_argument("--json-input", action="store_true", help="输入是 JSON 字符串数组")
    p.add_argument("--out", help="输出 JSON 文件（默认 stdout）")
    p.set_defaults(func=cmd_embed)

    p = sub.add_parser("search", help="在 embed/index 产出的 JSON 或 jsonl 索引上做余弦检索")
    p.add_argument("index")
    p.add_argument("query")
    p.add_argument("--topk", type=int, default=5)
    p.add_argument("--extra", action="append", help="附加索引（可重复），用于跨库联合检索")
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("translate", help="中英互译（自动判向）")
    p.add_argument("input", help="文本文件，- 表示 stdin")
    p.add_argument("--to-en", action="store_true", help="强制译为英文")
    p.add_argument("--to-zh", dest="to_en", action="store_false", help="强制译为中文")
    p.add_argument("--model", default=MT_MODEL)
    p.add_argument("--out")
    p.add_argument("-v", "--verbose", action="store_true")
    p.set_defaults(func=cmd_translate, to_en=None)

    p = sub.add_parser("extract", help="按 JSON Schema 约束抽取")
    p.add_argument("schema", help="JSON Schema 文件")
    p.add_argument("input", help="文本文件，- 表示 stdin")
    p.add_argument("--prompt", help="自定义指令；缺省为通用抽取指令")
    p.add_argument("--model", default=MT_MODEL)
    p.add_argument("--max-tokens", type=int, default=512)
    p.add_argument("-v", "--verbose", action="store_true")
    p.set_defaults(func=cmd_extract)

    a = ap.parse_args()
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
