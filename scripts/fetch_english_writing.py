#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
重新抓取**写作题面**（材料），修正 PDF 排版导致的串题。

问题（用户截图指出）
------------------
用 PDF 抽取写作题面时出现了两类错误：

**① 小作文的输入邮件丢失、大作文里混进了小作文的邮件**
PDF 的实际排版是：

    447| 51. Directions:  Read the following email …
    451| Part B
    452| 52. Directions:  Write an essay based on the picture and the chart below …
    458| 2020 年 2021 年 2022 年        ← 52 题的图表
    459| 某市近三年公园数量
    460| （单位：座）
    461| Dear Li Ming,                  ← **51 题的输入邮件，排在 52 题材料后面**
    466| Paul

即"51 题要回复的邮件"被排到了 52 题图表之后。按"截到下一个 Directions"
抽取时，51 只拿到 Directions、52 却把小作文的邮件也吞了。

**② 结尾残留章节标题**（`Part B` / `Part C`）。

修法
----
  · **题面用站点页**（`section3-part-a/b`、`section-iv-part-a/b`）——
    它是按题排好版的，顺序正确，小作文的输入邮件也在里面。
  · **图表注仍从 PDF 取**（站点页的图表是图片，中文图注只在 PDF 文字层），
    但**只取该题块里的中文行** —— 这样自动跳过后面的英文邮件。
  · 去掉 `Part X` / `Section X` 这类章节标题残留。

用法
----
    .venv/bin/python scripts/fetch_english_writing.py --all
    .venv/bin/python scripts/fetch_english_writing.py --all --write
"""
import argparse
import json
import os
import re
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from yj import english as en                                    # noqa: E402

SITE = "https://english-exam.lazynote.cn/kaoyan/sections"
SLUG = {"EN1": "english-one", "EN2": "english-two"}
WRITE_SEC = {("EN1", 0): "section3-part-a", ("EN1", 1): "section3-part-b",
             ("EN2", 0): "section-iv-part-a", ("EN2", 1): "section-iv-part-b"}
CJK = re.compile(r'[\u4e00-\u9fff]')


def parse_prompt(t):
    """
    从站点写作页抽题面。

    页面结构：
        英语一真题(2024)
        Section III Part A          ← 去掉
        Directions:
        Read the following email …
        ---
        Dear Li Ming,               ← 小作文的输入邮件
        …
        Paul
        ---
        Write your answer in about 100 words … (10 points)
        【参考范文 · 102 词】        ← 到此为止

    所以取 `Directions:` 之后、`【参考范文` 之前，去掉 `---` 分隔线与章节标题。
    """
    lines = [l.strip() for l in t.split("\n")]
    start = next((i for i, l in enumerate(lines)
                  if re.match(r'^Directions?\s*[:：]?$', l)), None)
    if start is None:
        start = next((i for i, l in enumerate(lines)
                      if re.match(r'^Directions?', l)), None)
    if start is None:
        return ""
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].startswith("【参考范文") or lines[j].startswith("【参考译文"):
            end = j
            break
    out = []
    for l in lines[start + 1:end]:
        if not l or l in ("---", "—"):
            continue
        if re.match(r'^Section\s+[IVX]+\b', l) or re.match(r'^Part\s+[AB]\b$', l):
            continue
        if l in ("写作题和范文", "PROMPT & MODEL ESSAY · 写作题和范文"):
            continue
        if l.startswith("本页是") or l.startswith("本页写作题面"):
            continue
        out.append(l)
    return "\n".join(out).strip()


def chart_note_from_pdf(tier, year, idx, qnums):
    """
    从 PDF 取该题的**图表中文注**（只保留中文行）。

    站点页的图表是图片，中文图注只在 PDF 文字层里。
    只取中文行的好处：自动跳过被排到同一块里的英文邮件。
    """
    import glob
    sub = "英语一" if tier == "EN1" else "英语二"
    src = os.environ.get("KYZHENTI", "/tmp/kyzhenti/公共课/英语真题")
    cands = [c for c in glob.glob(f'{src}/{sub}/*{year}*真题.pdf')
             if '带书签' not in c and '无解析' not in c]
    if not cands:
        return ""
    from scripts.parse_english import norm_lines
    try:
        lines = norm_lines(cands[0])
    except Exception:                                       # noqa: BLE001
        return ""
    n = qnums[idx]
    starts = [i for i, l in enumerate(lines)
              if re.match(rf'^\s*{n}\s*[.、]\s*Directions?', l)]
    if not starts:
        return ""
    i0 = starts[0]
    i1 = len(lines)
    for l2 in lines[i0 + 1:]:
        pass
    ends = [i for i in range(i0 + 1, len(lines))
            if re.match(r'^\s*\d{1,2}\s*[.、]\s*Directions?', lines[i])
            or re.match(r'^\s*Section\s+[IVX]+', lines[i])]
    if ends:
        i1 = ends[0]
    block = lines[i0 + 1:i1]
    zh = []
    for l in block:
        # 阈值放宽到 0.3：图表注里常混着数字（`2020 年 2021 年 2022 年`），
        # 按 0.5 会把年份那一行挡掉。
        if len(CJK.findall(l)) >= 2 and len(CJK.findall(l)) / max(1, len(l)) > 0.3:
            zh.append(l)
    return " ".join(zh).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()

    from playwright.sync_api import sync_playwright
    jobs = ([(t, y) for t in ("EN1", "EN2") for y in en.years(t)]
            if a.all else [])
    if not jobs:
        print("请用 --all")
        return

    with sync_playwright() as pw:
        b = pw.chromium.launch()
        ctx = b.new_context(viewport={"width": 1300, "height": 1000})
        pg = ctx.new_page()
        pg.goto("https://english-exam.lazynote.cn/kaoyan/",
                wait_until="domcontentloaded", timeout=45000)
        pg.wait_for_timeout(1500)

        for tier, year in jobs:
            rec = en.paper(tier, year) or {}
            write_ps = [ps for ps in rec.get("篇目", []) if ps.get("部分") == "WRITE"]
            if not write_ps:
                continue
            qnums = [int(q["题号"]) for ps in write_ps for q in ps["小题"]]
            slug = SLUG[tier]
            got = {}
            for idx, qn in enumerate(qnums):
                sec = WRITE_SEC.get((tier, idx))
                if not sec:
                    continue
                try:
                    pg.goto(f"{SITE}/{year}-{slug}/{sec}/",
                            wait_until="domcontentloaded", timeout=30000)
                    pg.wait_for_timeout(2200)
                    prompt = parse_prompt(pg.inner_text("body"))
                except Exception:                       # noqa: BLE001
                    prompt = ""
                note = chart_note_from_pdf(tier, year, idx, qnums)
                mat = prompt
                if note and note not in prompt:
                    mat = (prompt + "\n\n图表/图意：" + note).strip()
                if mat:
                    got[qn] = mat
                time.sleep(0.8)
            status = " / ".join(f'{k}:{len(v)}字' for k, v in sorted(got.items()))
            print(f"  {en.TIERS[tier]['简称']} {year}: {status or '（无）'}")
            if a.write and got:
                p = en.path_of(tier, year)
                for ps in rec.get("篇目", []):
                    if ps.get("部分") != "WRITE":
                        continue
                    for q in ps["小题"]:
                        if int(q["题号"]) in got:
                            q["材料"] = got[int(q["题号"])]
                            ps["材料"] = got[int(q["题号"])]
                tmp = p + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(rec, f, ensure_ascii=False, indent=1)
                os.replace(tmp, p)
            time.sleep(0.8)
        b.close()
    print("完成")


if __name__ == "__main__":
    main()
