#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NPU (FastFlowLM / XDNA2) 服务测试工具  —— 端口 8219

用途：验证 NPU 推理服务是否正常、测量真实性能、对比 iGPU。
依赖：Python 3 标准库（无需第三方包）

用法：
  ./test-npu.sh                      # 全套体检（推荐）
  ./test-npu.sh health               # 只查服务存活
  ./test-npu.sh bench                # 只测吞吐（3 次）
  ./test-npu.sh compare              # NPU vs iGPU 对比
  ./test-npu.sh ask "你的问题"        # 单次提问
  ./test-npu.sh stream "你的问题"     # 流式输出（看逐字返回）
  ./test-npu.sh loadtest 5           # 并发 5 个请求，测排队行为
  ./test-npu.sh models               # 列出可用模型
"""

import json
import sys
import time
import urllib.request
import urllib.error
import concurrent.futures

NPU = "http://127.0.0.1:8219"
IGPU = "http://127.0.0.1:8080"
NPU_MODEL = "qwen3.5:4b"


def _post(url, payload, timeout=300):
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _get(url, timeout=20):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def health():
    """检查 NPU 服务是否存活"""
    print("[1/1] 健康检查 —— " + NPU)
    try:
        t0 = time.time()
        d = _get(NPU + "/v1/models")
        dt = time.time() - t0
        ids = [m["id"] for m in d.get("data", [])]
        if NPU_MODEL in ids:
            print("  状态: 存活  (响应 %.2fs)" % dt)
            print("  当前模型: %s" % NPU_MODEL)
            return True
        print("  状态: 服务在，但未找到模型 %s" % NPU_MODEL)
        return False
    except Exception as e:
        print("  状态: 不可达 -> %s" % e)
        return False


def ask(prompt, model=NPU_MODEL):
    """单次提问，返回回答与计时"""
    t0 = time.time()
    d = _post(
        NPU + "/v1/chat/completions",
        {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 400,
            "stream": False,
        },
    )
    total = time.time() - t0
    txt = d["choices"][0]["message"]["content"]
    u = d.get("usage", {})
    print("--- 提问 ---")
    print(prompt)
    print("--- 回答 ---")
    print(txt)
    print("--- 指标 ---")
    if "decoding_speed_tps" in u:
        # FLM 原生细粒度指标
        print("  TTFT(首字)      : %.2f s" % u.get("prefill_duration_ttft", 0))
        print("  prefill 速度    : %.1f t/s" % u.get("prefill_speed_tps", 0))
        print("  解码速度        : %.1f t/s" % u.get("decoding_speed_tps", 0))
        print("  KV 占用         : %.1f%%" % u.get("kv_token_occupancy_rate_percentage", 0))
    print("  输出 tokens     : %s" % u.get("completion_tokens"))
    print("  端到端耗时      : %.2f s" % total)
    return d


def stream(prompt, model=NPU_MODEL):
    """流式输出，观察逐字返回速度"""
    body = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 400,
            "stream": True,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        NPU + "/v1/chat/completions",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    t0 = time.time()
    ttft = None
    n = 0
    print("--- 流式输出 ---")
    with urllib.request.urlopen(req, timeout=300) as r:
        for line in r:
            line = line.decode("utf-8", "ignore").strip()
            if not line.startswith("data: "):
                continue
            p = line[6:]
            if p == "[DONE]":
                break
            try:
                d = json.loads(p)
                c = d["choices"][0].get("delta", {}).get("content")
                if c:
                    if ttft is None:
                        ttft = time.time() - t0
                    n += 1
                    sys.stdout.write(c)
                    sys.stdout.flush()
            except Exception:
                pass
    tot = time.time() - t0
    dec = n / (tot - ttft) if ttft and tot > ttft else 0
    print("\n--- 指标 ---")
    print("  TTFT            : %.2f s" % (ttft or 0))
    print("  解码速度        : %.1f t/s" % dec)
    print("  输出 tokens     : %d" % n)
    print("  端到端耗时      : %.2f s" % tot)


def bench(rounds=3):
    """吞吐基准测试"""
    print("=== NPU 吞吐基准（%d 次）===" % rounds)
    print("模型: %s @ %s\n" % (NPU_MODEL, NPU))
    ttfts, decs = [], []
    for i in range(rounds):
        try:
            t0 = time.time()
            d = _post(
                NPU + "/v1/chat/completions",
                {
                    "model": NPU_MODEL,
                    "messages": [
                        {
                            "role": "user",
                            "content": "详细写一段400字的文章，介绍黑龙江的冰雪旅游资源。",
                        }
                    ],
                    "max_tokens": 400,
                    "stream": False,
                },
            )
            tot = time.time() - t0
            u = d.get("usage", {})
            ttft = u.get("prefill_duration_ttft", 0)
            dec = u.get("decoding_speed_tps", 0)
            tok = u.get("completion_tokens", 0)
            ttfts.append(ttft)
            decs.append(dec)
            print(
                "第%d次: TTFT %.2fs | 解码 %.1f t/s | 输出 %d tok | 总耗时 %.2fs"
                % (i + 1, ttft, dec, tok, tot)
            )
        except Exception as e:
            print("第%d次: 失败 -> %s" % (i + 1, e))
    if decs:
        print(
            "\n平均: TTFT %.2fs | 解码 %.1f t/s"
            % (sum(ttfts) / len(ttfts), sum(decs) / len(decs))
        )


def compare():
    """NPU vs iGPU 对比（同一问题）"""
    prompt = "用200字介绍什么是统一内存架构。"
    print("=== NPU vs iGPU 对比 ===")
    print("问题: %s\n" % prompt)
    for name, url, model in [
        ("NPU  (8219)", NPU, NPU_MODEL),
        ("iGPU (8080)", IGPU, None),
    ]:
        try:
            payload = {
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 300,
                "stream": False,
            }
            if model:
                payload["model"] = model
            else:
                # iGPU 用 /props 拿模型名
                try:
                    props = _get(IGPU + "/props", timeout=10)
                    payload["model"] = props.get("model_path", "local")
                except Exception:
                    payload["model"] = "local"
            t0 = time.time()
            d = _post(url + "/v1/chat/completions", payload)
            tot = time.time() - t0
            u = d.get("usage", {})
            dec = u.get("decoding_speed_tps")
            dec_s = "%.1f" % dec if dec else "n/a(未上报)"
            print("%s: 总耗时 %.2fs | 解码 %s t/s" % (name, tot, dec_s))
        except Exception as e:
            print("%s: 不可用 -> %s" % (name, e))
    print("\n说明: NPU 会主动上报 decoding_speed_tps；")
    print("      iGPU(llama.cpp) 需启动时加 --metrics 才上报，否则只给端到端耗时。")


def loadtest(n=5):
    """并发压测：观察 NPU 排队行为（同期仅 1 个 LLM）"""
    print("=== 并发压测（%d 个同时请求）===" % n)
    print("预期：NPU 设备独占，会出现 'NPU busy, request queued' 排队\n")

    def one(i):
        t0 = time.time()
        try:
            d = _post(
                NPU + "/v1/chat/completions",
                {
                    "model": NPU_MODEL,
                    "messages": [{"role": "user", "content": "数到%d。" % (i * 10)}],
                    "max_tokens": 200,
                    "stream": False,
                },
            )
            u = d.get("usage", {})
            return i, time.time() - t0, u.get("decoding_speed_tps", 0)
        except Exception as e:
            return i, time.time() - t0, "ERR:%s" % e

    t0 = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=n) as ex:
        for i, dt, dec in ex.map(one, range(n)):
            print("  请求%d: 耗时 %.2fs | 解码 %s" % (i, dt, dec))

    print("\n全部完成总耗时: %.2fs" % (time.time() - t0))
    print("提示：若各请求耗时明显累加，说明是串行排队（NPU 特性，非故障）。")


def models():
    """列出 FLM 支持的模型"""
    d = _get(NPU + "/v1/models")
    ids = sorted(m["id"] for m in d.get("data", []))
    print("=== FLM 支持模型（%d 个）===" % len(ids))
    for i in ids:
        print("  " + i)
    print("\n拉取新模型: flm pull <模型名>")


def usage():
    print(__doc__)


def main():
    args = sys.argv[1:]
    if not args:
        health()
        print()
        bench(3)
        print("\n提示: 输入 'ask \"问题\"' 做单次提问")
        return
    cmd = args[0]
    if cmd == "health":
        health()
    elif cmd == "bench":
        bench(3)
    elif cmd == "compare":
        compare()
    elif cmd == "ask":
        ask(" ".join(args[1:]) or "你好")
    elif cmd == "stream":
        stream(" ".join(args[1:]) or "你好")
    elif cmd == "loadtest":
        loadtest(int(args[1]) if len(args) > 1 else 5)
    elif cmd == "models":
        models()
    else:
        ask(" ".join(args))


if __name__ == "__main__":
    main()
