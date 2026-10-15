#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
解析考研英语真题 PDF → `data/english/<tier>-<年>.json`（**只含试题**）。

题源与依据
----------
    英语一：1998–2026 ／ 英语二：2010–2026
    来源：GitHub `Fantasia1999/kaoyanzhenti`（文字层干净，**不需要 OCR**）

**结构靠 PDF 书签，而不是靠内容猜**
-----------------------------------
仓库里的合订本 `10-22英语一真题带书签.pdf` 有完整书签：

    2011年考研英语一真题        p15
      完型 / Text1 / Text2 / Text3 / Text4 / 新题型 / 翻译 / 作文

这给出了**精确的页码边界**，比用正则去正文里猜"哪里是 Text 2"可靠得多
（英语正文是散文，题号和数字在文章里大量出现，纯内容匹配容易切错）。

文字层的坑（都实测过，逐个处理）
--------------------------------
1. **英文单词间是双空格**（PDF 两端对齐）：`'Nearly  2,000  years'`
   → 必须把连续空白压成单空格
2. **页码单独成行**，且会被拼进正文（`'... to a  curious treasure'` 里的
   `a` 后其实跟着页码）→ 先剔除纯数字行
3. **跨页会丢词**：`'they '` 与 `'curious'` 之间原文是 `left behind a`，
   而它落在上一页末尾 → 这是**题源本身的缺陷**，无法在解析层修复，
   已在 docs/english_sources.md 记录；答题用的题干/选项不受影响

用法
----
    .venv/bin/python scripts/parse_english.py --tier EN1 --year 2024 \
        --pdf <试卷.pdf> [--write]
    .venv/bin/python scripts/parse_english.py --tier EN1 --bookmarks  # 看书签
