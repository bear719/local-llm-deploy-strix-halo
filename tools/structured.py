#!/usr/bin/env python3
# 许可：CC0-1.0，公共领域贡献，无任何限制。
# -*- coding: utf-8 -*-
"""
结构化输出封装（8080 llama-server + xgrammar JSON Schema 约束）

为什么需要它（2026-11-23，见 `2026-11-23-提升本地Qwen能力方案清单.md` C3）：
  自由文本输出必然出现「格式对、字段错」——比如把 `plt` 填成 `hb`，
  或者少一个必填字段，下游解析器直接崩。用 `response_format.json_schema`
  让 xgrammar 在采样层面约束，输出**语法上必定合法**，
  再加一层本地字段校验，把「语法合法但语义缺失」也挡住。

能力边界（必须说清）：
  schema 只保证**结构**，不保证**内容正确**。字段填错值仍会发生，
  所以校验结果里区分 `syntax_ok`（JSON 合 schema）与 `content_ok`（关键字段非空且类型对）。
  内容正确性只能靠人工抽查或交叉核对，不要用「schema 通过了」当准确性证明。

用法：
  python3 tools/structured.py --list
  python3 tools/structured.py ev_endoscopy --text "胃镜下见..."
  python3 tools/structured.py lab_panel --file /tmp/lab.txt --json
  python3 tools/structured.py op_record --text "..." --repeat 3    # 一致性测试
  python3 tools/structured.py ev_endoscopy --text "..." --service 18090
"""

import argparse
import glob
import json
import os
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SDIR = os.path.join(HERE, "schemas")

DEFAULT_INSTR = ("你是病历结构化引擎。严格按给定 JSON Schema 抽取原文中的字段。"
                 "原文未提及的字段填 null；不要推测、不要补全、不要输出解释。"
                 "★ 否定表述是有效信息：原文写「无活动性出血」「未见穿孔」「阴性」时，"
                 "对应 boolean 字段必须填 false、字符串字段填「无」，不要因为「没有阳性发现」就填 null。"
                 "null 只用于原文完全没提到该主题的情况。")

TYPE_MAP = {
    "string": str, "number": (int, float), "integer": int,
    "boolean": bool, "array": list, "object": dict, "null": type(None),
}


def load_schema(name):
    p = os.path.join(SDIR, name + ".json") if not name.endswith(".json") else name
    if not os.path.exists(p):
        cand = glob.glob(os.path.join(SDIR, name + "*.json"))
        if len(cand) == 1:
            p = cand[0]
        else:
            raise SystemExit("[ERROR] 找不到 schema: %s -> 用 --list 查看" % name)
    with open(p, "r", encoding="utf-8") as f:
        return os.path.basename(p)[:-5], json.load(f)


def validate(obj, schema, path="$"):
    """返回 (错误列表, 缺失的必填字段列表)。只覆盖本项目用到的关键字子集"""
    errs, missing = [], []
    t = schema.get("type")
    if t is not None:
        ts = t if isinstance(t, list) else [t]
        py = tuple(TYPE_MAP[x] for x in ts if x in TYPE_MAP)
        # bool 是 int 的子类，需排除
        if isinstance(obj, bool) and "boolean" not in ts:
            errs.append("%s: 期望 %s，得到 boolean" % (path, ts))
            return errs, missing
        if py and not isinstance(obj, py):
            errs.append("%s: 期望 %s，得到 %s" % (path, ts, type(obj).__name__))
            return errs, missing
    if "enum" in schema and obj not in schema["enum"]:
        errs.append("%s: 值 %r 不在枚举 %s 内" % (path, obj, schema["enum"]))
    if isinstance(obj, dict):
        for k in schema.get("required", []):
            if k not in obj:
                missing.append("%s.%s" % (path, k))
        props = schema.get("properties", {})
        for k, v in obj.items():
            if k in props:
                e, m = validate(v, props[k], path + "." + k)
                errs.extend(e)
                missing.extend(m)
            elif schema.get("additionalProperties") is False:
                errs.append("%s: 多余字段 %s" % (path, k))
    if isinstance(obj, list) and "items" in schema:
        for i, v in enumerate(obj):
            e, m = validate(v, schema["items"], "%s[%d]" % (path, i))
            errs.extend(e)
            missing.extend(m)
    return errs, missing


