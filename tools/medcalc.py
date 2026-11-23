#!/usr/bin/env python3
# 许可：CC0-1.0，公共领域贡献，无任何限制。
# -*- coding: utf-8 -*-
"""
消化科常用临床评分/公式计算器（纯规则、零依赖、可 import 可 CLI）

定位（2026-11-23 立项，见 `2026-11-23-提升本地Qwen能力方案清单.md` C2）：
  这类计算是**确定性规则**，让 LLM 去算既慢又错（数值推理是弱项），
  而规则引擎命中率 100%。所以把它做成工具，让模型调用而不是自己算。

★ 单位铁律：每个参数名都带单位后缀（`bili_mgdl` / `bili_umol` / `plt_1e9l`），
  不加隐式换算。医学计算器最常见的错误来源就是 mg/dL 与 µmol/L 混用。
  胆红素换算：1 mg/dL = 17.1 µmol/L。

来源标注：每个评分都写明原始文献或指南，便于病历/科研引用。

用法：
  python3 tools/medcalc.py --list
  python3 tools/medcalc.py child_pugh --bili_mgdl 2.5 --albumin_gdl 3.0 --inr 1.8 --ascites mild --enceph 0
  python3 tools/medcalc.py meld3 --bili_mgdl 3.2 --inr 2.1 --creat_mgdl 1.4 --sodium 132 --female
  python3 tools/medcalc.py baveno --lsm_kpa 12 --plt_1e9l 168
  python3 tools/medcalc.py gbs --bun_mmol 9.5 --hb_gl 92 --sbp 105 --hr 102 --sex male --melena
  python3 tools/medcalc.py --json child_pugh --bili_mgdl 2.5 --albumin_gdl 3.0 --inr 1.8

CLI 参数规则：
  --xxx 1.5        数值参数
  --xxx            布尔参数（置 true）
  --xxx value      枚举参数（如 ascites mild / sex female）
"""

import argparse
import json
import math
import sys

REGISTRY = {}


def register(name, cn, params, source, note=""):
    """注册一个计算器。params 用于 --list 与 MCP schema 展示"""
    def deco(fn):
        REGISTRY[name] = {"fn": fn, "cn": cn, "params": params, "source": source, "note": note}
        return fn
    return deco


def _r(x, n=2):
    return None if x is None else round(float(x), n)


def _grade(score, cuts, labels):
    """cuts 为升序阈值列表，返回对应标签"""
    for c, lab in zip(cuts, labels):
        if score < c:
            return lab
    return labels[-1]


# ============================================================ 肝功能 / 门脉高压

@register("child_pugh", "Child-Pugh 分级",
          {"bili_mgdl": "总胆红素 mg/dL", "albumin_gdl": "白蛋白 g/dL",
           "inr": "INR（与 pt_prolong_s 二选一）", "pt_prolong_s": "PT 延长秒数",
           "ascites": "none|mild|severe", "enceph": "0|1|2（0 无，1 为 1-2 级，2 为 3-4 级）"},
          "Pugh RN et al. Br J Surg 1973;60:646")
def child_pugh(p):
    pts = {}
    b = p["bili_mgdl"]
    pts["bili"] = 1 if b < 2 else (2 if b <= 3 else 3)
    a = p["albumin_gdl"]
    pts["albumin"] = 1 if a > 3.5 else (2 if a >= 2.8 else 3)
    if p.get("inr") is not None:
        i = p["inr"]
        pts["inr"] = 1 if i < 1.7 else (2 if i <= 2.3 else 3)
    else:
        s = p["pt_prolong_s"]
        pts["inr"] = 1 if s < 4 else (2 if s <= 6 else 3)
    pts["ascites"] = {"none": 1, "mild": 2, "severe": 3}[p["ascites"]]
    pts["enceph"] = {"0": 1, "1": 2, "2": 3}[str(p["enceph"])]
    total = sum(pts.values())
    cls = "A" if total <= 6 else ("B" if total <= 9 else "C")
    surv = {"A": "1 年 100% / 2 年 85%", "B": "80% / 60%", "C": "45% / 35%"}[cls]
    return {"score": total, "grade": cls, "points": pts, "survival": surv,
            "meaning": {"A": "代偿良好，围手术期风险低",
                        "B": "显著肝功能受损，需评估手术耐受",
                        "C": "失代偿，手术/操作高危"}[cls]}


