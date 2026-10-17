#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
抓取写作题的**配图**（大作文的图表/漫画）。

为什么必须做：大作文的题干是"describe the picture and the chart below"，
**没有图学生根本没法写**。原先只抓了文字（Directions + 中文图意），
用户指出"作文里的图表为什么显示不出来，没有图表用户拿什么去做"。

图源：懒笔记写作页上的 `<img>`（`img-paper.lazynote.cn/...jpg`），
下载到 `data/english/img/`，路径记在题目的 `图片` 字段，
由 NiceGUI 静态目录 `/en_img` 提供访问。

用法：
    .venv/bin/python scripts/fetch_english_writing_img.py --all
    .venv/bin/python scripts/fetch_english_writing_img.py --all --write
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
WRITE_SEC = {("EN1", 0): "section3-part-a", ("EN1", 1): "section3-part-b",
             ("EN2", 0): "section-iv-part-a", ("EN2", 1): "section-iv-part-b"}
IMGDIR = os.path.join(en.ENG_DIR, "img")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    if not a.all:
        print("请用 --all")
        return
    os.makedirs(IMGDIR, exist_ok=True)

    from playwright.sync_api import sync_playwright
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
                qnums = [int(q["题号"]) for ps in rec.get("篇目", [])
                         if ps.get("部分") == "WRITE" for q in ps["小题"]]
                if not qnums:
                    continue
                slug = SLUG[tier]
                got = {}
                for idx, qn in enumerate(qnums):
                    sec = WRITE_SEC.get((tier, idx))
                    if not sec:
                        continue
                    # 【要重试】实测连续快速请求会被限流，页面拿不到图片元素
                    # （表现为 "0/2 张图"），隔久一点重试就正常。
                    urls = []
                    for attempt in range(3):
                        try:
                            pg.goto(f"{SITE}/{year}-{slug}/{sec}/",
                                    wait_until="domcontentloaded", timeout=30000)
                            pg.wait_for_timeout(2200 + attempt * 1500)
                            urls = pg.evaluate("""() => [...document.querySelectorAll('img')]
                                .map(i=>i.getAttribute('src'))
                                .filter(s=>s && !s.includes('favicon'))""")
                            if urls:
                                break
                        except Exception:               # noqa: BLE001
                            pass
                    if not urls:
                        continue
                    src = urls[0]
                    if src.startswith("/"):
                        src = "https://english-exam.lazynote.cn" + src
                    try:
                        r = ctx.request.get(src, timeout=30000)
                        if r.status == 200:
                            ext = os.path.splitext(src.split("?")[0])[1] or ".jpg"
                            fn = f"{tier}-{year}-{qn}{ext}"
                            with open(os.path.join(IMGDIR, fn), "wb") as f:
                                f.write(r.body())
                            got[qn] = f"img/{fn}"
                    except Exception:                   # noqa: BLE001
                        pass
                    time.sleep(1.2)
                print(f"  {en.TIERS[tier]['简称']} {year}: "
                      f"{len(got)}/{len(qnums)} 张图 " +
                      ", ".join(f"{k}→{v.split('/')[-1]}" for k, v in got.items()))
                if a.write and got:
                    p = en.path_of(tier, year)
                    for ps in rec.get("篇目", []):
                        if ps.get("部分") != "WRITE":
                            continue
                        for q in ps["小题"]:
                            if int(q["题号"]) in got:
                                q["图片"] = got[int(q["题号"])]
                    tmp = p + ".tmp"
                    with open(tmp, "w", encoding="utf-8") as f:
                        json.dump(rec, f, ensure_ascii=False, indent=1)
                    os.replace(tmp, p)
                time.sleep(1.5)
        b.close()
    print("完成")


if __name__ == "__main__":
    main()
