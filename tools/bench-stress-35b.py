#!/usr/bin/env python3
"""35B-A3B 压力测试套件 —— 并发 + 长上下文 + 多轮对话 + 流式/非流式。

用法:
    python3 bench-stress-35b.py                  # 默认全跑（约 2 分钟）
    python3 bench-stress-35b.py --port 8080      # 指定端口
    python3 bench-stress-35b.py --concurrency 10 # 提高并发数
    python3 bench-stress-35b.py --no-streaming   # 跳过非流式，只跑流式
"""
import json
import os
import statistics
import sys
import time
import urllib.request

PORT = os.environ.get("BENCH_PORT", "8080")
URL = f"http://127.0.0.1:{PORT}"
CONCURRENCY = int(os.environ.get("BENCH_CONCURRENCY", "5"))
NO_STREAMING = "--no-streaming" in sys.argv

# ---- 测试用例 ----
SHORT_PROMPTS = [
    "只回复两个字：收到",
    "1+1等于几？",
    "黑塞的《荒原狼》讲了什么？一句话。",
]
MEDIUM_PROMPTS = [
    "写一份 300 字左右的胃镜检查前肠道准备说明。",
    "解释肝硬化门脉高压的发病机制。",
    "列出消化内科五种急症及其处理原则，每个用一句话概括。",
]
LONG_PROMPTS = [
    "写一篇 800 字的文章，对比 Qwen3.6-35B-A3B 和 Qwen3.8-27B 在本地推理场景下的优劣，从 MoE 稀疏性、推理延迟、显存占用、多模态能力四个维度展开。",
    "你是一名消化内科医生，请给一位刚做完 EIS 治疗的患者写一份术后注意事项，包括饮食、活动、用药、复诊时间，400 字左右。",
]
MULTI_TURN = [
    "你知道哈尔滨吗？",
    "那冬天冷不冷？",
    "最冷多少度？",
    "推荐个适合冬天去的地方。",
]

def post(path, payload, stream=False, timeout=600):
    hdrs = {"Content-Type": "application/json"}
    data = json.dumps(payload).encode()
    req = urllib.request.Request(URL + path, data=data, headers=hdrs)
    try:
        r = urllib.request.urlopen(req, timeout=timeout)
        if stream:
            chunks = []
            buf = b""
            while True:
                chunk = r.read(1)
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    line = line.strip()
                    if line and line != b"data: [DONE]":
                        if line.startswith(b"data: "):
                            chunks.append(line[6:])
            text = "".join(c.decode("utf-8") for c in chunks)
            # 解析 usage
            usage_header = buf.decode("utf-8")
            usage = json.loads(usage_header.replace("data: ", "", 1)).get("usage", {}) if "data: " in usage_header else {}
            return {"text": text, "usage": usage}
        resp = json.loads(r.read().decode())
        # 检查是否有 error 字段（即使 HTTP 200，API 也可能返回错误）
        if "error" in resp:
            return {"text": f"[ERROR] {resp['error']}", "usage": {}, "error": resp["error"]}
        return {"text": resp["choices"][0]["message"]["content"], "usage": resp.get("usage", {})}
    except Exception as e:
        return {"text": "", "usage": {}, "error": str(e)}

def check_health():
    try:
        r = urllib.request.urlopen(URL + "/health", timeout=5)
        if r.status == 200:
            return True
    except:
        pass
    return False

def get_metrics():
    try:
        txt = urllib.request.urlopen(URL + "/metrics", timeout=10).read().decode()
        out = {}
        for key in ("spec_decode_num_draft_tokens_total", "spec_decode_num_accepted_tokens_total", "spec_decode_num_drafts_total"):
            for line in txt.splitlines():
                if line.startswith(f"llamacpp:{key} "):
                    out[key] = float(line.split()[-1])
        return out
    except:
        return None

def get_slots():
    try:
        txt = urllib.request.urlopen(URL + "/slots", timeout=5).read().decode()
        d = json.loads(txt)
        return d[0].get("params", {}).get("speculative", {}) if d else {}
    except:
        return {}

# ---- 打印头 ----
def header(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")

# ---- 并发测试 ----
def stress_concurrent(n=CONCURRENCY, prompt="只回复两个字：收到"):
    header(f"并发测试：{n} 个请求同时发")
    if not check_health():
        print("[ERROR] 服务未就绪"); return
    print(f"目标: {URL}")
    print(f"并发数: {n}")
    print(f"提示: {prompt}")
    print()
    
    results = []
    start_all = time.time()
    threads = []
    
    # 简单用子进程模拟并发（避免 threading GIL 问题）
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(n, 10)) as executor:
        futures = [executor.submit(post, "/v1/chat/completions", {
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 16,
            "temperature": 0.6,
            "chat_template_kwargs": {"enable_thinking": False}
        }) for _ in range(n)]
    for future in concurrent.futures.as_completed(futures):
        r = future.result()
        elapsed = time.time() - start_all
        has_error = "error" in r
        results.append({
            "elapsed": elapsed,
            "success": not has_error,
            "tokens": r.get("usage", {}).get("completion_tokens", 0),
            "text": r.get("text", "")[:40] if "text" in r else ""
        })
        print(f"  [{elapsed:.2f}s] {'✓' if not has_error else '✗'} {r.get('text', 'ERROR')[:30]} | tokens={r.get('usage', {}).get('completion_tokens', 'N/A')}")
    
    total = time.time() - start_all
    successes = [r for r in results if r["success"]]
    print(f"\n结果:")
    print(f"  总耗时: {total:.2f}s ({n} 并发)")
    print(f"  成功率: {len(successes)}/{n} ({100*len(successes)/max(n,1):.0f}%)")
    if successes:
        print(f"  平均延迟: {statistics.mean([r['elapsed'] for r in successes]):.2f}s")
        print(f"  最小延迟: {min([r['elapsed'] for r in successes]):.2f}s")
        print(f"  最大延迟: {max([r['elapsed'] for r in successes]):.2f}s")
        total_tokens = sum(r['tokens'] for r in successes)
        print(f"  总生成 token: {total_tokens}")
        print(f"  吞吐量: {total_tokens/total:.1f} tokens/s")