@register("meld3", "MELD 3.0（2023 版，含性别与钠）",
          {"bili_mgdl": "总胆红素 mg/dL", "inr": "INR", "creat_mgdl": "肌酐 mg/dL",
           "sodium": "血钠 mmol/L", "female": "true=女性", "dialysis": "true=透析（肌酐按 3.0）"},
          "Kim WR et al. Gastroenterology 2021;161:1887（UNOS 2023 起用于肝移植分配）")
def meld3(p):
    b = max(p["bili_mgdl"], 1.0)
    i = max(p["inr"], 1.0)
    cr = 3.0 if p.get("dialysis") else min(max(p["creat_mgdl"], 1.0), 3.0)
    na = min(max(p["sodium"], 125.0), 137.0)
    s = (1.33 * (1 if p.get("female") else 0)
         + 4.56 * math.log(b)
         + 0.82 * (137 - na)
         - 0.24 * (137 - na) * math.log(b)
         + 9.53 * math.log(i)
         + 0.93 * math.log(cr)
         + 6.43)
    s = min(max(s, 6.0), 40.0)
    return {"score": _r(s, 1), "grade": _grade(s, [10, 20, 30, 40],
                                               ["<10 低危", "10-19 中危", "20-29 高危", "30-39 极高危", "≥40 最高"]),
            "used": {"bili": b, "inr": i, "creat": cr, "sodium": na}}


@register("meld_na", "MELD-Na（UNOS 2016）",
          {"bili_mgdl": "总胆红素 mg/dL", "inr": "INR", "creat_mgdl": "肌酐 mg/dL",
           "sodium": "血钠 mmol/L", "dialysis": "true=透析"},
          "OPTN/UNOS 2016；Kim WR et al. NEJM 2008;359:1018")
def meld_na(p):
    b = max(p["bili_mgdl"], 1.0)
    i = max(p["inr"], 1.0)
    cr = 3.0 if p.get("dialysis") else min(max(p["creat_mgdl"], 1.0), 4.0)
    meld = 3.78 * math.log(b) + 11.2 * math.log(i) + 9.57 * math.log(cr) + 6.43
    meld = min(max(meld, 6.0), 40.0)
    na = min(max(p["sodium"], 125.0), 137.0)
    if na < 137:
        s = meld + 1.32 * (137 - na) - 0.033 * meld * (137 - na)
    else:
        s = meld
    s = min(max(s, 6.0), 40.0)
    return {"score": _r(s, 1), "meld_base": _r(meld, 1),
            "grade": _grade(s, [10, 20, 30, 40],
                            ["<10 低危", "10-19 中危", "20-29 高危", "30-39 极高危", "≥40 最高"])}


@register("albi", "ALBI 分级（白蛋白-胆红素）",
          {"bili_umol": "总胆红素 µmol/L", "albumin_gl": "白蛋白 g/L"},
          "Johnson PJ et al. J Clin Oncol 2015;33:550（肝癌肝功能分层）")
def albi(p):
    s = (math.log10(p["bili_umol"]) * 0.66) + (p["albumin_gl"] * -0.085)
    g = 1 if s <= -2.60 else (2 if s <= -1.39 else 3)
    return {"score": _r(s, 3), "grade": "grade %d" % g,
            "meaning": {1: "肝功能好，预后佳", 2: "中等", 3: "差，预后不良"}[g]}


@register("baveno", "Baveno VII 代偿期进展性慢性肝病（CSPH）判定",
          {"lsm_kpa": "肝脏硬度 kPa（FibroScan）", "plt_1e9l": "血小板 ×10⁹/L",
           "etiology_cured": "true=已病因清除（如 HCV 治愈/HBV 抑制）"},
          "de Franchis R et al. J Hepatol 2022;76:959（Baveno VII 共识）")
