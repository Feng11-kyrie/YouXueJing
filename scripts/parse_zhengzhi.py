#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把考研政治真题 PDF 解析成结构化题库（客观题 + 分析题）。

为什么单独写一个解析器
----------------------
政治的排版与 408 不同，实测（2015 年那份 PDF）踩到四个坑：
  ① **答案在题干末尾的括号里**："…这表明（答案：B）" —— 408 的答案在单独的文件里
  ② **答案标记可能跨行断开**："…（答\\n案：D）" —— 直接按行处理会漏
  ③ **选项符号全角半角混用**：多数是 "A．"，但实测有 "D." —— 只匹配一个会漏选项
  ④ **题干有多余换行**："书本知\\n识非常重要" —— 必须把换行合并，否则题干读起来是断的

题型分值（2010 年改革后固定，16 年一致）：
    一、单项选择题 1～16    每题 1 分，共 16 分
    二、多项选择题 17～33   每题 2 分，共 34 分
    三、材料分析题 34～38   每题 10 分，共 50 分
**只有前两类可机判（50 分）**；分析题是主观题，界面走"参考答案 + 自评给分"。

用法：
    .venv/bin/python scripts/parse_zhengzhi.py --pdf .cache/zhengzhi/2015.pdf --year 2015
    .venv/bin/python scripts/parse_zhengzhi.py --pdf ... --year 2015 --write
"""
import argparse
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

OUT_DIR = os.path.join(BASE, "data", "zhengzhi")

# 三个大题的标题（允许"一、"与"单项选择题"之间有空格）
SEC = re.compile(r'[一二三]\s*[、,.]\s*(单项选择题|多项选择题|材料分析题|分析题)')
# 题号：行首的 "12." 或 "12．"
QNUM = re.compile(r'(?m)^\s*(\d{1,2})\s*[.．、]\s*')
# 答案标记：允许括号内换行、冒号全半角、可无括号
# 冒号后**允许换行** —— 实测第 27 题是 "（答案：\nBCD）"，原来的正则漏掉了它，
# 表现为"33 道题只解析出 32 道"。
ANS = re.compile(r'[（(]\s*答\s*案\s*[:：]\s*([A-D]{1,4})\s*[)）]', re.S)
# 选项：允许全角/半角点号
OPT = re.compile(r'(?m)^\s*([A-D])\s*[.．、]\s*(.+?)(?=\n\s*[A-D]\s*[.．、]|\Z)', re.S)


def clean(s: str) -> str:
    """合并题干里的多余换行与空格（PDF 抽出的中文常被硬换行切碎）"""
    s = re.sub(r'[ \t\u3000]+', ' ', s)
    s = re.sub(r'\s*\n\s*', '', s)       # 中文不需要空格补位
    return s.strip()


def parse(pdf_path, year):
    from pypdf import PdfReader
    raw = "\n".join((p.extract_text() or "") for p in PdfReader(pdf_path).pages)
    # 先把"跨行断开的答案标记"接上，否则会漏题
    raw = re.sub(r'[（(]\s*答\s*\n\s*案', '（答案', raw)

    # 按三个大题切段
    secs = list(SEC.finditer(raw))
    if not secs:
        raise SystemExit("没找到题型标题 —— PDF 可能不是真题排版")
    spans = []
    for i, m in enumerate(secs):
        end = secs[i + 1].start() if i + 1 < len(secs) else len(raw)
        spans.append((m.group(1), raw[m.end():end]))

    items = []
    for name, body in spans:
        is_choice = name in ("单项选择题", "多项选择题")
        n = {"单项选择题": 1, "多项选择题": 2, "材料分析题": 10,
             "分析题": 10}[name]
        nums = list(QNUM.finditer(body))
        for i, m in enumerate(nums):
            end = nums[i + 1].start() if i + 1 < len(nums) else len(body)
            chunk = body[m.end():end]
            num = int(m.group(1))

            if not is_choice:
                # 分析题：整块当题干（含材料），没有选项与答案
                stem = clean(chunk)
                if len(stem) > 20:
                    items.append({"题号": str(num), "题型": name, "分值": n,
                                  "题干": stem, "选项": {}, "答案": None})
                continue

            am = ANS.search(chunk)
            if not am:
                # 【不丢题】原来这里直接 continue，会丢掉"答案标记格式异常"的题。
                # 现在改成：整块当题干、答案留空，交给 vote_zz_answers.py 投票定答案。
                # 理由：政治题源本身错漏不少（实测多选约 30% 答案有误），
                # 答案本来就不可信，不值得为它丢掉一道题。
                stem_only = clean(chunk)
                om2 = OPT.search(stem_only)
                if om2:
                    stem_only = clean(stem_only[:om2.start()])
                if len(stem_only) > 15:
                    items.append({"题号": str(num), "题型": name, "分值": n,
                                  "题干": stem_only, "选项": {}, "答案": None,
                                  "待投票": True})
                continue
            stem = clean(chunk[:am.start()])
            opts = {}
            for om in OPT.finditer(chunk[am.end():]):
                opts[om.group(1)] = clean(om.group(2))
            if len(opts) < 4:
                continue                     # 选项不全的丢弃，避免入库后判分出错
            items.append({"题号": str(num), "题型": name, "分值": n,
                          "题干": stem, "选项": opts,
                          "答案": am.group(1)})
    return items


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--year", required=True)
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    items = parse(args.pdf, args.year)
    by_type = {}
    for it in items:
        by_type.setdefault(it["题型"], []).append(it)
    print(f"{args.year} 年解析结果：共 {len(items)} 道")
    for k, v in by_type.items():
        have_ans = sum(1 for x in v if x.get("答案"))
        print(f"  {k}: {len(v)} 道" + (f"（{have_ans} 道有答案）"
                                       if k != "材料分析题" else "（主观题）"))

    pending = [x for x in items if x.get("待投票")]
    if pending:
        print(f"  ⚠️ {len(pending)} 道因答案标记异常需投票定答案："
              f"{[x['题号'] for x in pending]}")
    if by_type.get("单项选择题"):
        s = by_type["单项选择题"][0]
        print(f"\n抽查单选第 {s['题号']} 题：")
        print("  题干:", s["题干"][:70])
        for k in sorted(s["选项"]):
            print(f"    {k}. {s['选项'][k][:50]}")
        print("  答案:", s["答案"])

    if args.write:
        os.makedirs(OUT_DIR, exist_ok=True)
        dst = os.path.join(OUT_DIR, f"{args.year}.json")
        json.dump({"年份": args.year, "题数": len(items), "题目": items},
                  open(dst, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"\n已写入 {dst}")


if __name__ == "__main__":
    main()
