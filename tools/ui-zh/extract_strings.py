# 许可：CC0-1.0，公共领域贡献，无任何限制。
# -*- coding: utf-8 -*-
"""从 llama.cpp WebUI 源码中抽取面向用户的英文文案，并与已编译 bundle 求交集。
只保留「在 bundle 中能按字面匹配到」的串，保证后续替换有效且无死条目。"""
import re, json, sys, pathlib

SRC = pathlib.Path("/home/<user>/llama-qwen4exp-rocmfpx/tools/ui/src")
BUNDLE = pathlib.Path("/home/<user>/llama-qwen4exp-rocmfpx/build-vk4/tools/ui/dist/_app/immutable/bundle.D2CaPqLt.js")

bundle = BUNDLE.read_text(encoding="utf-8", errors="ignore")

def looks_en(s: str) -> bool:
    s = s.strip()
    if len(s) < 2 or len(s) > 120:
        return False
    if not re.search(r"[A-Za-z]{3}", s):
        return False
    # 纯标识符/路径/类名/URL 排除
    if re.fullmatch(r"[A-Za-z0-9_.\-/:]+", s):
        return False
    if re.search(r"(https?:|www\.|@|\.svelte|\.ts\b|/[a-z]+/)", s):
        return False
    if re.search(r"^[a-z]", s):          # 小写开头：多为 key/类名/技术串
        return False
    # 至少含一个空格，或短单词标签
    return (" " in s) or (len(s.split()) == 1 and s[0].isupper() and len(s) <= 24)

cands = {}

ATTR = r'(?:placeholder|title|aria-label|alt|label|tooltip|text|description)\s*=\s*"([^"{}]{2,120})"'

for f in SRC.rglob("*"):
    if f.suffix not in (".svelte", ".ts") or "node_modules" in str(f):
        continue
    try:
        txt = f.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        continue
    # 1) 属性类
    for m in re.finditer(ATTR, txt):
        s = m.group(1).strip()
        if looks_en(s):
            cands.setdefault(s, set()).add(f.name)
    # 2) 文本节点：>...< 之间
    for m in re.finditer(r">([^<>{}]{2,120})<", txt):
        s = " ".join(m.group(1).split())
        if looks_en(s):
            cands.setdefault(s, set()).add(f.name)
    # 3) TS/Svelte 中的字符串字面量（toast/title/message/错误提示等）
    for m in re.finditer(r'"([^"\\\n{}]{4,120})"', txt):
        s = m.group(1).strip()
        if looks_en(s) and (s.endswith((".", "!", "?", "...")) or s[0].isupper()):
            cands.setdefault(s, set()).add(f.name)
    for m in re.finditer(r"'([^'\\\n{}]{4,120})'", txt):
        s = m.group(1).strip()
        if looks_en(s) and (s.endswith((".", "!", "?", "...")) or s[0].isupper()):
            cands.setdefault(s, set()).add(f.name)

# 与 bundle 求交集（bundle 中的换行/转义差异：尝试原文与 HTML 实体两种）
def in_bundle(s):
    if s in bundle:
        return True
    esc = s.replace("'", "&#39;").replace('"', "&quot;")
    return esc in bundle

hit = {k: sorted(v) for k, v in cands.items() if in_bundle(k)}
print(f"源码候选 {len(cands)} 条，bundle 命中 {len(hit)} 条")
out = pathlib.Path("strings_src.json")
out.write_text(json.dumps(hit, ensure_ascii=False, indent=1), encoding="utf-8")
for k in sorted(hit)[:25]:
    print("  ", k)
