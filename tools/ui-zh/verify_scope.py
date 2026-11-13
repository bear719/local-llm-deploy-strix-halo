# 许可：CC0-1.0，公共领域贡献，无任何限制。
# -*- coding: utf-8 -*-
"""静态校验：确认汉化 bundle 中所有中文字符都落在字符串字面量内部。
原理：扫描 JS（处理单/双/反引号、模板插值、注释、正则粗略跳过），
遇到字符串外的 CJK 字符即判定为「替换越界」（会导致语法错误或逻辑错误）。"""
import sys, pathlib

CJK = lambda ch: "\u4e00" <= ch <= "\u9fff" or "\u3000" <= ch <= "\u303f" or "\uff00" <= ch <= "\uffef"

def scan(path):
    s = pathlib.Path(path).read_text(encoding="utf-8")
    i, n = 0, len(s)
    state = None  # None | '"' | "'" | '`'
    depth_tpl = 0
    out = []
    line = 1
    while i < n:
        c = s[i]
        if c == "\n":
            line += 1
        if state is None:
            if c in "\"'":
                state = c; i += 1; continue
            if c == "`":
                state = "`"; i += 1; continue
            if c == "/" and i + 1 < n and s[i+1] == "/":
                j = s.find("\n", i); i = (j if j >= 0 else n); continue
            if c == "/" and i + 1 < n and s[i+1] == "*":
                j = s.find("*/", i); line += s.count("\n", i, j); i = (j + 2 if j >= 0 else n); continue
            if CJK(c):
                out.append((line, c, s[max(0,i-40):i+40].replace("\n", " ")))
            i += 1; continue
        else:
            if c == "\\":
                i += 2; continue
            if c == state and state != "`":
                state = None; i += 1; continue
            if c == "`":
                state = None; i += 1; continue
            if state == "`" and c == "$" and i + 1 < n and s[i+1] == "{":
                # 模板插值内可含表达式：跳过到匹配的 }（简化处理，遇字符串再递归）
                lvl = 1; i += 2
                while i < n and lvl:
                    if s[i] == "{": lvl += 1
                    elif s[i] == "}": lvl -= 1
                    elif s[i] == "\n": line += 1
                    elif s[i] in "\"`":
                        q = s[i]; i += 1
                        while i < n and s[i] != q:
                            if s[i] == "\\": i += 1
                            i += 1
                    i += 1
                continue
            i += 1; continue
    return out

if __name__ == "__main__":
    p = sys.argv[1]
    bad = scan(p)
    print(f"字符串外中文出现次数: {len(bad)}")
    for b in bad[:20]:
        print("  行", b[0], repr(b[1]), "…", b[2])
