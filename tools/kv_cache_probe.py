#!/usr/bin/env python3
# 许可：CC0-1.0，公共领域贡献，无任何限制。
# -*- coding: utf-8 -*-
"""kv_cache_probe.py — 查看 llama-server 的 prompt cache / KV 槽状态

背景：llama-server **没有**枚举缓存条目的 REST 端点。
  - /slots   只有当前槽（id / n_ctx / n_prompt_tokens），不含历史条目
  - /metrics 只有累计计数（prompt_tokens_cached_total 等）
  - 逐条明细只在 TRACE 日志里（tools/server/server-task.cpp:1896-1900）：
         - cache state: N prompts, X MiB (limits: L MiB, T tokens, E est)
           - prompt 0xADDR:  100147 tokens, checkpoints: 12,  1220.338 MiB
    且**只有 token 数 / checkpoint 数 / 体积，没有文本内容**。
    要看必须给 llama-server 加 `-lv 4`（或 `--log-verbosity 4`）并重启。

用法：
  python3 tools/kv_cache_probe.py                    # 汇总视图（不需重启）
  python3 tools/kv_cache_probe.py --log /tmp/x.log   # 解析 TRC 日志里的条目表
  python3 tools/kv_cache_probe.py --json             # 机器可读输出

VRAM 基线：模型 + KV + compute 的空载占用，用于反推缓存实际吃掉多少。
  本机 Q5_K_P + MTP draft 实测 33.33 GiB；换模型时用 --base-gib 覆盖。
"""

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request

DEFAULT_HOST = "http://127.0.0.1:8080"
VRAM_TOTAL = 96.0 * 2 ** 30          # BIOS UMA carve-out，字节
DEFAULT_BASE_GIB = 33.33             # 空载基线（模型+KV+compute），本机实测


def get_json(url, timeout=3):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.load(r)
    except Exception:
        return None


def vram_used_bytes():
    """rocm-smi 读显存；非交互必须 < /dev/null，否则本机会卡死。"""
    try:
        out = subprocess.run(
            ["rocm-smi", "--showmeminfo", "vram"],
            capture_output=True, text=True, timeout=10, stdin=subprocess.DEVNULL,
        ).stdout
    except Exception:
        return None
    for line in out.splitlines():
        if "Used Memory (B)" in line:
            return int(line.split(":")[-1].strip())
    return None


def parse_metrics(text):
    """从 /metrics 取需要的计数。"""
    want = {
        "llamacpp:prompt_tokens_total": "新算 token 累计",
        "llamacpp:prompt_tokens_cached_total": "命中缓存 token 累计",
        "llamacpp:prompt_seconds_total": "prefill 累计秒",
        "llamacpp:tokens_predicted_total": "生成 token 累计",
    }
    out = {}
    for line in (text or "").splitlines():
        if line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[0] in want:
            try:
                out[parts[0]] = float(parts[1])
            except ValueError:
                pass
    return out


