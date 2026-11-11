#!/usr/bin/env python3
# 许可：CC0-1.0，公共领域贡献，无任何限制。
"""按需把「tools + system prompt」前缀预置到 llama-server 的槽里。

===============================================================================
2026-11-11 重写说明（v2）
===============================================================================
v1（2026-11-09）硬编码的是 docproxy *disclosure 模式*的 catalog prompt
（2671 token）。但 18090 当前跑的是 passthrough，那段 prompt 根本不进
WorkBuddy 的真实请求 —— 它与真实请求的最长公共前缀 = 0，预热收益 = 0。
v1 在 11-10 03:38 → 11-11 04:56 连续跑了 1519 次、1519 次全部 cache_n=2685
（自己命中自己），且让用户槽长期停在 2689 token，是纯负优化。已停 cron。

v2 改为：从 docproxy 的请求快照（DUMP_PROMPT）里提取**真实请求形态**重放。

--------------------------------------------------------------------------
实测数据（2026-11-11，Qwen3.6-35B-A3B Q5_K_P，-c 262144）
--------------------------------------------------------------------------
  真实请求 prompt_n            ≈ 40,210    (tools 22~23 个 + system 54,321 字符)
  冷 prefill 40K               52.7 s      (≈ 463 t/s，长上下文实测值)
  槽内 LCP 命中                0.81 s      (cache_n = 40,206，65×)
  cache-ram 恢复               9.9 s       (5.3×)
  tools JSON 键顺序影响        < 0.2%      (prompt_n 40,210 → 40,164)
    → Jinja 的 `tools | tojson` 已按键排序，preload 可自由重建 tools 对象

--------------------------------------------------------------------------
核心结论（决定了本脚本的默认行为）
--------------------------------------------------------------------------
只要槽里存在过**任意一次真实请求**，tools+system 就已经在槽内，
新会话首请求会自动 LCP 命中 40K —— 不需要预加载。

真正需要补位的只有「槽真空」这一种情况：
  · llama-server 刚重启
  · 有人 POST /slots/N?action=erase
  · 槽被一条不带 tools 的短请求（探活、连通性测试）冲掉

所以默认行为是【严格守卫】：槽忙、或槽内有真实会话时，一律跳过，
绝不覆盖用户的 100K 会话（覆盖的代价是 ~80 s 的 prompt_save）。

===============================================================================
用法
===============================================================================
  python3 tools/preload_system_prompt.py --stats      # 只看快照统计，不发请求
  python3 tools/preload_system_prompt.py --dry-run    # 打印决策，不发请求
  python3 tools/preload_system_prompt.py              # 守卫通过才预热
  python3 tools/preload_system_prompt.py --force      # 无视守卫强制覆盖槽
  python3 tools/preload_system_prompt.py --profile latest   # 用最新形态（默认）
  python3 tools/preload_system_prompt.py --profile mode     # 用出现最多的形态

不挂 cron。需要时手动跑一次即可。
===============================================================================
"""

import argparse
import json
import os
import sys
import time
import urllib.request
from collections import Counter

# ---------- 配置 ----------
BASE_URL = "http://127.0.0.1:8080"
DUMP_DIR = "/home/<user>/.cache/docproxy_prompt_dump"
STATE_FILE = "/tmp/preload_state.json"

# 预置槽里的那条占位 user 消息；长度固定，便于比对"槽里是不是我的内容"
HEARTBEAT = "preload_heartbeat"
# 判定"槽里是 preload 自己"的容差（token）
SELF_TOL = 8


# ---------- 快照读取 ----------
def load_dump():
    path = os.path.join(DUMP_DIR, "requests.jsonl")
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return rows


def pick_profile(rows, mode="latest"):
    """挑一个真实请求形态。只考虑带 tools 且有 system 的请求。"""
    cand = [r for r in rows if r.get("tools_n") and r.get("sys_chars", 0) > 500]
    if not cand:
        return None
    if mode == "mode":
        cnt = Counter((r["tools_sha"], r["sys_sha"]) for r in cand)
        t, s = cnt.most_common(1)[0][0]
        hits = [r for r in cand if r["tools_sha"] == t and r["sys_sha"] == s]
        return hits[-1]
    return cand[-1]


