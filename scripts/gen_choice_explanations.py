#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
给**单项选择题（1–40）**批量生成解析。

为什么需要
----------
答案册的解析只覆盖综合题（41–47，已抽出 126 道）。
单选 **720 道一直没有任何解析** —— 讲义页的配套真题因此只能显示
"这道题暂无解析"。而单选题有**标准答案**（720/720 全有）和**考点标签**，
足够让 AI 写出可靠解析（答案已知，AI 只需解释"为什么"）。

存储
----
    data/solutions/<年份>-choice.json
        {"年份": "2023", "来源": "AI 生成", "解答": {"24": "...", ...}}
    单独放一个文件，**不混进 <年份>.json**（那个存的是综合题解析，
    格式与来源都不同，混在一起以后无法分辨哪条来自答案册、哪条是 AI 写的）。

工程要求（都是踩过坑之后加的）
-------------------------------
  · **按年份增量写盘**：720 道要跑 40–60 分钟，中途失败不能从零重来。
    每完成一道就检查是否需要落盘（按年份攒够若干条或该年跑完时写一次）。
  · **可断点续跑**：启动时先读已有文件，已生成的跳过。
  · 走 llm.complete() 的缓存 —— 重复运行时已生成的题目不会重复花额度。
  · 失败不中断整体：记录失败题号，最后汇总。

用法：
    .venv/bin/python scripts/gen_choice_explanations.py --dry-run
    .venv/bin/python scripts/gen_choice_explanations.py --limit 20      # 先小批
    .venv/bin/python scripts/gen_choice_explanations.py --write         # 全部
"""
import argparse
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from yj import data, llm                              # noqa: E402

OUT = os.path.join(BASE, "data", "solutions")


def path_of(year):
    return os.path.join(OUT, f"{year}-choice.json")


def load(year):
    p = path_of(year)
    if os.path.exists(p):
        try:
            return json.load(open(p, encoding="utf-8"))
        except Exception:                            # noqa: BLE001
            pass
    return {"年份": year, "来源": "AI 生成（未经官方核验）", "解答": {}}


def save(year, rec):
    rec["题数"] = len(rec["解答"])
    tmp = path_of(year) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path_of(year))                   # 原子写，避免中断留半个文件


def prompt_for(q, year):
    opts = q.get("选项") or {}
    opts_txt = "\n".join(f'{k}. {v}' for k, v in sorted(opts.items()))
    return f"""你是 408 考研（计算机学科专业基础综合）的辅导老师。
下面是一道**单项选择题**，正确答案已给出。请写一段解析。

要求：
1. **先说为什么正确答案对** —— 讲清关键原理，不要只说"选 A 因为 A 对"。
2. **再指出主要干扰项错在哪** —— 哪几个选项最容易误选、为什么错。
3. **1–3 句话，不超过 120 字**。学生要的是快速看懂，不要长篇大论。
4. 只讲本题考点，不要扩展到考纲外。
5. 直接给解析正文，不要加"解析："前缀，不要重复题干和选项。

【题目】
{year} 年 第 {q['题号']} 题　考点：{q.get('主考点名', '未知')}　难度：{q.get('难度')}
题干：{q['题干']}
{opts_txt}
正确答案：{q['答案']}
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 道（试质量用）")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    ok, msg = llm.status()
    print(f"LLM: {msg}")
    if not ok:
        print("未配置 key，无法生成", file=sys.stderr)
        sys.exit(1)

    qs = data.questions()
    targets = [q for q in qs.values() if q.get("题型") == "单项选择题"]
    targets.sort(key=lambda x: (str(x["year"]), int(x["题号"])))

    todo = []
    for q in targets:
        year = str(q["year"])
        rec = load(year)
        if str(q["题号"]) not in rec["解答"]:
            todo.append(q)
    print(f"单选题共 {len(targets)} 道，已有解析 {len(targets)-len(todo)} 道，"
          f"待生成 {len(todo)} 道")
    if args.limit:
        todo = todo[:args.limit]
        print(f"（--limit {args.limit}，本次只跑 {len(todo)} 道）")
    if args.dry_run or not todo:
        return

    done = fail = 0
    fails = []
    pending = {}                      # year -> rec（攒着，按年份落盘）
    for i, q in enumerate(todo, 1):
        year = str(q["year"])
        rec = pending.get(year) or load(year)
        r = llm.complete("choice", prompt_for(q, year),
                         payload={"y": year, "n": q["题号"], "v": 1})
        if not r.get("text"):
            fail += 1
            fails.append(f"{year}-{q['题号']}")
            print(f"  [{i}/{len(todo)}] {year}-{q['题号']} 失败")
            continue
        rec["解答"][str(q["题号"])] = r["text"].strip()
        pending[year] = rec
        done += 1
        if done % 20 == 0 or i == len(todo):
            for y, rc in pending.items():
                if args.write:
                    save(y, rc)
            print(f"  [{i}/{len(todo)}] 已完成 {done} 道（已落盘 {len(pending)} 个年份）")
    # 收尾落盘
    if args.write:
        for y, rc in pending.items():
            save(y, rc)
    print(f"\n完成 {done} 道，失败 {fail} 道")
    if fails:
        print("失败题号:", fails[:20])
    if not args.write:
        print("（未写入，加 --write 才落盘）")


if __name__ == "__main__":
    main()
