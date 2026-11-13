# 许可：CC0-1.0，公共领域贡献，无任何限制。
# -*- coding: utf-8 -*-
"""整串翻译模板/HTML 字面量：保留标签、属性、${...}、转义与空白结构。"""
import json, os, re, time, urllib.request

EP = "http://127.0.0.1:8080/v1/chat/completions"
OUT = "dict_lits.json"
BATCH = 4

SYS = (
    "你是软件界面本地化译者。用户给出 JSON 数组，每项含 id 和 text（可能含 HTML 标签、属性、"
    "${...} 模板插值、\\n \\t 转义、行内代码）。请把其中**面向用户的英文文本**翻成简体中文，"
    "并严格遵守：\n"
    "1) HTML 标签、标签属性、${...}、反引号代码片段、\\n \\t 等转义序列必须逐字节原样保留，位置不变；\n"
    "2) 不要新增或删除任何标签、换行；\n"
    "3) **必须使用简体中文，严禁繁体字**；技术名词 API/MCP/JSON/HTTP/URL/GPU/token/prompt/CSS/HTML/Markdown 保留英文；\n"
    "4) 只输出 JSON 对象：{\"<id>\": \"译文\", ...}，不要解释、不要 markdown 代码块。"
)

def call(items):
    body = {"model": "local",
            "messages": [{"role": "system", "content": SYS},
                         {"role": "user", "content": json.dumps(items, ensure_ascii=False)}],
            "temperature": 0, "max_tokens": 4096,
            "response_format": {"type": "json_object"},
            "chat_template_kwargs": {"enable_thinking": False}}
    req = urllib.request.Request(EP, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=900) as r:
        txt = json.load(r)["choices"][0]["message"]["content"]
    txt = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", txt.strip())
    i, j = txt.find("{"), txt.rfind("}")
    return json.loads(txt[i:j+1])

def main():
    todo = json.load(open("todo_lits.json", encoding="utf-8"))
    done = json.load(open(OUT, encoding="utf-8")) if os.path.exists(OUT) else {}
    todo = [t for t in todo if str(t["i"]) not in done]
    print("待译", len(todo), flush=True)
    for s in range(0, len(todo), BATCH):
        batch = todo[s:s+BATCH]
        payload = [{"id": str(t["i"]), "text": t["text"][:1200]} for t in batch]
        got = {}
        for _ in range(3):
            try:
                got = call(payload); break
            except Exception as e:
                print("[WARN]", s, e, flush=True); time.sleep(2)
        for t in batch:
            v = got.get(str(t["i"]))
            if isinstance(v, str) and v.strip():
                done[str(t["i"])] = v
        json.dump(done, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("进度", min(s+BATCH, len(todo)), "/", len(todo), flush=True)
    print("完成", len(done), flush=True)

if __name__ == "__main__":
    main()