def baveno(p):
    lsm, plt = p["lsm_kpa"], p["plt_1e9l"]
    if lsm <= 15 and plt >= 150:
        g, m = "排除 CSPH", "可免内镜筛查；代偿期肝硬化 3 年失代偿风险 <1%"
    elif lsm >= 25:
        g, m = "诊断 CSPH", "按 CSPH 管理，需筛查静脉曲张并评估 β 阻滞剂"
    elif p.get("etiology_cured") and lsm < 20 and plt > 150:
        g, m = "低危（病因已清除）", "可暂缓内镜，1-2 年复查 LSM/PLT"
    else:
        g, m = "灰区", "需结合 PLT/脾大/肝静脉压差进一步评估，建议内镜"
    return {"grade": g, "lsm": lsm, "plt": plt, "meaning": m}


@register("sarin", "胃静脉曲张 Sarin 分型 + LDRf",
          {"type": "GOV1|GOV2|IGV1|IGV2"},
          "Sarin SK et al. Gastroenterology 1992;103:1664；国内 LDRf 分型见《肝硬化门静脉高压食管胃静脉曲张出血的防治指南》")
def sarin(p):
    t = p["type"].upper()
    d = {"GOV1": "食管静脉曲张沿胃小弯侧向下延伸（最常见，约占 GOV 的 75%），出血风险与 EV 相近",
         "GOV2": "食管静脉曲张跨越贲门延伸至胃底，曲张团块大、出血量大，治疗难度高于 GOV1",
         "IGV1": "孤立性胃底静脉曲张（无食管静脉曲张），常提示胃短静脉/胃后静脉反流，需 EUS 评估",
         "IGV2": "异位静脉曲张（胃体、胃窦、十二指肠、直肠等）"}
    if t not in d:
        return {"error": "type 必须是 GOV1/GOV2/IGV1/IGV2"}
    tip = {"GOV1": "首选 EIS 或 EVL；TAI 可用于辅助栓塞供血支",
           "GOV2": "首选组织胶（氰基丙烯酸酯）注射或 TIPS；EIS 单独效果差",
           "IGV1": "首选组织胶注射 ± TIPS；需排除脾静脉血栓",
           "IGV2": "按部位个体化，多需介入/外科"}[t]
    return {"grade": t, "meaning": d[t], "treatment_hint": tip}


# ============================================================ 纤维化 / 脂肪肝

@register("fib4", "FIB-4 肝纤维化指数",
          {"age": "年龄（岁）", "ast_ul": "AST U/L", "alt_ul": "ALT U/L", "plt_1e9l": "血小板 ×10⁹/L"},
          "Sterling RK et al. Hepatology 2006;43:1317")
def fib4(p):
    v = (p["age"] * p["ast_ul"]) / (p["plt_1e9l"] * math.sqrt(p["alt_ul"]))
    cut = 2.0 if p["age"] > 65 else 1.3
    g = "低危（可排除进展性纤维化）" if v < cut else ("灰区（需 FSM/ELASTOGRAFHY 复查）" if v <= 2.67 else "高危（疑似进展性纤维化）")
    return {"score": _r(v, 2), "grade": g,
            "threshold": "年龄>65 用 2.0，否则 1.3；>2.67 为高危"}


@register("apri", "APRI（AST/PLT 比值指数）",
          {"ast_ul": "AST U/L", "ast_uln": "AST 正常上限 U/L（常取 40）", "plt_1e9l": "血小板 ×10⁹/L"},
          "Wai CT et al. Hepatology 2003;38:518")
def apri(p):
    v = (p["ast_ul"] / p["ast_uln"]) * 100 / p["plt_1e9l"]
    g = "排除显著纤维化" if v < 0.5 else ("显著纤维化可能" if v < 1.5 else ("显著纤维化" if v < 2.0 else "肝硬化可能"))
    return {"score": _r(v, 2), "grade": g}