# ---- 长上下文测试 ----
def stress_long_context():
    header("长上下文测试：800 字生成")
    if not check_health():
        print("[ERROR] 服务未就绪"); return
    for i, prompt in enumerate(LONG_PROMPTS, 1):
        print(f"\n用例 {i}/{len(LONG_PROMPTS)}")
        print(f"提示: {prompt[:50]}...")
        start = time.time()
        r = post("/v1/chat/completions", {
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 1024,
            "temperature": 0.7,
        })
        elapsed = time.time() - start
        tokens = r.get("usage", {}).get("completion_tokens", 0)
        print(f"  耗时: {elapsed:.2f}s")
        print(f"  生成 token: {tokens}")
        if tokens > 0:
            print(f"  速度: {tokens/elapsed:.1f} tokens/s")
            print(f"  内容: {r.get('text', '')[:80]}...")

# ---- 多轮对话测试 ----
def stress_multi_turn():
    header(f"多轮对话测试：{len(MULTI_TURN)} 轮")
    if not check_health():
        print("[ERROR] 服务未就绪"); return
    messages = []
    for i, turn in enumerate(MULTI_TURN, 1):
        messages.append({"role": "user", "content": turn})
        print(f"\n第 {i}/{len(MULTI_TURN)} 轮")
        print(f"用户: {turn}")
        start = time.time()
        r = post("/v1/chat/completions", {
            "messages": messages.copy(),
            "max_tokens": 128,
            "temperature": 0.7,
        })
        elapsed = time.time() - start
        tokens = r.get("usage", {}).get("completion_tokens", 0)
        print(f"  耗时: {elapsed:.2f}s | tokens: {tokens}")
        if "text" in r:
            print(f"  模型: {r['text'][:80]}...")
        if i == len(MULTI_TURN):
            total_ctx = sum(len(m["content"]) for m in messages)
            total_out = r.get("usage", {}).get("total_tokens", 0)
            print(f"\n多轮总结:")
            print(f"  总输入字符: {total_ctx}")
            print(f"  总消耗 token: {total_out}")
            if total_out > 0:
                print(f"  上下文放大比: {total_out/total_ctx*100:.1f}%")

# ---- 流式测试 ----
def stress_streaming(n=3):
    if NO_STREAMING:
        print("\n[跳过] --no-streaming 参数指定")
        return
    header(f"流式/非流式对比：{n} 轮")
    if not check_health():
        print("[ERROR] 服务未就绪"); return
    
    for i in range(n):
        prompt = SHORT_PROMPTS[i % len(SHORT_PROMPTS)]
        print(f"\n第 {i+1}/{n} 轮 (提示: {prompt})")
        
        # 非流式
        print("  非流式: ", end="", flush=True)
        start = time.time()
        r_nostream = post("/v1/chat/completions", {
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 64,
            "temperature": 0.7,
        }, stream=False)
        t_ns = time.time() - start
        print(f"{t_ns:.2f}s | tokens: {r_nostream.get('usage', {}).get('completion_tokens', 0)}")
        
        # 流式
        print("  流式:   ", end="", flush=True)
        start = time.time()
        r_stream = post("/v1/chat/completions", {
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 64,
            "temperature": 0.7,
            "stream": True
        }, stream=True)
        t_stream = time.time() - start
        print(f"{t_stream:.2f}s | 内容: {r_stream.get('text', 'ERROR')[:40]}")

# ---- MTP 指标检查 ----
def check_mtp_metrics():
    header("MTP 投机解码指标")
    if not check_health():
        print("[ERROR] 服务未就绪"); return
    
    slots = get_slots()
    print(f"\n当前 speculative.types: {slots}")
    
    metrics = get_metrics()
    if not metrics:
        print("[INFO] /metrics 不可用或未启用（启动时需加 --metrics）")
        return
    
    draft = metrics.get("spec_decode_num_draft_tokens_total") or 0
    accepted = metrics.get("spec_decode_num_accepted_tokens_total") or 0
    steps = metrics.get("spec_decode_num_drafts_total") or 0
    
    print(f"\n累计指标（自服务启动以来）:")
    print(f"  总草稿 token: {draft}")
    print(f"  总接受 token: {accepted}")
    print(f"  总解码步数: {steps}")
    if draft > 0 and steps > 0:
        accept_rate = accepted / draft * 100
        avg_per_step = accepted / steps if steps > 0 else 0
        print(f"  接受率: {accept_rate:.1f}% ({accepted}/{draft})")
        print(f"  每步平均接受: {avg_per_step:.2f} token（越接近 N 越好，N=草稿数）")
        print(f"\n  参考（2026-10-02 上午实测）:")
        print(f"    85.46 t/s (95% CI: 82.66~91.46), MTP 接受率 74.4% (457/614)")
        print(f"    每步平均接受: 1.99 token")

# ---- 主程序 ----
if __name__ == "__main__":
    print("="*60)
    print("  35B-A3B 压力测试套件")
    print(f"  端口: {URL}")
    print(f"  并发: {CONCURRENCY}")
    print("="*60)
    
    check_mtp_metrics()
    stress_concurrent()
    stress_long_context()
    stress_multi_turn()
    stress_streaming()
    
    print("\n" + "="*60)
    print("  测试完成")
    print("="*60)
