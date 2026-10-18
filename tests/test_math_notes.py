#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数学考点速记的回归测试：配套真题选题、缓存读写、Markdown/公式渲染。

不联网：LLM 调用用 monkeypatch 替换；测试结束恢复原缓存文件。

用法：  .venv/bin/python tests/test_math_notes.py
"""
import json
import os
import shutil
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from yj import math_notes as mn                                 # noqa: E402
from yj import mathrender as mr                                 # noqa: E402

TIER, POINT = "一", "二次型"


def check_related():
    qs = mn.related(TIER, POINT, 4)
    assert 1 <= len(qs) <= 4
    for q in qs:
        assert (q.get("考点") or "") == POINT
        assert q.get("_year")


def check_render():
    h = mr.note_html("## 核心公式\n- 二次型 $x^TAx$\n正文 $\\frac{1}{2}$")
    assert "<h4" in h and "核心公式" in h and "$x^TAx$" in h and "•" in h


def check_generate_and_cache():
    path = mn._path(TIER, POINT)
    backup = path + ".bak"
    if os.path.exists(path):
        shutil.copy(path, backup)
    try:
        if os.path.exists(path):
            os.remove(path)
        assert mn.cached(TIER, POINT) is None
        old = mn.llm.complete
        mn.llm.complete = lambda *a, **k: {"text": "## 核心\n- 测试要点 $a^2$",
                                           "source": "llm"}
        try:
            rec = mn.generate(TIER, POINT)
            assert rec.get("文本") and rec.get("题目")
            assert mn.cached(TIER, POINT) is not None
        finally:
            mn.llm.complete = old
    finally:
        if os.path.exists(backup):
            shutil.move(backup, path)
        elif os.path.exists(path):
            os.remove(path)          # 测试生成的假速记不要留在缓存里


if __name__ == "__main__":
    check_related()
    check_render()
    check_generate_and_cache()
    print("数学考点速记测试通过（选题 / 渲染 / 生成与缓存）")
