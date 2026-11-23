#!/usr/bin/env python3
# 许可：CC0-1.0，公共领域贡献，无任何限制。
"""A/B 交错压测 llama-server 的 decode 速度。

设计要点（遵循本机压测铁律）：
  - 每次请求带随机 uuid 前缀，避免 LCP 缓存命中导致秒回
  - 前 2 次预热丢弃（填充 compute buffer / 暖 GPU 频率）
  - 读服务端 timings.predicted_per_second，不用客户端墙钟
  - 同一进程内多次采样取中位数，降噪

用法:
    python3 bench-ab.py --n 5 --tag baseline
    python3 bench-ab.py --n 5 --tag fa_on --port 8080
"""
import argparse
import json
import statistics
import urllib.request
import uuid

BODY = (
    "请从病理生理机制出发，系统阐述肝硬化门静脉高压的形成过程，"
    "并逐条说明食管胃静脉曲张破裂出血的一级预防、急性期处理与二级预防策略。"
    "要求分节展开，每节不少于 150 字。"
)


def post(port, payload, timeout=600):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def one(port, n_predict):
    # 随机前缀：确保 cache_n=0，full prefill + full decode
    tag = uuid.uuid4().hex[:16]
    payload = {
        "messages": [{"role": "user", "content": f"[{tag}] {BODY}"}],
        "max_tokens": n_predict,
        "temperature": 0.7,
        "top_p": 0.9,
        "stream": False,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    d = post(port, payload)
    t = d.get("timings", {})
    return {
        "tg": t.get("predicted_per_second"),
        "pp": t.get("prompt_per_second"),
        "n_pred": t.get("predicted_n"),
        "n_prompt": t.get("prompt_n"),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=5, help="有效采样次数（不含预热）")
    ap.add_argument("--warmup", type=int, default=2, help="预热次数，结果丢弃")
    ap.add_argument("--port", default="8080")
    ap.add_argument("--tag", default="run")
    ap.add_argument("--n-predict", type=int, default=400)
    args = ap.parse_args()

    for i in range(args.warmup):
        r = one(args.port, 64)
        print(f"  预热 {i + 1}/{args.warmup}: {r['tg']:.1f} t/s (丢弃)")

    tg, pp = [], []
    for i in range(args.n):
        r = one(args.port, args.n_predict)
        tg.append(r["tg"])
        pp.append(r["pp"])
        print(f"  [{args.tag}] #{i + 1}: decode {r['tg']:.2f} t/s | prefill {r['pp']:.1f} t/s "
              f"| n_prompt={r['n_prompt']} n_pred={r['n_pred']}")

    print(f"RESULT {args.tag} decode_median={statistics.median(tg):.2f} "
          f"decode_min={min(tg):.2f} decode_max={max(tg):.2f} "
          f"prefill_median={statistics.median(pp):.1f} n={args.n}")


if __name__ == "__main__":
    main()