"""
import argparse
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from yj import english as en                                # noqa: E402

QNUM_Q = re.compile(r'^(\d{1,2})\s*[.、]\s*(.*)$')          # 题干： 21. xxx
OPT_Q = re.compile(r'^([A-D])\s*[.、]\s*(.*)$')             # 选项： A. xxx
# 新题型用括号题号： (41) Hannah
QNUM_PAREN = re.compile(r'^\((\d{1,2})\)\s*(.*)$')


def norm_lines(pdf):
    """
    把 PDF 归一化成"干净的行列表"（见模块开头的三条坑）。
    """
    from pypdf import PdfReader
    out = []
    for pg in PdfReader(pdf).pages:
        for ln in (pg.extract_text() or "").split("\n"):
            s = re.sub(r'[ \t]{2,}', ' ', ln).strip()
            if not s:
                continue
            if re.fullmatch(r'\d{1,3}', s):     # 页码
                continue
            out.append(s)
    return out


def bookmarks(pdf):
    """
    取书签 → [(标题, 起始页), ...]（页号为 1 基）。

    书签是**跨年合订本**的，所以标题形如 "2011年考研英语一真题"、
    "完型" / "Text1" / ... / "作文"。
    """
    from pypdf import PdfReader
    r = PdfReader(pdf)

    def walk(items, out):
        for it in items:
            if isinstance(it, list):
                walk(it, out)
            else:
                try:
                    pg = r.get_destination_page_number(it) + 1
                except Exception:                           # noqa: BLE001
                    pg = None
                out.append((str(it.title).strip(), pg))
    out = []
    try:
        walk(r.outline, out)
    except Exception:                                       # noqa: BLE001
        pass
    return out, len(r.pages)


def split_parts_by_content(lines):
    """
    从**单年试卷**的行列表里切出各部分。

    单年 PDF（如 `2024年考研英语一真题.pdf`）没有书签，但它的分节标题
    很规整，实测可靠：
        Section I Use of English / Section II Reading Comprehension
        Part A / Part B / Part C / Section III Writing
        Text 1..4
    """
    marks = []
    for i, l in enumerate(lines):
        m = re.match(r'^Section\s*([IVX]+)\s*(.*)$', l)
        if m:
            marks.append((i, "SEC", f"Section {m.group(1)} {m.group(2)}".strip()))
            continue
        m = re.match(r'^Part\s*([ABC])\s*$', l)
        if m:
            marks.append((i, "PART", f"Part {m.group(1)}"))
            continue
        m = re.match(r'^Text\s*(\d)\s*$', l)
        if m:
            marks.append((i, "TEXT", f"Text {m.group(1)}"))
    return marks


def parse_cloze(lines, lo=1, hi=20):
    """
    完形填空（1–20）的解析 —— **它和阅读的排版完全不同**。

    实测排版是**两栏选项表**（不是"题干 + 四个选项连续"）：

        ... 文章正文（空处只标数字：`would be more 20`）...
        1. A. Through          ← 每行一个题的 A 选项
        2. A. revealing
        ...
        20. A. appropriate
        B. Despite             ← 接着是 B 列（同样 20 行，不带题号）
        B. demanding
        ...
        C. xxx / D. xxx

    所以按"题号行 → 后 3 行是 B/C/D"来配对，而不是靠四个选项连续出现。
    （我原来的 parse_choice_block 按阅读的排版写，结果把 A 选项当成了题干。）

    返回 (题目列表, 文章正文)。文章的"空"以数字标出（如 `more 20`），
    界面要能把空渲染成可选项 —— 但那是渲染层的事，这里原样保留。
    """
    # 定位 A 栏：行形如 "1. A. Through"
    a_rows = []
    for i, l in enumerate(lines):
        m = re.match(r'^(\d{1,2})\.\s+([A-D])\.\s*(.*)$', l)
        if m and lo <= int(m.group(1)) <= hi:
            a_rows.append((i, int(m.group(1)), m.group(3).strip()))
    if not a_rows:
        return [], "\n".join(lines)

    # 四个并列栏：某题的 B 选项在 `A栏起点 + 栏宽`，**不是紧跟其后** ——
    # 我第一版按"紧随其后 3 行"配对，结果把第 2/3/4 题的 A 选项
    # 当成了第 1 题的 B/C/D（题干也错成了 A 选项文本）。
    col = {"A": {n: t for _, n, t in a_rows}}
    width = len(a_rows)
    a0 = a_rows[0][0]
    nums = [n for _, n, _ in a_rows]
    for k, letter in enumerate("BCD"):
        base = a0 + width * (k + 1)
        for idx, n in enumerate(nums):
            j = base + idx
            if j >= len(lines):
                continue
            m = re.match(r'^([A-D])\.\s*(.*)$', lines[j])
            col.setdefault(letter, {})[n] = (m.group(2).strip()
                                             if m else lines[j].strip())

    qs = [{"题号": n, "题干": "",
           "选项": {L: col.get(L, {}).get(n, "") for L in "ABCD"}}
          for n in nums]

    # 文章正文 = 选项表开始之前的内容
    first = a0
    body = []
    for l in lines[:first]:
        # 跳过 Directions 段落（它不是文章）
        if re.match(r'^(Directions|Section)\b', l):
            continue
        body.append(l)
    return qs, "\n".join(body)


def parse_choice_block(lines, lo, hi):
    """
    从一段行里抽"题干 + A–D 选项"。返回 {题号: {题干, 选项}}。

    适用：完形（1–20）、阅读（21–40）、新题型（41–45）。
    实测排版规整：题干与四个选项各占一行。
    """
    out = {}
    cur = None
    for l in lines:
        m = QNUM_Q.match(l) or QNUM_PAREN.match(l)
        if m and lo <= int(m.group(1)) <= hi:
            n = int(m.group(1))
            # 题干可能跨行：以"下一行不是选项"为界继续吸收
            cur = {"题号": n, "题干": m.group(2).strip(), "选项": {}}
            out[n] = cur
            continue
        mo = OPT_Q.match(l)
        if mo and cur is not None and len(cur["选项"]) < 4:
            cur["选项"][mo.group(1)] = mo.group(2).strip()
            continue
        if cur is not None:
            # 题干的续行（不是选项、也不是新题号）
            if not cur["选项"] and len(cur["题干"]) < 400:
                cur["题干"] += " " + l
            elif cur["选项"]:
                # 选项的续行：接到最后一个选项上
                k = sorted(cur["选项"])[-1]
                cur["选项"][k] += " " + l
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", help="试卷 PDF")
    ap.add_argument("--tier", required=True, choices=list(en.TIERS))
    ap.add_argument("--year", help="年份；不传则从正文识别")
    ap.add_argument("--bookmarks", action="store_true", help="只打印书签")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    if args.bookmarks:
        bm, npages = bookmarks(args.pdf)
        print(f"{npages} 页，{len(bm)} 条书签：")
        for t, pg in bm[:60]:
            print(f"  {t:<68} p{pg}")
        return

    lines = norm_lines(args.pdf)
    print(f"{len(lines)} 行")
    marks = split_parts_by_content(lines)
    print("分节：")
    for i, kind, name in marks:
        print(f"  {i:>5}| {kind:<5} {name}")

    if args.write:
        # 按 Section/Part 边界切段，再按题号区间解析
        bounds = [i for i, _, _ in marks] + [len(lines)]
        seg = {}
        for k, (i, kind, name) in enumerate(marks):
            seg[name] = lines[i:bounds[k + 1]]
        rec = {"tier": args.tier, "年份": args.year, "篇目": []}

        # 完形：1–20（排版与阅读不同，用专门解析）
        if "Section I Use of English" in seg:
            qs, body = parse_cloze(seg["Section I Use of English"], 1, 20)
            rec["篇目"].append({"部分": "CLOZE", "材料": body, "小题": qs})
            print(f"  完形 {len(qs)} 题（材料 {len(body)} 字）")

        # 阅读：Text1–4，各自 5 题
        for t in ("Text 1", "Text 2", "Text 3", "Text 4"):
            if t in seg:
                qs = parse_choice_block(seg[t], 21, 40)
                rec["篇目"].append({"部分": "READ", "材料": "",
                                    "小题": [qs[k] for k in sorted(qs)]})
                print(f"  {t}: {len(qs)} 题")

        # 新题型：41–45
        if "Part B" in seg:
            qs = parse_choice_block(seg["Part B"], 41, 45)
            rec["篇目"].append({"部分": "NEW", "材料": "",
                                "小题": [qs[k] for k in sorted(qs)]})
            print(f"  新题型 {len(qs)} 题")

        total = sum(len(p["小题"]) for p in rec["篇目"])
        rec["题目数"] = total
        print(f"合计 {total} 题（客观题）")
        if args.write and args.year:
            os.makedirs(en.ENG_DIR, exist_ok=True)
            p = en.path_of(args.tier, args.year)
            json.dump(rec, open(p, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=1)
            print(f"已写入 {os.path.relpath(p, BASE)}")


if __name__ == "__main__":
    main()
