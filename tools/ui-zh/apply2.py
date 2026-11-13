# 许可：CC0-1.0，公共领域贡献，无任何限制。
# -*- coding: utf-8 -*-
"""第三步：按 plan 重建 bundle（字面量级替换，杜绝中英混排）
- exact：整串查表
- prose：整串用模型译文，先做结构校验（标签/插值/换行/制表符），不合格则退回「只在标签间文本层查表」
"""
import json, re, shutil, pathlib, html

SRC = pathlib.Path("/home/<user>/llama-qwen4exp-rocmfpx/build-vk4/tools/ui/dist")
DST = pathlib.Path("/home/<user>/llama-ui-zh")
BUNDLE_REL = "_app/immutable/bundle.D2CaPqLt.js"

lits = json.load(open("/tmp/lits_orig.json", encoding="utf-8"))
plan = json.load(open("plan.json", encoding="utf-8"))
dic = json.load(open("dict.json", encoding="utf-8"))
lits_zh = json.load(open("dict_lits.json", encoding="utf-8"))
keys = sorted(dic, key=len, reverse=True)

TAG = re.compile(r"<[^>]*>")
PH = re.compile(r"\$\{[^}]*\}")

def esc_tpl(cooked: str) -> str:
    out = cooked.replace("\\", "\\\\").replace("`", "\\`")
    out = out.replace("${", "\\${")
    return out

def fallback_text_nodes(val: str) -> str:
    """只在 HTML 文本节点（> 与 < 之间）内做词条替换，标签/属性不动。"""
    parts = re.split(r"(<[^>]*>)", val)
    for i, p in enumerate(parts):
        if p.startswith("<") and p.endswith(">"):
            continue
        s = p
        for k in keys:
            if k in s:
                s = s.replace(k, dic[k])
        parts[i] = s
    return "".join(parts)

TRAD = set("們個這說為對開關編輯訊應與來時間樣麼點選單頁檔數據網路設定確認載入儲存檢視刪處裡從會後發現實體變數")
def ok_structure(orig: str, new: str) -> bool:
    """结构校验：HTML 标签多重集与 ${} 插值序列必须一致；禁止繁体字。"""
    return (sorted(TAG.findall(orig)) == sorted(TAG.findall(new))
            and PH.findall(orig) == PH.findall(new)
            and not (TRAD & set(new)))

def main():
    if DST.exists():
        shutil.rmtree(DST)
    shutil.copytree(SRC, DST)
    idx_html = DST / "index.html"
    t = idx_html.read_text(encoding="utf-8").replace('<html lang="en">', '<html lang="zh-CN">')
    idx_html.write_text(t, encoding="utf-8")
    mf = DST / "manifest.webmanifest"
    if mf.exists():
        m = json.load(open(mf, encoding="utf-8"))
        m.update({"lang": "zh-CN", "description": "由 llama.cpp 驱动的本地 AI 对话界面（汉化版）"})
        json.dump(m, open(mf, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))

    # 以 UTF-16LE 字节为单位编辑：acorn 偏移是 UTF-16 码元，Python 字符下标与之不等价
    raw_bytes = (DST / BUNDLE_REL).read_bytes()
    b16 = raw_bytes.decode("utf-8").encode("utf-16-le")
    edits, stat = [], {"exact": 0, "prose": 0, "fallback": 0, "skip": 0}
    for p in plan:
        it = lits[p["i"]]
        val, raw, kind = it.get("val"), it["raw"], it["kind"]
        if p["mode"] == "skip" or not isinstance(val, str) or not val.strip():
            stat["skip"] += 1
            continue
        core = val.strip()
        lead = val[:len(val) - len(val.lstrip())]
        trail = val[len(val.rstrip()):]
        if p["mode"] == "exact":
            key = p.get("key", core)
            new_val = lead + dic[key] + trail
            stat["exact"] += 1
        else:
            cand = lits_zh.get(str(p["i"]))
            if cand and ok_structure(val, cand):
                new_val = cand
                stat["prose"] += 1
            else:
                # 校验未通过：保持英文原文，绝不产出中英混排
                stat["fallback"] += 1
                continue
        if new_val == val:
            continue
        # 一致性自检：该偏移处应正好是原始字面量
        probe = b16[it["start"]*2: it["end"]*2].decode("utf-16-le")
        if probe != raw:
            stat["offset_mismatch"] = stat.get("offset_mismatch", 0) + 1
            continue
        # 一致性自检：该偏移处应正好是原始字面量
        probe = b16[it["start"]*2: it["end"]*2].decode("utf-16-le")
        if probe != raw:
            stat["offset_mismatch"] = stat.get("offset_mismatch", 0) + 1
            continue
        if kind == "lit":
            q = raw[0]
            body = json.dumps(new_val, ensure_ascii=False)
            if q == "'":
                body = "'" + new_val.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n").replace("\t", "\\t") + "'"
            edits.append((it["start"]*2, it["end"]*2, body.encode("utf-16-le")))
        else:
            edits.append((it["start"]*2, it["end"]*2, esc_tpl(new_val).encode("utf-16-le")))

    for s, e, body in sorted(edits, key=lambda x: x[0], reverse=True):
        b16 = b16[:s] + body + b16[e:]
    (DST / BUNDLE_REL).write_bytes(b16.decode("utf-16-le").encode("utf-8"))
    print("统计", stat, "改动字面量", len(edits))

if __name__ == "__main__":
    main()
