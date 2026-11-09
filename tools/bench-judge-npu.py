#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""judge 判定器「35B(iGPU) vs lfm2.5-1.2B(NPU)」一致性对比。

背景
----
OpenClaw 的分层路由链路是：

    OpenClaw → 8081(router.py) → judge.choice 定档 → cheap(18090) / reasoning(云端)

其中 judge 是**高频、短输入、只输出一个 JSON** 的调用，正是 NPU 小模型的
最佳落点；而 cheap 档承接「日常对话/改写/摘要」，绝不能换成 1.2B。

本脚本只回答一个问题：把 judge 迁到 NPU 后，**定档结论是否还和 35B 一致**。
不一致率高就不能迁，否则会把该上云端的复杂请求压回本地。

执行纪律（沿用 2026-11-08 压测教训）
------------------------------------
* 逐条 **A/B 交错** 执行，不做「先跑完 A 再跑 B」的整组分组（会撞冷态爬坡）。
* 只统计判定结果与单次延迟，不比较 t/s（judge 关心的是结论与响应快慢）。

用法
----
  python3 tools/bench-judge-npu.py
  python3 tools/bench-judge-npu.py --gpu 8080 --npu 8219 --repeat 1
"""

import argparse
import json
import statistics
import time
import urllib.error
import urllib.request

# 与 jev-local/judge.py 完全一致的提示词，保证比较的是同一任务
SYS_PROMPT = (
    "你是判断引擎，不是聊天助手。禁止输出任何解释、前后缀或 Markdown。"
    "只输出一个 JSON 对象，字段由用户消息指定。所有概率必须在 [0,1] 区间内。"
)
QUESTION = ("该请求应路由到哪个档位（cheap=日常对话/改写/摘要/简单问答；"
            "reasoning=复杂推理/数学/代码架构/多步规划/证明）")
THRESHOLD = 0.6  # 与 router.py 的 REASONING_THRESHOLD 一致

# 10 条明确该走 cheap，10 条明确该走 reasoning；各含一个「边界」样本
CASES = [
    ("cheap", "你好"),
    ("cheap", "帮我把这段话改得更简洁：今天天气不错，我早上八点起床，然后去了公园散步，"
              "看到很多人在跳广场舞，气氛非常热闹，我心情也变得很好。"),
    ("cheap", "把「我明天去哈尔滨」翻译成英文。"),
    ("cheap", "总结一下：本季度销售额同比增长 12%，主要来自华东区新开的三家门店，"
              "但毛利率因促销活动下降了 2 个百分点。"),
    ("cheap", "谢谢，辛苦了"),
    ("cheap", "把这封邮件改成更正式的语气：老板，那个报表我明天给你。"),
    ("cheap", "帮我列一个周末去超市要买的东西，做四菜一汤。"),
    ("cheap", "「饕餮」这两个字怎么读？"),
    ("cheap", "继续"),
    ("cheap", "下面这段日志有什么明显异常吗：INFO 服务启动成功 port=8080"),

    ("reasoning", "证明根号 2 是无理数。"),
    ("reasoning", "设计一个支持百万级并发的消息队列架构，说明分区策略与一致性取舍。"),
    ("reasoning", "求 f(x)=x^3-3x 的极值点，并说明二阶导数的判定过程。"),
    ("reasoning", "比较 B+ 树与 LSM 树在写放大上的差异，分别给出适用场景和理由。"),
    ("reasoning", "一个水池有甲乙两个进水管，甲单独注满需 6 小时，乙需 4 小时，"
                  "排水管丙单独排空需 12 小时。三管同开，多久注满？"),
    ("reasoning", "用动态规划求解最长回文子串，写出状态转移方程并分析复杂度。"),
    ("reasoning", "解释 CAP 定理，并论证为什么实际分布式系统只能在三者中取其二。"),
    ("reasoning", "分析这段代码的时间复杂度并指出性能瓶颈："
                  "for i in range(n):\\n    for j in range(i, n):\\n        s = sum(a[i:j+1])"),
    ("reasoning", "请分步骤论证：为什么 TCP 建立连接必须是三次握手而不能是两次。"),
    ("reasoning", "设计一个跨机房一致的分布式限流方案，需说明时钟偏差如何处理。"),
]

FMT = '{"choice": "<候选之一>", "probabilities": {"cheap": <0到1>, "reasoning": <0到1>}}'


def build_user(state: str) -> str:
    return (f"[判断类型]\nchoice\n\n"
            f"[问题]\n{QUESTION}\n\n"
            f"[输出格式]\n{FMT}\n\n"
            f"[状态]\n{state}")


def extract_json(text: str) -> dict:
    """与 judge.py 同款：逐起点 raw_decode，取第一个可解析对象。"""
    dec = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch == "{":
            try:
                obj, _ = dec.raw_decode(text[i:])
                if isinstance(obj, dict):
                    return obj
            except json.JSONDecodeError:
                continue
    raise ValueError("无可解析 JSON")


def call(port: int, state: str, model: str, max_tokens: int = 1024, timeout: int = 180):
    """返回 (choice, p_reasoning, 耗时秒, 错误)。

    model 必须按后端分别给：llama.cpp 单模型服务忽略该字段，但 flm 会拿它定位
    模型，发 "local" 会立刻 404（0.00s 失败的根因）。
    """
    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": SYS_PROMPT},
            {"role": "user", "content": build_user(state)},
        ],
        "temperature": 0.0,
        "max_tokens": max_tokens,
    }).encode()
    req = urllib.request.Request(
        "http://127.0.0.1:%d/v1/chat/completions" % port,
        data=payload, headers={"Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
        dt = time.time() - t0
        msg = data["choices"][0]["message"]
        txt = msg.get("content") or msg.get("reasoning_content") or ""
        out = extract_json(txt)
        p = float(out.get("probabilities", {}).get("reasoning", 0.0))
        c = out.get("choice")
        if c not in ("cheap", "reasoning"):
            return None, p, dt, "choice 非法: %r" % c
        return c, p, dt, None
    except Exception as e:  # noqa: BLE001
        return None, 0.0, time.time() - t0, "%s: %s" % (type(e).__name__, str(e)[:80])


def tier_of(p: float) -> str:
    return "reasoning" if p >= THRESHOLD else "cheap"


def main():
    ap = argparse.ArgumentParser(description="judge 定档一致性对比：35B vs 1.2B")
    ap.add_argument("--gpu", type=int, default=8080, help="35B 后端端口")
    ap.add_argument("--npu", type=int, default=8219, help="1.2B 后端端口")
    ap.add_argument("--gpu-model", default="local", help="35B 侧 model 字段（llama.cpp 忽略）")
    ap.add_argument("--npu-model", default="lfm2.5-it:1.2b", help="1.2B 侧 model 字段（flm 必填）")
    ap.add_argument("--max-tokens", type=int, default=1024, help="与 judge.py 一致默认 1024")
    a = ap.parse_args()

    print("=== judge 定档一致性：%d(%s) vs %d(%s)（阈值 %.1f）==="
          % (a.gpu, a.gpu_model, a.npu, a.npu_model, THRESHOLD))
    print("说明：逐条 A/B 交错执行，避免整组分组撞冷态；单次最大 %d token\n" % a.max_tokens)

    agree = total = 0
    gpu_lat, npu_lat = [], []
    gpu_err = npu_err = 0
    err_detail = {"35B": [], "1.2B": []}
    rows = []

    for idx, (expect, text) in enumerate(CASES, 1):
        # 交错：每条先 A 后 B，且顺序按索引奇偶对调，进一步抵消先后偏差
        if idx % 2 == 1:
            order = [("35B", a.gpu, a.gpu_model), ("1.2B", a.npu, a.npu_model)]
        else:
            order = [("1.2B", a.npu, a.npu_model), ("35B", a.gpu, a.gpu_model)]
        res = {}
        for name, port, model in order:
            c, p, dt, err = call(port, text, model, a.max_tokens)
            res[name] = (c, p, dt, err)
            if name == "35B":
                gpu_lat.append(dt)
                if err:
                    gpu_err += 1
                    err_detail["35B"].append("  #%d %s" % (idx, err))
            else:
                npu_lat.append(dt)
                if err:
                    npu_err += 1
                    err_detail["1.2B"].append("  #%d %s" % (idx, err))

        gc, gp, gdt, gerr = res["35B"]
        nc, np_, ndt, nerr = res["1.2B"]
        total += 1
        if gerr is None and nerr is None and tier_of(gp) == tier_of(np_):
            agree += 1
            mark = "一致"
        elif gerr or nerr:
            mark = "失败"
        else:
            mark = "★不一致"
        rows.append((idx, expect, gc, gp, nc, np_, mark))

        print("  #%-2d 预期=%-9s 35B=%-9s(p=%.2f %5.2fs)  1.2B=%-9s(p=%.2f %5.2fs)  %s"
              % (idx, expect,
                 gc or "ERR", gp, gdt, nc or "ERR", np_, ndt, mark))

    print("\n=== 汇总 ===")
    if total:
        print("  档位一致率      : %d/%d = %.1f%%" % (agree, total, 100.0 * agree / total))
    if gpu_lat:
        print("  35B 单次延迟中位: %.2fs  (max %.2fs)" % (statistics.median(gpu_lat), max(gpu_lat)))
    if npu_lat:
        print("  1.2B 单次延迟中位: %.2fs  (max %.2fs)" % (statistics.median(npu_lat), max(npu_lat)))
    print("  解析/请求失败   : 35B %d 次 / 1.2B %d 次" % (gpu_err, npu_err))
    for side in ("35B", "1.2B"):
        if err_detail[side]:
            print("    [%s 失败明细] %s" % (side, "; ".join(err_detail[side][:3])))

    bad = [r for r in rows if r[6] == "★不一致"]
    if bad:
        print("\n  不一致明细（按预期看谁判错）：")
        for idx, expect, gc, gp, nc, np_, _ in bad:
            print("    #%-2d 预期 %s | 35B→%s(p=%.2f) | 1.2B→%s(p=%.2f)"
                  % (idx, expect, gc, gp, nc, np_))

    verdict = "可迁 NPU（≥90%）" if total and agree / total >= 0.9 else "不建议迁 NPU（<90%）"
    print("\n  判定: %s" % verdict)
    print("  注意: 本脚本只比结论一致性；NPU 的实际价值是省下 8080 主 slot 的 prefill，")
    print("        不占用 LCP 前缀缓存，不是「单条更快」那么简单。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# 许可：CC0-1.0，公共领域贡献，无任何限制。
