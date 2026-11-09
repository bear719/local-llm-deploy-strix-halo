#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""judge 定档一致性对比（约束解码版）：35B@8080 vs 1.2B@8219

与 bench-judge-npu.py 的区别：
  两侧都强制 response_format=json_schema，用 xgrammar 屏蔽非法 token。
  这样比的是「语义判断力」而不是「格式服从性」——后者本来就不该由模型承担。

用法：
  python tools/bench-judge-schema.py                # 默认 20 条
  python tools/bench-judge-schema.py --gpu 18090    # 35B 走 docproxy（生产口径）
  python tools/bench-judge-schema.py --npu-model qwen3.5:4b   # 换 NPU 侧模型
"""
import argparse
import json
import time
import urllib.error
import urllib.request

# 与 jev-local/router.py 的 REASONING_THRESHOLD 对齐，仅用于展示
THRESHOLD = 0.6

# 20 条用例：(期望档位, 文本)，正负各半，覆盖口语短句与硬推理
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
                  "for i in range(n):\n    for j in range(i, n):\n        s = sum(a[i:j+1])"),
    ("reasoning", "请分步骤论证：为什么 TCP 建立连接必须是三次握手而不能是两次。"),
    ("reasoning", "设计一个跨机房一致的分布式限流方案，需说明时钟偏差如何处理。"),
]

# 约束 schema：choice 强制为两个枚举值，probability 强制为 0~1 的数
ROUTE_SCHEMA = {
    "type": "object",
    "properties": {
        "choice": {"type": "string", "enum": ["cheap", "reasoning"]},
        "probability": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["choice", "probability"],
    "additionalProperties": False,
}

SYS_PROMPT = (
    "你是请求分档器。判断用户请求应交给哪个档位：\n"
    "cheap = 闲聊、问候、改写、翻译、摘要、常识问答、简单操作\n"
    "reasoning = 数学证明、算法设计、架构设计、多步推理、复杂度分析、技术论证\n"
    "只输出 JSON。"
)


def judge_prompt(text: str) -> str:
    return "用户请求：\n%s\n\n它的档位是？" % text


def call(port: int, model: str, text: str, timeout: int = 180):
    """返回 (choice, probability, 耗时秒, 错误)。"""
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYS_PROMPT},
            {"role": "user", "content": judge_prompt(text)},
        ],
        "temperature": 0.0,
        "max_tokens": 64,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "route", "strict": True, "schema": ROUTE_SCHEMA},
        },
    }
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        "http://127.0.0.1:%d/v1/chat/completions" % port,
        data=body, headers={"Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read())
        dt = time.time() - t0
        content = d["choices"][0]["message"].get("content") or ""
        obj = json.loads(content)
        c = obj.get("choice")
        p = obj.get("probability")
        if c not in ("cheap", "reasoning"):
            return None, None, dt, "choice 非法: %r" % c
        return c, float(p) if p is not None else None, dt, None
    except urllib.error.HTTPError as e:
        return None, None, time.time() - t0, "HTTP %d: %s" % (
            e.code, e.read().decode("utf-8", "ignore")[:120])
    except Exception as e:
        return None, None, time.time() - t0, "%s: %s" % (type(e).__name__, str(e)[:120])


def med(xs):
    xs = [x for x in xs if x]
    return sorted(xs)[len(xs) // 2] if xs else 0.0


def main():
    ap = argparse.ArgumentParser(description="judge 定档一致性对比（约束解码）")
    ap.add_argument("--gpu", type=int, default=8080, help="35B 后端端口")
    ap.add_argument("--gpu-model", default="local", help="35B 模型名")
    ap.add_argument("--npu", type=int, default=8219, help="NPU 后端端口")
    ap.add_argument("--npu-model", default="lfm2.5-it:1.2b", help="NPU 模型名")
    ap.add_argument("--warmup", type=int, default=2, help="预热条数（结果丢弃）")
    a = ap.parse_args()

    print("=== judge 定档一致性（约束解码强制合法 JSON）===")
    print("  35B : :%d model=%s" % (a.gpu, a.gpu_model))
    print("  NPU : :%d model=%s" % (a.npu, a.npu_model))
    print("  策略：预热 %d 条丢弃 + 逐条 A/B 交错 + 顺序奇偶对调\n" % a.warmup)

    # 预热两侧，避免首条撞冷态拉偏
    for i in range(a.warmup):
        call(a.gpu, a.gpu_model, CASES[i][1])
        call(a.npu, a.npu_model, CASES[i][1])

    rows = []
    gpu_lat, npu_lat = [], []
    gpu_err = npu_err = 0
    gpu_hit = npu_hit = 0
    agree = 0
    conf = {}  # 混淆矩阵 {(gpu, npu): n}

    for idx, (expect, text) in enumerate(CASES, 1):
        order = [("35B", a.gpu, a.gpu_model), ("1.2B", a.npu, a.npu_model)]
        if idx % 2 == 0:
            order.reverse()
        res = {}
        for name, port, model in order:
            c, p, dt, err = call(port, model, text)
            res[name] = (c, p, dt, err)
            if name == "35B":
                gpu_lat.append(dt)
                if err:
                    gpu_err += 1
                elif c == expect:
                    gpu_hit += 1
            else:
                npu_lat.append(dt)
                if err:
                    npu_err += 1
                elif c == expect:
                    npu_hit += 1
        gc, gp, gd, ge = res["35B"]
        nc, np_, nd, ne = res["1.2B"]
        if gc and nc:
            if gc == nc:
                agree += 1
            conf[(gc, nc)] = conf.get((gc, nc), 0) + 1
        rows.append((idx, expect, text[:26], gc, nc, gd, nd, ge, ne))

    print("  %-3s %-10s %-28s %-9s %-9s %7s %7s" %
          ("#", "期望", "输入", "35B", "1.2B", "35Bs", "1.2Bs"))
    print("  " + "-" * 82)
    for (i, exp, txt, gc, nc, gd, nd, ge, ne) in rows:
        mark = "" if gc == nc else "  << 分歧"
        print("  %-3d %-10s %-28s %-9s %-9s %7.2f %7.2f%s" %
              (i, exp, txt, gc or ("ERR" if ge else "-"),
               nc or ("ERR" if ne else "-"), gd, nd, mark))

    n = len(CASES)
    print("\n=== 汇总 ===")
    print("  两侧一致率      : %d/%d = %.0f%%" % (agree, n, agree * 100.0 / n))
    print("  35B 判对率      : %d/%d = %.0f%%" % (gpu_hit, n, gpu_hit * 100.0 / n))
    print("  1.2B 判对率     : %d/%d = %.0f%%" % (npu_hit, n, npu_hit * 100.0 / n))
    print("  35B 中位延迟    : %.2f s   (失败 %d)" % (med(gpu_lat), gpu_err))
    print("  1.2B 中位延迟   : %.2f s   (失败 %d)" % (med(npu_lat), npu_err))
    if conf:
        print("  混淆矩阵 (35B→1.2B):")
        for k in sorted(conf):
            print("      %-10s -> %-10s %d" % (k[0], k[1], conf[k]))
    print("\n  判定：", end="")
    if agree >= 18 and npu_err == 0:
        print("可用 —— 一致率 ≥90%，可做 NPU 兜底/降级路径")
    elif agree >= 16:
        print("有条件可用 —— 一致率 80~90%%，仅适用于判错代价低的场景")
    else:
        print("不可用 —— 一致率 <80%%，误判代价高于收益")


if __name__ == "__main__":
    main()

# 许可：CC0-1.0，公共领域贡献，无任何限制。
