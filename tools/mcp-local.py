#!/usr/bin/env python3
# 许可：CC0-1.0，公共领域贡献，无任何限制。
# -*- coding: utf-8 -*-
"""
本机 MCP 工具服务（stdio，无第三方依赖）

暴露四个工具（2026-11-23 立项，见 `2026-11-23-提升本地Qwen能力方案清单.md` C2/C3）：
  1. search_docs        混合检索本机文档库（向量 + BM25 + RRF + MMR，带 文件:行 定位）
  2. medcalc            临床评分计算（Child-Pugh / MELD3 / Baveno / GBS / BISAP …）
  3. medcalc_list       列出全部可用评分
  4. sql_query          SQLite 只读查询（科室统计、登记表做 SQL 聚合）
  5. structured_extract 用 8080 的 JSON Schema 约束抽取（xgrammar 强制合法 JSON）

设计原则：
  - **不重复实现**。检索直接调 `npu-search.py`，评分直接调 `medcalc.py`，
    保证 CLI 与 MCP 两条路径行为一致，改一处即两处生效。
  - **只读**。sql_query 强制 mode=ro + 仅允许 SELECT/WITH/PRAGMA，绝不写库。
  - stdout 只出 JSON-RPC，日志一律 stderr（MCP 协议硬要求）。

注册方式：写进 ~/.workbuddy/mcp.json 的 mcpServers，然后在连接器页面点「信任」。
  {"mcpServers": {"local-tools": {"command": "python3",
     "args": ["/home/<user>/WorkBuddy/调试本地模型/tools/mcp-local.py"]}}}

自测（不依赖客户端）：
  echo '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | python3 tools/mcp-local.py
"""

import json
import os
import sqlite3
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PY = sys.executable
SEARCH = os.path.join(HERE, "npu-search.py")
MEDCALC = os.path.join(HERE, "medcalc.py")
PROTO = "2024-11-05"

TOOLS = [
    {
        "name": "search_docs",
        "description": "检索本机文档库（约 1400 块，覆盖 llama.cpp 部署、NPU、视频生成、"
                       "项目决策记录与发布文档）。向量 + BM25 双路召回后融合去重，"
                       "返回 文件:行 精确定位。查历史结论、参数定案、踩坑记录时优先用它。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "检索问题或关键词"},
                "topk": {"type": "integer", "description": "返回条数，默认 6", "default": 6},
                "source": {"type": "string", "description": "来源 glob 过滤，如 'publish/*'"},
                "bm25_only": {"type": "boolean", "description": "跳过向量召回（NPU 忙时提速）"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "medcalc",
        "description": "计算临床评分。已收录 child_pugh / meld3 / meld_na / albi / baveno / "
                       "sarin / fib4 / apri / nfs / gbs / aims65 / rockall / bisap / ranson / "
                       "egfr_ckdepi2021 / crcl / corrected_calcium / saag / bmi / "
                       "clavien_dindo / asr_grade。数值计算不要自己算，交给它。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "score": {"type": "string", "description": "评分名称，如 child_pugh"},
                "params": {"type": "object", "description": "参数表，键名见 medcalc_list，"
                                                          "必须带单位后缀（bili_mgdl / plt_1e9l …）",
                           "additionalProperties": True},
            },
            "required": ["score", "params"],
        },
    },
    {
        "name": "medcalc_list",
        "description": "列出全部可用的临床评分及其所需参数（首次调用某评分前先查参数名）。",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "sql_query",
        "description": "对本地 SQLite 库执行只读 SQL（仅 SELECT/WITH/PRAGMA）。"
                       "用于科室工作量、手术计费、随访登记的聚合统计。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "db": {"type": "string", "description": "SQLite 文件绝对路径"},
                "sql": {"type": "string", "description": "只读 SQL"},
                "limit": {"type": "integer", "description": "最多返回行数，默认 200"},
            },
            "required": ["db", "sql"],
        },
    },
    {
        "name": "structured_extract",
        "description": "用 8080 本地模型做 JSON Schema 强约束抽取（xgrammar），"
                       "输出必为合法 JSON。适合化验单、手术记录、计费明细等字段级抽取。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "待抽取的原文"},
                "schema": {"type": "object", "description": "JSON Schema 对象"},
                "instruction": {"type": "string", "description": "抽取要求（可选）"},
                "max_tokens": {"type": "integer", "default": 2048},
            },
            "required": ["text", "schema"],
        },
    },
]


def _run(args, timeout=180):
    r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout or "exit %d" % r.returncode).strip()[:800])
    return r.stdout