def parse_log(path):
    """解析 TRACE 日志，返回 (最后一次 cache state 汇总, 条目列表, 淘汰事件数)。"""
    if not os.path.isfile(path):
        return None, [], 0
    with open(path, encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    summary = None
    entries = []
    evicted = 0
    cur = []          # 当前正在累积的条目
    for line in lines:
        if "removing oldest entry" in line:
            evicted += 1
        m = re.search(
            r"cache state:\s*(\d+)\s*prompts,\s*([\d.]+)\s*MiB\s*"
            r"\(limits:\s*([\d.]+)\s*MiB,\s*(\d+)\s*tokens,\s*(\d+)\s*est\)", line)
        if m:
            summary = {
                "prompts": int(m.group(1)),
                "size_mib": float(m.group(2)),
                "limit_mib": float(m.group(3)),
                "limit_tokens": int(m.group(4)),
                "limit_tokens_est": int(m.group(5)),
            }
            cur = []
            continue
        m = re.search(
            r"- prompt (0x[0-9a-fA-F]+):\s*(\d+) tokens,\s*checkpoints:\s*(\d+),\s*([\d.]+) MiB", line)
        if m:
            cur.append({
                "addr": m.group(1),
                "tokens": int(m.group(2)),
                "checkpoints": int(m.group(3)),
                "mib": float(m.group(4)),
            })
            continue
        # 条目块结束后把 cur 固化（遇到非条目行即认为块结束）
        if cur and "prompt " not in line:
            entries = cur
            cur = []
    if cur:
        entries = cur
    return summary, entries, evicted


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--log", help="llama-server 的 TRC 日志路径（需 -lv 4）")
    ap.add_argument("--base-gib", type=float, default=DEFAULT_BASE_GIB,
                    help=f"空载 VRAM 基线 GiB（默认 {DEFAULT_BASE_GIB}）")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    slots = get_json(args.host + "/slots") or []
    try:
        with urllib.request.urlopen(args.host + "/metrics", timeout=3) as r:
            metrics = parse_metrics(r.read().decode("utf-8", "replace"))
    except Exception:
        metrics = {}
    vused = vram_used_bytes()
    summary, entries, evicted = parse_log(args.log) if args.log else (None, [], 0)

    cached_gib = None
    if vused is not None:
        cached_gib = vused / 2 ** 30 - args.base_gib

    new_tok = metrics.get("llamacpp:prompt_tokens_total", 0)
    hit_tok = metrics.get("llamacpp:prompt_tokens_cached_total", 0)
    hit_rate = (hit_tok / (hit_tok + new_tok) * 100) if (hit_tok + new_tok) else 0.0

    if args.json:
        print(json.dumps({
            "vram_used_gib": None if vused is None else round(vused / 2 ** 30, 2),
            "vram_total_gib": round(VRAM_TOTAL / 2 ** 30, 2),
            "cache_gib": None if cached_gib is None else round(cached_gib, 2),
            "slots": [{"id": s.get("id"), "n_ctx": s.get("n_ctx"),
                       "n_prompt_tokens": s.get("n_prompt_tokens")} for s in slots],
            "metrics": metrics, "hit_rate_pct": round(hit_rate, 1),
            "cache_state": summary, "entries": entries, "evicted_events": evicted,
        }, ensure_ascii=False, indent=2))
        return 0

    print("=" * 62)
    print("llama-server prompt cache / KV 槽状态")
    print("=" * 62)

    if vused is None:
        print("  VRAM        : 读取失败")
    else:
        print(f"  VRAM        : {vused / 2**30:6.2f} GiB 已用 / {VRAM_TOTAL / 2**30:.0f} GiB"
              f"  ({vused / VRAM_TOTAL * 100:.1f}%)")
        print(f"  其中缓存    : {cached_gib:6.2f} GiB"
              f"（基线 {args.base_gib:.2f} GiB + 缓存）")

    print(f"  累计新算    : {new_tok:,.0f} tokens")
    print(f"  累计命中    : {hit_tok:,.0f} tokens")
    print(f"  命中率      : {hit_rate:.1f}%")

    print("-" * 62)
    if slots:
        for s in slots:
            print(f"  槽 {s.get('id')}  n_ctx={s.get('n_ctx')}  "
                  f"当前 prompt={s.get('n_prompt_tokens')} tokens  "
                  f"processing={s.get('is_processing')}")
    else:
        print("  槽信息不可读")

    print("-" * 62)
    if summary:
        print(f"  缓存条目    : {summary['prompts']} 条，{summary['size_mib']:.1f} MiB")
        print(f"  上限        : {summary['limit_mib']:.0f} MiB / "
              f"{summary['limit_tokens']} tokens（动态估 {summary['limit_tokens_est']}）")
        print(f"  淘汰事件    : {evicted} 次（日志中出现 removing oldest entry）")
        if entries:
            print(f"\n  {'地址':<14}{'tokens':>10}{'ckpt':>6}{'体积 MiB':>12}{'等效每千token':>14}")
            for e in entries:
                per_k = e["mib"] / (e["tokens"] / 1000) if e["tokens"] else 0
                print(f"  {e['addr']:<14}{e['tokens']:>10}{e['checkpoints']:>6}"
                      f"{e['mib']:>12.1f}{per_k:>14.1f}")
    else:
        print("  条目明细    : 不可见")
        print("    原因：llama-server 默认 -lv 3，SRV_TRC 行不输出；且无 REST 端点枚举。")
        print("    启用：启动参数加 `-lv 4`，重启后用 --log <日志路径> 重跑本工具。")
        if cached_gib and cached_gib > 0.5:
            print(f"    旁证：VRAM 增量 {cached_gib:.2f} GiB ≈ "
                  f"{cached_gib / 1.22:.1f} 条 100K 条目（按实测 1.22 GiB/条）")
    print("=" * 62)
    return 0


if __name__ == "__main__":
    sys.exit(main())