def build_payload(profile):
    """按快照还原一份最小可复现的请求体：tools + system + 占位 user。

    注意：不重放历史 messages —— 那会把 100K 历史灌进 prefill，
    而且历史每轮都变，对新会话毫无价值。稳定前缀只有 tools + system。
    """
    tools_path = os.path.join(DUMP_DIR, f"tools_{profile['tools_sha']}.json")
    sys_path = os.path.join(DUMP_DIR, f"sys_{profile['sys_sha']}.txt")
    if not (os.path.exists(tools_path) and os.path.exists(sys_path)):
        raise FileNotFoundError(
            f"快照文件缺失：tools={os.path.exists(tools_path)} sys={os.path.exists(sys_path)}"
        )
    with open(tools_path, encoding="utf-8") as f:
        tools = json.load(f)
    with open(sys_path, encoding="utf-8") as f:
        sys_content = f.read()

    return {
        "model": profile.get("model"),
        "tools": tools,
        "messages": [
            {"role": "system", "content": sys_content},
            {"role": "user", "content": HEARTBEAT},
        ],
        "max_tokens": 1,
        "temperature": 0,
        "cache_prompt": True,
        "stream": False,
    }


# ---------- 槽状态 ----------
def get_slots():
    with urllib.request.urlopen(BASE_URL + "/slots", timeout=10) as r:
        return json.loads(r.read())


def read_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def write_state(obj):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(obj, f)
    except OSError:
        pass


def decide(force=False):
    """返回 (是否预热, 原因)。"""
    if force:
        return True, "强制模式（--force）"
    try:
        slots = get_slots()
    except Exception as e:
        return False, f"读不到 /slots：{e}"
    if not slots:
        return False, "/slots 为空"
    if any(s.get("is_processing") for s in slots):
        return False, "槽正在处理请求"
    n = slots[0].get("n_prompt_tokens", 0) or 0
    if n == 0:
        return True, "槽为空，可安全补位"
    last = read_state().get("n_prompt_tokens")
    if last is not None and abs(n - last) <= SELF_TOL:
        return False, f"槽内已是 preload 内容（{n} tok），无需重复"
    return False, f"槽内有真实会话（{n} tok），不覆盖"


