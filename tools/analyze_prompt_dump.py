#!/usr/bin/env python3
# 许可：CC0-1.0，公共领域贡献，无任何限制。
"""分析 docproxy 请求快照，估算「定向预加载」的真实收益。

数据源
  $DUMP_DIR/requests.jsonl   每次 /v1/chat/completions 一行元数据
  $DUMP_DIR/sys_<sha>.txt    每个新 system prompt 指纹的首份全文
  $DUMP_DIR/tools_<sha>.json 每个新 tools 定义指纹的首份全文
  （由 tools/docproxy.py 在 DUMP_PROMPT=1 时写入，2026-11-11 起）

用法
  python3 tools/analyze_prompt_dump.py                # 汇总 + 前缀估算
  python3 tools/analyze_prompt_dump.py --tokenize     # 调 /tokenize 换算精确 token 数
  python3 tools/analyze_prompt_dump.py --top 5        # 只看出现最多的前 5 个 system 版本
  python3 tools/analyze_prompt_dump.py --dir /path    # 指定落点目录

判定口径
  稳定前缀 = 全部请求的 (tools + system) 渲染文本的最长公共前缀。
  收益     = 稳定前缀 token 数 ÷ 冷 prefill 速率（本机长上下文实测 463 t/s）。
  阈值     = 稳定前缀 < 2000 token 时不值得预加载（每分钟踢槽的代价更大）。
"""

import argparse
import collections
import json
import os
import sys
import urllib.request

DEFAULT_DIR = os.environ.get("DUMP_DIR", os.path.expanduser("~/.cache/docproxy_prompt_dump"))
TOKENIZE_URL = "http://127.0.0.1:8080/tokenize"
COLD_PREFILL_TPS = 463.0   # 本机 100K 上下文实测（2026-11-09），勿用 27.8K 的 935


def longest_common_prefix(texts):
    """返回全部 texts 的最长公共前缀（字符级）。"""
    if not texts:
        return ""
    shortest = min(texts, key=len)
    for i, ch in enumerate(shortest):
        for other in texts:
            if other[i] != ch:
                return shortest[:i]
    return shortest


def count_tokens(text):
    """调 llama-server /tokenize 换算 token 数；失败返回 None。"""
    if not text:
        return 0
    try:
        req = urllib.request.Request(
            TOKENIZE_URL,
            data=json.dumps({"content": text}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            return len(json.loads(resp.read()).get("tokens", []))
    except Exception as e:
        print(f"[WARN] tokenize 失败: {e}", file=sys.stderr)
        return None


def load_dump(dump_dir):
    req_path = os.path.join(dump_dir, "requests.jsonl")
    if not os.path.exists(req_path):
        return None, []

    rows = []
    with open(req_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    def read(path):
        try:
            with open(path, encoding="utf-8") as f:
                return f.read()
        except OSError:
            return ""

    for r in rows:
        r["sys"] = read(os.path.join(dump_dir, f"sys_{r.get('sys_sha', '')}.txt"))
        r["tools"] = read(os.path.join(dump_dir, f"tools_{r.get('tools_sha', '')}.json"))
        # 近似 chat template 渲染顺序：tools 段在前，system 段在后
        r["head"] = (r["tools"] + "\n" + r["sys"]).strip()

    return req_path, rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=DEFAULT_DIR)
    ap.add_argument("--top", type=int, default=8)
    ap.add_argument("--tokenize", action="store_true")
    args = ap.parse_args()

    req_path, rows = load_dump(args.dir)
    if req_path is None:
        print(f"[ERROR] 未找到 {os.path.join(args.dir, 'requests.jsonl')}")
        print("        确认 docproxy 以 DUMP_PROMPT=1 运行，且已有真实请求经过 18090。")
        return 1
    if not rows:
        print("[ERROR] requests.jsonl 为空")
        return 1

    print(f"数据源   {req_path}")
    print(f"请求总数 {len(rows)}")
    span = (rows[0].get("ts", "?"), rows[-1].get("ts", "?"))
    print(f"时间跨度 {span[0]} → {span[1]}")

    # ---- system prompt 稳定性 ----
    sys_groups = collections.Counter(r.get("sys_sha", "") for r in rows)
    tools_groups = collections.Counter(r.get("tools_sha", "") for r in rows)
    print(f"\nsystem 版本数 {len(sys_groups)}   tools 版本数 {len(tools_groups)}")
    print(f"{'占比':>7}  {'次数':>6}  {'字符':>7}  sha")
    for sha, cnt in sys_groups.most_common(args.top):
        sample = next(r for r in rows if r.get("sys_sha") == sha)
        print(f"{cnt/len(rows)*100:6.1f}%  {cnt:6d}  {sample.get('sys_chars', 0):7d}  {sha}")

    # ---- 稳定前缀 ----
    heads = [r["head"] for r in rows if r["head"]]
    lcp_all = longest_common_prefix(heads)

    main_sha = sys_groups.most_common(1)[0][0]
    heads_main = [r["head"] for r in rows if r.get("sys_sha") == main_sha and r["head"]]
    lcp_main = longest_common_prefix(heads_main) if heads_main else ""

    print(f"\n{'前缀口径':<28} {'字符':>8} {'token':>8} {'省时':>8}")
    print("-" * 58)

    for label, text in (("全体最长公共前缀", lcp_all),
                        (f"众数版本内前缀({main_sha[:8]})", lcp_main)):
        tok = count_tokens(text) if args.tokenize else None
        tok_disp = f"{tok:8d}" if tok is not None else "      --"
        save = f"{tok/COLD_PREFILL_TPS:7.1f}s" if tok else "      --"
        print(f"{label:<28} {len(text):8d} {tok_disp} {save:>8}")

    if args.tokenize:
        tok_all = count_tokens(lcp_all) or 0
        print()
        if tok_all < 2000:
            print(f"[判定] 稳定前缀仅 {tok_all} token → 不值得预加载。"
                  f"每分钟 preload 会踢槽，100K 会话每次 restore 12–14 s，纯负收益。")
        else:
            print(f"[判定] 稳定前缀 {tok_all} token → 值得定向预加载，"
                  f"每新会话可省 {tok_all/COLD_PREFILL_TPS:.1f} s。")
    else:
        print("\n提示：加 --tokenize 可换算精确 token 数并给出判定。")

    # ---- system prompt 分节结构（判断哪一段在变）----
    if main_sha:
        sample = next(r for r in rows if r.get("sys_sha") == main_sha)
        heads_lines = [ln for ln in sample["sys"].splitlines() if ln.startswith("#")]
        if heads_lines:
            print("\n众数 system 的一级/二级标题（共 %d 个）：" % len(heads_lines))
            for ln in heads_lines[:24]:
                print("  " + ln[:100])

    return 0


if __name__ == "__main__":
    sys.exit(main())
