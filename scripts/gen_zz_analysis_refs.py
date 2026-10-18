#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
给政治**材料分析题（34–38）**补「参考要点」。

为什么需要
----------
政治分析题在公开资料里没有"标准答案"（官方只给评分要点），我们原来 34–38
只有题干和材料，没有可对照的解析，免费评分也只能做结构体检。
这份脚本用服务端 LLM 写一份**参考要点**，存进 <年>-解析.json，
并在界面明确标注「AI 参考要点（非官方）」—— 它是自评的参照，不是阅卷答案。

原则
----
· 只写**题干/材料里能支撑的考点**，明确要求不编造具体数字、文件名；
· 已有解析（人工或题源）的题**不覆盖**；--force 才重写；
· 输出必须是分条要点（（1）（2）…），否则视为失败、重试；
· 结果进 llm 缓存，重复跑不重复花钱。

用法：
    .venv/bin/python scripts/gen_zz_analysis_refs.py --all
    .venv/bin/python scripts/gen_zz_analysis_refs.py --year 2024
"""
import argparse
import json
import os
import re
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from yj import llm                                            # noqa: E402
from yj import zhengzhi as zz                                 # noqa: E402

SRC = "AI 参考要点（非官方）"

PROMPT = """你是考研政治阅卷老师。请为下面这道材料分析题写「参考答案要点」，供学生自评使用。

要求：
1. 按官方评分习惯分条（用（1）（2）…），每条先点出原理/观点，再结合材料一句话；
2. 覆盖该题涉及的马原/毛中特/史纲/思修/时政考点，点到为止，不堆砌；
3. 不要编造材料中没有的具体数字、文件名、会议届次；不确定的表述用概括性语言；
4. 总字数 200–400 字；不要写“参考答案”“答案要点”这类标题，直接给要点。

【题目】
{stem}

【分值】{score} 分
"""


def _ok(text):
    if not text or len(text) < 100:
        return False
    return bool(re.search(r"[（(]\s*1\s*[)）]|^1[.、]", text.strip()))


def gen_one(year, q):
    n = str(q["题号"])
    prompt = PROMPT.format(stem=(q.get("题干") or "")[:3000],
                           score=q.get("分值") or 10)
    for attempt in range(2):
        r = llm.complete("zz_analysis_ref", prompt, use_cache=True)
        text = (r.get("text") or "").strip()
        if _ok(text):
            return text, r.get("source")
        time.sleep(1.5 * (attempt + 1))
    return None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", action="append")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--force", action="store_true", help="已有文本也重写")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    years = zz.years() if a.all else (a.year or [])
    if not years:
        print("用 --all 或 --year 指定年份")
        return 1

    done = skipped = failed = 0
    for y in years:
        path = os.path.join(BASE, "data", "zhengzhi", f"{y}-解析.json")
        rec = json.load(open(path, encoding="utf-8"))
        ans = rec.setdefault("解答", {})
        paper = zz.paper(y)
        for q in paper["题目"]:
            # 不同年份的题型标签不统一：有的写「分析题」、有的写「材料分析题」
            if "分析题" not in str(q.get("题型")):
                continue
            n = str(q["题号"])
            cur = ans.get(n) or {}
            if (cur.get("文本") or "").strip() and not a.force:
                skipped += 1
                continue
            if a.dry_run:
                print(f"[dry] {y}-{n}  {(q.get('题干') or '')[:40]}")
                continue
            text, source = gen_one(y, q)
            if not text:
                failed += 1
                print(f"{y}-{n} 失败（模型没有给出合格的分条要点）")
                continue
            ans[n] = {"文本": text, "来源": SRC}
            done += 1
            print(f"{y}-{n} ok · {len(text)} 字 · {source}")
            # 每写一题就落盘，中断不至于全丢
            json.dump(rec, open(path, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=1)
            time.sleep(0.8)

    print(f"\n完成 {done} · 跳过 {skipped} · 失败 {failed}")


if __name__ == "__main__":
    sys.exit(main())
