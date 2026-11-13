# 许可：CC0-1.0，公共领域贡献，无任何限制。
# -*- coding: utf-8 -*-
"""重建 bundle（第四版，最终方案）
思路：任何字面量只做两种处理，绝不做子串替换
  A) 整串命中词条 → 整串替换
  B) 含 HTML 标签 / ${} 插值 → 按「标签、插值」切分，**逐段**翻译文本段（段级词表 segments.json），标签与插值原样保留
未命中的英文文本段收集到 segments_todo.json，供补译后再次运行。
"""
import json, re, shutil, pathlib

SRC = pathlib.Path("/home/<user>/llama-qwen4exp-rocmfpx/build-vk4/tools/ui/dist")
DST = pathlib.Path("/home/<user>/llama-ui-zh")
REL = "_app/immutable/bundle.D2CaPqLt.js"

lits = json.load(open("/tmp/lits_orig.json", encoding="utf-8"))
dic = json.load(open("dict.json", encoding="utf-8"))
SEG_EXTRA = json.load(open("segments.json", encoding="utf-8")) if pathlib.Path("segments.json").exists() else {}

SPLIT = re.compile(r"(<[^>]*>|\$\{[^}]*\})")

def is_prose(s: str) -> bool:
    """判定是否为可翻译的界面自然语言（严格白名单，避免误伤代码片段）"""
    if len(s) < 4 or len(s) > 200:
        return False
    if not re.fullmatch(r"""[A-Za-z][A-Za-z0-9 ,.'’"@;*\-:!?%&/+()]*""", s):
        return False
    if "--" in s or "//" in s:
        return False
    words = re.findall(r"[A-Za-z][A-Za-z’'\-]*", s)
    if len(words) < 2:
        return False
    stops = {"the","to","or","and","of","in","for","your","you","a","is","are","not","with","when",
             "this","that","will","can","it","be","all","if","has","have","by","on","from","as","at",
             "use","using","used","may","should","must","do","does","was","were","them","they","its"}
    return bool(set(w.lower() for w in words) & stops)


def main():
    if DST.exists():
        shutil.rmtree(DST)
    shutil.copytree(SRC, DST)
    ih = DST / "index.html"
    ih.write_text(ih.read_text(encoding="utf-8").replace('<html lang="en">', '<html lang="zh-CN">'), encoding="utf-8")
    mf = DST / "manifest.webmanifest"
    if mf.exists():
        m = json.load(open(mf, encoding="utf-8"))
        m.update({"lang": "zh-CN", "description": "由 llama.cpp 驱动的本地 AI 对话界面（汉化版）"})
        json.dump(m, open(mf, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))

    SEG = {**{k: v for k, v in dic.items()}, **SEG_EXTRA}   # 段级词表 = 整串词表 + 段专用词表
    SEG = {**{k: v for k, v in dic.items()}, **SEG_EXTRA}   # 段级词表 = 整串词表 + 段专用词表
    b16 = (DST / REL).read_text(encoding="utf-8").encode("utf-16-le")
    edits, todo = [], {}
    stat = {"exact": 0, "seg": 0, "skip": 0}
    for it in lits:
        val = it.get("val")
        if not isinstance(val, str) or not val.strip():
            continue
        core, norm = val.strip(), " ".join(val.split())
        parts = SPLIT.split(val)
        has_markup = len(parts) > 1
        if core in dic or norm in dic:
            key = core if core in dic else norm
            lead = val[:len(val) - len(val.lstrip())] if core == val.strip() else ""
            new_val = lead + dic[key] + val[len(val.rstrip()):]
            stat["exact"] += 1
        elif has_markup:
            changed = False
            for i, p in enumerate(parts):
                if i % 2 == 1:            # 标签或插值，保持原样
                    continue
                s = p.strip()
                if not s:
                    continue
                if s in SEG:
                    lead = p[:len(p) - len(p.lstrip())]
                    trail = p[len(p.rstrip()):]
                    parts[i] = lead + SEG[s] + trail
                    changed = True
                elif is_prose(s):
                    todo[s] = todo.get(s, 0) + 1
            new_val = "".join(parts) if changed else None
            if changed:
                stat["seg"] += 1
        else:
            new_val = None
        if not new_val or new_val == val:
            stat["skip"] += 1
            continue
        if it["kind"] == "lit":
            q = it["raw"][0]
            body = json.dumps(new_val, ensure_ascii=False)
            if q == "'":
                body = "'" + new_val.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n").replace("\t", "\\t") + "'"
        else:
            body = new_val.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")
        edits.append((it["start"] * 2, it["end"] * 2, body.encode("utf-16-le")))

    for s, e, body in sorted(edits, key=lambda x: x[0], reverse=True):
        b16 = b16[:s] + body + b16[e:]
    (DST / REL).write_bytes(b16.decode("utf-16-le").encode("utf-8"))
    json.dump(sorted(todo), open("segments_todo.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("统计", stat, "| 待译文本段", len(todo))

if __name__ == "__main__":
    main()
