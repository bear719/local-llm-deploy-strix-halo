# 许可：CC0-1.0，公共领域贡献，无任何限制。
# -*- coding: utf-8 -*-
"""第三版抽取：修正「单个 Title Case 单词被当成标识符丢弃」的漏洞。
只接受在 bundle 中以完整字面量（可带首尾空白）出现的串，保证可安全整串替换。"""
import re, json, pathlib

SRC = pathlib.Path("/home/<user>/llama-qwen4exp-rocmfpx/tools/ui/src")
bundle = pathlib.Path("/home/<user>/llama-qwen4exp-rocmfpx/build-vk4/tools/ui/dist/_app/immutable/bundle.D2CaPqLt.js").read_text(encoding="utf-8")
have = set(json.load(open("dict.json", encoding="utf-8")))

def literal_forms(s):
    """返回 bundle 中真实存在的字面量内容（含可能的首尾空格）"""
    outs = []
    for cand in (s, " " + s, s + " ", " " + s + " "):
        for q in ('"', "'", "`"):
            if q + cand + q in bundle:
                outs.append(cand)
    return outs

def accept(s: str) -> bool:
    s = s.strip()
    if not s or len(s) > 60 or s in have:
        return False
    if not re.search(r"[A-Za-z]{3}", s):
        return False
    if re.search(r"(https?:|www\.|@|\.svelte|\.ts\b|^[/.])", s):
        return False
    # 允许多词，或单词 Title Case（Settings/Close/General 这类）
    if " " in s:
        return not re.fullmatch(r"[a-z0-9_\-\./]+", s)
    return bool(re.fullmatch(r"[A-Z][A-Za-z]{2,24}", s))

cands = {}
for f in SRC.rglob("*"):
    if f.suffix not in (".svelte", ".ts"):
        continue
    txt = f.read_text(encoding="utf-8", errors="ignore")
    for m in re.finditer(r'(?:placeholder|title|aria-label|alt|tooltip|label)\s*[=:]\s*["\']([^"\'{}]{2,60})["\']', txt):
        s = m.group(1).strip()
        if accept(s):
            cands.setdefault(s, f.name)
    for m in re.finditer(r">([^<>{}]{2,60})<", txt):
        s = " ".join(m.group(1).split())
        if accept(s):
            cands.setdefault(s, f.name)
    for m in re.finditer(r"([\"'`])([^\"'`\\\n{}]{3,60})\1", txt):
        s = m.group(2).strip()
        if accept(s):
            cands.setdefault(s, f.name)

new = {}
for s in cands:
    if literal_forms(s):
        new[s] = cands[s]
json.dump(new, open("strings_src3.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"候选 {len(cands)}，新增 {len(new)}")
print(" / ".join(list(new)[:60]))
