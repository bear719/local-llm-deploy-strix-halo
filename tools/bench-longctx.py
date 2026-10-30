#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
长上下文 KV 量化对比测试
测什么：填充 N token 长上下文后，生成 256 token 的 decode 速度
为什么：KV 量化的代价（反量化开销）随上下文长度累积，短 prompt 测不出来
用法：python3 bench-longctx.py <端口> [填充token数] [轮数]
"""
import json
import sys
import time
import urllib.request

PORT = sys.argv[1] if len(sys.argv) > 1 else "8080"
FILL = int(sys.argv[2]) if len(sys.argv) > 2 else 32768
ROUNDS = int(sys.argv[3]) if len(sys.argv) > 3 else 3

# 用可预测的散文填充，避免被 tokenizer 过度压缩
SENTENCE = ("在消化内科的临床工作中，内镜治疗后的食管胃底静脉曲张管理需要综合评估患者的"
            "肝功能分级、门静脉压力梯度以及既往出血史。每位患者的随访周期与用药方案"
            "都应当个体化制定。")
# 估算：1 个中文字 ≈ 1 token（Qwen tokenizer 大致如此）
REPEAT = max(1, FILL // 60)
PROMPT = SENTENCE * REPEAT


def run_once(tag):
    payload = {
        "messages": [{"role": "user", "content": PROMPT + "\n\n请用一句话总结上文。"}],
        "max_tokens": 256,
        "stream": False,
        "cache_prompt": False,   # 关键：禁止前缀复用，否则测不出真实 prefill
    }
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=900) as resp:
        body = json.load(resp)
    wall = time.time() - t0
    usage = body.get("usage", {})
    t = body.get("timings", {})
    pp = t.get("prompt_per_second", 0.0)
    tg = t.get("predicted_per_second", 0.0)
    pn = t.get("prompt_n", 0)
    gn = t.get("predicted_n", 0)
    print(f"  [{tag}] pp={pp:7.2f} t/s  tg={tg:7.2f} t/s  "
          f"prompt_n={pn:6d}  gen_n={gn:4d}  wall={wall:6.2f}s")
    return pp, tg


if __name__ == "__main__":
    print(f"目标填充 token ≈ {FILL}（实际 prompt 字符 {len(PROMPT)}）")
    print(f"端口 {PORT}，{ROUNDS} 轮")
    tgs, pps = [], []
    for i in range(ROUNDS):
        pp, tg = run_once(f"#{i+1}")
        pps.append(pp)
        tgs.append(tg)
    print(f"--- {ROUNDS} 轮中位数 ---")
    pps.sort(); tgs.sort()
    mid = ROUNDS // 2
    med_pp = pps[mid] if ROUNDS % 2 else (pps[mid-1]+pps[mid])/2
    med_tg = tgs[mid] if ROUNDS % 2 else (tgs[mid-1]+tgs[mid])/2
    print(f"  prefill 中位数: {med_pp:.2f} t/s")
    print(f"  decode  中位数: {med_tg:.2f} t/s")
