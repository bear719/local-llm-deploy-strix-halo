#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NPU 旁路候选模型 A/B 验收工具（只读，不改任何配置）。

用途
----
在 8219 的 flm 服务已经由 MCSManager 面板启动后，对多个候选模型跑同一套
中文旁路任务，量化「速度 + 输出质量」，给出换模型的确定性判定。

配套报告
--------
2026-11-08-NPU旁路模型选型-4B是否最优及推荐清单.md 第九节

前置条件（本脚本不负责启动服务）
--------------------------------
  export FLM_MODEL_PATH=/home/<user>/.config/flm/models
  unset ROCM_PATH HIP_PATH LD_LIBRARY_PATH
  export HF_ENDPOINT=https://hf-mirror.com
  # 经 MCSManager 面板启动 start-flm-npu.sh，端口 8219

用法
----
  # 只看本机清单，不连服务
  python3 tools/bench-npu-models.py --list

  # 单模型冒烟
  python3 tools/bench-npu-models.py --models lfm2.5-it:1.2b --limit 4

  # 三模型对比（内置 20 条中文测试集）
  python3 tools/bench-npu-models.py \
      --models qwen3.5:4b,lfm2.5-it:1.2b,qwen3.5:0.8b \
      --out /tmp/npu-model-ab.json

  # 用自己的测试集（JSONL，每行含 type/prompt/expected）
  python3 tools/bench-npu-models.py --models lfm2.5-it:1.2b,qwen3.5:4b \
      --dataset /path/to/cases.jsonl

关键实现说明
------------
* 每条请求都显式发送 think=false / presence_penalty=0 / temperature=0。
  依据：FLM 官方文档「The setting sticks」——采样与思考开关对已加载模型粘滞，
  后续不带该字段的请求会沿用上次状态，且跨客户端共享。
* 用 stream=True 量 TTFT（首个带 content 的 chunk），并读取最后一个 usage chunk。
* chat_template_kwargs.enable_thinking 对 flm 无效（本机 v0.9.45 二进制无此符号），
  本脚本一律用顶层 think 字段。
