# 许可：CC0-1.0，公共领域贡献，无任何限制。
# -*- coding: utf-8 -*-
"""用本机 llama-server(8080) 批量把 UI 英文文案翻成简体中文，产出 dict.json。
- 温度 0 + enable_thinking=false，减少无效 token
- 严格校验：缺键自动重试（拆小批量）
- 增量落盘：中断可续跑
"""
import json, os, re, sys, time, urllib.request

ENDPOINT = "http://127.0.0.1:8080/v1/chat/completions"
SRC_JSON = "strings_src.json"
OUT_JSON = "dict.json"
BATCH = 40

SYS = (
    "你是软件界面本地化译者。把用户给出的英文 UI 文案翻译成简体中文。规则：\n"
    "1) 简洁，符合中文软件界面习惯，不要加解释；\n"
    "2) 保留占位符、变量名、路径、代码片段、以及 {{ }} { } < > $ 包裹的内容原样不动；\n"
    "3) API、MCP、JSON、HTTP、URL、GPU、token、prompt、CUDA、Vulkan 等技术名词保留英文；\n"
    "4) 键必须与原文完全一致（逐字符），只输出一个 JSON 对象，不要 markdown 代码块。"
)

def call(keys):
    prompt = json.dumps(keys, ensure_ascii=False)
    body = {
        "model": "local",
        "messages": [{"role": "system", "content": SYS}, {"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": 4096,
        "response_format": {"type": "json_object"},
        "chat_template_kwargs": {"enable_thinking": False},
    }
    req = urllib.request.Request(ENDPOINT, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=900) as r:
        data = json.load(r)
    txt = data["choices"][0]["message"]["content"]
    txt = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", txt.strip())
    i, j = txt.find("{"), txt.rfind("}")
    if i < 0 or j < 0:
        raise ValueError("响应中无 JSON")
    return json.loads(txt[i:j+1])

def main():
    src = json.load(open(SRC_JSON, encoding="utf-8"))
    keys = sorted(src.keys(), key=len, reverse=True)
    done = {}
    if os.path.exists(OUT_JSON):
        done = json.load(open(OUT_JSON, encoding="utf-8"))
    todo = [k for k in keys if k not in done]
    print(f"总计 {len(keys)} 条，已完成 {len(done)}，待译 {len(todo)}", flush=True)

    for start in range(0, len(todo), BATCH):
        batch = todo[start:start+BATCH]
        for attempt in range(3):
            try:
                got = call(batch)
                break
            except Exception as e:
                print(f"[WARN] 批次 {start} 第 {attempt+1} 次失败: {e}", flush=True)
                got = {}
                time.sleep(2)
        miss = []
        for k in batch:
            v = got.get(k)
            if isinstance(v, str) and v.strip():
                done[k] = v.strip()
            else:
                miss.append(k)
        # 缺失逐条补译
        for k in miss:
            try:
                one = call([k])
                v = one.get(k)
                if isinstance(v, str) and v.strip():
                    done[k] = v.strip()
                else:
                    print(f"[MISS] 未译出: {k}", flush=True)
            except Exception as e:
                print(f"[MISS] {k} -> {e}", flush=True)
        json.dump(done, open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"进度 {min(start+BATCH, len(todo))}/{len(todo)}", flush=True)
    print(f"完成，词条 {len(done)} 条", flush=True)

if __name__ == "__main__":
    main()