@register("nfs", "NFS 非酒精性脂肪肝纤维化评分",
          {"age": "年龄", "bmi": "BMI kg/m²", "ifg_dm": "true=空腹血糖受损或糖尿病",
           "ast_alt_ratio": "AST/ALT 比值", "plt_1e9l": "血小板 ×10⁹/L", "albumin_gl": "白蛋白 g/L"},
          "Angulo P et al. Hepatology 2007;45:846")
def nfs(p):
    v = (-1.675 + 0.037 * p["age"] + 0.094 * p["bmi"]
         + 1.13 * (1 if p.get("ifg_dm") else 0)
         + 0.99 * p["ast_alt_ratio"]
         - 0.013 * p["plt_1e9l"]
         - 0.66 * p["albumin_gl"])
    g = "可排除进展性纤维化（F3-F4）" if v < -1.455 else ("灰区" if v <= 0.676 else "进展性纤维化高风险")
    return {"score": _r(v, 3), "grade": g}


# ============================================================ 消化道出血

@register("gbs", "Glasgow-Blatchford 评分（GBS）",
          {"bun_mmol": "尿素氮 mmol/L", "hb_gl": "血红蛋白 g/L", "sex": "male|female",
           "sbp": "收缩压 mmHg", "hr": "心率 次/分",
           "melena": "true=黑便", "syncope": "true=晕厥", "liver_dz": "true=肝病",
           "cardiac": "true=心衰"},
          "Blatchford O et al. Lancet 2000;356:1318")
def gbs(p):
    pts = {}
    u = p["bun_mmol"]
    pts["bun"] = 0 if u < 6.5 else (2 if u < 8.0 else (3 if u < 10.0 else (4 if u < 25.0 else 6)))
    hb, male = p["hb_gl"], p.get("sex") == "male"
    if male:
        pts["hb"] = 0 if hb >= 130 else (1 if hb >= 120 else (3 if hb >= 100 else 6))
    else:
        pts["hb"] = 0 if hb >= 120 else (1 if hb >= 100 else 6)
    s = p["sbp"]
    pts["sbp"] = 0 if s >= 110 else (1 if s >= 100 else (2 if s >= 90 else 3))
    pts["hr"] = 1 if p["hr"] >= 100 else 0
    pts["melena"] = 1 if p.get("melena") else 0
    pts["syncope"] = 1 if p.get("syncope") else 0
    pts["liver"] = 2 if p.get("liver_dz") else 0
    pts["cardiac"] = 2 if p.get("cardiac") else 0
    total = sum(pts.values())
    g = ("极低危（可门诊管理，无需住院内镜）" if total <= 1
         else ("低危" if total <= 5 else "高危（需积极复苏 + 24h 内内镜）"))
    return {"score": total, "points": pts, "grade": g}


@register("aims65", "AIMS65",
          {"albumin_gl": "白蛋白 g/L", "inr": "INR", "altered_mental": "true=意识改变",
           "sbp": "收缩压 mmHg", "age": "年龄"},
          "Saltzman JR et al. Gastrointest Endosc 2011;74:1215")
def aims65(p):
    pts = {"albumin": 1 if p["albumin_gl"] < 30 else 0,
           "inr": 1 if p["inr"] > 1.5 else 0,
           "mental": 1 if p.get("altered_mental") else 0,
           "sbp": 1 if p["sbp"] < 90 else 0,
           "age": 1 if p["age"] > 65 else 0}
    t = sum(pts.values())
    return {"score": t, "points": pts,
            "grade": "低危" if t < 2 else "高危（院内死亡风险显著升高）",
            "mortality": {"0": "0.3%", "1": "1.2%", "2": "3.0%", "3": "5.3%", "4": "9.0%", "5": "15.0%"}.get(str(t), ">15%")}


