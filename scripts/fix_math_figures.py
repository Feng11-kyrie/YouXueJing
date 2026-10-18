#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
补数学题的**原题图**：题干提到「如图 / 图形 / 右图」但 JSON 里没有图的，
按真题墙的题目图片补上（并保留 `含图` 标记的题）。

为什么需要
----------
部分题目的图在文字源里丢了（"其图形如右图所示"），没有图学生无法作答。
真题墙的 `kaoyan_math_images/数学X/<年>/Qnn_id*.png` 是整道题的原图，
补上最稳（会比文字多一张图，但保证信息完整）。

用法：
    .venv/bin/python scripts/fix_math_figures.py --all
    .venv/bin/python scripts/fix_math_figures.py --tier 二
"""
import argparse
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "scripts"))

import import_math_lx as lx                                    # noqa: E402
from yj import math as m                                       # noqa: E402

FIG_HINT = re.compile(r"如图|图形|图所示|图中|右图|下图|曲线如图")


def fix(tier):
    n_done = 0
    for y in m.years(tier):
        p = os.path.join(BASE, "data", "math", tier, f"{y}.json")
        d = json.load(open(p, encoding="utf-8"))
        changed = False
        for q in d["题目"]:
            if q.get("图片"):
                continue
            if q.get("含图") or FIG_HINT.search(q.get("题干") or ""):
                rel = lx.fetch_question_image(tier, y, q["题号"])
                if rel:
                    q["图片"] = rel
                    changed = True
                    n_done += 1
        if changed:
            json.dump(d, open(p, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=1)
    print(f"数学{tier}: 补图 {n_done} 道")
    return n_done


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", action="append", choices=["一", "二", "三"])
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()
    for t in (["一", "二", "三"] if a.all else (a.tier or ["一"])):
        fix(t)
