# 许可：CC0-1.0，公共领域贡献，无任何限制。
# -*- coding: utf-8 -*-
"""重建 bundle（第三版）：
1) 整串命中词条 → 整串替换（UTF-16 码元偏移，避免代理对被错位）
2) HTML 模板字面量 → 只在「标签之间的文本节点」做**整节点**等值替换（绝不子串替换，杜绝中英混排）
3) 文本节点里未命中的英文散文 → 收集到 untranslated.json 供下一步补译
"""
import json, re, shutil, pathlib

SRC = pathlib.Path("/home/<user>/llama-qwen4exp-rocmfpx/build-vk4/tools/ui/dist")
DST = pathlib.Path("/home/<user>/llama-ui-zh")
REL = "_app/immutable/bundle.D2CaPqLt.js"

lits = json.load(open("/tmp/lits_orig.json", encoding="utf-8"))
dic = json.load(open("dict.json", encoding="utf-8"))
lits_zh = json.load(open("dict_lits.json", encoding="utf-8"))
TAGSPLIT = re.compile(r"(<[^>]*>)")

def is_en_prose(s: str) -> bool:
    s = s.strip()
    if len(s) < 3 or len(s) > 200:
        return False
    if not re.search(r"[A-Za-z]{3}", s):
        return False
    if re.search(r"[{}<>;=\\]", s):
        return False
    words = re.findall(r"[A-Za-z][A-Za-z’'\-]*", s)
    if len(words) < 2:
        return False
    return bool(set(w.lower() for w in words) & {"the","to","or","and","of","in","for","your","you","a","is","are","not","with","when","this","that","will","can","it","be","all","if","has","have","by","on","from","as","at"})

def translate_html(val: str):
    """按文本节点做等值替换；返回 (新值, 未命中文本节点列表)"""
    parts = TAGSPLIT.split(val)
    miss = []
    for i, p in enumerate(parts):
        if p.startswith("<") and p.endswith(">"):
            continue
        core = p.strip()
        if not core:
            continue
        if core in dic:
            lead = p[:len(p) - len(p.lstrip())]
            trail = p[len(p.rstrip()):]
            parts[i] = lead + dic[core] + trail
        elif is_en_prose(core):
            miss.append(core)
    return "".join(parts), miss

def main():
    if DST.exists():
        shutil.rmtree(DST)
    shutil.copytree(SRC, DST)
    idx_html = DST / "index.html"
    idx_html.write_text(idx_html.read_text(encoding="utf-8").replace('<html lang="en">', '<html lang="zh-CN">'), encoding="utf-8")
    mf = DST / "manifest.webmanifest"
    if mf.exists():
        m = json.load(open(mf, encoding="utf-8"))
        m.update({"lang": "zh-CN", "description": "由 llama.cpp 驱动的本地 AI 对话界面（汉化版）"})
        json.dump(m, open(mf, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))

    b16 = (DST / REL).read_text(encoding="utf-8").encode("utf-16-le")
    edits, miss_all, stat = [], [], {"exact": 0, "whole": 0, "html": 0, "skip": 0}
    for li, it in enumerate(lits):
        val, raw, kind = it.get("val"), it["raw"], it["kind"]
        if not isinstance(val, str) or not val.strip():
            continue
        core, norm = val.strip(), " ".join(val.split())
        new_val = None
        if core in dic or norm in dic:
            key = core if core in dic else norm
            lead = val[:len(val) - len(val.lstrip())] if core is val.strip() else ""
            new_val = lead + dic[key] + val[len(val.rstrip()):]
            stat["exact"] += 1
        else:
            cand = lits_zh.get(str(li))
            if cand and sorted(TAGSPLIT.findall(val)) == sorted(TAGSPLIT.findall(cand)):
                new_val = cand
                stat["whole"] += 1
            else:
                nv, miss = translate_html(val)
                if nv != val:
                    new_val = nv
                    stat["html"] += 1
                miss_all.extend(miss)
        if new_val is None or new_val == val:
            stat["skip"] += 1
            continue
        if kind == "lit":
            q = raw[0]
            body = json.dumps(new_val, ensure_ascii=False)
            if q == "'":
                body = "'" + new_val.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n").replace("\t", "\\t") + "'"
        else:
            body = new_val.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")
        edits.append((it["start"] * 2, it["end"] * 2, body.encode("utf-16-le")))

    for s, e, body in sorted(edits, key=lambda x: x[0], reverse=True):
        b16 = b16[:s] + body + b16[e:]
    (DST / REL).write_bytes(b16.decode("utf-16-le").encode("utf-8"))
    uniq = sorted(set(miss_all))
    json.dump(uniq, open("untranslated.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("统计", stat, "| 未命中文本节点(去重)", len(uniq))

if __name__ == "__main__":
    main()
