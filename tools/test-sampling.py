#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
采样参数对照测试：验证「输出崩坏/重复」是否由采样参数导致
不换模型，只改采样参数，看输出是否变健康

用法：python3 test-sampling.py
"""
import json
import sys
import urllib.request

PORT = sys.argv[1] if len(sys.argv) > 1 else "8080"

# 用容易触发重复的任务：中长文本生成、列表、专业内容
TASKS = [
    ("长文生成", "详细介绍食管胃底静脉曲张的内镜下治疗方式，包括套扎术、硬化剂注射和组织胶注射的适应证、操作要点与并发症。不少于 300 字。"),
    ("列表任务", "列出消化内科常见急症的鉴别诊断要点，每条包含病名、典型症状、首选检查。至少 8 条。"),
    ("代码任务", "用 Python 写一个函数，读取 Excel 文件并统计每个科室的手术量，按数量降序输出。"),
    ("推理任务", "一个患者门静脉压力梯度 14 mmHg，Child-Pugh B 级，既往 2 次出血史。请分析其再出血风险并提出随访方案。"),
]

# 对照配置
CONFIGS = [
    ("当前默认", {"temperature": 1.0, "top_k": 20, "top_p": 0.95, "min_p": 0.05,
                  "repeat_penalty": 1.0, "presence_penalty": 0.0, "frequency_penalty": 0.0}),
    ("保守档",   {"temperature": 0.7, "top_k": 40, "top_p": 0.9, "min_p": 0.05,
                  "repeat_penalty": 1.05, "presence_penalty": 0.0, "frequency_penalty": 0.1}),
    ("强抑制档", {"temperature": 0.6, "top_k": 40, "top_p": 0.9, "min_p": 0.02,
                  "repeat_penalty": 1.1, "presence_penalty": 0.2, "frequency_penalty": 0.2}),
]


def gen(task, cfg):
    payload = {
        "messages": [{"role": "user", "content": task}],
        "max_tokens": 700,
        "stream": False,
        "cache_prompt": False,
        **cfg,
    }
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=600) as resp:
        body = json.load(resp)
    return body["choices"][0]["message"]["content"], body.get("usage", {})


def detect_degeneration(text):
    """检测重复/崩坏：返回 (是否崩坏, 说明)

    注意误报：代码里的标识符（如函数名、变量名）会高频重复，
    这是正常的，不能当崩坏。故只检测「markdown 结构行」的重复。
    """
    if len(text) < 20:
        return True, "输出过短"

    lines = [l.strip() for l in text.split("\n") if l.strip()]

    # 1. 结构行连排重复（markdown 标题/分隔符/列表符号 连续 3 次以上）
    struct_dups = 0
    for i in range(1, len(lines)):
        a, b = lines[i-1], lines[i]
        # 只看明显是结构标记的短行
        if a == b and len(a) < 60 and (a.startswith(("*", "-", "#", "|", "---"))
                                       or a.endswith("：") or a.endswith(":")):
            struct_dups += 1
    if struct_dups >= 3:
        return True, f"结构行连排重复 {struct_dups} 次"

    # 2. 整句级别的循环（长片段重复，排除代码块）
    body = text
    if "```" in body:
        # 去掉代码块再检测，避免函数名误报
        parts = body.split("```")
        body = "".join(parts[i] for i in range(0, len(parts), 2))
    for n in (16, 24, 32):
        seen = {}
        for i in range(0, max(0, len(body) - n)):
            frag = body[i:i+n]
            if len(frag.strip()) < n * 0.6:
                continue
            seen[frag] = seen.get(frag, 0) + 1
        top = max(seen.items(), key=lambda kv: kv[1], default=("", 0))
        if top[1] >= 5:
            return True, f"片段「{top[0][:16]}...」重复 {top[1]} 次"

    # 3. 非中文乱码比例
    weird = sum(1 for c in text if ord(c) > 0xFFFF or (0xE000 <= ord(c) <= 0xF8FF))
    if weird > len(text) * 0.02:
        return True, f"可疑字符 {weird} 个"

    return False, "正常"


if __name__ == "__main__":
    print("=" * 70)
    print("采样参数对照测试（不换模型）")
    print("=" * 70)
    summary = []
    for cname, cfg in CONFIGS:
        print(f"\n{'─'*70}\n【配置】{cname}")
        print(f"  {json.dumps(cfg, ensure_ascii=False)}")
        bad = 0
        for tname, task in TASKS:
            try:
                text, usage = gen(task, cfg)
                degen, why = detect_degeneration(text)
                if degen:
                    bad += 1
                mark = "✗崩坏" if degen else "✓正常"
                print(f"  [{mark}] {tname:8s} len={len(text):5d}  {why}")
                if degen:
                    # 打印崩坏片段供人工确认
                    print(f"         片段: {text[:120]}...")
            except Exception as e:
                print(f"  [ERROR] {tname}: {e}")
                bad += 1
        summary.append((cname, bad, len(TASKS)))

    print(f"\n{'='*70}\n汇总")
    for cname, bad, tot in summary:
        print(f"  {cname:10s}: {bad}/{tot} 崩坏")
