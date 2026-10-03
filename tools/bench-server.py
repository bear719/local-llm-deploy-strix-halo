#!/usr/bin/env python3
"""对运行中的 llama-server 做批量对话测速（OpenAI 兼容端点）。

用法: python3 bench-server.py [次数] [端口]
输出: 每次的 pp/tg 速率，以及中位数、draft 接受率增量
"""
import json
import statistics
import sys
import time
import urllib.request

N = int(sys.argv[1]) if len(sys.argv) > 1 else 5
PORT = sys.argv[2] if len(sys.argv) > 2 else "8080"
URL = f"http://127.0.0.1:{PORT}"
PROMPTS = [
    "写一段关于胃镜检查前肠道准备的说明，200字左右。",
    "解释什么是肝硬化门脉高压，并说明其常见并发症。",
    "列出消化内科常见的五种急症及其处理原则。",
]


def post(path, payload):
    req = urllib.request.Request(
        URL + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read())


def metrics_snapshot():
    """返回 (draft, accepted, steps)"""
    try:
        txt = urllib.request.urlopen(URL + "/metrics", timeout=10).read().decode()
    except Exception:
        return None
    out = {}
    for key in ("spec_decode_num_draft_tokens_total",
                "spec_decode_num_accepted_tokens_total",
                "spec_decode_num_drafts_total"):
        for line in txt.splitlines():
            if line.startswith(f"llamacpp:{key} "):
                out[key] = float(line.split()[-1])
    return (out.get("spec_decode_num_draft_tokens_total"),
            out.get("spec_decode_num_accepted_tokens_total"),
            out.get("spec_decode_num_drafts_total"))


pps, tgs = [], []
before = metrics_snapshot()
for i in range(N):
    body = {
        "messages": [{"role": "user", "content": PROMPTS[i % len(PROMPTS)]}],
        "max_tokens": 256,
        "temperature": 0.7,
    }
    t0 = time.time()
    d = post("/v1/chat/completions", body)
    wall = time.time() - t0
    t = d.get("timings", {})
    pp, tg = t.get("prompt_per_second", 0.0), t.get("predicted_per_second", 0.0)
    pps.append(pp); tgs.append(tg)
    print(f"  #{i+1}: pp={pp:7.2f} t/s  tg={tg:7.2f} t/s  n={t.get('predicted_n',0):4d}  wall={wall:5.2f}s")

after = metrics_snapshot()
print(f"--- {N} 次中位数 ---")
print(f"  prefill: {statistics.median(pps):.2f} t/s   decode: {statistics.median(tgs):.2f} t/s")
print(f"  decode 区间: {min(tgs):.2f} ~ {max(tgs):.2f} t/s")
if before and after and all(before) and all(after):
    dd = after[0] - before[0]
    da = after[1] - before[1]
    ds = after[2] - before[2]
    if dd > 0:
        print(f"  draft 接受率: {da/dd*100:.1f}%  (draft {dd:.0f} / 接受 {da:.0f} / 步 {ds:.0f})")
        print(f"  每步接受: {da/ds:.2f} token/step" if ds else "")
