#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数学题库的**渲染体检**：任何题干/解析都不能退化成原始 LaTeX。

背景：latexml 渲染失败时 yj/mathrender 会退回 <code>$...$</code>，
用户在页面上看到的就是一坨 \\begin{array}...（2025 数一第 5 题实测）。
这个测试把 1112 道题全部过一遍，防止后续导入把坏 LaTeX 又带进来。

用法：  .venv/bin/python tests/test_math_render.py
"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from yj import math as m                                       # noqa: E402
from yj import mathrender as mr                                # noqa: E402


def check_all():
    bad = []
    for t in ("一", "二", "三"):
        for y in m.years(t):
            for q in m.questions(t, y):
                for field in ("题干", "解析"):
                    s = q.get(field) or ""
                    if s and "<code>" in mr.to_html(s):
                        bad.append(f"{t}-{y}-{q['题号']}-{field}")
    assert not bad, f"渲染回退为原始 LaTeX：{bad[:10]}"


def check_2025_q5():
    q = m.question("一", 2025, 5)
    h = mr.to_html(q["解析"])
    assert "<code>" not in h
    assert "aligned" not in h
    assert "<mi>&</mi>" not in h


def check_images():
    """配图只给"确实引用图形"的题；别把「几何图形」这类说法误判成图题。"""
    import re
    hint = re.compile(r"如图|图所示|图中|右图|下图|曲线如图|见图|图示|图形如图")
    bad = []
    for t in ("一", "二", "三"):
        for y in m.years(t):
            for q in m.questions(t, y):
                if not q.get("图片"):
                    continue
                stem = q.get("题干") or ""
                if "题干见下方原题图" in stem or not stem.strip():
                    continue
                if not hint.search(stem):
                    bad.append(f"{t}-{y}-{q['题号']}")
    assert not bad, f"没有引用图形却配了图：{bad}"


if __name__ == "__main__":
    check_all()
    check_2025_q5()
    check_images()
    print("数学渲染体检通过（1112 题无原始 LaTeX 回退 / 配图无误判）")
