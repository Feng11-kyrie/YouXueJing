#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
四个科目「免费评分」的冒烟测试 —— 不联网、不花钱、不需要 API Key。

为什么单独一份：
  免费评分分散在四个入口（408/政治走 score_generic|rubric|politics，
  英语走 score_translation|score_writing，数学走 score_math）。
  任何一处改动都可能让某一科静默变成"不可用"或"永远 0 分"。
  这里用一份正常作答 + 一份跑题作答，确保四科都能给出分数且能区分好坏。

用法：  .venv/bin/python tests/test_free_score.py
"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from yj import math_checker as mc                              # noqa: E402
from yj import rubric_checker as rc                            # noqa: E402

GOOD_408 = """（1）算法的基本思想：从数组末尾向前扫描，维护后缀最大值和后缀最小值。
（2）对 A[i]，若 A[i]≥0 则乘后缀最大值，若 A[i]<0 则乘后缀最小值，结果存入 res[i]。
（3）时间复杂度 O(n)，空间复杂度 O(1)。
"""
GOOD_ZZ = """（1）实践是认识的来源和检验真理的唯一标准，调查只提供感性材料，必须经过加工。
（2）感性认识有待于发展为理性认识，不能停留在现象罗列。
（3）坚持一切从实际出发、实事求是，把调查和科学理论结合起来。
"""
GOOD_MATH = ("由 ln(1+x)=x-x^2/2+x^3/3+o(x^3)，得 a=1, b=-1/6。"
             "求导得 f'(x)=1+a/(1+x)+b(sin x+x cos x)，所以 a=1，b=-1/6。")


def check_408():
    r = rc.score_generic(GOOD_408, "设计算法求后缀最大乘积", "", 13, 120)
    assert 0 < r["分数"] <= 13, r
    bad = rc.score_generic("不会", "设计算法", "", 13, 120)
    assert bad["分数"] == 0


def check_zz():
    ref = ("（1）实践是认识的来源和检验真理的唯一标准，调查只提供感性材料。\n"
           "（2）感性认识有待于发展为理性认识，不能停留于现象罗列。\n"
           "（3）坚持一切从实际出发、实事求是。")
    r = rc.score_politics(GOOD_ZZ, "如何理解调查并不自然产生科学结论", ref, 10, 150)
    assert 0 < r["分数"] <= 10, r
    assert any(i["项"] == "参考要点覆盖" for i in r["分项"])
    bad = rc.score_politics("不会", "如何理解调查", ref, 10, 150)
    assert bad["分数"] == 0


def check_en():
    r = rc.score_translation("研究人员确信，大象的嗅觉远比人们之前认为的灵敏。",
                             "研究人员确信，大象的嗅觉远比人们之前认为的灵敏。", 2)
    assert r["分数"] > 1.5, r
    w = rc.score_writing(
        "With the rapid development of technology, our life has changed a lot. "
        "Firstly, communication becomes much easier. Secondly, we can learn "
        "anything online. In conclusion, we should make good use of it.", 100, 10)
    assert 0 < w["分数"] <= 10, w


def check_math():
    ref = (r"由 $\ln(1+x)=x-\frac{x^2}{2}+o(x^2)$ 得 $a=1,b=-\frac{1}{6}$。"
           r"求导得 $f'(x)=1+\frac{a}{1+x}+b(\sin x+x\cos x)$，"
           r"所以 $a=1,b=-\frac{1}{6}$。")
    r = mc.score_math(GOOD_MATH, ref, "求 a,b", 10)
    assert 0 < r["分数"] <= 10, r
    bad = mc.score_math("不会", ref, "求 a,b", 10)
    assert bad["分数"] == 0


if __name__ == "__main__":
    check_408()
    check_zz()
    check_en()
    check_math()
    print("四科免费评分冒烟测试通过（408 / 政治 / 英语 / 数学）")
