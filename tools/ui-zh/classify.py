# 许可：CC0-1.0，公共领域贡献，无任何限制。
# -*- coding: utf-8 -*-
"""第二步：对 bundle 中每个字符串字面量做分类
A) exact  —— 整串（去首尾空白后）就是词条 → 直接查表替换
B) prose  —— 整串未命中，但内部含词条（原先会产出中英混排）→ 整串送模型翻译
C) skip   —— 其余一律不碰（代码/类名/路径/键名）
产出 todo_lits.json（待模型翻译的字面量）与 plan.json（替换计划骨架）
"""
import json, re, pathlib

lits = json.load(open("/tmp/lits_orig.json", encoding="utf-8"))
dic  = json.load(open("dict.json", encoding="utf-8"))
keys = sorted(dic, key=len, reverse=True)

CODE_HINT = re.compile(r"(=>|function\s*\(|^\s*[/.]{0,2}[a-z0-9_\-/\.]+\.(js|ts|json|css|png|svg|woff2?)$|^#|^--[a-z])")
def prose_like(s: str) -> bool:
    if len(s) > 1500:
        return False
    if CODE_HINT.search(s):
        return False
    words = re.findall(r"[A-Za-z]{2,}", s)
    return len(words) >= 2

def strip_tags(s):
    return re.sub(r"<[^>]*>", "", re.sub(r"\$\{[^}]*\}", "", s))

plan, todo = [], []
for idx, it in enumerate(lits):
    val = it.get("val")
    if not isinstance(val, str) or not val.strip():
        continue
    core = val.strip()
    norm = " ".join(val.split())
    if core in dic or norm in dic:
        plan.append({"i": idx, "mode": "exact", "key": core if core in dic else norm})
        continue
    # 含词条但非整串 → 整串翻译（要求词条覆盖率 ≥20%，避免长代码串误判）
    cov = sum(len(k) for k in keys if len(k) >= 4 and k in val)
    if prose_like(val) and cov / max(len(val), 1) >= 0.2:
        plan.append({"i": idx, "mode": "prose"})
        todo.append({"i": idx, "text": val})
    else:
        plan.append({"i": idx, "mode": "skip"})

json.dump(plan, open("plan.json", "w", encoding="utf-8"))
json.dump(todo, open("todo_lits.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
from collections import Counter
c = Counter(p["mode"] for p in plan)
print(dict(c), "总字面量", len(lits))
