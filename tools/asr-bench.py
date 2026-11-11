#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ASR 准确率基准：用 edge-tts 合成已知文本，反算 CER（字符错误率）。

为什么必须这么做：真实录音没有 ground truth，改什么都只能"感觉好一点"。
TTS 合成音频的原文完全已知，CER 可以精确到小数点后一位，优化才可归因。

用法：
  python tools/asr-bench.py gen                 # 生成测试音频（幂等，已存在跳过）
  python tools/asr-bench.py run                 # 基线：原样转写
  python tools/asr-bench.py run --variant pp16k # 前处理：重采样+归一化+高通
  python tools/asr-bench.py run --variant seg   # 分段转写
  python tools/asr-bench.py run --variant lm    # LLM 后处理纠错
  python tools/asr-bench.py all                 # 全变体对照
"""
import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ADIR = os.path.join(ROOT, "bench", "asr")
PY = sys.executable

ASR_URL = "http://127.0.0.1:8219/v1/audio/transcriptions"
LLM_URL = "http://127.0.0.1:18090/v1/chat/completions"
ASR_MODEL = "whisper-v3:turbo"

# ---- 测试语料：真实消化科病历措辞，密集覆盖术语 ----
CASES = [
    ("t1", "患者行胃肠镜检查，发现食管胃底静脉曲张，予EVL套扎治疗。"),
    ("t2", "予奥美拉唑四十毫克静滴，每日两次，复查血红蛋白八十二克每升。"),
    ("t3", "既往乙型肝炎后肝硬化病史十年，肝功能Child-Pugh B级。"),
    ("t4", "幽门螺杆菌阳性，建议行碳十三尿素呼气试验复查。"),
    ("t5", "腹部增强CT提示肝右叶结节，甲胎蛋白升高，需警惕肝癌。"),
    ("t6", "患者牡丹江人，主诉上腹部隐痛三月，伴反酸嗳气。"),
]

# 三种"说话人"：用 instruction 模拟，验证结论是否跨音色成立
# 之所以要有男声/快语速/低沉，是因为中文 ASR 的错误率与基频、语速强相关，
# 只在一种音色上优化出来的结论不具备普适性。
VOICES = [
    ("default", "A clear, neutral Mandarin female voice with normal pace."),
    ("male_fast", "A middle-aged Mandarin man speaking quickly and casually, like on a phone call."),
    ("elder_low", "An elderly Mandarin man with a low, slightly hoarse voice and slow careful delivery."),
]

BREEZE_BIN = "/home/<user>/src/Breeze-TTS-2.cpp/build/breeze-cli"
BREEZE_MODEL = "/home/<user>/models/breeze-tts-2/breeze-tts-2-q8_0.gguf"


def ffmpeg() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


# ---------- 音频生成（本地 Breeze-TTS，走 Vulkan carve-out，不占 GTT）----------
def _tts(text: str, instruction: str, out_wav: str):
    """本地 TTS。edge-tts 已被微软加校验（403），改用本机 gguf 模型。"""
    cmd = [BREEZE_BIN, BREEZE_MODEL, "--text", text,
           "--instruction", instruction, "--output", out_wav]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=600)
    if p.returncode != 0 or not os.path.exists(out_wav) or os.path.getsize(out_wav) < 4000:
        raise RuntimeError(p.stdout.decode("utf-8", "ignore")[-200:])


def gen():
    os.makedirs(ADIR, exist_ok=True)
    made, skipped = 0, 0
    for cid, text in CASES:
        for vname, instr in VOICES:
            wav = os.path.join(ADIR, "%s_%s.wav" % (cid, vname))
            if os.path.exists(wav) and os.path.getsize(wav) > 4000:
                skipped += 1
                continue
            print("  合成 %-4s %-10s " % (cid, vname), end="", flush=True)
            try:
                _tts(text, instr, wav)
                print("%.2fs  %.0f KB" % (probe_dur(wav), os.path.getsize(wav) / 1024))
                made += 1
            except Exception as e:
                print("[FAIL] %s" % str(e)[:140])
    print("[gen] 新建 %d，跳过 %d，目录 %s" % (made, skipped, ADIR))


# ---------- 音频前处理 ----------
def wav16k(src: str, dst_wav: str, filters=None):
    """转 16k 单声道 wav；filters 为 ffmpeg -af 字符串。"""
    f = ffmpeg()
    cmd = [f, "-y", "-loglevel", "error", "-i", src, "-ar", "16000", "-ac", "1"]
    if filters:
        cmd += ["-af", filters]
    cmd += ["-c:a", "pcm_s16le", dst_wav]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def probe_dur(path: str) -> float:
    """用 ffmpeg 读时长（无 ffprobe）。"""
    f = ffmpeg()
    p = subprocess.run([f, "-i", path, "-f", "null", "-"],
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    m = re.search(r"time=(\d+):(\d+):(\d+\.\d+)", p.stdout.decode("utf-8", "ignore"))
    if not m:
        return 0.0
    h, mi, s = m.groups()
    return int(h) * 3600 + int(mi) * 60 + float(s)


# ---------- 转写 ----------
# 引擎：flm（NPU，http 接口）或 cpp（whisper.cpp + Vulkan，同一个 ggml 模型）
ENGINE = os.environ.get("ASR_ENGINE", "flm").lower()
CPP_BIN = "/home/<user>/whisper.cpp/build-vk/bin/whisper-cli"
CPP_MODEL = "/home/<user>/whisper.cpp/models/ggml-large-v3-turbo-q5_0.bin"


def transcribe_cpp(path: str, timeout=300):
    """whisper.cpp 转写。输出写临时 txt 再读，避免解析 stdout 里的日志行。"""
    base = path + ".cppout"
    cmd = [CPP_BIN, "-m", CPP_MODEL, "-l", "zh", "-f", path,
           "-nt", "--no-prints", "-otxt", "-of", base]
    t0 = time.time()
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       check=True, timeout=timeout)
        with open(base + ".txt", encoding="utf-8") as f:
            txt = f.read().strip()
        return txt, time.time() - t0, None
    except Exception as e:
        return "", time.time() - t0, "%s: %s" % (type(e).__name__, str(e)[:140])


def transcribe(path: str, lang=None, prompt=None, timeout=300):
    if ENGINE == "cpp":
        return transcribe_cpp(path, timeout=timeout)
    boundary = "----flm" + uuid.uuid4().hex
    parts = []

    def field(name, value):
        parts.append(("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n"
                      % (boundary, name, value)).encode())

    field("model", ASR_MODEL)
    if lang:
        field("language", lang)
    if prompt:
        field("prompt", prompt)
    fn = os.path.basename(path)
    ext = fn.rsplit(".", 1)[-1].lower()
    mime = {"wav": "audio/wav", "mp3": "audio/mpeg", "flac": "audio/flac",
            "ogg": "audio/ogg", "opus": "audio/opus", "m4a": "audio/mp4"}.get(ext, "application/octet-stream")
    with open(path, "rb") as fh:
        data = fh.read()
    parts.append(("--%s\r\nContent-Disposition: form-data; name=\"file\"; filename=\"%s\"\r\n"
                  "Content-Type: %s\r\n\r\n" % (boundary, fn, mime)).encode())
    parts.append(data)
    parts.append(("\r\n--%s--\r\n" % boundary).encode())

    req = urllib.request.Request(ASR_URL, data=b"".join(parts),
                                 headers={"Content-Type": "multipart/form-data; boundary=%s" % boundary})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read().decode("utf-8", "ignore"))
        return (d.get("text") or "").strip(), time.time() - t0, None
    except urllib.error.HTTPError as e:
        return "", time.time() - t0, "HTTP %d: %s" % (e.code, e.read().decode("utf-8", "ignore")[:160])
    except Exception as e:
        return "", time.time() - t0, "%s: %s" % (type(e).__name__, str(e)[:160])


# ---------- CER ----------
PUNCT = re.compile(r"[\s，。、；：？！“”‘’（）《》,.!?;:\"'()\[\]<>—…·\-]")

_CN_D = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
         "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_CN_U = {"十": 10, "百": 100, "千": 1000}
_CN_RUN = re.compile(r"[零〇一二两三四五六七八九十百千]+")


def _cn2num(s: str) -> str:
    """中文数字串 → 阿拉伯数字。避免「四十毫克」vs「40毫克」被当成 3 个字错。"""
    if not s or not any(c in _CN_U for c in s):
        # 纯数字位（如"十三"没有单位时按位拼）
        if len(s) > 1:
            return "".join(str(_CN_D[c]) for c in s)
        return str(_CN_D.get(s, s))
    total, cur = 0, 0
    for c in s:
        if c in _CN_D:
            cur = _CN_D[c]
        elif c in _CN_U:
            u = _CN_U[c]
            total += (cur if cur else 1) * u
            cur = 0
    total += cur
    return str(total)


def norm(s: str) -> str:
    s = PUNCT.sub("", s)
    s = _CN_RUN.sub(lambda m: _cn2num(m.group(0)), s)   # 中文数字 → 阿拉伯数字
    # 全角字母/符号 → 半角，避免 CER 虚高
    out = []
    for ch in s:
        o = ord(ch)
        if 0xFF01 <= o <= 0xFF5E:
            out.append(chr(o - 0xFEE0))
        elif ch == "\u3000":
            out.append(" ")
        else:
            out.append(ch)
    return "".join(out).upper().replace(" ", "")


def cer(ref: str, hyp: str):
    r, h = norm(ref), norm(hyp)
    if not r:
        return 1.0, 0, len(h)
    prev = list(range(len(h) + 1))
    for i, rc in enumerate(r, 1):
        cur = [i] + [0] * len(h)
        for j, hc in enumerate(h, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (rc != hc))
        prev = cur
    d = prev[-1]
    return d / len(r), d, len(r)


# ---------- 变体 ----------
PP_FILTERS = "highpass=f=80,dynaudnorm=f=150:g=15,alimiter=limit=0.95"


def variant_baseline(src, cid, vname, text):
    """原样直传 24k wav，不做任何处理。"""
    return transcribe(src)


def variant_pp16k(src, cid, vname, text):
    """重采样 16k + 高通去低频 + 动态归一化。"""
    w = os.path.join(ADIR, "%s_%s_pp.wav" % (cid, vname))
    if not os.path.exists(w):
        wav16k(src, w, PP_FILTERS)
    return transcribe(w)


def variant_rate(src, cid, vname, text):
    """减速 10% 再转写：whisper 对偏快语速敏感，减速等价于延长音素。"""
    w = os.path.join(ADIR, "%s_%s_slow.wav" % (cid, vname))
    if not os.path.exists(w):
        wav16k(src, w, "atempo=0.9,highpass=f=80,dynaudnorm=f=150:g=15")
    return transcribe(w)


def variant_seg(src, cid, vname, text):
    """按静音切段后逐段转写再拼接：减少长音频上下文漂移。"""
    w = os.path.join(ADIR, "%s_%s_pp.wav" % (cid, vname))
    if not os.path.exists(w):
        wav16k(src, w, PP_FILTERS)
    seg_dir = os.path.join(ADIR, "seg_%s_%s" % (cid, vname))
    os.makedirs(seg_dir, exist_ok=True)
    f = ffmpeg()
    subprocess.run([f, "-y", "-loglevel", "error", "-i", w,
                    "-af", "silenceremove=stop_periods=-1:stop_duration=0.35:stop_threshold=-38dB",
                    "-f", "segment", "-segment_time", "12",
                    os.path.join(seg_dir, "p%03d.wav")],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    segs = sorted(x for x in os.listdir(seg_dir) if x.endswith(".wav"))
    texts, t_all = [], 0.0
    for s in segs:
        t, dt, err = transcribe(os.path.join(seg_dir, s))
        t_all += dt
        if err:
            return "", t_all, err
        texts.append(t)
    return "".join(texts), t_all, None


LM_SYS = ("你是中文病历语音转写校对器。输入是 ASR 初步转写，可能有同音字错误。"
          "请依据消化科语境纠正明显的同音/近音错别字，尤其是医学术语。"
          "只输出纠正后的正文，不要解释、不要加标点以外的任何内容。"
          "如果原文没有明显错误，原样输出。")


def lm_fix(text: str, timeout=180):
    payload = {"messages": [{"role": "system", "content": LM_SYS},
                            {"role": "user", "content": text}],
               "temperature": 0, "max_tokens": max(64, len(text) * 2),
               "chat_template_kwargs": {"enable_thinking": False}}
    req = urllib.request.Request(LLM_URL, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read())
        c = (d["choices"][0]["message"].get("content") or "").strip()
        return c, time.time() - t0, None
    except Exception as e:
        return "", time.time() - t0, "%s: %s" % (type(e).__name__, str(e)[:140])


def variant_lm(src, cid, vname, text):
    """基线转写 + 35B 语境纠错。"""
    w = os.path.join(ADIR, "%s_%s_pp.wav" % (cid, vname))
    if not os.path.exists(w):
        wav16k(src, w, PP_FILTERS)
    raw, dt1, err = transcribe(w)
    if err:
        return "", dt1, err
    fixed, dt2, err2 = lm_fix(raw)
    if err2 or not fixed:
        return raw, dt1 + dt2, "LM失败(%s)，已回退原文" % err2
    return fixed, dt1 + dt2, None


VARIANTS = {
    "baseline": variant_baseline,
    "pp16k": variant_pp16k,
    "rate": variant_rate,
    "seg": variant_seg,
    "lm": variant_lm,
}


# ---- 拼音层纠错（复用 tools/pyfix.py）----
sys.path.insert(0, HERE)
import pyfix  # noqa: E402

_IDX = pyfix.build_index()
_JUDGE = None


def _judge():
    global _JUDGE
    if _JUDGE is None:
        _JUDGE = pyfix.LLMJudge(cache_path=os.path.join(ADIR, "judge_cache.json"))
    return _JUDGE


def variant_pyfix(src, cid, vname, text):
    """转写 + 英文术语正则 + 拼音精确匹配纠错（无 LLM，纯确定性）。"""
    raw, dt, err = transcribe(src)
    if err:
        return "", dt, err
    en, enh = pyfix.fix_english(raw)
    t1, ch, _ = pyfix.fix_text(en, _IDX, min_sim=0.999)
    new, nv = pyfix.fix_verbs(t1)
    n = len(ch) + len(enh) + nv
    return new, dt, ("改%d处" % n) if n else None


def variant_pyfix_judge(src, cid, vname, text):
    """转写 + 英文术语 + 拼音精确匹配 + 35B 判别（防切分歧义误伤）。"""
    raw, dt, err = transcribe(src)
    if err:
        return "", dt, err
    en, enh = pyfix.fix_english(raw)
    t0 = time.time()
    t1, ch, rj = pyfix.fix_text(en, _IDX, min_sim=0.999, judge=_judge(), min_prob=0.6)
    new, nv = pyfix.fix_verbs(t1)
    dt += time.time() - t0
    n = len(ch) + len(enh) + nv
    return new, dt, ("改%d/否%d" % (n, len(rj))) if (n or rj) else None


VARIANTS.update({"pyfix": variant_pyfix, "pyfix_judge": variant_pyfix_judge})


def variant_fuzz_judge(src, cid, vname, text):
    """转写 + 完整纠错流水线（英文→精确→虚词→模糊+整句判别）。"""
    raw, dt, err = transcribe(src)
    if err:
        return "", dt, err
    t0 = time.time()
    out, n, nf, nrej = pyfix.fix_all(
        raw, _IDX, judge=_judge(),
        fuzzy_sim=float(os.environ.get("FUZZY_SIM", 0.85)))
    dt += time.time() - t0
    return out, dt, ("改%d(模糊%d)/否%d" % (n, nf, nrej)) if (n or nrej) else None


VARIANTS["fuzz_judge"] = variant_fuzz_judge


def run(variant: str):
    fn = VARIANTS[variant]
    rows = []
    tot_d = tot_n = 0
    tot_t = 0.0
    print("=== 引擎 %s / 变体 %s ===" % (ENGINE, variant))
    print("%-4s %-9s %6s %7s %8s  %s" % ("case", "voice", "CER", "错字", "耗时s", "转写结果"))
    print("-" * 108)
    for cid, text in CASES:
        for vname, _ in VOICES:
            srcf = os.path.join(ADIR, "%s_%s.wav" % (cid, vname))
            if not os.path.exists(srcf):
                print("  [跳过] 缺 %s" % os.path.basename(srcf))
                continue
            hyp, dt, err = fn(srcf, cid, vname, text)
            c, d, n = cer(text, hyp)
            tot_d += d
            tot_n += n
            tot_t += dt
            flag = "" if not err else "  <%s>" % err[:60]
            print("%-4s %-9s %6.1f%% %7d %8.2f  %s%s" % (
                cid, vname, c * 100, d, dt, hyp[:56], flag))
            rows.append({"case": cid, "voice": vname, "cer": c, "dist": d,
                         "ref": text, "hyp": hyp, "err": err})
    overall = (tot_d / tot_n * 100) if tot_n else 0
    print("-" * 108)
    print("[汇总] 总体 CER = %.2f%%  (%d/%d 字)   总耗时 %.1fs" % (overall, tot_d, tot_n, tot_t))
    out = os.path.join(ADIR, "result_%s_%s.json" % (ENGINE, variant))
    os.makedirs(ADIR, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"engine": ENGINE, "variant": variant, "overall_cer": overall, "rows": rows},
                  f, ensure_ascii=False, indent=1)
    print("       结果已存 %s" % out)
    return overall


def main():
    ap = argparse.ArgumentParser(description="ASR 准确率基准（TTS ground truth + CER）")
    ap.add_argument("cmd", choices=["gen", "run", "all"])
    ap.add_argument("--variant", default="baseline", choices=list(VARIANTS))
    a = ap.parse_args()

    if a.cmd == "gen":
        gen()
    elif a.cmd == "run":
        run(a.variant)
    else:
        gen()
        res = {}
        for v in VARIANTS:
            res[v] = run(v)
            print()
        print("=== 变体总排名（CER 越低越好）===")
        for v, c in sorted(res.items(), key=lambda x: x[1]):
            print("  %-10s %.2f%%" % (v, c))


if __name__ == "__main__":
    main()

# 许可：CC0-1.0，公共领域贡献，无任何限制。
