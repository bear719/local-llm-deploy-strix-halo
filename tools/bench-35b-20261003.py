#!/usr/bin/env python3
"""35B-A3B 纯文本测速（2026-10-03）。

关键：每条请求 prefix 带随机 uuid，避免命中 --cache-idle-slots 的 LCP 前缀复用（否则秒回）。
纯文本，无任何 media marker / image，规避 mmproj tokenize 400 错误。

覆盖：
  1. 短上下文 decode（3 次，短 prompt + max_tokens=256）
  2. 长上下文 prefill（2 次，~308KB prompt，复现 WorkBuddy 实际注入体量）
"""
import json
import os
import statistics
import sys
import time
import urllib.request
import uuid

PORT = sys.argv[1] if len(sys.argv) > 1 else "8080"
URL = f"http://127.0.0.1:{PORT}"

PROMPTS = [
    "写一段关于胃镜检查前肠道准备的说明，200字左右。",
    "解释什么是肝硬化门脉高压，并说明其常见并发症。",
    "列出消化内科常见的五种急症及其处理原则。",
]


def post(path, payload, timeout=300):
    req = urllib.request.Request(
        URL + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def metrics_snapshot():
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


def build_long_prompt(target_bytes=308 * 1024):
    """构造约 target_bytes 的纯文本长 prompt（带随机 uuid 前缀），不附任何图。"""
    base = (
        "患者男性，58岁，因\"反复黑便伴乏力两周\"入院。既往乙肝肝硬化病史10年，"
        "Child-Pugh B级。入院查体：神志清楚，慢性肝病面容，肝掌阳性，蜘蛛痣阳性，"
        "腹软，移动性浊音阳性，双下肢轻度水肿。血常规：Hb 78 g/L，PLT 52×10^9/L。"
        "凝血功能：PT 18.6s，INR 1.7。胃镜示食管胃底静脉曲张（GOV2型），"
        "红色征阳性。请结合上述资料，阐述该患者的诊断、风险评估及下一步诊疗方案。"
    )
    prefix = f"[ctx-{uuid.uuid4().hex}] "
    body = prefix
    while len(body.encode("utf-8")) < target_bytes:
        body += base
    return body


print("=== 1. 短上下文 decode（3 次，带随机 uuid 前缀） ===")
pps, tgs = [], []
before = metrics_snapshot()
for i in range(3):
    body = {
        "messages": [{
            "role": "user",
            "content": f"[q-{uuid.uuid4().hex[:12]}] " + PROMPTS[i % len(PROMPTS)],
        }],
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
print(f"--- 短上下文中位数 ---")
print(f"  prefill: {statistics.median(pps):.2f} t/s   decode: {statistics.median(tgs):.2f} t/s")
print(f"  decode 区间: {min(tgs):.2f} ~ {max(tgs):.2f} t/s")
if before and after and all(before) and all(after):
    dd = after[0] - before[0]; da = after[1] - before[1]; ds = after[2] - before[2]
    if dd > 0:
        print(f"  draft 接受率: {da/dd*100:.1f}%  (draft {dd:.0f} / 接受 {da:.0f} / 步 {ds:.0f})")
        if ds: print(f"  每步接受: {da/ds:.2f} token/step")

print()
print("=== 2. 长上下文 prefill（2 次，~308KB prompt，带随机 uuid 前缀） ===")
for i in range(2):
    lp = build_long_prompt()
    payload = {
        "messages": [{"role": "user", "content": lp}],
        "max_tokens": 16,
        "temperature": 0.7,
    }
    t0 = time.time()
    d = post("/v1/chat/completions", payload, timeout=300)
    wall = time.time() - t0
    t = d.get("timings", {})
    pp = t.get("prompt_per_second", 0.0)
    ntok = t.get("prompt_n", 0)
    print(f"  #{i+1}: prompt_tokens={ntok}  prefill={pp:7.2f} t/s  wall={wall:5.2f}s")

print()
print("=== 3. MTP 累计（自服务启动） ===")
m = metrics_snapshot()
if m and all(m):
    dd, da, ds = m
    print(f"  draft 接受率: {da/dd*100:.1f}%  (draft {dd:.0f} / 接受 {da:.0f} / 步 {ds:.0f})")
    if ds: print(f"  每步接受: {da/ds:.2f} token/step")
