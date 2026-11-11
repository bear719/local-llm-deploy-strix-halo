#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
中文 ASR 拼音层确定性纠错。

为什么在拼音层做：实测 flm/whisper 的错误 90% 以上是同音/近音字替换
（胃肠镜→未肠镜、套扎→套杂、幽门螺杆菌→游门罗杆军）。声学层其实听对了，
错在字形选择。字形选择是可以用词表+拼音确定性地修的。

与 PhoneInbox/correct_transcripts.py 的差别：
  那个用**精确**无声调拼音匹配，只覆盖「木淡江→牡丹江」这类完全同音的。
  本模块加了**模糊音归一化**（zh/z、ch/c、sh/s、ing/in、eng/en、ang/an、
  iang/ian、uang/uan），因为真实错误里大量是「套扎/套杂」「胃肠镜/胃肠性」
  这种声母或韵尾只差一点的。
"""
import re
import unicodedata

# ---------------------------------------------------------------- 词表
# 消化科病历/内镜场景正字表。命中即纠正为这里的写法。
MED_LEXICON = [
    # 地名 / 机构
    "牡丹江", "哈尔滨", "<医院>", "<院区>",
    # 科室人员
    "消化科", "内镜中心", "护士长", "主任", "主班", "值班", "主治医师",
    # 症状
    "呕血", "黑便", "反酸", "嗳气", "隐痛", "腹胀", "纳差", "体重下降", "上腹部",
    # 检查
    "胃镜", "肠镜", "胃肠镜", "内镜下", "超声内镜", "腹部CT", "增强CT", "核磁",
    "采血", "心电图", "碳十三", "呼气试验", "病理", "活检",
    # 疾病
    "食管胃底静脉曲张", "静脉曲张", "肝硬化", "乙型肝炎", "肝炎", "肝右叶",
    "结节", "肝癌", "肝细胞癌", "幽门螺杆菌", "胃溃疡", "息肉", "腺瘤",
    "消化道出血", "腹水", "食管", "胃底",
    # 治疗
    "套扎", "硬化", "栓塞", "奥美拉唑", "普萘洛尔", "生长抑素", "输血",
    "去白红细胞", "静滴", "静脉滴注", "口服",
    # 指标
    "血红蛋白", "白细胞", "血小板", "甲胎蛋白", "白蛋白", "胆红素",
    "凝血酶原时间", "肝功能", "阳性", "阴性",
    # 病历结构
    "主诉", "现病史", "既往史", "查体", "诊断", "医嘱", "入院", "出院",
    # 症状搭配（词组而非单字，避免「办→伴」这类误伤）
    "伴反酸", "伴嗳气", "伴恶心", "伴呕吐", "伴腹胀", "无反酸", "无嗳气",
    "反酸嗳气", "上腹部隐痛",
    # 单位
    "每升", "毫克", "克每升",
    # 流程费用
    "门诊", "急诊", "病房", "住院", "挂号", "床位", "医保", "报销",
    "自费", "复诊", "复查", "化验", "禁食", "清肠", "手术", "术后", "麻醉",
]

# ---------------------------------------------------------------- 保护词
# 拼音与领域词相近、但本身是合法常用词 → 默认禁止替换（防误伤）
PROTECT = {
    "主人", "场景", "病例", "病历", "助理", "助人", "是关",
    "今天", "今年", "住院", "出血", "门诊",   # 本身已是正字或高频合法词
    "隐形", "经营", "已经", "进行", "自行", "不行", "现行",   # 「隐形/已经」易被误改「乙型/胰」
}

# ---------------------------------------------------------------- 模糊音
# 顺序敏感：长的先替换
FUZZY_RULES = [
    ("zh", "z"), ("ch", "c"), ("sh", "s"),
    ("iang", "ian"), ("uang", "uan"),
    ("ing", "in"), ("eng", "en"), ("ang", "an"),
]

# 只对这些 2 字医疗术语开放模糊匹配。
# 理由：它们出错频率高且误伤代价低（"今王"不是词，"杨幸"在病历里也不会出现）；
# 而全局放开 2 字模糊会把「办理→伴理」这类正常词改坏。
FUZZY_2CHAR = {"既往", "嗳气", "阳性", "阴性", "患者", "套扎", "胃镜", "肠镜",
               "息肉", "麻醉", "活检", "呕血", "黑便", "隐痛", "腹胀"}

_PY_RE = re.compile(r"[a-z]+")


def _lazy(s: str):
    from pypinyin import lazy_pinyin
    return lazy_pinyin(s, errors=lambda x: list(x))


def py_raw(s: str) -> str:
    """无声调拼音串，中文以外的字符原样保留（转小写）。"""
    out = []
    for chunk in _lazy(s):
        out.append(chunk.lower() if chunk.isascii() else chunk)
    return "".join(out)


def py_norm(s: str) -> str:
    """模糊音归一化。用于放宽匹配，让「套杂/套扎」落到同一个键。"""
    p = py_raw(s)
    for a, b in FUZZY_RULES:
        p = p.replace(a, b)
    return p


def edit_dist(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
        prev = cur
    return prev[-1]


def similarity(a: str, b: str) -> float:
    """拼音相似度 0~1（基于归一化拼音的编辑距离）。"""
    na, nb = py_norm(a), py_norm(b)
    if not na or not nb:
        return 0.0
    return 1.0 - edit_dist(na, nb) / max(len(na), len(nb))


def han_only(seg: str) -> bool:
    return bool(re.fullmatch(r"[\u4e00-\u9fff]+", seg))


# ---------------------------------------------------------------- 索引
def build_index(lexicon=None, min_sim_len=2):
    """词表 → {字数: [(词, 拼音归一化)]}，按字数分桶，匹配时只比对同字数。"""
    words = lexicon if lexicon is not None else MED_LEXICON
    by_len = {}
    for w in words:
        if w in PROTECT or not han_only(w):
            continue
        by_len.setdefault(len(w), []).append((w, py_norm(w)))
    return by_len


# ---------------------------------------------------------------- 纠错
def fix_text(text: str, idx=None, min_sim=0.999, judge=None, min_prob=0.6,
             fuzzy_sim=None, fuzzy_min_len=3, verbose=False):
    """滑窗匹配词表，替换同音/近音错字。

    min_sim=0.999 → 只做「归一化拼音完全相同」的确定性替换（最保守，零误伤）
    fuzzy_sim=0.85 + fuzzy_min_len=3 → 精确层未命中时，对**长术语**尝试模糊候选。
        只放开长词是因为：实测「幽门螺杆菌→楼门罗感军」相似度 0.933 值得救，
        而 2 字短词的模糊候选（伴→万，0.667）几乎全是误伤。
        模糊命中**必须**有 judge，否则拒绝替换。

    返回 (新文本, 变更列表, 弃用列表)
      变更项 (原片段, 正字, 相似度, p_是)
      弃用项 (原片段, 候选, 相似度, p_是)
    """
    if idx is None:
        idx = build_index()
    lens = sorted(idx.keys(), reverse=True)
    minlen = min(lens) if lens else 2

    out, changes, rejected = [], [], []
    i, n = 0, len(text)
    while i < n:
        hit = None
        for L in lens:                      # 长词优先
            if i + L > n:
                continue
            seg = text[i:i + L]
            if not han_only(seg) or seg in PROTECT:
                continue
            seg_py = py_norm(seg)
            exact = None
            best, best_sim = None, 0.0
            for w, wp in idx[L]:
                if w == seg:
                    exact = None
                    best, best_sim = None, 2.0   # 已正确，短路
                    break
                if wp == seg_py:
                    exact = w
                    break
                if fuzzy_sim is not None and (L >= fuzzy_min_len or w in FUZZY_2CHAR):
                    s = similarity(seg, w)
                    if s > best_sim:
                        best, best_sim = w, s
            if best_sim >= 2.0:
                break                            # 该片段已经是正字，不动
            if exact:
                hit = (seg, exact, 1.0, L, False)
                break
            if best and best_sim >= (fuzzy_sim or 2.0):
                hit = (seg, best, best_sim, L, True)
                break
        if not hit:
            out.append(text[i])
            i += 1
            continue

        seg, good, sim, L, is_fuzzy = hit
        p_yes = 1.0
        if judge is not None:
            ctx = text[max(0, i - 16):i + L + 16]
            ok, p_yes = judge.judge(seg, good, ctx, fuzzy=is_fuzzy, sentence=text)
            if not ok or p_yes < min_prob:
                rejected.append((seg, good, sim, p_yes))
                out.append(seg)
                i += L
                continue
        elif is_fuzzy:
            # 没有 judge 就不允许模糊替换（宁可漏改，不可改错）
            out.append(seg)
            i += L
            continue
        out.append(good)
        changes.append((seg, good, sim, p_yes))
        i += L
    return "".join(out), changes, rejected


# ---------------------------------------------------------------- 英文术语
# whisper 会把英文缩写念成中文同音（Child-Pugh → 超的PBG / 拆得比喻毕级）。
# 拼音匹配救不了（拼音串差太远），只能用上下文正则确定性替换。
EN_FIXES = [
    # Child-Pugh 的多种听写形态
    (re.compile(r"(?:child\s*[-–—]?\s*pugh|child\s*peer|超的\s*P?B?G?|拆得\s*比喻|"
                r"吃的\s*普格|菜的\s*普)", re.I), "Child-Pugh"),
    # 分级后缀：毕级 / 必及 / BG级 / b 级 → B 级
    (re.compile(r"(?<=Child-Pugh)\s*(?:毕级|必及|比级|PG级|BG级|B\s*级|b\s*级)"), " B级"),
    # 其它内镜/影像缩写
    (re.compile(r"(?:E\s*V\s*L|e\s*v\s*l|伊威艾尔|EV1)", re.I), "EVL"),
    (re.compile(r"(?:E\s*I\s*S|伊艾斯)", re.I), "EIS"),
]


def fix_english(text: str):
    """英文/缩写术语确定性修正。返回 (新文本, 命中列表)。"""
    out, hits = text, []
    for pat, rep in EN_FIXES:
        new = pat.sub(rep, out)
        if new != out:
            hits.append((pat.pattern[:28], rep))
            out = new
    return out, hits


# ---------------------------------------------------------------- 虚词
# 「予 + 药名/治疗」是病历固定句式，ASR 常写成同音的 与/于/以/已。
# 只在「标点后 + 紧接已知药名/治疗」时替换，避免把正文里的「与/以」改坏。
VERB_FIX = re.compile(
    r"(^|[，。；：、\s])(与|于|以|已)"
    r"(?=(?:奥美拉唑|普萘洛尔|生长抑素|去白红细胞|静滴|静脉滴注|口服|套扎))"
    r"|(与|于|以|已)(?=(?:EVL|EIS|TAI)(?![A-Za-z]))")
VERB_REPL = "予"


def fix_verbs(text: str):
    """虚词确定性修正。返回 (新文本, 命中次数)。"""
    n = 0

    def _rep(m):
        nonlocal n
        n += 1
        if m.group(1) is not None:      # 第一种形式：标点 + 虚词
            return m.group(1) + VERB_REPL
        return VERB_REPL                 # 第二种形式：虚词 + 英文缩写

    return VERB_FIX.sub(_rep, text), n


# ---------------------------------------------------------------- LLM 判别
JUDGE_SYS = """你是医院病历语音转写的校对判别器。语音识别会把医学词识别成同音错字。
用户给出「可疑片段」「候选正字」「上下文」，判断：在这个上下文里，把可疑片段换成候选正字是否更符合原意。

