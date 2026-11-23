#!/usr/bin/env python3
# 许可：CC0-1.0，公共领域贡献，无任何限制。
# -*- coding: utf-8 -*-
"""
NPU 健康探针 —— 输出 Prometheus textfile 格式（或人类可读）

指标：
  npu_up                      1/0         栈是否 ready（flm validate .ready）
  npu_fw_ok                   1/0         FW 版本是否匹配
  npu_cols                    int         可用 column 数（8 = 正常）
  npu_platform_info           1{platform="aie2p"}
  npu_power_state             1{state="D0"}
  npu_link_speed_gts          float       PCIe 链路速率
  npu_link_width              int
  npu_kernel_info             1{kernel="7.0.0-43-generic"}
  npu_probe_seconds           float       探针自身耗时
  npu_serving                 1/0         8219 是否有响应

用法：
  python3 npu-health.py                 # 人类可读
  python3 npu-health.py --prom          # Prometheus 格式（写 textfile）
  python3 npu-health.py --prom --out /var/lib/node_exporter/textfile/npu.prom
  python3 npu-health.py --json

cron 示例（每 2 分钟）：
  */2 * * * * /usr/bin/python3 .../npu-health.py --prom --out /tmp/npu.prom

注意：温度与功耗（W）**取不到** —— amdxdna 无 hwmon 节点，xrt-smi 未安装。
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request

ACCEL = "/sys/class/accel/accel0/device"
NPU_URL = os.environ.get("NPU_URL", "http://127.0.0.1:8219")


def _read(path, default=""):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return default


def collect():
    t0 = time.time()
    d = {}
    # flm validate（最权威的 ready 判据）
    try:
        out = subprocess.run(["flm", "validate", "-j"], capture_output=True,
                             text=True, timeout=20).stdout
        v = json.loads(out)
        d["validate"] = v
        d["ready"] = bool(v.get("ready"))
        d["cols"] = int(v.get("devices", [{}])[0].get("cols", 0) or 0)
        d["fw_ok"] = bool(v.get("all_fw_ok"))
        fw = v.get("devices", [{}])[0]
        d["fw"] = "%s.%s.%s.%s" % (fw.get("fw_major"), fw.get("fw_minor"),
                                   fw.get("fw_patch"), fw.get("fw_build"))
        d["platform"] = v.get("npu_platform", "unknown")
        d["kernel"] = v.get("kernel", "unknown")
    except Exception as e:
        d["validate_error"] = "%s: %s" % (type(e).__name__, e)
        d["ready"] = False
        d["cols"] = 0
        d["fw_ok"] = False
        d["fw"] = "unknown"
        d["platform"] = "unknown"
        d["kernel"] = "unknown"

    d["power_state"] = _read(ACCEL + "/power_state", "unknown")
    try:
        d["link_speed"] = float(_read(ACCEL + "/current_link_speed").split()[0])
    except Exception:
        d["link_speed"] = 0.0
    try:
        d["link_width"] = int(_read(ACCEL + "/current_link_width"))
    except Exception:
        d["link_width"] = 0

    # 8219 是否在服务
    try:
        with urllib.request.urlopen(NPU_URL + "/v1/models", timeout=5) as r:
            r.read(64)
        d["serving"] = 1
    except Exception:
        d["serving"] = 0

    d["probe_seconds"] = round(time.time() - t0, 3)
    return d


def as_prom(d):
    L = []
    L.append("# HELP npu_up NPU 栈就绪（flm validate .ready）")
    L.append("# TYPE npu_up gauge")
    L.append("npu_up %d" % (1 if d["ready"] else 0))
    L.append("# HELP npu_fw_ok 固件版本校验通过")
    L.append("# TYPE npu_fw_ok gauge")
    L.append("npu_fw_ok %d" % (1 if d["fw_ok"] else 0))
    L.append("# HELP npu_cols 可用 AIE column 数")
    L.append("# TYPE npu_cols gauge")
    L.append("npu_cols %d" % d["cols"])
    L.append("# HELP npu_serving 8219 端口是否在服务")
    L.append("# TYPE npu_serving gauge")
    L.append("npu_serving %d" % d["serving"])
    L.append("# HELP npu_power_state 电源状态（D0 活动 / D3hot 休眠）")
    L.append("# TYPE npu_power_state gauge")
    L.append('npu_power_state{state="%s"} 1' % d["power_state"])
    L.append("# HELP npu_link_speed_gts PCIe 链路速率 GT/s")
    L.append("# TYPE npu_link_speed_gts gauge")
    L.append("npu_link_speed_gts %g" % d["link_speed"])
    L.append("# HELP npu_link_width PCIe 链路宽度")
    L.append("# TYPE npu_link_width gauge")
    L.append("npu_link_width %d" % d["link_width"])
    L.append("# HELP npu_info 静态标签")
    L.append("# TYPE npu_info gauge")
    L.append('npu_info{platform="%s",kernel="%s",fw="%s"} 1'
             % (d["platform"], d["kernel"], d["fw"]))
    L.append("# HELP npu_probe_seconds 探针耗时")
    L.append("# TYPE npu_probe_seconds gauge")
    L.append("npu_probe_seconds %g" % d["probe_seconds"])
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prom", action="store_true", help="Prometheus textfile 格式")
    ap.add_argument("--json", action="store_true", help="JSON")
    ap.add_argument("--out", help="写入文件（原子替换）")
    a = ap.parse_args()

    d = collect()
    if a.json:
        text = json.dumps(d, ensure_ascii=False, indent=2) + "\n"
    elif a.prom:
        text = as_prom(d)
    else:
        ok = "✅" if d["ready"] and d["serving"] else "❌"
        print("%s NPU  %s" % (ok, d.get("platform")))
        print("  ready        : %s" % d["ready"])
        print("  columns      : %d" % d["cols"])
        print("  固件         : %s（校验 %s）" % (d["fw"], "通过" if d["fw_ok"] else "失败"))
        print("  kernel       : %s" % d["kernel"])
        print("  电源状态     : %s" % d["power_state"])
        print("  链路         : %.1f GT/s × %d" % (d["link_speed"], d["link_width"]))
        print("  8219 服务    : %s" % ("在服务" if d["serving"] else "无响应"))
        print("  探针耗时     : %.3f s" % d["probe_seconds"])
        if d.get("validate_error"):
            print("  [ERROR] %s" % d["validate_error"])
        return 0 if (d["ready"] and d["serving"]) else 1

    if a.out:
        tmp = a.out + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, a.out)
    else:
        sys.stdout.write(text)
    return 0 if d["ready"] else 1


if __name__ == "__main__":
    sys.exit(main())