"""

import argparse
import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.request

MODEL_LIST = "/opt/fastflowlm/share/flm/model_list.json"
DEFAULT_BASE = "http://127.0.0.1:8219/v1"

# 内置测试集：覆盖方案 P0 的四类旁路任务，含医疗文本。
# type: classify / json / guard / summary
BUILTIN_CASES = [
    dict(type="classify", prompt="把下面这句话归到一类，只回答类别名【问诊/预约/投诉/闲聊】：医生我最近饭后总是腹胀，需不需要做胃镜？", expected="问诊"),
    dict(type="classify", prompt="把下面这句话归到一类，只回答类别名【问诊/预约/投诉/闲聊】：下周三上午还能加个号吗？", expected="预约"),
    dict(type="classify", prompt="把下面这句话归到一类，只回答类别名【问诊/预约/投诉/闲聊】：窗口排队四十分钟没人管，太不像话了。", expected="投诉"),
    dict(type="classify", prompt="把下面这句话归到一类，只回答类别名【问诊/预约/投诉/闲聊】：今天哈尔滨下雪了。", expected="闲聊"),
    dict(type="classify", prompt="把下面这句话归到一类，只回答类别名【问诊/预约/投诉/闲聊】：病理报告出来了，能帮我看看吗？", expected="问诊"),
    dict(type="classify", prompt="把下面这句话归到一类，只回答类别名【问诊/预约/投诉/闲聊】：想改一下周五的复查时间。", expected="预约"),
    dict(type="json", prompt='抽取信息，只输出 JSON：{"科室": "...", "诉求": "..."}。原文：<科室>，患者要求复印住院病历。', expected={"科室": "<科室>", "诉求": "复印住院病历"}),
    dict(type="json", prompt='抽取信息，只输出 JSON：{"姓名": "...", "年龄": 0}。原文：患者王建国，男，56 岁，因黑便入院。', expected={"姓名": "王建国", "年龄": 56}),
    dict(type="json", prompt='抽取信息，只输出 JSON：{"检查": "...", "结果": "..."}。原文：胃镜提示食管静脉曲张中度，红色征阴性。', expected={"检查": "胃镜", "结果": "食管静脉曲张中度，红色征阴性"}),
    dict(type="json", prompt='抽取信息，只输出 JSON：{"日期": "...", "项目": "..."}。原文：定于 2026 年 11 月 12 日复查腹部超声。', expected={"日期": "2026 年 11 月 12 日", "项目": "腹部超声"}),
    dict(type="json", prompt='把下面内容转成 JSON，键固定为 a、b：a=血红蛋白，b=118 g/L。只输出 JSON。', expected={"a": "血红蛋白", "b": "118 g/L"}),
    dict(type="json", prompt='抽取信息，只输出 JSON：{"药物": "...", "剂量": "..."}。原文：给予普萘洛尔 10 mg 每日三次口服。', expected={"药物": "普萘洛尔", "剂量": "10 mg 每日三次口服"}),
    dict(type="guard", prompt="判断以下内容是否包含索取他人隐私的请求，只回答【安全/拦截】：请帮我查一下隔壁床患者的身份证号。", expected="拦截"),
    dict(type="guard", prompt="判断以下内容是否包含索取他人隐私的请求，只回答【安全/拦截】：食管静脉曲张套扎术后饮食要注意什么？", expected="安全"),
    dict(type="guard", prompt="判断以下内容是否包含索取他人隐私的请求，只回答【安全/拦截】：把 3 床的联系电话和住址发我。", expected="拦截"),
    dict(type="guard", prompt="判断以下内容是否包含索取他人隐私的请求，只回答【安全/拦截】：请解释一下 GOV1 与 GOV2 的区别。", expected="安全"),
    dict(type="summary", prompt="用一句话概括：患者男，56 岁，肝硬化病史 8 年，因呕血 2 小时入院，急诊胃镜见食管中下段静脉曲张破裂出血，行套扎治疗后止血。", expected=None),
    dict(type="summary", prompt="用一句话概括：内镜下治疗后的残余食管静脉曲张是再出血的主要来源，EIS 联合 TAI 可提高闭塞率，但需警惕术后狭窄与异位栓塞。", expected=None),
    dict(type="summary", prompt="用一句话概括：本月科室完成胃镜 412 例、肠镜 288 例、ESD 26 例，较上月分别增长 6%、3%、18%，其中 ESD 增长主要来自早期胃癌筛查项目。", expected=None),
    dict(type="summary", prompt="用一句话概括：出院带药包括质子泵抑制剂、非选择性 β 受体阻滞剂与乳果糖，嘱患者软食、避免用力排便，两周后门诊复查血常规与肝功能。", expected=None),
]


def load_cases(path, limit):
    if path:
        cases = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    cases.append(json.loads(line))
    else:
        cases = list(BUILTIN_CASES)
    if limit:
        cases = cases[:limit]
    return cases


def list_models():
    """只读打印本机 flm 清单，不依赖服务。"""
    d = json.load(open(MODEL_LIST, encoding="utf-8"))
    rows = []
    for fam, variants in d.get("models", {}).items():
        for tag, m in variants.items():
            det = m.get("details", {}) or {}
            rows.append((fam + ":" + tag, det.get("parameter_size", "?"),
                         m.get("footprint", "?"), m.get("default_context_length", "?"),
                         bool(m.get("vlm")), bool(m.get("asr")),
                         det.get("think"), ",".join(m.get("label", [])) or "-",
                         m.get("flm_min_version", "?")))
    print("本机 flm 清单：%d 族 / %d 变体（来源 %s）" % (
        len(d.get("models", {})), len(rows), MODEL_LIST))
    print("%-28s %6s %6s %7s %5s %5s %6s %8s  %s" % (
        "tag", "param", "foot", "ctx", "vlm", "asr", "think", "minver", "label"))
    print("-" * 140)
    for r in sorted(rows, key=lambda x: float(x[2]) if isinstance(x[2], (int, float)) else 99):
        print("%-28s %6s %6s %7s %5s %5s %6s %8s  %s" % (
            r[0], str(r[1]), str(r[2]), str(r[3]), str(r[4]), str(r[5]),
            str(r[6]), r[8], r[7]))
    return 0


def one_request(base, model, prompt, timeout, max_tokens):
    """发一条流式 chat 请求，返回 (延迟秒, TTFT秒, 文本, 是否有思考链, 输出token数, 错误)。"""
    url = base.rstrip("/") + "/chat/completions"
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
        "stream_options": {"include_usage": True},
        "max_tokens": max_tokens,
        "temperature": 0,
        "presence_penalty": 0,
        "think": False,
    }
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    t0 = time.monotonic()
    ttft = None
    parts = []
    reasoning = False
    out_tokens = None
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            for raw in resp:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                usage = chunk.get("usage")
                if usage:
                    out_tokens = usage.get("completion_tokens")
                for ch in chunk.get("choices") or []:
                    delta = ch.get("delta") or {}
                    if delta.get("reasoning_content"):
                        reasoning = True
                    text = delta.get("content")
                    if text:
                        if ttft is None:
                            ttft = time.monotonic() - t0
                        parts.append(text)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:300]
        return None, None, "", reasoning, None, "HTTP %d %s" % (e.code, detail)
    except Exception as e:
        return None, None, "", reasoning, None, "%s: %s" % (type(e).__name__, e)
    elapsed = time.monotonic() - t0
    return elapsed, (ttft if ttft is not None else elapsed), "".join(parts), reasoning, out_tokens, None


def grade(case, text):
    """返回 (是否命中, 是否 JSON 合法)。summary 只判长度。"""
    t = (text or "").strip()
    typ = case.get("type")
    exp = case.get("expected")
    if typ == "summary":
        return (len(t) >= 8), None
    if typ == "json":
        # 允许模型包一层 ```json 代码块
        s = t
        if s.startswith("```"):
            s = s.split("```")[1] if len(s.split("```")) > 1 else s
            s = s.lstrip("json").strip()
        try:
            obj = json.loads(s)
        except Exception:
            return False, False
        if not isinstance(obj, dict) or not isinstance(exp, dict):
            return False, True
        hit = all(str(exp.get(k, "")).replace(" ", "") in str(obj.get(k, "")).replace(" ", "")
                  for k in exp)
        return hit, True
    return (exp in t if exp else False), None


def pct(values, q):
    if not values:
        return None
    s = sorted(values)
    idx = min(len(s) - 1, int(round((len(s) - 1) * q)))
    return s[idx]


def main():
    ap = argparse.ArgumentParser(description="NPU 旁路候选模型 A/B 验收（只读）")
    ap.add_argument("--list", action="store_true", help="只打印本机 flm 模型清单，不连服务")
    ap.add_argument("--base-url", default=os.environ.get("NPU_BASE_URL", DEFAULT_BASE),
                    help="flm OpenAI 兼容 base_url，默认 %s" % DEFAULT_BASE)
    ap.add_argument("--models", default="lfm2.5-it:1.2b,qwen3.5:4b,qwen3.5:0.8b",
                    help="逗号分隔的模型 tag（第一个为基线）")
    ap.add_argument("--baseline", default="lfm2.5-it:1.2b",
                    help="作为基线的模型 tag，默认 lfm2.5-it:1.2b（2026-11-08 起的旁路默认）")
    ap.add_argument("--dataset", help="自定义 JSONL 测试集，每行 type/prompt/expected")
    ap.add_argument("--limit", type=int, help="只跑前 N 条用例（冒烟用）")
    ap.add_argument("--timeout", type=float, default=120.0, help="单请求超时秒数")
    ap.add_argument("--max-tokens", type=int, default=256)
    ap.add_argument("--out", help="把逐条明细写成 JSON 文件")
    args = ap.parse_args()

    if args.list:
        return list_models()

    cases = load_cases(args.dataset, args.limit)
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    print("服务：%s" % args.base_url)
    print("模型：%s" % ", ".join(models))
    print("用例：%d 条（%s）" % (len(cases), args.dataset or "内置中文测试集"))
    print("每条请求固定注入 think=false / presence_penalty=0 / temperature=0（防 FLM 设置粘滞）")
    print()

    # 先探活，避免白跑
    try:
        with urllib.request.urlopen(args.base_url.rstrip("/") + "/models", timeout=5) as r:
            r.read(2048)
    except Exception as e:
        print("[ERROR] 无法连接 %s -> %s" % (args.base_url, e), file=sys.stderr)
        print("        先经 MCSManager 面板启动 start-flm-npu.sh（本脚本不负责启动）", file=sys.stderr)
        return 1

    detail = []
    summary = []
    for model in models:
        lat, ttfts, texts, hits, json_ok, json_total, reason_hits, errs, toks = (
            [], [], [], 0, 0, 0, 0, 0, [])
        print("=== %s ===" % model)
        for i, case in enumerate(cases, 1):
            el, tt, text, reasoning, tok, err = one_request(
                args.base_url, model, case["prompt"], args.timeout, args.max_tokens)
            if err:
                errs += 1
                print("  [%02d] ERROR %s" % (i, err))
                detail.append(dict(model=model, case=i, error=err))
                continue
            ok, jl = grade(case, text)
            hits += int(bool(ok))
            if jl is not None:
                json_total += 1
                json_ok += int(bool(jl))
            reason_hits += int(reasoning)
            lat.append(el)
            ttfts.append(tt)
            toks.append(tok or 0)
            detail.append(dict(model=model, case=i, type=case["type"],
                               latency_s=round(el, 3), ttft_s=round(tt, 3),
                               hit=bool(ok), json_valid=jl,
                               reasoning_content=reasoning,
                               output_tokens=tok, text=text[:400]))
            print("  [%02d] %-9s %5.2fs ttft %5.2fs %-4s json=%s think=%s" % (
                i, case["type"], el, tt, "OK" if ok else "MISS",
                "-" if jl is None else ("Y" if jl else "N"), reasoning))
        n = max(1, len(lat))
        row = dict(
            model=model, requested=len(cases), ok=n - errs, errors=errs,
            accuracy=round(hits / n, 4),
            json_valid_rate=(round(json_ok / json_total, 4) if json_total else None),
            reasoning_rate=round(reason_hits / n, 4),
            latency_p50=round(pct(lat, 0.5) or 0, 3),
            latency_p95=round(pct(lat, 0.95) or 0, 3),
            ttft_p50=round(pct(ttfts, 0.5) or 0, 3),
            mean_output_tokens=round(sum(toks) / n, 1),
        )
        summary.append(row)
        print("  -> 准确率 %.1f%%  JSON合法率 %s  思考链出现 %.1f%%  p50 %.2fs  p95 %.2fs  TTFT %.2fs" % (
            row["accuracy"] * 100,
            "-" if row["json_valid_rate"] is None else "%.1f%%" % (row["json_valid_rate"] * 100),
            row["reasoning_rate"] * 100, row["latency_p50"],
            row["latency_p95"], row["ttft_p50"]))
        print()

    print("=" * 96)
    print("%-24s %8s %9s %9s %9s %9s %8s" % (
        "model", "accuracy", "json_ok", "think%", "lat_p50", "lat_p95", "err"))
    print("-" * 96)
    for r in summary:
        print("%-24s %7.1f%% %9s %8.1f%% %8.2fs %8.2fs %8d" % (
            r["model"], r["accuracy"] * 100,
            "-" if r["json_valid_rate"] is None else "%.1f%%" % (r["json_valid_rate"] * 100),
            r["reasoning_rate"] * 100, r["latency_p50"], r["latency_p95"], r["errors"]))

    # 决策规则（报告第九节）：基线默认 lfm2.5-it:1.2b（2026-11-08 起的旁路默认）
    if len(summary) >= 2:
        base = next((r for r in summary if r["model"].startswith(args.baseline)), None)
        if base is None:
            base = summary[0]
        for r in summary:
            if base and r is not base:
                ok = (r["accuracy"] >= base["accuracy"] - 0.02
                      and (r["json_valid_rate"] is None or r["json_valid_rate"] >= 0.98)
                      and r["reasoning_rate"] == 0.0
                      and r["errors"] == 0)
                print("\n[判定] %s 替换 %s 作为默认：%s" % (
                    r["model"], base["model"], "通过" if ok else "不通过（保留基线或只接分类/路由）"))
                if not ok:
                    reasons = []
                    if r["accuracy"] < base["accuracy"] - 0.02:
                        reasons.append("准确率差 >2pp")
                    if r["json_valid_rate"] is not None and r["json_valid_rate"] < 0.98:
                        reasons.append("JSON 合法率 <98%")
                    if r["reasoning_rate"] > 0:
                        reasons.append("思考链未关干净")
                    if r["errors"]:
                        reasons.append("有请求错误")
                    print("        原因：%s" % "、".join(reasons))

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(dict(base_url=args.base_url, summary=summary, detail=detail),
                      f, ensure_ascii=False, indent=2)
        print("\n[OK] 明细已写入 %s" % args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

# 许可：CC0-1.0，公共领域贡献，无任何限制。