def tool_search_docs(a):
    cmd = [PY, SEARCH, a["query"], "--topk", str(a.get("topk") or 6), "--json"]
    if a.get("source"):
        cmd += ["--source", a["source"]]
    if a.get("bm25_only"):
        cmd.append("--bm25-only")
    hits = json.loads(_run(cmd))
    lines = []
    for i, h in enumerate(hits, 1):
        lines.append("%d. %s:%s  [%s]" % (i, h["source"], h.get("line") or "?", h.get("title") or ""))
        lines.append(h["text"][:900])
        lines.append("")
    return "\n".join(lines) or "（无结果）"


def tool_medcalc(a):
    cmd = [PY, MEDCALC, "--json", a["score"]]
    for k, v in (a.get("params") or {}).items():
        if isinstance(v, bool):
            if v:
                cmd.append("--" + k)
        elif v is not None:
            cmd += ["--" + k, str(v)]
    return _run(cmd)


def tool_medcalc_list(_a):
    return _run([PY, MEDCALC, "--list"])


def tool_sql_query(a):
    db = os.path.abspath(os.path.expanduser(a["db"]))
    if not os.path.isfile(db):
        raise RuntimeError("库文件不存在: " + db)
    sql = a["sql"].strip()
    head = sql.lstrip("( \n\t").split(None, 1)[0].upper() if sql else ""
    if head not in ("SELECT", "WITH", "PRAGMA", "EXPLAIN"):
        raise RuntimeError("只允许只读语句（SELECT/WITH/PRAGMA），收到: " + head)
    lim = int(a.get("limit") or 200)
    con = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
    try:
        con.row_factory = sqlite3.Row
        cur = con.execute(sql)
        rows = cur.fetchmany(lim)
        cols = [d[0] for d in cur.description] if cur.description else []
        if not cols:
            return "（无结果列）"
        out = [" | ".join(cols), "-" * 40]
        for r in rows:
            out.append(" | ".join("" if r[c] is None else str(r[c]) for c in cols))
        if len(rows) >= lim:
            out.append("… 已截断至 %d 行" % lim)
        return "\n".join(out)
    finally:
        con.close()


def tool_structured_extract(a):
    import urllib.request
    schema = a["schema"]
    if isinstance(schema, str):
        schema = json.loads(schema)
    instr = a.get("instruction") or ("按给定 JSON Schema 从原文抽取字段；原文没有的信息填 null，不要编造。"
                                     "★ 否定表述是有效信息：原文写「无」「未见」「阴性」时，"
                                     "boolean 字段填 false、字符串字段填「无」，不要填 null。")
    body = {
        "model": "local",
        "messages": [
            {"role": "system", "content": instr},
            {"role": "user", "content": a["text"]},
        ],
        "temperature": 0,
        "max_tokens": int(a.get("max_tokens") or 2048),
        "response_format": {"type": "json_schema",
                            "json_schema": {"name": "out", "strict": True, "schema": schema}},
        "chat_template_kwargs": {"enable_thinking": False},
    }
    req = urllib.request.Request(
        "http://127.0.0.1:8080/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=300) as r:
        d = json.loads(r.read())
    return d["choices"][0]["message"]["content"]


HANDLERS = {
    "search_docs": tool_search_docs,
    "medcalc": tool_medcalc,
    "medcalc_list": tool_medcalc_list,
    "sql_query": tool_sql_query,
    "structured_extract": tool_structured_extract,
}


def send(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def handle(req):
    mid = req.get("id")
    method = req.get("method")

    if method == "initialize":
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": PROTO,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "local-tools", "version": "1.0.0"},
        }}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}}
    if method == "tools/call":
        name = (req.get("params") or {}).get("name")
        args = (req.get("params") or {}).get("arguments") or {}
        fn = HANDLERS.get(name)
        if not fn:
            return {"jsonrpc": "2.0", "id": mid,
                    "error": {"code": -32601, "message": "unknown tool: %s" % name}}
        try:
            text = fn(args)
            return {"jsonrpc": "2.0", "id": mid,
                    "result": {"content": [{"type": "text", "text": text}], "isError": False}}
        except Exception as e:
            return {"jsonrpc": "2.0", "id": mid,
                    "result": {"content": [{"type": "text", "text": "[ERROR] %s: %s"
                                            % (type(e).__name__, e)}], "isError": True}}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    if mid is None:  # 通知类，不响应
        return None
    return {"jsonrpc": "2.0", "id": mid,
            "error": {"code": -32601, "message": "unknown method: %s" % method}}


def main():
    print("[mcp-local] started, %d tools" % len(TOOLS), file=sys.stderr)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception as e:
            print("[mcp-local] bad json: %s" % e, file=sys.stderr)
            continue
        resp = handle(req)
        if resp is not None:
            send(resp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
