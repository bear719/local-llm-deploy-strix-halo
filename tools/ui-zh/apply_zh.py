# 许可：CC0-1.0，公共领域贡献，无任何限制。
# -*- coding: utf-8 -*-
"""把 dist 复制成中文版目录，并把英文 UI 文案替换为中文。
- 只做字符串字面量级替换，最长优先，避免子串互相覆盖
- 同时处理 HTML 实体转义变体
- 输出每条命中次数，0 命中会列出（说明该串在编译产物中被拆分/改写）
"""
import json, re, shutil, sys, pathlib, html

SRC = pathlib.Path("/home/<user>/llama-qwen4exp-rocmfpx/build-vk4/tools/ui/dist")
DST = pathlib.Path("/home/<user>/llama-ui-zh")
DICT = pathlib.Path("dict.json")

# bundle 里未加前缀的纯 HTML 实体文本需要转义后匹配
def variants(s):
    out = [s]
    if "'" in s or '"' in s or "&" in s:
        out.append(html.escape(s, quote=False).replace("&#x27;", "&#39;"))
        out.append(s.replace("'", "&#39;").replace('"', "&quot;"))
    return list(dict.fromkeys(out))

def main():
    d = json.load(open(DICT, encoding="utf-8"))
    d = {k: v for k, v in d.items() if k and v and k != v}
    if DST.exists():
        shutil.rmtree(DST)
    shutil.copytree(SRC, DST)

    # 1) index.html
    idx = DST / "index.html"
    t = idx.read_text(encoding="utf-8")
    t = t.replace('<html lang="en">', '<html lang="zh-CN">')
    idx.write_text(t, encoding="utf-8")

    # 2) manifest
    mf = DST / "manifest.webmanifest"
    if mf.exists():
        m = json.load(open(mf, encoding="utf-8"))
        m["lang"] = "zh-CN"
        m["description"] = "由 llama.cpp 驱动的本地 AI 对话界面（汉化版）"
        json.dump(m, open(mf, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))

    # 3) bundle
    bundle = DST / "_app/immutable/bundle.D2CaPqLt.js"
    s = bundle.read_text(encoding="utf-8")
    keys = sorted(d.keys(), key=len, reverse=True)
    hit, miss = {}, []
    for k in keys:
        n = 0
        for v in variants(k):
            if v in s:
                c = s.count(v)
                s = s.replace(v, d[k])
                n += c
        if n:
            hit[k] = n
        else:
            miss.append(k)
    bundle.write_text(s, encoding="utf-8")
    json.dump({"hit": hit, "miss": miss}, open("apply_report.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"替换成功 {len(hit)} 条 / 未命中 {len(miss)} 条 / 总替换 {sum(hit.values())} 处")
    for k in miss[:20]:
        print("  [未命中]", k)

if __name__ == "__main__":
    main()