@register("rockall", "Rockall 评分（含内镜）",
          {"age": "年龄", "shock": "none|tachy|hypo（none 无；tachy SBP≥100 且 HR≥100；hypo SBP<100）",
           "comorbid": "none|major|renal（none 无；major 心衰/IHD/其他；renal 肾衰/肝衰/肿瘤）",
           "endoscopic": "none|blood|tumor（none 无病变/Mallory-Weiss；blood 溃疡/糜烂/血管畸形；tumor 消化道肿瘤）",
           "stigmata": "none|blood（none 无或黑斑；blood 血液/血块/涌血）",
           "no_endoscopy": "true=仅临床部分（前 3 项，0-7 分）"},
          "Rockall TA et al. Gut 1996;38:316")
def rockall(p):
    pts = {"age": 0 if p["age"] < 60 else (1 if p["age"] < 80 else 2),
           "shock": {"none": 0, "tachy": 1, "hypo": 2}[p["shock"]],
           "comorbid": {"none": 0, "major": 2, "renal": 3}[p["comorbid"]]}
    if not p.get("no_endoscopy"):
        pts["endoscopic"] = {"none": 0, "blood": 1, "tumor": 2}[p["endoscopic"]]
        pts["stigmata"] = {"none": 0, "blood": 2}[p["stigmata"]]
    t = sum(pts.values())
    g = "低危" if t <= 2 else ("中危" if t <= 4 else "高危（再出血/死亡风险高，需 ICU 级监护）")
    return {"score": t, "points": pts, "grade": g}


# ============================================================ 胰腺炎

@register("bisap", "BISAP（急性胰腺炎严重度）",
          {"bun_mgdl": "尿素氮 mg/dL", "gcs_lt15": "true=GCS<15", "sirs": "true=SIRS≥2 项",
           "age": "年龄", "pleural_effusion": "true=胸腔积液"},
          "Wu BU et al. Gut 2008;57:1698")
def bisap(p):
    pts = {"bun": 1 if p["bun_mgdl"] > 25 else 0,
           "mental": 1 if p.get("gcs_lt15") else 0,
           "sirs": 1 if p.get("sirs") else 0,
           "age": 1 if p["age"] > 60 else 0,
           "effusion": 1 if p.get("pleural_effusion") else 0}
    t = sum(pts.values())
    return {"score": t, "points": pts,
            "grade": "轻症" if t < 3 else "重症高风险（病死率约 7-12%，需 ICU 评估）"}


@register("ranson", "Ranson 评分（非胆源性）",
          {"age": "年龄", "wbc_1e9l": "WBC ×10⁹/L", "glucose_mmol": "血糖 mmol/L",
           "ast_ul": "AST U/L", "ldh_ul": "LDH U/L",
           "hct_drop_pct": "48h 内 Hct 下降 %（可选）", "bun_rise_mmol": "48h 内 BUN 升高 mmol/L（可选）",
           "calcium_mmol": "血钙 mmol/L（可选）", "pao2_mmhg": "PaO₂ mmHg（可选）",
           "base_deficit": "碱缺失 mmol/L（可选）", "fluid_seq_ml": "48h 液体隔离量 mL（可选）"},
          "Ranson JH et al. Surg Gynecol Obstet 1974;139:69")
def ranson(p):
    adm = {"age": 1 if p["age"] > 55 else 0,
           "wbc": 1 if p["wbc_1e9l"] > 16 else 0,
           "glucose": 1 if p["glucose_mmol"] > 11.1 else 0,
           "ast": 1 if p["ast_ul"] > 250 else 0,
           "ldh": 1 if p["ldh_ul"] > 350 else 0}
    h = {"hct": 1 if (p.get("hct_drop_pct") or 0) > 10 else 0,
         "bun": 1 if (p.get("bun_rise_mmol") or 0) > 1.8 else 0,
         "ca": 1 if (p.get("calcium_mmol") is not None and p["calcium_mmol"] < 2.0) else 0,
         "pao2": 1 if (p.get("pao2_mmhg") is not None and p["pao2_mmhg"] < 60) else 0,
         "bd": 1 if (p.get("base_deficit") or 0) > 4 else 0,
         "fluid": 1 if (p.get("fluid_seq_ml") or 0) > 6000 else 0}
    t = sum(adm.values()) + sum(h.values())
    mort = "约 1%" if t <= 2 else ("约 15%" if t <= 4 else ("约 40%" if t <= 6 else "接近 100%"))
    return {"score": t, "admission": adm, "at48h": h,
            "grade": "轻症" if t <= 2 else ("中重度" if t <= 4 else "重症"),
            "mortality": mort,
            "note": "48h 项未提供者按 0 计，结果偏低估 —— 完整评分需等 48h 数据"}