def call(service, text, schema, instr, max_tokens, temperature=0):
    body = {
        "model": "local",
        "messages": [
            {"role": "system", "content": instr},
            {"role": "user", "content": text},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_schema",
                            "json_schema": {"name": "out", "strict": True, "schema": schema}},
        "chat_template_kwargs": {"enable_thinking": False},
    }
    req = urllib.request.Request(
        "http://127.0.0.1:%d/v1/chat/completions" % service,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=600) as r:
        d = json.loads(r.read())
    dt = time.time() - t0
    ch = d["choices"][0]
    usage = d.get("usage") or {}
    return ch["message"]["content"], dt, usage, ch.get("finish_reason")


def main():
    ap = argparse.ArgumentParser(description="结构化输出封装")
    ap.add_argument("schema", nargs="?", help="schema 名称，如 ev_endoscopy")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--text", help="待抽取文本")
    ap.add_argument("--file", help="从文件读取文本")
    ap.add_argument("--instr", default=DEFAULT_INSTR)
    ap.add_argument("--service", type=int, default=8080)
    ap.add_argument("--max-tokens", type=int, default=2048)
    ap.add_argument("--repeat", type=int, default=1, help="重复次数，测一致性")
    ap.add_argument("--json", action="store_true", help="只输出抽取结果 JSON")
    ap.add_argument("--raw", action="store_true", help="输出模型原始返回")
    a = ap.parse_args()

    if a.list or not a.schema:
        print("可用 schema：")
        for p in sorted(glob.glob(os.path.join(SDIR, "*.json"))):
            with open(p, "r", encoding="utf-8") as f:
                s = json.load(f)
            req = s.get("required") or []
            print("  %-20s %s" % (os.path.basename(p)[:-5], s.get("title", "")))
            print("  %-20s 必填: %s" % ("", ", ".join(req)))
        return 0

    if a.text:
        text = a.text
    elif a.file:
        with open(a.file, "r", encoding="utf-8") as f:
            text = f.read()
    else:
        text = sys.stdin.read()

    name, schema = load_schema(a.schema)

    runs = []
    for i in range(a.repeat):
        try:
            content, dt, usage, fin = call(a.service, text, schema, a.instr, a.max_tokens)
        except Exception as e:
            print("[ERROR] 调用失败: %s" % e, file=sys.stderr)
            return 2
        try:
            obj = json.loads(content)
        except Exception:
            if a.raw:
                print(content)
            print("[ERROR] 返回非合法 JSON（schema 约束未生效？检查服务版本）", file=sys.stderr)
            return 2
        errs, missing = validate(obj, schema)
        runs.append({"obj": obj, "dt": dt, "usage": usage, "finish": fin,
                     "errs": errs, "missing": missing})

    if a.json:
        print(json.dumps(runs[0]["obj"], ensure_ascii=False, indent=2))
        if len(runs) > 1:
            same = all(r["obj"] == runs[0]["obj"] for r in runs)
            print("# repeat=%d 一致=%s" % (len(runs), same), file=sys.stderr)
        return 0

    r0 = runs[0]
    print("schema   %s" % name)
    print("耗时     %.2fs   输出 tok=%s   结束原因=%s"
          % (r0["dt"], (r0["usage"] or {}).get("completion_tokens"), r0["finish"]))
    print("语法     结构合法=%s  缺必填=%d  其他错误=%d"
          % ("是" if not r0["missing"] and not r0["errs"] else "否",
             len(r0["missing"]), len(r0["errs"])))
    for m in r0["missing"]:
        print("  缺 %s" % m)
    for e in r0["errs"]:
        print("  ! %s" % e)
    print("-" * 72)
    print(json.dumps(r0["obj"], ensure_ascii=False, indent=2))
    if len(runs) > 1:
        same = all(r["obj"] == runs[0]["obj"] for r in runs)
        dts = [r["dt"] for r in runs]
        print("-" * 72)
        print("repeat=%d  完全一致=%s  耗时 %.2f~%.2fs"
              % (len(runs), same, min(dts), max(dts)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
