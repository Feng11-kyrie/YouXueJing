#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
考研数学题库的数据层（数一 / 数二 / 数三）。

为什么单独一层
--------------
数学与 408/政治/英语的结构都不同：
  · 数学分**卷种**（数一/数二/数三），同一年的三份卷子题号体系相同、题目不同；
  · 每份卷子 150 分，题型固定：选择 / 填空 / 解答；
  · 题干和选项里有大量 **LaTeX 公式**，渲染不是纯文本（见 yj/mathrender.py）。

数据形态（data/math/<卷种>/<年>.json）：
    {"年份": 2015, "卷种": "一", "题数": 23,
     "题目": [{"题号": 1, "题型": "单项选择题", "题干": "...", "选项": {...},
               "答案": "C", "解析": "..."}, ...]}
"""
import json
import os
import re
from functools import lru_cache

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MATH_DIR = os.path.join(BASE, "data", "math")

TIERS = {"一": "数学一", "二": "数学二", "三": "数学三"}
TIER_CODE = {"一": "301", "二": "302", "三": "303"}

# 各年客观题分值：2010–2020 选择/填空 4 分；2021 起 5 分
def point_each(year):
    return 5 if int(year) >= 2021 else 4


def _path(tier, year):
    return os.path.join(MATH_DIR, tier, f"{year}.json")


def tiers_available():
    """有数据的卷种，按「一、二、三」排序。"""
    out = []
    for t in ("一", "二", "三"):
        d = os.path.join(MATH_DIR, t)
        if os.path.isdir(d) and any(f.endswith(".json") and f[0].isdigit()
                                   for f in os.listdir(d)):
            out.append(t)
    return out


def years(tier):
    d = os.path.join(MATH_DIR, tier)
    if not os.path.isdir(d):
        return []
    ys = []
    for f in os.listdir(d):
        m = re.fullmatch(r"(\d{4})\.json", f)
        if m:
            ys.append(m.group(1))
    return sorted(ys)


@lru_cache(maxsize=64)
def paper(tier, year):
    """读某卷种某年的整份卷子；没有返回 None。"""
    p = _path(str(tier), str(year))
    if not os.path.exists(p):
        return None
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:                                       # noqa: BLE001
        return None


def questions(tier, year):
    rec = paper(tier, year) or {}
    return rec.get("题目") or []


def question(tier, year, qno):
    for q in questions(tier, year):
        if str(q.get("题号")) == str(qno):
            return q
    return None


def full_score(tier, year):
    """整卷满分（数学固定 150）。"""
    return 150


def q_score(q, year):
    """单题分值：题库里有「分值」就用它，其次题干里的「本题满分 X 分」，
    最后按题型默认（选择/填空 4 或 5，解答 10）。"""
    if q.get("分值"):
        try:
            return float(q["分值"])
        except (TypeError, ValueError):
            pass
    m = re.search(r"本题满分\s*(\d+)\s*分", q.get("题干") or "")
    if m:
        return int(m.group(1))
    if q.get("题型") == "解答题":
        return 10
    return point_each(year)


def stats(tier, year):
    qs = questions(tier, year)
    from collections import Counter
    c = Counter(q.get("题型") for q in qs)
    return {"题数": len(qs), "选择题": c.get("单项选择题", 0),
            "填空题": c.get("填空题", 0), "解答题": c.get("解答题", 0)}


# ---------------------------------------------------------------- 考点与诊断
def points(tier):
    """{考点: [题目...]}，只统计有考点标签的题。"""
    out = {}
    for y in years(tier):
        for q in questions(tier, y):
            kp = (q.get("考点") or "").strip()
            if not kp:
                continue
            q = dict(q)
            q["_year"] = y
            out.setdefault(kp, []).append(q)
    return out


def point_list(tier):
    """考点列表（按题量降序），供诊断覆盖与筛题用。"""
    ps = points(tier)
    return [{"考点": k, "题数": len(v)}
            for k, v in sorted(ps.items(), key=lambda kv: (-len(kv[1]), kv[0]))]


def diagnostic(tier, n=12):
    """
    组一套诊断卷：**每个考点抽一道选择题**，优先近年、优先没做过的。

    为什么按考点而不是随机：诊断要能回答"哪块弱"，随机抽 12 道很可能
    全落在同一章；按考点各抽一道，12 道题就是 12 个考点的探针。
    """
    ps = points(tier)
    if not ps:
        return []
    items = []
    for kp in sorted(ps):
        choices = [q for q in ps[kp] if q.get("题型") == "单项选择题"]
        if not choices:
            continue
        choices.sort(key=lambda q: (-int(q["_year"]), int(q["题号"])))
        items.append((kp, choices[0]))
    # 用题量做一点分层：题多的考点优先（更常考），但保证不同考点
    items.sort(key=lambda kv: (-len(ps[kv[0]]), kv[0]))
    return [{"考点": kp, "题目": q} for kp, q in items[:n]]


def point_mastery(tier, answers):
    """
    按数学作答记录算考点掌握度。

    answers: store.get_answers() 的 {id: {chosen,is_correct,source}}
    只统计**客观题**（选择/填空）；解答题自评不计入正确率。
    返回 [{考点, 作答, 答对, 正确率, 题数}]，按正确率升序。
    """
    ps = points(tier)
    out = []
    for kp, qs in ps.items():
        done = ok = 0
        for q in qs:
            if q.get("题型") == "解答题":
                continue
            rec = answers.get(f"MATH-{tier}-{q['_year']}-{q['题号']}")
            if not rec or rec.get("source") == "selfscore":
                continue
            done += 1
            ok += 1 if rec.get("is_correct") else 0
        out.append({"考点": kp, "作答": done, "答对": ok,
                    "正确率": (ok / done) if done else None,
                    "题数": len(qs)})
    out.sort(key=lambda r: (r["正确率"] is None, r["正确率"] or 0, -r["作答"]))
    return out
