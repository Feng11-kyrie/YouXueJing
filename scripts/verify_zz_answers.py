#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
政治真题答案的**独立交叉验证**。

为什么必须有这一步
------------------
2026-10-14 实测踩到：`.cache/zhengzhi/2015.pdf`（某高校官网放的"真题及答案"）
里**至少有一道题答案是错的**：

    第 16 题 PDF 标注（答案：A），但正确答案是 D
    （ISIS 崛起牵制了美国"重返亚太"战略 —— 该题原文还把"受到"打成"收到"）

**我的解析是忠实的**（确实提取了 A），错的是题源本身。
所以"能解析出题目"不等于"答案可信" —— 政治没有像 408 那样经过人工校对的
答案册，网上流传的版本有抄错、漏改。必须独立验证。

验证方法
--------
让 LLM **只看题干和选项自己解**（不给它 PDF 里的答案，避免它偷懒附和），
再与抽出的答案比对。不一致的题不能直接入库 —— 要么人工裁决、要么换题源。

注意：LLM 自己也会错（实测第 16 题它答对、第 20 题可能是它错），
所以**不一致只是"需要人工看一眼"的信号，不是"题源错了"的结论**。

用法：
    .venv/bin/python scripts/verify_zz_answers.py --year 2015 --sample 12
    .venv/bin/python scripts/verify_zz_answers.py --year 2015 --all
"""
import argparse
import json
import os
import random
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from yj import llm                                   # noqa: E402

ZZ_DIR = os.path.join(BASE, "data", "zhengzhi")


def solve(it, year):
    opts = "\n".join(f'{k}. {v}' for k, v in sorted(it["选项"].items()))
    kind = ("单选（只有一个正确）" if it["题型"] == "单项选择题"
            else "多选（有 2-4 个正确）")
    p = f"""你是考研政治阅卷老师。下面是{kind}题，请**只根据题干和选项独立作答**。
不要考虑"某份资料上写的是什么"，就按你的判断。

【题干】{it['题干']}
【选项】
{opts}

要求：先写 1-2 句判断依据，最后一行单独输出「我的答案：X」（多选如「我的答案：ABD」）。"""
    # payload 必须带上年份 —— 写死会导致换年份时命中错误缓存（自己踩过）
    r = llm.complete("zz_verify", p, payload={"y": str(year), "n": it["题号"], "v": 2})
    txt = r.get("text") or ""
    m = re.search(r'我的答案[:：]\s*([A-D]{1,4})', txt)
    return (m.group(1) if m else None), txt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", required=True)
    ap.add_argument("--sample", type=int, default=12)
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()

    rec = json.load(open(os.path.join(ZZ_DIR, f"{args.year}.json"), encoding="utf-8"))
    choice = [i for i in rec["题目"] if i["题型"] in ("单项选择题", "多项选择题")]
    todo = choice if args.all else random.Random(3).sample(
        choice, min(args.sample, len(choice)))

    ok = diff = none = 0
    mismatches = []
    for it in todo:
        got, _raw = solve(it, args.year)
        if not got:
            none += 1
            continue
        if got == it["答案"]:
            ok += 1
        else:
            diff += 1
            mismatches.append({"题号": it["题号"], "题型": it["题型"],
                               "抽出": it["答案"], "LLM": got,
                               "题干": it["题干"][:80]})
        print(f"  第 {it['题号']:>2} 题 [{it['题型'][:2]}] "
              f"抽出={it['答案']:<4} LLM={got:<4} "
              f"{'✓' if got == it['答案'] else '✗ 待人工确认'}")

    print(f"\n一致 {ok}｜不一致 {diff}｜未解析出 {none}（共 {len(todo)} 道）")
    if mismatches:
        dst = os.path.join(ZZ_DIR, f"{args.year}-待确认.json")
        json.dump(mismatches, open(dst, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print(f"不一致清单已写入 {dst} —— 这些题**不要直接入库**")


if __name__ == "__main__":
    main()
