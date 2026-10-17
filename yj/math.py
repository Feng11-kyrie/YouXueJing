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
    """单题分值：题干里写了「本题满分 X 分」就用它，否则按题型默认。"""
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