# ============================================================ 通用

@register("egfr_ckdepi2021", "eGFR（CKD-EPI 2021，无种族系数）",
          {"creat_mgdl": "肌酐 mg/dL", "age": "年龄", "female": "true=女性"},
          "Inker LA et al. NEJM 2021;385:1737")
def egfr(p):
    scr, age, f = p["creat_mgdl"], p["age"], bool(p.get("female"))
    k = 0.7 if f else 0.9
    al = -0.241 if f else -0.302
    v = 142 * (min(scr / k, 1) ** al) * (max(scr / k, 1) ** -1.200) * (0.9938 ** age) * (1.012 if f else 1)
    g = ("G1 正常" if v >= 90 else ("G2 轻度下降" if v >= 60 else ("G3a" if v >= 45 else
         ("G3b" if v >= 30 else ("G4" if v >= 15 else "G5 肾衰")))))
    return {"score": _r(v, 1), "unit": "mL/min/1.73m²", "grade": g}


@register("crcl", "Cockcroft-Gault 肌酐清除率（药物剂量调整用）",
          {"age": "年龄", "weight_kg": "体重 kg", "creat_mgdl": "肌酐 mg/dL", "female": "true=女性"},
          "Cockcroft DW, Gault MH. Nephron 1976;16:31")
def crcl(p):
    v = ((140 - p["age"]) * p["weight_kg"] * (0.85 if p.get("female") else 1)) / (72 * p["creat_mgdl"])
    return {"score": _r(v, 1), "unit": "mL/min",
            "note": "按实际体重；肥胖患者宜用调整体重，结果可能高估"}


@register("corrected_calcium", "白蛋白校正血钙",
          {"ca_mgdl": "实测总钙 mg/dL", "albumin_gdl": "白蛋白 g/dL"},
          "Orell DH. Ann Intern Med 1988；1 mg/dL 白蛋白 ≈ 0.8 mg/dL 钙")
def corrected_calcium(p):
    v = p["ca_mgdl"] + 0.8 * (4.0 - p["albumin_gdl"])
    return {"score": _r(v, 2), "unit": "mg/dL",
            "grade": "低钙" if v < 8.4 else ("正常" if v <= 10.2 else "高钙")}


@register("saag", "SAAG（血清-腹水白蛋白梯度）",
          {"serum_albumin_gdl": "血清白蛋白 g/dL", "ascites_albumin_gdl": "腹水白蛋白 g/dL"},
          "Runyon BA et al. Ann Intern Med 1992;117:215")
def saag(p):
    v = p["serum_albumin_gdl"] - p["ascites_albumin_gdl"]
    g = "门脉高压性腹水（≥1.1）" if v >= 1.1 else "非门脉高压性腹水（<1.1，如腹膜癌/结核）"
    return {"score": _r(v, 2), "unit": "g/dL", "grade": g}


@register("bmi", "BMI + BSA",
          {"height_cm": "身高 cm", "weight_kg": "体重 kg"},
          "WHO；BSA 用 Mosteller 公式")
def bmi(p):
    h = p["height_cm"] / 100.0
    v = p["weight_kg"] / (h * h)
    bsa = math.sqrt(p["height_cm"] * p["weight_kg"] / 3600)
    g = ("偏瘦" if v < 18.5 else "正常" if v < 24 else "超重" if v < 28 else "肥胖")
    return {"bmi": _r(v, 1), "bsa_m2": _r(bsa, 2), "grade": g,
            "note": "分级按中国标准（超重≥24，肥胖≥28）"}


