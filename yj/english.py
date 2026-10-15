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


def part_of(num, tier="EN1"):
    """题号 → 部分代码。返回 (代码, 边界题?)"""
    n = int(num)
    for code, d in PARTS.items():
        lo, hi = d["题号"]
        # 英语二的翻译只有 46 题（1 段 15 分），不占 46–50
        if tier == "EN2" and code == "TRANS" and n != 46:
            continue
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
    e = (rec.get("解答") or {}).get(str(num))
    if not e:
        return None
    return e


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
