#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NPU 旁路分流的验证与 A/B 验收工具（只读 + 发请求，不改任何文件/服务）。

前置条件
--------
1. 8219 的 flm 实例已由 MCSManager 面板启动（start-flm-npu.sh）。
2. 已用 apply-npu-route.py --apply 打补丁，并在隔离端口起验证代理：
     NPU_UPSTREAM=http://127.0.0.1:8219 \
     python3 tools/docproxy.py serve --port 18091 --upstream http://127.0.0.1:8080
3. 验证完成后关闭 18091 临时实例；生产 18090 只在阶段 4 授权后才动。

用法
----
  python3 tools/verify-npu-route.py check                    # 三处健康 + 内存水位
  python3 tools/verify-npu-route.py route                   # 4 条分流用例
  python3 tools/verify-npu-route.py route --sidecar         # 追加 embeddings 用例
  python3 tools/verify-npu-route.py ab                      # GPU 基线 vs NPU 并发
  python3 tools/verify-npu-route.py ab --rounds 5 --loaders 2

判定门槛（见方案 §11）
  GPU decode 降幅 ≤ 3% / MemAvailable 全程 ≥ 4 GiB / 无 reset / 无 502
"""

import argparse
import glob
import json
import statistics
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid

BASE = "http://127.0.0.1"
PROMPTS = [
    "写一段关于胃镜检查前肠道准备的说明，200字左右。",
    "解释什么是肝硬化门脉高压，并说明其常见并发症。",
    "列出消化科常见的五种急症及其处理原则。",
]


# ---------------- 基础工具 ----------------

def http_req(url, payload=None, headers=None, timeout=300, method=None):
    """发一条请求，返回 (状态码, 解析后的 JSON 或原始文本)。"""
    data = json.dumps(payload).encode() if payload is not None else None
    h = {"Content-Type": "application/json"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "ignore")
            try:
                return r.status, json.loads(raw)
            except json.JSONDecodeError:
                return r.status, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "ignore")
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, raw
    except Exception as e:
        return -1, {"error": str(e)}


def mem_mib():
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) // 1024
    except Exception:
        return None
    return None


def gtt_used_gib():
    try:
        v = int(open("/sys/class/drm/card1/device/mem_info_gtt_used").read())
        return round(v / (1024 ** 3), 2)
    except Exception:
        return None


def power_w():
    """best-effort 读 GPU 功耗（µW -> W）。读不到返回 None，不影响主流程。"""
    for p in glob.glob("/sys/class/drm/card1/device/hwmon/hwmon*/power1_average"):
        try:
            return round(int(open(p).read().strip()) / 1e6, 2)
        except Exception:
            pass
    return None


def sclk():
    try:
        for line in open("/sys/class/drm/card1/device/pp_dpm_sclk"):
            if "*" in line:
                return line.strip()
    except Exception:
        pass
    return None


def snap():
    return "MemAvailable=%s MiB  GTTused=%s GiB  功耗=%s W  sclk=%s" % (
        mem_mib(), gtt_used_gib(), power_w(), sclk())


def backend_of(resp):
    """判断响应来自哪个后端：llama.cpp 给 timings，flm 给 decoding_speed_tps。"""
    if not isinstance(resp, dict):
        return "未知"
    if "timings" in resp:
        return "iGPU/8080"
    u = resp.get("usage") or {}
    if "decoding_speed_tps" in u or "prefill_speed_tps" in u:
        return "NPU/8219"
    return "未知(model=%s)" % resp.get("model", "?")


def text_of(resp):
    if not isinstance(resp, dict):
        return str(resp)[:160]
    try:
        return (resp["choices"][0]["message"]["content"] or "")[:120]
    except Exception:
        return json.dumps(resp, ensure_ascii=False)[:160]


# ---------------- 子命令 ----------------

def cmd_check(a):
    print("=== 健康检查 ===")
    print("本机状态:", snap())
    print()
    endpoints = [
        ("验证代理 %s" % a.proxy, "%s:%s/health" % (BASE, a.proxy)),
        ("NPU 8219 模型列表", "%s:%s/v1/models" % (BASE, a.npu)),
        ("iGPU 8080 健康", "%s:%s/health" % (BASE, a.gpu)),
        ("生产代理 18090 健康", "%s:18090/health" % BASE),
    ]
    for name, url in endpoints:
        code, body = http_req(url, timeout=10)
        if name.startswith("NPU"):
            ids = [m.get("id") for m in body.get("data", [])] if isinstance(body, dict) else []
            brief = "模型数=%d  %s" % (len(ids), ids[:6])
        else:
            brief = json.dumps(body, ensure_ascii=False)[:220] if isinstance(body, dict) else str(body)[:220]
        print("  [%s] %-24s HTTP %s  %s" % ("OK" if code == 200 else "--", name, code, brief))
    print()
    m = mem_mib()
    print("水位线判定: %s (阈值 4096 MiB)" % (
        "PASS 可分流" if m and m >= 4096 else "FAIL 会被 docproxy 拒绝(503)"))
    return 0


def cmd_route(a):
    url = "%s:%s/v1/chat/completions" % (BASE, a.proxy)
    print("=== 分流用例（目标代理 %s） ===" % a.proxy)
    print("判定依据: llama.cpp 响应含 timings / flm 响应含 usage.decoding_speed_tps")
    print("注意: 用例 1 会占用一次 8080 主 slot，验证请在隔离端口做\n")

    cases = [
        ("① 默认请求（无标记）→ 应走 iGPU/8080",
         {"messages": [{"role": "user", "content": "用一句话说明统一内存架构。"}],
          "max_tokens": 32}, {}),
        ("② X-Backend: npu → 应走 NPU/8219",
         {"messages": [{"role": "user", "content": "用一句话说明统一内存架构。"}],
          "max_tokens": 32}, {"X-Backend": "npu"}),
        ("③ 带主模型别名 + X-Backend: npu → 验证 model 自动改写后仍成功",
         {"model": "Qwen3.6-35B-A3B-Uncensored-Q5_K_P",
          "messages": [{"role": "user", "content": "用一句话说明统一内存架构。"}],
          "max_tokens": 32}, {"X-Backend": "npu"}),
        ("④ model=lfm2.5-it:1.2b（白名单）+ 无头 → 应走 NPU/8219",
         {"model": "lfm2.5-it:1.2b",
          "messages": [{"role": "user", "content": "用一句话说明统一内存架构。"}],
          "max_tokens": 32}, {}),
    ]
    failed = 0
    for title, payload, headers in cases:
        code, body = http_req(url, payload, headers, timeout=180)
        be = backend_of(body)
        ok = code == 200
        if not ok:
            failed += 1
        print("  %s" % title)
        print("    HTTP %s  后端=%s  %s" % (code, be, "OK" if ok else "FAIL"))
        print("    响应: %s" % (text_of(body) if ok else json.dumps(body, ensure_ascii=False)[:200]))
    if a.sidecar:
        code, body = http_req(
            "%s:%s/v1/embeddings" % (BASE, a.proxy),
            {"model": "embed-gemma:300m", "input": "本地推理测试"},
            {"X-Backend": "npu"}, timeout=120)
        dim = None
        if isinstance(body, dict) and body.get("data"):
            dim = len(body["data"][0].get("embedding", []))
        print("  ⑤ /v1/embeddings → HTTP %s  维度=%s  %s" % (code, dim, "OK" if code == 200 else "FAIL"))
        if code != 200:
            failed += 1
    print("\n[%s] 失败 %d 条" % ("PASS" if failed == 0 else "FAIL", failed))
    return 0 if failed == 0 else 1


def npu_loader(proxy, stop, counter, lock):
    """后台持续给 NPU 加压，模拟「NPU 一直在干活」。"""
    url = "%s:%s/v1/chat/completions" % (BASE, proxy)
    while not stop.is_set():
        payload = {
            "messages": [{"role": "user",
                          "content": "[npu-load-%s] 请写一段 300 字左右的科普说明，主题是本地大模型推理。"
                                     % uuid.uuid4().hex[:8]}],
            "max_tokens": 400,
        }
        code, _ = http_req(url, payload, {"X-Backend": "npu"}, timeout=180)
        with lock:
            counter[0] += 1
            if code != 200:
                counter[1] += 1
        if stop.is_set():
            break


def gpu_measure(proxy, rounds, tag):
    """测 GPU decode，随机 uuid 前缀规避 --cache-idle-slots 的 LCP 复用。"""
    url = "%s:%s/v1/chat/completions" % (BASE, proxy)
    vals = []
    print("  --- %s ---" % tag)
    for i in range(rounds):
        payload = {
            "messages": [{"role": "user",
                          "content": "[q-%s] %s" % (uuid.uuid4().hex[:12], PROMPTS[i % len(PROMPTS)])}],
            "max_tokens": 256,
            "temperature": 0.7,
        }
        t0 = time.time()
        code, body = http_req(url, payload, timeout=300)
        wall = time.time() - t0
        tg = (body.get("timings") or {}).get("predicted_per_second", 0.0) if isinstance(body, dict) else 0.0
        vals.append(tg)
        print("    #%d: HTTP %s  decode=%.2f t/s  wall=%.2fs  %s"
              % (i + 1, code, tg, wall, snap()))
    return vals


def cmd_ab(a):
    print("=== A/B 验收：GPU 单独 vs NPU 持续并发 ===")
    print("代理=%s  轮次=%d  NPU 加压线程=%d" % (a.proxy, a.rounds, a.loaders))
    print("基线参考: 90.14 t/s（2026-10-03-35B速度复测.md）")
    print("门槛: GPU decode 降幅 ≤ 3%、MemAvailable ≥ 4096 MiB、无 502\n")

    base = gpu_measure(a.proxy, a.rounds, "A 组：NPU 空闲（基线）")

    stop = threading.Event()
    counter, lock = [0, 0], threading.Lock()
    threads = [threading.Thread(target=npu_loader, args=(a.proxy, stop, counter, lock),
                                daemon=True) for _ in range(a.loaders)]
    for t in threads:
        t.start()
    time.sleep(2)  # 让 NPU 先进入稳态
    busy = gpu_measure(a.proxy, a.rounds, "B 组：NPU 持续加压")
    stop.set()
    for t in threads:
        t.join(timeout=200)

    mb = statistics.median(base) if base else 0
    mm = statistics.median(busy) if busy else 0
    drop = (mb - mm) / mb * 100 if mb else 0
    print("\n  NPU 加压请求: 完成 %d 条，失败 %d 条" % (counter[0], counter[1]))
    print("  A 组中位 decode = %.2f t/s" % mb)
    print("  B 组中位 decode = %.2f t/s" % mm)
    print("  降幅 = %.2f%%   %s" % (drop, "PASS" if drop <= 3 else "FAIL(>3%)"))
    print("  收尾状态: %s" % snap())
    print("\n  另外需人工确认：")
    print("    - dmesg 无 GPU reset / MODE2")
    print("    - 8219 无 502（本工具统计到的失败数应为 0）")
    print("    - 长会话 LCP 复用仍 < 1 s（需专门的同会话观测）")
    ok = (drop <= 3 and counter[1] == 0 and (mem_mib() or 0) >= 4096)
    print("\n  [%s] 总判定" % ("PASS 可进入阶段 4" if ok else "FAIL 先按方案 §11.3 降级"))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description="NPU 分流验证与 A/B 验收")
    ap.add_argument("cmd", choices=["check", "route", "ab"])
    ap.add_argument("--proxy", default="18091", help="验证代理端口，默认 18091（隔离实例）")
    ap.add_argument("--npu", default="8219", help="flm 端口")
    ap.add_argument("--gpu", default="8080", help="llama-server 端口")
    ap.add_argument("--sidecar", action="store_true", help="route 时追加 embeddings 用例")
    ap.add_argument("--rounds", type=int, default=3, help="A/B 每组测量轮次")
    ap.add_argument("--loaders", type=int, default=2, help="NPU 加压并发线程数")
    a = ap.parse_args()
    if a.proxy == "18090":
        print("[警告] --proxy 18090 是生产代理，A/B 会占用主 slot；确认已获授权。")
    return {"check": cmd_check, "route": cmd_route, "ab": cmd_ab}[a.cmd](a)


if __name__ == "__main__":
    raise SystemExit(main())

# 许可：CC0-1.0，公共领域贡献，无任何限制。
