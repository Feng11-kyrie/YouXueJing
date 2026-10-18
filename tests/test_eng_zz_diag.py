#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
英语（按题型）/ 政治（按部分）诊断的回归测试。

钉住：
  · 英语诊断卷 = 完形 + 阅读 + 新题型，30 题，题目都有 id/答案；
  · 政治诊断卷 = 5 部分 × 3 题（2 单选 + 1 多选），id 唯一；
  · 题型/部分掌握度能按作答记录算对（1 对 = 100%，1 错 = 0%）。

用法：  .venv/bin/python tests/test_eng_zz_diag.py
"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from yj import english as en                                   # noqa: E402
from yj import zhengzhi as zz                                  # noqa: E402


def check_english():
    parts = en.part_list()
    assert [(p["部分"], p["客观"]) for p in parts] == [
        ("CLOZE", True), ("READ", True), ("NEW", True),
        ("TRANS", False), ("WRITE", False)]
    diag = en.diagnostic("EN1")
    assert diag and diag["题数"] == 30
    codes = [p["部分"] for p in diag["篇目"]]
    assert codes == ["CLOZE", "READ", "NEW"], codes
    for ps in diag["篇目"]:
        for q in ps["小题"]:
            assert q.get("id")
            e = en.explanation("EN1", diag["year"], q["题号"]) or {}
            assert (e.get("答案") or "").strip(), (diag["year"], q["题号"])

    # 掌握度：拿阅读第一题做一对一错
    q = diag["篇目"][1]["小题"][0]
    qid = q["id"]
    a = {qid: {"is_correct": True, "source": "diagnostic", "chosen": "A"}}
    row = [r for r in en.part_mastery("EN1", a) if r["部分"] == "READ"][0]
    assert row["作答"] == 1 and row["答对"] == 1 and row["正确率"] == 1.0
    a[qid] = {"is_correct": False, "source": "diagnostic", "chosen": "B"}
    row = [r for r in en.part_mastery("EN1", a) if r["部分"] == "READ"][0]
    assert row["作答"] == 1 and row["答对"] == 0 and row["正确率"] == 0.0


def check_zz():
    parts = zz.part_list()
    assert len(parts) == 5
    items = zz.diagnostic()
    assert len(items) == 15
    from collections import Counter
    c = Counter(zz.part_of(x["题目"]["题号"], x["题目"]["题型"])[0]
                for x in items)
    assert set(c) == set(zz.PARTS) and all(v == 3 for v in c.values()), c
    ids = [x["题目"]["id"] for x in items]
    assert len(ids) == len(set(ids))
    kinds = {x["题目"]["题型"] for x in items}
    assert kinds == {"单项选择题", "多项选择题"}, kinds

    # 掌握度：拿马原第一道单选做一对一错
    item = next(x for x in items
                if zz.part_of(x["题目"]["题号"], x["题目"]["题型"])[0] == "MY"
                and x["题目"]["题型"] == "单项选择题")
    qid = item["题目"]["id"]
    a = {qid: {"is_correct": True, "source": "diagnostic", "chosen": "A"}}
    row = [r for r in zz.part_mastery(a) if r["部分"] == "MY"][0]
    assert row["作答"] == 1 and row["答对"] == 1
    a[qid] = {"is_correct": False, "source": "diagnostic", "chosen": "B"}
    row = [r for r in zz.part_mastery(a) if r["部分"] == "MY"][0]
    assert row["答对"] == 0 and row["正确率"] == 0.0


if __name__ == "__main__":
    check_english()
    check_zz()
    print("英语/政治诊断测试通过（题型/部分覆盖、id、掌握度）")