@register("clavien_dindo", "Clavien-Dindo 手术并发症分级",
          {"grade": "I|II|IIIa|IIIb|IVa|IVb|V"},
          "Dindo D et al. Ann Surg 2004;240:205")
def clavien(p):
    g = str(p["grade"])
    d = {"I": "无需治疗干预（止吐、退热、镇痛、利尿、理疗），仅允许床边处理",
         "II": "需要药物治疗（含输血、TPN），不需侵入性操作",
         "IIIa": "需介入/内镜/放射引导下操作，不需全麻",
         "IIIb": "需全麻下手术/内镜/介入",
         "IVa": "单器官功能衰竭（含透析）",
         "IVb": "多器官功能衰竭",
         "V": "死亡"}
    if g not in d:
        return {"error": "grade 必须是 I/II/IIIa/IIIb/IVa/IVb/V"}
    return {"grade": g, "meaning": d[g]}


@register("asr_grade", "ASA 麻醉风险分级",
          {"class": "1|2|3|4|5|6"},
          "ASA Physical Status Classification（2020 版）")
def asa(p):
    d = {"1": "健康", "2": "轻度系统性疾病", "3": "重度系统性疾病，非失能",
         "4": "失能性系统性疾病，持续威胁生命", "5": "濒死，预期不手术难存活 24h",
         "6": "脑死亡，器官捐献"}
    k = str(p["class"])
    return {"grade": "ASA %s" % k, "meaning": d.get(k, "未知分级")}


# ============================================================ CLI

def _parse(argv):
    """把 --k v 解析成 dict，自动转数值/布尔"""
    out = {}
    i = 0
    while i < len(argv):
        tok = argv[i]
        if not tok.startswith("--"):
            i += 1
            continue
        k = tok[2:]
        nxt = argv[i + 1] if i + 1 < len(argv) else None
        if nxt is not None and not nxt.startswith("--"):
            out[k] = nxt
            i += 2
        else:
            out[k] = True
            i += 1
    # 数值化
    for k, v in list(out.items()):
        if isinstance(v, str):
            try:
                out[k] = int(v) if (v.lstrip("-").isdigit()) else float(v)
            except ValueError:
                out[k] = v
    return out


def main():
    argv = sys.argv[1:]
    if not argv or argv[0] in ("--list", "-l"):
        for name, m in sorted(REGISTRY.items()):
            print("%-20s %s" % (name, m["cn"]))
            print("%22s%s" % ("", "来源: " + m["source"]))
        print("\n用法: medcalc.py <名称> --参数 值 ...   （--json 在前或后均可）")
        return 0

    as_json = "--json" in argv
    argv = [a for a in argv if a != "--json"]
    name = argv[0]
    if name not in REGISTRY:
        print("[ERROR] 未知计算器: %s -> 用 --list 查看" % name, file=sys.stderr)
        return 2

    m = REGISTRY[name]
    p = _parse(argv[1:])
    # 布尔参数在 CLI 里可能是字符串 "true"
    for k, v in list(p.items()):
        if isinstance(v, str) and v.lower() in ("true", "false"):
            p[k] = v.lower() == "true"
    try:
        res = m["fn"](p)
    except KeyError as e:
        print("[ERROR] 缺少参数 %s -> 需要: %s" % (e, list(m["params"])), file=sys.stderr)
        return 2
    except Exception as e:
        print("[ERROR] %s: %s" % (type(e).__name__, e), file=sys.stderr)
        return 2

    res["_calc"] = name
    res["_cn"] = m["cn"]
    res["_source"] = m["source"]
    if as_json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print("【%s】" % m["cn"])
        for k, v in res.items():
            if k.startswith("_"):
                continue
            if isinstance(v, dict):
                print("  %-12s %s" % (k, " / ".join("%s=%s" % (a, b) for a, b in v.items())))
            else:
                print("  %-12s %s" % (k, v))
        print("  来源: %s" % m["source"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