# ---------- 预热 ----------
def preheat(payload):
    req = urllib.request.Request(
        BASE_URL + "/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=900) as r:
        resp = json.loads(r.read())
    wall = time.time() - t0
    t = resp.get("timings", {})

    # 预热后槽里应正好是这份内容，记下来供下次比对
    n_after = 0
    try:
        slots = get_slots()
        n_after = slots[0].get("n_prompt_tokens", 0) or 0
    except Exception:
        pass
    write_state({
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "n_prompt_tokens": n_after,
        "prompt_n": t.get("prompt_n"),
        "cache_n": t.get("cache_n"),
        "wall_s": round(wall, 2),
    })
    return t, wall, n_after


def cmd_warm_all(rows, force=False):
    """把快照里出现过的**每一个** (tools, system) 版本依次预热进 cache-ram。

    为什么需要：
      tools / system 任一字符变化，LCP 立刻断在 tools 段 → cache_n=0 → 全量
      prefill（40K 实测 45 s）。但一旦该版本进过一次 cache-ram，后续每次切换
      都是 7.6 s（实测 A↔C 四个来回全部命中）。
    所以「版本漂移」的真正代价只有**每个版本首次出现的那一次 45 s**。
    服务重启后跑一次本命令，把所有已知版本灌进 cache-ram，之后都是 7.6 s。
    """
    real = [r for r in rows if r.get("tools_n") and r.get("sys_chars", 0) > 500]
    if not real:
        print("[SKIP] 快照里没有带 tools+system 的请求")
        return 0

    cnt = Counter((r["tools_sha"], r["sys_sha"]) for r in real)
    latest = {}
    for r in real:
        latest[(r["tools_sha"], r["sys_sha"])] = r  # 后来的覆盖 → 取最新样本
    order = sorted(latest, key=lambda k: -cnt[k])

    print(f"[WARM-ALL] 共 {len(order)} 个版本，按出现次数降序处理")
    hit = miss = fail = 0
    t_all = time.time()

    for i, key in enumerate(order, 1):
        tools_sha, sys_sha = key
        prof = latest[key]
        try:
            payload = build_payload(prof)
        except FileNotFoundError as e:
            print(f"  [{i}/{len(order)}] 跳过 tools={tools_sha}: {e}")
            fail += 1
            continue

        # 忙则等一等，别和真实请求抢槽
        for _ in range(20):
            try:
                if not any(s.get("is_processing") for s in get_slots()):
                    break
            except Exception:
                pass
            time.sleep(3)

        try:
            tim, wall, n_after = preheat(payload)
        except Exception as e:
            print(f"  [{i}/{len(order)}] 失败 tools={tools_sha}: {e}")
            fail += 1
            continue

        cache_n = tim.get("cache_n") or 0
        if cache_n > 0:
            hit += 1
        else:
            miss += 1
        print(f"  [{i}/{len(order)}] tools={tools_sha} sys={sys_sha} "
              f"tools_n={prof['tools_n']} sys_chars={prof['sys_chars']} → "
              f"cache_n={cache_n} prefill={tim.get('prompt_ms', 0)/1000:.1f}s wall={wall:.1f}s")

    print(f"[WARM-ALL] 完成：{hit} 个已命中 / {miss} 个新灌入 / {fail} 个失败，"
          f"总耗时 {time.time() - t_all:.1f}s")
    return 0


def cmd_stats(rows):
    print(f"快照目录: {DUMP_DIR}")
    print(f"请求总数: {len(rows)}")
    if not rows:
        return
    print(f"时间跨度: {rows[0].get('ts')} → {rows[-1].get('ts')}")
    print()
    real = [r for r in rows if r.get("tools_n") and r.get("sys_chars", 0) > 500]
    print(f"带 tools+system 的真实请求: {len(real)} / {len(rows)}")
    print()
    print("形态分布（tools_sha / sys_sha → 次数）：")
    cnt = Counter((r["tools_sha"], r["sys_sha"]) for r in real)
    for (t, s), c in cnt.most_common(10):
        sample = next(x for x in real if x["tools_sha"] == t and x["sys_sha"] == s)
        print(f"  tools={t} sys={s}  {c:3d} 次  tools_n={sample['tools_n']} "
              f"sys_chars={sample['sys_chars']}")
    print()
    bad = [r for r in rows if not r.get("tools_n") or r.get("sys_chars", 0) < 500]
    print(f"会冲掉槽前缀的短请求: {len(bad)} 条")
    for r in bad[:8]:
        print(f"  {r.get('ts')}  tools_n={r.get('tools_n')} sys_chars={r.get('sys_chars')} "
              f"n_msg={r.get('n_msg')} model={str(r.get('model'))[:50]}")
    if len(bad) > 8:
        print(f"  … 另有 {len(bad) - 8} 条")


def main():
    ap = argparse.ArgumentParser(description="把 tools+system 前缀预置到 llama-server 槽")
    ap.add_argument("--stats", action="store_true", help="只输出快照统计")
    ap.add_argument("--dry-run", action="store_true", help="打印决策但不发请求")
    ap.add_argument("--force", action="store_true", help="无视守卫强制覆盖槽")
    ap.add_argument("--warm-all", action="store_true",
                    help="把快照里所有 (tools,system) 版本依次预热进 cache-ram")
    ap.add_argument("--profile", choices=["latest", "mode"], default="latest",
                    help="latest=最新形态（默认），mode=出现最多的形态")
    args = ap.parse_args()

    rows = load_dump()

    if args.stats:
        cmd_stats(rows)
        return 0

    if args.warm_all:
        return cmd_warm_all(rows, args.force)

    profile = pick_profile(rows, args.profile)
    if not profile:
        print("[SKIP] 快照里还没有带 tools 的真实请求，先让本地模型跑一次对话")
        return 0

    print(f"[PROFILE] {profile.get('ts')}  tools_n={profile['tools_n']} "
          f"sys_chars={profile['sys_chars']}  model={profile.get('model')}")

    ok, why = decide(args.force)
    print(f"[DECIDE] {'预热' if ok else '跳过'} — {why}")
    if not ok or args.dry_run:
        if args.dry_run:
            try:
                payload = build_payload(profile)
                print(f"[DRY-RUN] payload: tools={len(payload['tools'])} "
                      f"sys={len(payload['messages'][0]['content'])} 字符")
            except FileNotFoundError as e:
                print(f"[DRY-RUN][ERROR] {e}")
        return 0

    try:
        payload = build_payload(profile)
    except FileNotFoundError as e:
        print(f"[ERROR] {e}")
        return 1

    print(f"[SEND] tools={len(payload['tools'])} "
          f"sys={len(payload['messages'][0]['content'])} 字符")
    try:
        t, wall, n_after = preheat(payload)
    except Exception as e:
        print(f"[ERROR] 预热失败：{e}")
        return 1

    print(f"[DONE] wall={wall:.2f}s prompt_n={t.get('prompt_n')} "
          f"cache_n={t.get('cache_n')} prefill={t.get('prompt_ms', 0)/1000:.2f}s "
          f"槽内 n_prompt_tokens={n_after}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
