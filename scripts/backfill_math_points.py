#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
给数学题回填**考点**标签（来自真题墙 answers.json 的 knowledge_point）。

背景：数一 2010–2020 的题面来自 TsekaLuk，没有考点字段；数三有 5 道
图片转录题也不在答案库里。没有考点就没法做"按考点诊断/筛题"。
这个脚本按 `数学<卷种>_<年>_Q<题号>` 从答案库补，已有的不覆盖。

用法：
    .venv/bin/python scripts/backfill_math_points.py --all
    .venv/bin/python scripts/backfill_math_points.py --tier 一
"""
import argparse
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "scripts"))

import import_math_lx as lx                                    # noqa: E402

TIERS = ("一", "二", "三")


def fill(tier):
    meta = lx.answer_meta(tier)
    filled = total = 0
    for f in sorted(os.listdir(os.path.join(BASE, "data", "math", tier))):
        if not f.endswith(".json"):
            continue
        y = f[:4]
        p = os.path.join(BASE, "data", "math", tier, f)
        d = json.load(open(p, encoding="utf-8"))
        changed = False
        for q in d["题目"]:
            total += 1
            if (q.get("考点") or "").strip():
                continue
            m = meta.get(f"数学{tier}_{y}_Q{q['题号']:02d}") or {}
            kp = (m.get("knowledge_point") or "").strip()
            if kp:
                q["考点"] = kp
                filled += 1
                changed = True
        if changed:
            json.dump(d, open(p, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=1)
    print(f"数学{tier}: 补 {filled} 题（共 {total} 题）")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", action="append", choices=TIERS)
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()
    for t in (TIERS if a.all else (a.tier or TIERS)):
        fill(t)
