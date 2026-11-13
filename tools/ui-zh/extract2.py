# 许可：CC0-1.0，公共领域贡献，无任何限制。
# -*- coding: utf-8 -*-
"""第二版抽取：补抓「小写开头的句子片段」「单个单词标签」，但只保留在 bundle 中以
**完整字面量**（"..." / '...' / `...`）形式存在的串 —— 保证替换不会造成中英混排。"""
import re, json, pathlib

SRC = pathlib.Path("/home/<user>/llama-qwen4exp-rocmfpx/tools/ui/src")
BUNDLE = pathlib.Path("/home/<user>/llama-qwen4exp-rocmfpx/build-vk4/tools/ui/dist/_app/immutable/bundle.D2CaPqLt.js")
bundle = BUNDLE.read_text(encoding="utf-8")
have = set(json.load(open("dict.json", encoding="utf-8")))

def is_exact_literal(s: str) -> bool:
    if s in have:
        return False
    for q in ('"', "'", "`"):
        if (q + s + q) in bundle:
            return True
    return False

ATTR = r'(?:placeholder|title|aria-label|alt)\s*=\s*"([^"{}]{2,120})"'
cands = {}
for f in SRC.rglob("*"):
    if f.suffix not in (".svelte", ".ts"):
        continue
    txt = f.read_text(encoding="utf-8", errors="ignore")
    for m in re.finditer(ATTR, txt):
        s = m.group(1).strip()
        if s and re.search(r"[A-Za-z]{2}", s):
            cands.setdefault(s, f.name)
    for m in re.finditer(r">([^<>{}]{2,120})<", txt):
        s = " ".join(m.group(1).split())
        if s and re.search(r"[A-Za-z]{2}", s):
            cands.setdefault(s, f.name)
    # 源码里的短字面量（含小写片段），例如 ' or upload files to get started'
    for m in re.finditer(r"([\"'`])([^\"'`\\\n]{3,120})\1", txt):
        s = m.group(2).strip()
        if re.search(r"[A-Za-z]{3}", s) and not re.match(r"^[/.@#]", s) \
           and not re.fullmatch(r"[a-z0-9_\-]+", s):
            cands.setdefault(s, f.name)

new = {k: v for k, v in cands.items() if is_exact_literal(k)}
json.dump(new, open("strings_src2.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"候选 {len(cands)}，新增可整串替换 {len(new)}")
for k in list(new)[:30]:
    print("  ", repr(k))
