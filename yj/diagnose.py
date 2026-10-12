#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
答题记录 → 章节/学科掌握度。

核心设计
--------
1. **聚合到章节级**: 申报表明确"不做精细化学情诊断", 所以只做到章(24 个)。
   叶子级掌握度仅供参考, 不对外暴露为"诊断结论"。

2. **Laplace 平滑**: 掌握度 = (答对 + 1) / (题数 + 2)。
   不做平滑的话, 只答 1 题答对就是 100%、答错就是 0%,
   会给出极端且不稳的推荐 —— 这是新用户冷启动必须处理的。

3. **诊断与练习统一口径**: 两个来源的作答都计入, 但分别可查。
   诊断用于冷启动, 练习用于持续修正。
"""
from collections import defaultdict

from . import data

ALPHA = 1.0          # 平滑系数


def _smoothed(correct, total):
    return (correct + ALPHA) / (total + 2 * ALPHA)


def mastery_by_chapter(answers):
    """
    答案 -> {章 id: {掌握度, 题数, 答对, 章节名, 学科}}

    一道题的归属: 按它的**主考点**所在的章。
    """
    qs = data.questions()
    agg = defaultdict(lambda: {"correct": 0, "total": 0})
    for qid, a in answers.items():
        q = qs.get(qid)
        if not q:
            continue
        ch = data.chapter_of(q["主考点"])
        if not ch:
            continue
        agg[ch]["total"] += 1
        agg[ch]["correct"] += 1 if a["is_correct"] else 0

    out = {}
    for ch, v in agg.items():
        n = data.nodes().get(ch, {})
        out[ch] = {
            "chapter": ch,
            "章节名": n.get("name", ch),
            "学科": data.CODE2NAME.get(n.get("subject"), ""),
            "学科码": n.get("subject"),
            "掌握度": round(_smoothed(v["correct"], v["total"]), 3),
            "题数": v["total"],
            "答对": v["correct"],
        }
    return out


def mastery_by_leaf(answers):
    """叶子考点级掌握度(内部用, 用于精确定位与生成资源)"""
    qs = data.questions()
    agg = defaultdict(lambda: {"correct": 0, "total": 0})
    for qid, a in answers.items():
        q = qs.get(qid)
        if not q:
            continue
        leaf = q["主考点"]
        agg[leaf]["total"] += 1
        agg[leaf]["correct"] += 1 if a["is_correct"] else 0
    out = {}
    for leaf, v in agg.items():
        out[leaf] = {
            "leaf": leaf, "考点名": data.node_name(leaf),
            "学科": data.CODE2NAME.get(data.subject_of(leaf), ""),
            "章节": data.node_name(data.chapter_of(leaf)),
            "掌握度": round(_smoothed(v["correct"], v["total"]), 3),
            "题数": v["total"], "答对": v["correct"],
        }
    return out


def mastery_by_subject(answers):
    """学科级掌握度: 该学科所有作答的整体正确率(同样平滑)"""
    qs = data.questions()
    agg = defaultdict(lambda: {"correct": 0, "total": 0})
    for qid, a in answers.items():
        q = qs.get(qid)
        if not q:
            continue
        code = data.NAME2CODE.get(q["学科"])
        if not code:
            continue
        agg[code]["total"] += 1
        agg[code]["correct"] += 1 if a["is_correct"] else 0
    out = {}
    for code, v in agg.items():
        out[code] = {
            "学科码": code, "学科": data.CODE2NAME[code],
            "满分": next(s["满分"] for s in data.syllabus()["学科"] if s["id"] == code),
            "掌握度": round(_smoothed(v["correct"], v["total"]), 3),
            "题数": v["total"], "答对": v["correct"],
        }
    return out


def summarize(answers):
    """一次算齐三层掌握度, 供画像与路径复用"""
    return {
        "章节": mastery_by_chapter(answers),
        "考点": mastery_by_leaf(answers),
        "学科": mastery_by_subject(answers),
        "作答数": len(answers),
    }