特别注意：可疑片段可能本身是合法句子的一部分，只是恰好与医学词同音。例如：
 - "你见过吗最起码…" 里的"吗最"是"吗"+"最起码"，不是"麻醉"
 - "他应该是管堵了" 里的"是管"是"是"+"管堵了"，不是"食管"
 - "还是观看人" 里的"是观"是"是"+"观看"，不是"食管"
如果换个切分方式后句子仍然通顺、且更自然，就回答 否。

只输出 JSON：{"yes": true} 或 {"yes": false}"""


class LLMJudge:
    """用本地 35B 做「是/否」判别。历史上自由生成式纠错无效，二分类判别才有效。"""

    def __init__(self, url="http://127.0.0.1:18090/v1/chat/completions", cache_path=None):
        self.url = url
        self.cache = {}
        self.cache_path = cache_path
        if cache_path:
            try:
                import json
                with open(cache_path, encoding="utf-8") as f:
                    self.cache = json.load(f)
            except Exception:
                self.cache = {}
        self.calls = 0

    def _save(self):
        if not self.cache_path:
            return
        import json
        try:
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump(self.cache, f, ensure_ascii=False)
        except Exception:
            pass

    def judge(self, seg: str, cand: str, ctx: str, fuzzy: bool = False,
              sentence: str = None):
        """返回 (是否替换, 置信度)。

        优先用整句对比：把「改前/改后两句话哪句更通顺」交给模型，比只给
        12 字片段准得多 —— 实测片段式判别会因为周围错字干扰而误否。
        """
        key = "%s|%s|%s|%d" % (seg, cand, (sentence or ctx)[:60], int(fuzzy))
        if key in self.cache:
            v = self.cache[key]
            return bool(v.get("yes")), float(v.get("p", 1.0))
        import json
        import urllib.request
        if sentence and seg in sentence:
            fixed = sentence.replace(seg, cand, 1)
            user = ("原句：%s\n改动后：%s\n\n问题：把「%s」改成「%s」，是否让这句话更通顺、"
                    "更符合中文病历/门诊对话的表达？只回答 yes 或 no。"
                    % (sentence, fixed, seg, cand))
        else:
            user = "可疑片段：%s\n候选正字：%s\n上下文：%s" % (seg, cand, ctx)
        if fuzzy:
            user += ("\n\n注意：这个候选只是拼音相近，可能完全不对。"
                     "只有当原片段明显讲不通、且换成候选后整句更通顺时才回答 yes；"
                     "如果原片段在句子里本来就成立，一律回答 no。")
        body = {"messages": [{"role": "system", "content": JUDGE_SYS},
                             {"role": "user", "content": user}],
                "temperature": 0, "max_tokens": 24,
                "logprobs": True, "top_logprobs": 5,
                "chat_template_kwargs": {"enable_thinking": False}}
        try:
            req = urllib.request.Request(self.url, data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=60) as r:
                d = json.loads(r.read())
            self.calls += 1
            ch = d["choices"][0]
            txt = (ch["message"].get("content") or "").strip()
            yes = "true" in txt.lower()
            p = 0.5
            lp = ch.get("logprobs") or {}
            for tok in (lp.get("content") or []):
                if tok.get("token", "").strip().lower() in ("true", "false"):
                    p = pow(2.718281828, float(tok.get("logprob", -0.7)))
                    yes = tok["token"].strip().lower() == "true"
                    break
            self.cache[key] = {"yes": yes, "p": p}
            self._save()
            return yes, p
        except Exception:
            return True, 1.0    # LLM 不可用 → 放行规则结果，不阻塞


# ---------------------------------------------------------------- 统一入口
def fix_all(text: str, idx=None, judge=None, fuzzy=True, fuzzy_sim=0.85,
            fuzzy_min_len=3, min_prob=0.6):
    """完整纠错流水线。顺序不可颠倒：

    1. 英文术语正则（Child-Pugh / EVL）—— 拼音匹配对它无效
    2. pass1 精确拼音匹配 —— 先把药名、术语改对
    3. 虚词规则 —— 依赖上一步把「奥美拉座」改成「奥美拉唑」
    4. pass2 模糊匹配（可选，需 judge）—— 此时句子已干净，判别准确率才高

    judge=None 时 pass2 自动跳过（没有判别就不允许模糊替换）。
    返回 (文本, 变更数, 模糊命中数, 否决数)
    """
    if idx is None:
        idx = build_index()
    en, enh = fix_english(text)
    t1, ch1, _ = fix_text(en, idx, min_sim=0.999)
    t2, nv = fix_verbs(t1)
    n = len(ch1) + len(enh) + nv
    nfuzzy = 0
    if fuzzy and judge is not None:
        t3, ch2, rj = fix_text(t2, idx, min_sim=2.0, judge=judge, min_prob=min_prob,
                               fuzzy_sim=fuzzy_sim, fuzzy_min_len=fuzzy_min_len)
        nfuzzy = sum(1 for c in ch2 if c[2] < 0.999)
        return t3, n + len(ch2), nfuzzy, len(rj)
    return t2, n, nfuzzy, 0


def _cli():
    import argparse
    import glob
    ap = argparse.ArgumentParser(
        description="中文 ASR 转写拼音层纠错（病历/内镜场景）")
    ap.add_argument("text", nargs="?", help="直接给一段文本")
    ap.add_argument("--file", help="单个文本文件")
    ap.add_argument("--dir", help="目录，批量处理 *.txt")
    ap.add_argument("--llm", action="store_true", help="启用模糊匹配+35B 整句判别（慢但更准）")
    ap.add_argument("--llm-url", default="http://127.0.0.1:18090/v1/chat/completions")
    ap.add_argument("--fuzzy-sim", type=float, default=0.85)
    ap.add_argument("--apply", action="store_true", help="批量模式写回（自动备份 .bak）")
    ap.add_argument("--show", action="store_true", help="打印逐处变更")
    a = ap.parse_args()

    idx = build_index()
    judge = LLMJudge(url=a.llm_url) if a.llm else None

    def run_one(t, name=""):
        out, n, nf, nrej = fix_all(t, idx, judge=judge, fuzzy=a.llm,
                                   fuzzy_sim=a.fuzzy_sim)
        if a.show and n:
            print("  %s改动 %d 处（模糊 %d，否决 %d）" % (name, n, nf, nrej))
        return out, n

    if a.text:
        out, n = run_one(a.text)
        print(out)
        return

    if a.file:
        with open(a.file, encoding="utf-8") as f:
            t = f.read()
        out, n = run_one(t, a.file + " ")
        if a.apply:
            import shutil
            shutil.copy2(a.file, a.file + ".bak")
            with open(a.file, "w", encoding="utf-8") as f:
                f.write(out)
            print("[写回] %s（备份 %s.bak）" % (a.file, a.file))
        else:
            print(out)
        return

    if a.dir:
        files = sorted(glob.glob(os.path.join(a.dir, "*.txt")))
        if not files:
            print("[跳过] %s 下没有 .txt" % a.dir)
            return
        tot_n = changed = 0
        for fp in files:
            try:
                with open(fp, encoding="utf-8") as f:
                    t = f.read()
            except Exception as e:
                print("  [跳过] %s (%s)" % (os.path.basename(fp), e))
                continue
            out, n = run_one(t, os.path.basename(fp) + " ")
            if n:
                changed += 1
                tot_n += n
                print("  %-44s 改 %d 处" % (os.path.basename(fp), n))
            if a.apply and n:
                import shutil
                shutil.copy2(fp, fp + ".bak")
                with open(fp, "w", encoding="utf-8") as f:
                    f.write(out)
        print("\n[汇总] 扫描 %d 个文件，%d 个有改动，共 %d 处%s"
              % (len(files), changed, tot_n, "（已写回）" if a.apply else "（干跑）"))
        return

    ap.print_help()


if __name__ == "__main__":
    import os
    _cli()

# 许可：CC0-1.0，公共领域贡献，无任何限制。
