#!/usr/bin/env python3
# 许可：CC0-1.0，公共领域贡献，无任何限制。
# -*- coding: utf-8 -*-
"""抓取连向指定端口的本机进程（高频采样），用于定位 401 轮询来源。

用法：
    sudo -n python3 tools/sniff-port.py 8080 180
    sudo -n python3 tools/sniff-port.py 8080 180 -v   # 每次命中都打印时间

依赖：psutil（系统 python3 已装）

配套：tools/who-connects.py 看谁在连模型端口；本脚本用高频采样补齐「短连接抓不到」的盲区。
穿透流量到本机源地址恒为 127.0.0.1，真实公网 IP 只在 frps 侧审计（tools/frps-audit.sh）。
"""
import sys
import time
import collections

try:
    import psutil
except ImportError:
    sys.exit("[ERROR] 缺少 psutil -> sudo apt install python3-psutil 或 pip install psutil")

port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
dur = int(sys.argv[2]) if len(sys.argv) > 2 else 120
verbose = "-v" in sys.argv

hits = collections.Counter()
first_seen = {}
samples = 0
end = time.time() + dur

while time.time() < end:
    samples += 1
    try:
        conns = psutil.net_connections(kind="tcp")
    except Exception as e:
        print(f"[WARN] 读取连接失败: {e}")
        time.sleep(0.5)
        continue
    for c in conns:
        if not c.raddr:
            continue
        if c.raddr.port != port:
            continue
        key = (c.pid, c.raddr.ip, c.laddr.port if c.laddr else 0)
        hits[key] += 1
        if key not in first_seen:
            first_seen[key] = time.strftime("%H:%M:%S")
            if verbose:
                print(f"[{first_seen[key]}] pid={c.pid} -> {c.raddr.ip}:{port}")
    time.sleep(0.1)

print(f"\n=== 采样 {dur}s，共 {samples} 轮，命中 {sum(hits.values())} 次 ===")
if not hits:
    print("  无连接命中（轮询间隔可能长于采样窗口）")
    sys.exit(0)

print(f"{'pid':>7} {'进程名':<22} {'命令':<45} {'对端':<18} {'首见':>9} {'命中':>5}")
for (pid, rip, lport), n in hits.most_common(20):
    try:
        p = psutil.Process(pid)
        name = p.name()
        cmd = " ".join(p.cmdline())[:44]
    except Exception:
        name, cmd = "?", "?"
    print(f"{str(pid):>7} {name:<22} {cmd:<45} {rip+':'+str(lport):<18} {first_seen[(pid,rip,lport)]:>9} {n:>5}")
