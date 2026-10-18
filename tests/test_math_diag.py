#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数学诊断闭环的回归测试（数一/二/三）。

钉住：
  1. 每个卷种的所有题都有考点标签（没有考点就无法按考点诊断）；
  2. 诊断卷 12 道题覆盖 12 个不同考点，全部是选择题；
  3. 考点掌握度能按作答记录算对（1 对 1 错 = 50%）；
  4. 这道题/考点的 id 与 store 的作答 key 一致。

用法：  .venv/bin/python tests/test_math_diag.py
"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from yj import math as m                                       # noqa: E402


def check_tags():
    for tier in ("一", "二", "三"):
        missing = []
        for y in m.years(tier):
            for q in m.questions(tier, y):
                if not (q.get("考点") or "").strip():
                    missing.append(f"{y}-{q['题号']}")
        assert not missing, f"数学{tier} 缺考点：{missing[:8]}"


def check_diagnostic():
    for tier in ("一", "二", "三"):
        items = m.diagnostic(tier, 12)
        assert len(items) == 12, (tier, len(items))
        kps = [x["考点"] for x in items]
        assert len(set(kps)) == 12, (tier, kps)
        for x in items:
            q = x["题目"]
            assert q["题型"] == "单项选择题", (tier, x["考点"], q["题型"])
            assert (q.get("考点") or "") == x["考点"]
            assert str(q["_year"]) in m.years(tier)
            assert q.get("答案") in list("ABCD")


def check_mastery():
    # 找数一第一道有考点的选择题，构造一对一错
    qs = [q for q in m.points("一")["二次型"] if q["题型"] == "单项选择题"]
    q = qs[0]
    qid = f"MATH-一-{q['_year']}-{q['题号']}"
    answers = {qid: {"is_correct": True, "source": "diagnostic", "chosen": "A"}}
    row = [r for r in m.point_mastery("一", answers) if r["考点"] == "二次型"][0]
    assert row["作答"] == 1 and row["答对"] == 1 and row["正确率"] == 1.0
    answers[qid] = {"is_correct": False, "source": "diagnostic", "chosen": "B"}
    row = [r for r in m.point_mastery("一", answers) if r["考点"] == "二次型"][0]
    assert row["作答"] == 1 and row["答对"] == 0 and row["正确率"] == 0.0


if __name__ == "__main__":
    check_tags()
    check_diagnostic()
    check_mastery()
    print("数学诊断闭环测试通过（数一/二/三：考点标签、12 题覆盖、掌握度）")
