#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
考研英语真题的数据层。

为什么单独一个模块
------------------
英语与政治/408 **不是一个形状**，不能套用同一套模型：

  政治 / 408 ：一科一卷；「一道题 = 一问一答」，各自独立
  英语       ：一科多卷种（英语一/英语二）；
               **复合题** —— 完形 20 空共享 1 篇文章、阅读 4 篇 × 5 题

所以这里把"**材料 + 多个小题**"显式建成一层：
    paper(tier, year)           → 一套卷
    paper["篇目"] = [ {部分, 材料, 小题:[...]}, ... ]

  篇目（passage）是英语真题的天然单位：
    · 完形：1 篇文章 + 20 个空
    · 阅读 Part A：4 篇文章，每篇 + 5 题
    · 新题型 Part B：1 组材料 + 5 题
    · 翻译 Part C：1 段材料 + 若干句（或 1 题）
    · 写作：2 题（各自独立，无材料）

题号体系（英语一/二 **完全相同**）
---------------------------------
    1–20    完形
    21–40   阅读（4 篇 × 5 题）
    41–45   新题型
    46–50   翻译（英语二只有 46）
    51–52   写作

数据存放
--------
    data/english/<tier>-<年>.json     tier ∈ {EN1, EN2}
    data/english/<tier>-<年>-解析.json  答案与解析（与试题分开存 ——
        试题由 GitHub 那份干净 PDF 解析，答案是懒笔记的来源，
        两者的"重新导入"节奏不同，混在一起会互相覆盖）
