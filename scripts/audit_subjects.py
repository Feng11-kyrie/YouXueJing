#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
四科内容体检：题目 / 答案 / 解析 / 免费评分入口。

输出一张表，回答"每个科目到底缺什么"：
  题数 · 客观答案 · 解析 · 主观参考 · 免费评分入口

只读本地数据，不联网。用法：
    .venv/bin/python scripts/audit_subjects.py
    .venv/bin/python scripts/audit_subjects.py --write   # 写 docs/audit_content.md
"""
import argparse
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from yj import data as d408                                    # noqa: E402
from yj import english as en                                   # noqa: E402
from yj import math as mm                                      # noqa: E402
from yj import zhengzhi as zz                                  # noqa: E402


def audit_408():
    total = obj = obj_ans = obj_expl = subj = subj_sol = 0
    for y in d408.years():
        for q in d408.paper(y)["题目"]:
            total += 1
            s = d408.solution(y, q["题号"])
            if q["题型"] == "单项选择题":
                obj += 1
                obj_ans += bool(q.get("答案"))
                obj_expl += bool(s)
            else:
                subj += 1
                subj_sol += bool(s)
    return {
        "科目": "408", "题数": total,
        "客观答案": f"{obj_ans}/{obj}",
        "解析": f"{obj_expl + subj_sol}/{total}",
        "主观参考": f"{subj_sol}/{subj}",
        "免费评分": "客观自动判分；综合题 免费评分（评分标准/结构体检）+ BYOK AI",
    }


def audit_zz():
    total = obj = obj_ans = obj_expl = ana = ana_ref = 0
    for y in zz.years():
        for q in zz.paper(y)["题目"]:
            total += 1
            e = zz.explanation(y, q["题号"])
            if "选择" in q["题型"]:
                obj += 1
                obj_ans += bool((q.get("答案") or "").strip())
                obj_expl += bool(e)
            elif "分析题" in q["题型"]:
                ana += 1
                ana_ref += bool((e or {}).get("文本"))
    return {
        "科目": "政治", "题数": total,
        "客观答案": f"{obj_ans}/{obj}",
        "解析": f"{obj_expl + ana_ref}/{total}",
        "主观参考": f"{ana_ref}/{ana}",
        "免费评分": "客观自动判分；分析题 结构体检+参考要点覆盖 + BYOK AI",
    }


def audit_en():
    total = obj = obj_ans = obj_expl = subj = subj_ref = 0
    for tier in ("EN1", "EN2"):
        for y in en.years(tier):
            rec = en.paper(tier, y)
            for ps in rec.get("篇目", []):
                for q in ps.get("小题", []):
                    total += 1
                    e = en.explanation(tier, y, q["题号"]) or {}
                    if q.get("主观"):
                        subj += 1
                        # 写作的参考范文存在 `参考范文` 键，翻译存在 `_参考译文`
                        subj_ref += bool(e.get("_参考译文") or e.get("参考范文")
                                         or e.get("文本"))
                    else:
                        obj += 1
                        obj_ans += bool((e.get("答案") or "").strip())
                        obj_expl += bool(e.get("解析") or e.get("答案"))
    return {
        "科目": "英语", "题数": total,
        "客观答案": f"{obj_ans}/{obj}",
        "解析": f"{obj_expl + subj_ref}/{total}",
        "主观参考": f"{subj_ref}/{subj}",
        "免费评分": "客观自动判分；翻译/写作 免费评分 + BYOK AI",
    }


def audit_math():
    total = obj = obj_ans = expl = subj = 0
    for t in ("一", "二", "三"):
        for y in mm.years(t):
            for q in mm.questions(t, y):
                total += 1
                if q["题型"] == "单项选择题":
                    obj += 1
                    obj_ans += bool(q.get("答案"))
                if q["题型"] == "解答题":
                    subj += 1
                expl += bool((q.get("解析") or "").strip())
    return {
        "科目": "数学", "题数": total,
        "客观答案": f"{obj_ans}/{obj}",
        "解析": f"{expl}/{total}",
        "主观参考": f"{subj}/{subj}",
        "免费评分": "选择自动判分；填空 归一化比对+手判；解答 结构体检 + BYOK AI",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    rows = [audit_en(), audit_math(), audit_zz(), audit_408()]
    lines = ["# 四科内容体检", "",
             "| 科目 | 题数 | 客观答案 | 解析 | 主观参考 | 免费评分 |",
             "|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f'| {r["科目"]} | {r["题数"]} | {r["客观答案"]} | '
                     f'{r["解析"]} | {r["主观参考"]} | {r["免费评分"]} |')
    text = "\n".join(lines) + "\n"
    print(text)
    if a.write:
        os.makedirs(os.path.join(BASE, "docs"), exist_ok=True)
        open(os.path.join(BASE, "docs", "audit_content.md"), "w",
             encoding="utf-8").write(text)
        print("已写 docs/audit_content.md")


if __name__ == "__main__":
    main()
