#!/usr/bin/env python3
# 许可：CC0-1.0，公共领域贡献，无任何限制。
# -*- coding: utf-8 -*-
"""
本地模型服务 GPU 占用门控 —— 给 NPU 批处理任务让路

用途：NPU 批处理（建索引 / 批量翻译 / 批量抽取）运行时会抢占 UMA 带宽，
     实测 GPU decode 满载掉 12.7%。批处理应只在 GPU 空闲时跑。

判据（同时满足才算空闲）：
  1. 8080 的 /slots 无 is_processing=true
  2. 最近 idle 秒内没有新的推理活动（按各 slot 的 next_token 时间戳推算）
  3. host MemAvailable >= 阈值

用法：
  python3 npu-idle-gate.py                # 空闲退出 0，忙退出 1
  python3 npu-idle-gate.py --wait 600     # 最多等 600 s
  python3 npu-idle-gate.py --quiet        # 不打印

配合 shell：
  python3 npu-idle-gate.py --wait 1800 && python3 npu-sidecar.py embed big.txt --out idx.json
"""

import argparse
import json
import sys
import time
import urllib.request


def _get(url, timeout=5):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.load(r)


def _memavail_mib():
    with open("/proc/meminfo") as f:
        for line in f:
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) // 1024
    return 0


def gpu_busy(idle_s=15):
    """返回 (busy: bool, 原因: str)"""
    try:
        slots = _get("http://127.0.0.1:8080/slots")
    except Exception as e:
        return False, "8080 不可达（%s）→ 视为空闲" % type(e).__name__

    for s in slots:
        if s.get("is_processing"):
            return True, "slot %s 正在推理" % s.get("id", "?")
    # next_token 在本 fork 里是数组（逐槽），且 t_* 为进程内单调时钟，
    # 无法与 wall clock 比较 → 只用 is_processing 判活跃，配合 --idle 连续采样。
    return False, "所有 slot 空闲"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wait", type=int, default=0, help="最多等待秒数，0=只查一次")
    ap.add_argument("--idle", type=int, default=15, help="需连续空闲的秒数")
    ap.add_argument("--min-mem", type=int, default=4096, help="host MemAvailable 下限 MiB")
    ap.add_argument("--interval", type=int, default=5)
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()

    t_end = time.time() + a.wait
    idle_since = None
    while True:
        busy, why = gpu_busy(a.idle)
        mem = _memavail_mib()
        low = mem < a.min_mem
        ok = (not busy) and (not low)
        if ok:
            idle_since = idle_since or time.time()
        else:
            idle_since = None
        if not a.quiet:
            print("[%s] GPU=%s（%s） MemAvailable=%d MiB 已空闲 %.0fs"
                  % (time.strftime("%H:%M:%S"), "忙" if busy else "空闲", why, mem,
                     time.time() - idle_since if idle_since else 0), file=sys.stderr)
        if ok and time.time() - idle_since >= a.idle:
            return 0
        if time.time() + a.interval > t_end:
            if not a.quiet:
                print("[WAIT] 超时未等到空闲窗口", file=sys.stderr)
            return 1
        time.sleep(a.interval)


if __name__ == "__main__":
    sys.exit(main())
