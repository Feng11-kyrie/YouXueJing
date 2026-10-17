#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
补齐**缺失的写作题**（PDF 缺页时从站点补）。

背景：英语二 2023 的 PDF 在 47 题后即结束（427 行），大作文页不在文件里。
我手工补过一次，#但下一次 `import_english_from_site.py --write` 把它冲掉了#
—— 因为重导是整份 JSON 重建。

所以把"补缺"做成**独立、可重复运行**的脚本，放在导入之后跑。
它只做一件事：对每套卷，若写作题少于 2 道，就从站点的写作解析页
（`section3-part-b` / `section-iv-part-b`）取题面，补成缺失的那道。

用法：
    .venv/bin/python scripts/repair_english_writing.py --write
"""
import argparse
import json
import os
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from yj import english as en                                    # noqa: E402

SITE = "https://english-exam.lazynote.cn/kaoyan/sections"
SLUG = {"EN1": "english-one", "EN2": "english-two"}
SECOND = {"EN1": "section3-part-b", "EN2": "section-iv-part-b"}
# 两卷大作文的题号
BIG = {"EN1": 52, "EN2": 48}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()

    from playwright.sync_api import sync_playwright
    from scripts.fetch_english_writing import parse_prompt

    with sync_playwright() as pw:
        b = pw.chromium.launch()
        ctx = b.new_context(viewport={"width": 1300, "height": 1000})
        pg = ctx.new_page()
        pg.goto("https://english-exam.lazynote.cn/kaoyan/",
                wait_until="domcontentloaded", timeout=45000)
        pg.wait_for_timeout(1500)

        for tier in ("EN1", "EN2"):
            for year in en.years(tier):
                rec = en.paper(tier, year) or {}
                ws = [ps for ps in rec.get("篇目", []) if ps.get("部分") == "WRITE"]
                n = sum(len(ps["小题"]) for ps in ws)
                if n >= 2:
                    continue
                num = BIG[tier]
                sec = SECOND[tier]
                try:
                    pg.goto(f"{SITE}/{year}-{SLUG[tier]}/{sec}/",
                            wait_until="domcontentloaded", timeout=30000)
                    pg.wait_for_timeout(2200)
                    prompt = parse_prompt(pg.inner_text("body"))
                except Exception as e:                      # noqa: BLE001
                    print(f"  {en.TIERS[tier]['简称']} {year}: ❌ {type(e).__name__}")
                    continue
                if not prompt:
                    print(f"  {en.TIERS[tier]['简称']} {year}: 题面为空，跳过")
                    continue
                rec.setdefault("篇目", []).append({
                    "部分": "WRITE", "材料": prompt,
                    "小题": [{"题号": num, "题干": "写作", "材料": prompt,
                              "题型": "写作", "分值": 15 if tier == "EN2" else 20}],
                })
                rec["题目数"] = sum(len(ps["小题"]) for ps in rec["篇目"])
                print(f"  {en.TIERS[tier]['简称']} {year}: 补入第 {num} 题"
                      f"（题面 {len(prompt)} 字）")
                if a.write:
                    p = en.path_of(tier, year)
                    tmp = p + ".tmp"
                    with open(tmp, "w", encoding="utf-8") as f:
                        json.dump(rec, f, ensure_ascii=False, indent=1)
                    os.replace(tmp, p)
                time.sleep(0.6)
        b.close()
    print("完成")


if __name__ == "__main__":
    main()
