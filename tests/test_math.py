#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数学真题（数一/二/三）的回归测试 —— 不联网、不花钱、不需要 API Key。

钉住四件事：
  1. 三个卷种 2010–2025 每年都在，题量/题型符合当年大纲；
  2. 选择题有答案，选项要么四个、要么有原题图兜底；
  3. LaTeX → MathML 渲染不把 HTML 一起转义掉、也不执行标签；
  4. 解答题的免费评分与填空比对不会因为改动而失真。

用法：  .venv/bin/python tests/test_math.py
"""
import os
import sys
from collections import Counter

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from yj import math as m                                        # noqa: E402
from yj import math_checker as mc                               # noqa: E402
from yj import mathrender as mr                                 # noqa: E402
from proto.cards_math import _same_answer, norm_answer          # noqa: E402


def check_data():
    for tier in ("一", "二", "三"):
        ys = set(m.years(tier))
        missing = [str(y) for y in range(2010, 2026) if str(y) not in ys]
        assert not missing, f"数学{tier} 缺年份：{missing}"
        for y in sorted(ys):
            if int(y) < 2010:
                continue
            qs = m.questions(tier, y)
            c = Counter(q["题型"] for q in qs)
            want = (10, 6, 6) if int(y) >= 2021 else (8, 6, 9)
            got = (c["单项选择题"], c["填空题"], c["解答题"])
            assert got == want, f"数学{tier} {y} 题量 {got} != {want}"
            for q in qs:
                assert (q.get("题干") or "").strip() or q.get("图片"), \
                    f"数学{tier} {y} 第{q['题号']}题没题干也没图"
                if q["题型"] == "单项选择题":
                    assert q.get("答案") in list("ABCD"), \
                        f"数学{tier} {y} 第{q['题号']}题答案异常：{q.get('答案')}"
                    assert len(q.get("选项") or {}) == 4 or q.get("图片"), \
                        f"数学{tier} {y} 第{q['题号']}题选项不全"
                else:
                    assert q.get("解析") or q.get("图片"), \
                        f"数学{tier} {y} 第{q['题号']}题没有解析"


def check_render():
    html = mr.to_html(r"设 $x^2+\frac{1}{2}$，则（ ）")
    assert "<math" in html and "<mfrac>" in html and "x" in html
    # 公式之外的 HTML 必须转义，不能被执行
    evil = mr.to_html("<script>alert(1)</script> $x$")
    assert "<script>" not in evil and "&lt;script&gt;" in evil
    # latex2mathml 不认的宏要降级成文本，而不是让整题渲染失败
    weird = mr.to_html(r"$\textcircled{1} x$")
    assert "①" in weird


def check_answer_norm():
    assert _same_answer("2", r"$f(1)=\frac{\varphi'(1)-\varphi(1)}{2}=2.$")
    assert _same_answer("-1/2", r"$-\frac{1}{2}$")
    assert _same_answer("sqrt(2)", r"$\sqrt{2}$")
    assert not _same_answer("3", r"$-\frac{1}{2}$")
    assert norm_answer("（1）") == "(1)"


def check_free_score():
    ref = (r"由 $\ln(1+x)=x-\frac{x^2}{2}+o(x^2)$ 得 $a=1,b=-\frac{1}{6}$。"
           r"求导得 $f'(x)=1+\frac{a}{1+x}+b(\sin x+x\cos x)$，"
           r"所以 $a=1,b=-\frac{1}{6}$。")
    good = r"由 ln(1+x) 展开得 a=1，b=-1/6。求导 f'(x)=1+a/(1+x)+b(sin x+x cos x)，所以 a=1，b=-1/6。"
    r1 = mc.score_math(good, ref, "求 a,b", 10)
    assert 5 <= r1["分数"] <= 10, r1
    r2 = mc.score_math("不会", ref, "求 a,b", 10)
    assert r2["分数"] == 0
    assert r1["满分"] == 10


if __name__ == "__main__":
    check_data()
    check_render()
    check_answer_norm()
    check_free_score()
    print("数学真题测试全部通过：数据覆盖 / MathML 渲染 / 填空比对 / 免费评分")
