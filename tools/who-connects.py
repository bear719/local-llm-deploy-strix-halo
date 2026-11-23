#!/usr/bin/env python3
# 许可：CC0-1.0，公共领域贡献，无任何限制。
# -*- coding: utf-8 -*-
"""
who-connects.py —— 只读监控：谁在连接本机模型端口

判据来源：
  - ss -tnp（需 root 才能看他人进程名）
  - /opt/mcsmanager/daemon/data/InstanceLog/<uuid>.log（llama / docproxy 实例日志）

能力边界（务必知悉）：
  - 本机侧只能看到「frpc 进程」或「本地应用进程」发起的连接。
    经 frp 公网穿透进来的流量，到达本机时源地址恒为 127.0.0.1，
    真实公网 IP 只存在于 frps 服务器（<公网服务器IP>）的日志里。
  - llama-server 不记录 access log（不含 IP、不含 payload），只有 slot 计时行。
  - 对话全文仅 docproxy(18090) 在 DUMP_PROMPT=1 时留存：$DUMP_DIR/bag_<sha>.json

用法：
  ./who-connects.py                # 持续监控，每 2 秒差分打印新连接
  ./who-connects.py --once         # 只打印当前连接快照后退出
  ./who-connects.py --dump 20      # 附带导出最近 20 条 docproxy 请求元数据
"""
import argparse
import json
import os
import subprocess
import sys
import time

PORTS = {
    8080: "llama-server(真模型)",
    18090: "docproxy(代理)",
    8219: "flm(NPU)",
    8099: "anthropic 桥",
    8081: "localrouter",
}

INSTANCE_LOG = {
    8080: "/opt/mcsmanager/daemon/data/InstanceLog/9770784bb1f940ada5c5890fd003efb3.log",
    18090: "/opt/mcsmanager/daemon/data/InstanceLog/d81ea6096b1c46709f9d9b43fc8137f7.log",
    8219: "/opt/mcsmanager/daemon/data/InstanceLog/5fe3f03bbc624c519564ec120b071160.log",
}

DUMP_DIR = os.environ.get("DUMP_DIR", "/home/<user>/.cache/docproxy_prompt_dump")


def run(cmd):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
        return r.stdout
    except Exception:
        return ""


def parse_ss():
    """返回 [(local_ip, local_port, peer_ip, peer_port, proc_name, pid)]"""
    out = run(["sudo", "-n", "ss", "-tnpH", "state", "established"])
    rows = []
    for line in out.splitlines():
        if "users:" not in line:
            continue
        parts = line.split()
        try:
            i = parts.index("users:(")
        except ValueError:
            continue
        local, peer = parts[3], parts[4]
        li, lp = local.rsplit(":", 1)
        pi, pp = peer.rsplit(":", 1)
        proc = parts[i + 1]
        name = ""
        pid = ""
        if '"' in proc:
            name = proc.split('"')[1]
        if "pid=" in proc:
            pid = proc.split("pid=")[1].split(",")[0].strip(")")
        rows.append((li, int(lp), pi, int(pp), name, pid))
    return rows


def owner_of(rows, ip, port):
    """反查某个 (ip,port) 由哪个进程持有"""
    for li, lp, pi, pp, name, pid in rows:
        if lp == port and li == ip:
            return name, pid
    return "?", "?"


def snapshot():
    rows = parse_ss()
    res = []
    for li, lp, pi, pp, name, pid in rows:
        if lp in PORTS:
            src_proc, src_pid = owner_of(rows, pi, pp)
            via_frp = src_proc in ("frpc", "frps")
            res.append({
                "port": lp,
                "service": PORTS[lp],
                "server_proc": name,
                "peer": f"{pi}:{pp}",
                "src_proc": src_proc,
                "src_pid": src_pid,
                "origin": "外部经frp(真实IP在frps)" if via_frp else "本地进程",
            })
    return res


def fmt(item):
    return (f"[{time.strftime('%H:%M:%S')}] :{item['port']} {item['service']} "
            f"<- {item['peer']} 来源={item['origin']} 客户端进程={item['src_proc']}({item['src_pid']})")


def dump_recent(n):
    p = os.path.join(DUMP_DIR, "requests.jsonl")
    if not os.path.exists(p):
        print(f"[WARN] 无转储文件 {p}")
        return
    lines = [l for l in open(p, errors="replace") if l.strip().startswith("{")]
    print(f"\n=== docproxy 最近 {n} 条请求（全文在 bag_<sha>.json）===")
    for l in lines[-n:]:
        try:
            d = json.loads(l)
        except Exception:
            continue
        head = (d.get("sys_head") or "(无system)").replace("\n", " ")[:48]
        print(f"{d.get('ts')} {d.get('path')} n_msg={d.get('n_msg')} "
              f"chars={d.get('msgs_chars')} bag={d.get('bag_sha')} | {head}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="只打印一次快照")
    ap.add_argument("--dump", type=int, default=0, help="导出最近 N 条 docproxy 请求元数据")
    ap.add_argument("--interval", type=float, default=2.0)
    a = ap.parse_args()

    if a.dump:
        dump_recent(a.dump)

    if a.once:
        snap = snapshot()
        if not snap:
            print("当前无活动连接（各端口均空闲）")
        for it in snap:
            print(fmt(it))
        return

    print(f"监控中：{sorted(PORTS)}，Ctrl-C 结束")
    seen = set()
    try:
        while True:
            for it in snapshot():
                key = (it["port"], it["peer"], it["src_pid"])
                if key not in seen:
                    seen.add(key)
                    print(fmt(it))
            # 清理已断开
            live = {(it["port"], it["peer"], it["src_pid"]) for it in snapshot()}
            seen &= live
            time.sleep(a.interval)
    except KeyboardInterrupt:
        print("\n结束")


if __name__ == "__main__":
    main()