"""
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

ENG_DIR = os.path.join(BASE, "data", "english")

# ---------------------------------------------------------------- 卷种与部分
TIERS = {
    "EN1": {"简称": "英语一", "全称": "考研英语（一）",
            "适用": "学术型硕士为主，部分专硕"},
    "EN2": {"简称": "英语二", "全称": "考研英语（二）",
            "适用": "专业型硕士为主"},
}

# 部分定义：题号区间 + 题型 + 官方分值（英一/英二 只有 Part C 与写作不同）
PARTS = {
    "CLOZE":  {"全称": "完形填空 Use of English", "简称": "完形",
               "题号": (1, 20), "题型": "四选一", "分值": 10},
    "READ":   {"全称": "阅读理解 Part A", "简称": "阅读",
               "题号": (21, 40), "题型": "四选一", "分值": 40},
    "NEW":    {"全称": "新题型 Part B", "简称": "新题型",
               "题号": (41, 45), "题型": "选句/排序", "分值": 10},
    "TRANS":  {"全称": "翻译 Part C", "简称": "翻译",
               "题号": (46, 50), "题型": "主观（英译汉）",
               "分值": {"EN1": 10, "EN2": 15}},
    "WRITE":  {"全称": "写作 Part A/B", "简称": "写作",
               "题号": (51, 52), "题型": "主观（作文）",
               "分值": {"EN1": 30, "EN2": 25}},
}

# 主观部分：不能自动判分，走 AI 评阅或自评
SUBJECTIVE = {"TRANS", "WRITE"}


# 【两卷的主观题题号区间不同】必须按卷种分开，否则英语二全算不出来
#   英语一：翻译 46–50（5 句）、写作 51–52
#   英语二：翻译 46    （1 段）、写作 47–48
_TIER_RANGE = {
    ("EN1", "TRANS"): (46, 50), ("EN1", "WRITE"): (51, 52),
    ("EN2", "TRANS"): (46, 46), ("EN2", "WRITE"): (47, 48),
}


def part_of(num, tier="EN1"):
    """
    题号 → 部分代码。返回 (代码, 边界题?)

    **主观题的区间按卷种不同**：英语二写作是 47–48（不是 51–52）。
    我最初只写了"英语二翻译只有 46"这一个特例，写作仍按 51–52 判断，
    结果英语二的 47/48 落到"未归类"，分值算出 0 分。
    """
    n = int(num)
    for code, d in PARTS.items():
        lo, hi = d["题号"]
        if code in SUBJECTIVE:
            lo, hi = _TIER_RANGE.get((tier, code), (lo, hi))
        if lo <= n <= hi:
            return code, n in (lo, hi)
    return "未归类", False


def part_name(code):
    return PARTS.get(code, {}).get("简称", code)


def part_full(code):
    return PARTS.get(code, {}).get("全称", code)


def part_score(code, tier="EN1"):
    v = PARTS.get(code, {}).get("分值", 0)
    return v.get(tier, 0) if isinstance(v, dict) else v


def path_of(tier, year):
    return os.path.join(ENG_DIR, f"{tier}-{year}.json")


def expl_path_of(tier, year):
    return os.path.join(ENG_DIR, f"{tier}-{year}-解析.json")


def load_json(p):
    if not os.path.exists(p):
        return None
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:                                     # noqa: BLE001
        return None


def years(tier):
    """某卷种已有试题的年份（升序）。**严格匹配 `<tier>-<4位>.json`** ——
    目录里还有 `-解析.json` 等派生文件，宽松匹配会把同一年算两次。"""
    if not os.path.isdir(ENG_DIR):
        return []
    pat = re.compile(rf'{re.escape(tier)}-(\d{{4}})\.json')
    out = []
    for f in os.listdir(ENG_DIR):
        m = pat.fullmatch(f)
        if m:
            out.append(m.group(1))
    return sorted(out)


def paper(tier, year):
    """
    读一套卷。返回 {"tier","年份","篇目":[...],"题目数"} 或 None。

    每道小题都补上 id / 部分 / 部分名，供界面与作答记录使用
    （id 形如 `EN1-2024-21`，与政治 `ZZ-2024-1`、408 的风格一致）。
    """
    rec = load_json(path_of(tier, year))
    if not rec:
        return None
    for ps in rec.get("篇目", []):
        code = ps.get("部分") or part_of(
            (ps.get("小题") or [{}])[0].get("题号", 1), tier)[0]
        ps["部分"] = code
        ps["部分名"] = part_name(code)
        ps["部分全称"] = part_full(code)
        for q in ps.get("小题", []):
            n = q.get("题号")
            c, edge = part_of(n, tier) if n else (code, False)
            q["部分"] = c
            q["部分名"] = part_name(c)
            q["边界题"] = edge
            q["id"] = f"{tier}-{year}-{n}"
            q["tier"] = tier
            q["year"] = str(year)
            # 主观题标记：界面据此走"AI 评阅"而不是"对答案"
            q["主观"] = c in SUBJECTIVE
    return rec


def questions(tier=None):
    """全部小题（可按卷种过滤），键为 id。"""
    out = {}
    tiers = [tier] if tier else list(TIERS)
    for t in tiers:
        for y in years(t):
            rec = paper(t, y)
            if not rec:
                continue
            for ps in rec.get("篇目", []):
                for q in ps.get("小题", []):
                    out[q["id"]] = q
    return out


def explanation(tier, year, num):
    """
    取某题的答案与解析。返回 {"答案":..., "解析":..., "来源":...} 或 None。

    **与试题分开存放**（`<tier>-<年>-解析.json`）—— 试题和答案来自不同来源、
    重新导入的节奏不同，混在一起会互相覆盖（政治那边为此丢过三次答案）。
    """
    rec = load_json(expl_path_of(tier, year))
    if not rec:
        return None
    ans = rec.get("解答") or {}
    e = ans.get(str(num))
    if e:
        return e
    # 【翻译的参考译文是**整卷一份**，不分题号】
    # 写盘时只存了 `_参考译文` 一个键（一篇文章对应 46–50 五题共用），
    # 所以按题号取不到时回退到整卷那一份。
    #
    # **但必须限定在翻译题上** —— 我最初没限制，结果写作题（51/52）
    # 也拿到了翻译的参考译文，显示成"参考译文"而不是"参考范文"。
    try:
        if part_of(num, tier)[0] == "TRANS":   # 注意返回的是元组 (代码, 边界题?)
            ref = ans.get("_参考译文")
            if ref:
                return {"_参考译文": ref, "来源": "懒笔记"}
    except Exception:                                       # noqa: BLE001
        pass
    return None


def part_stats(tier, year):
    """按部分统计：题数 / 有答案数 / 分值。供真题页显示真实规模。"""
    rec = paper(tier, year)
    out = {}
    if not rec:
        return out
    for ps in rec.get("篇目", []):
        code = ps["部分"]
        d = out.setdefault(code, {"篇数": 0, "小题数": 0, "有答案": 0,
                                 "分值": part_score(code, tier)})
        d["篇数"] += 1
        for q in ps.get("小题", []):
            d["小题数"] += 1
            if explanation(tier, year, q["题号"]):
                d["有答案"] += 1
    return out


def tier_list():
    """供界面用：[{id, 简称, 全称, 适用, 年份数, 题量}, ...]"""
    out = []
    for tid, d in TIERS.items():
        ys = years(tid)
        n = 0
        for y in ys:
            rec = paper(tid, y)
            if rec:
                n += sum(len(ps.get("小题", [])) for ps in rec.get("篇目", []))
        out.append({**d, "id": tid, "年份数": len(ys),
                    "首年": ys[0] if ys else None,
                    "末年": ys[-1] if ys else None, "题量": n})
    return out


# ---------------------------------------------------------------------------
# 计分：单题分值 + 成绩单
# ---------------------------------------------------------------------------
# 为什么要单独算单题分值：`PARTS` 里只定义了**部分总分**，而成绩单需要
# 逐题累加。且主观题不能平均分 —— 小作文与大作文分值不同：
#     英语一：小作文 51 = 10 分，大作文 52 = 20 分（合计 30）
#     英语二：小作文 47 = 10 分，大作文 48 = 15 分（合计 25）
# 翻译则是平均分（英语一 5 句 × 2 分；英语二 1 段 15 分）。
_WRITE_SCORE = {
    ("EN1", 51): 10, ("EN1", 52): 20,
    ("EN2", 47): 10, ("EN2", 48): 15,
}
# 各部分题数（用于把部分总分摊到每题）
_PART_COUNT = {
    "CLOZE": {"EN1": 20, "EN2": 20},
    "READ":  {"EN1": 20, "EN2": 20},
    "NEW":   {"EN1": 5,  "EN2": 5},
    "TRANS": {"EN1": 5,  "EN2": 1},
}


def score_of(num, tier="EN1"):
    """某题的**分值**（分）。"""
    code = part_of(num, tier)[0]
    n = int(num)
    if code == "WRITE":
        return float(_WRITE_SCORE.get((tier, n), 0))
    cnt = _PART_COUNT.get(code, {}).get(tier)
    total = part_score(code, tier)
    if not cnt or not total:
        return 0.0
    return round(total / cnt, 2)


def report(tier, year, answers, ai_grades=None):
    """
    算一套卷的**成绩单**。

    核心口径（用户认可）：
      · 未做完时**不给总分**，只给「已作答部分的得分 + 正确率」
      · AI 评阅按官方档位折算成分数，**计入总分**（用户要求更直观），
        但成绩单上必须把「客观题得分」与「AI 评阅得分」**分开列**
        —— 混成一个数就分不清哪部分是机器判的
      · 未作答的题标 `answered=False`，**不按 0 分计入**（不能因为没做就拉低）

    answers: {question_id: {"chosen":..., "is_correct":...}}
    ai_grades: {question_id: {"score":..., "band":..., "score_max":...}}

    返回 dict：
      parts: [{code, 名称, 题数, 已作答, 答对, 得分, 满分, 主观?}]
      obj_done / obj_total / obj_score / obj_max / obj_acc
      sub_total / sub_max / sub_list（逐题 AI 档次与得分）
      done / total（题数覆盖）
      complete（是否全做完）
    """
    ai_grades = ai_grades or {}
    rec = paper(tier, year) or {}
    parts = []
    obj_done = obj_total = 0
    obj_score = obj_max = 0.0
    sub_total = sub_max = 0.0
    sub_list = []
    done_n = total_n = 0

    for ps in rec.get("篇目", []):
        code = ps.get("部分")
        if code not in PARTS:
            continue
        subs = ps.get("小题") or []
        is_subj = code in SUBJECTIVE
        d = 0
        ok = 0
        sc = 0.0
        mx = 0.0
        for q in subs:
            qid = q["id"]
            per = score_of(q["题号"], tier) or float(q.get("分值") or 0)
            mx += per
            total_n += 1
            a = answers.get(qid)
            if is_subj:
                g = ai_grades.get(qid)
                if g and g.get("score") is not None:
                    d += 1
                    done_n += 1
                    sc += float(g["score"])
                    sub_list.append({"题号": q["题号"], "题型": q.get("题型"),
                                     "band": g.get("band"),
                                     "position": g.get("position"),
                                     "score": g.get("score"),
                                     "score_max": per})
                else:
                    sub_list.append({"题号": q["题号"], "题型": q.get("题型"),
                                     "band": None, "score": None,
                                     "score_max": per})
            else:
                obj_total += 1
                mx_obj = per
                if a:
                    d += 1
                    done_n += 1
                    obj_done += 1
                    if a.get("is_correct"):
                        ok += 1
                        sc += per
                        obj_score += per
            # 累计客观题满分
        if is_subj:
            for item in sub_list:
                if item["score_max"] and item["band"]:
                    pass
            sub_total += sc
            sub_max += mx
        else:
            obj_max += mx
        # **按部分合并**：阅读是 4 篇、翻译是 5 句，逐篇目列会拆成很多行
        # （实测成绩单里出现 4 行"阅读"、5 行"翻译"），应按"部分"汇总。
        found = next((x for x in parts if x["code"] == code), None)
        if found:
            found["题数"] += len(subs)
            found["已作答"] += d
            found["答对"] += ok
            found["得分"] = round(found["得分"] + sc, 2)
            found["满分"] = round(found["满分"] + mx, 2)
        else:
            parts.append({
                "code": code, "名称": part_name(code),
                "题数": len(subs), "已作答": d, "答对": ok,
                "得分": round(sc, 2), "满分": round(mx, 2),
                "主观": is_subj,
            })

    return {
        "parts": parts,
        "obj_done": obj_done, "obj_total": obj_total,
        "obj_score": round(obj_score, 2), "obj_max": round(obj_max, 2),
        "obj_acc": (round(obj_score / obj_max * 100, 1) if obj_max else 0.0),
        "sub_total": round(sub_total, 2), "sub_max": round(sub_max, 2),
        "sub_list": sub_list,
        "done": done_n, "total": total_n,
        "complete": done_n >= total_n and total_n > 0,
        "total_score": round(obj_score + sub_total, 2),
        "total_max": round(obj_max + sub_max, 2),
    }
