#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从懒笔记的 **paper 页**导入英语真题（完形 1–20 + 阅读 21–40）。

为什么换这个源
--------------
原来用 GitHub 仓库的 PDF，实测有两个问题：
  ① **文字层噪声多**：题号里夹空格（`3 7.`、`3 .`）、行首多标点（`. 21.`）、
     两位数被拆开 —— 每漏一种噪声就整年进不来（我修了三轮才到 29/34）
  ② **2021/2022 的完形选项乱序且乱码**（`[C] peaks[ D] fades 1.[A] pauses[B] returs`，
     连拼写都错：returs / altermatively）—— 这段文字层不可救

换成懒笔记的 `/kaoyan/paper/<年>-english-<one|two>/` 页后：
  · 页面把题目渲染成**极规整的结构**（题号单行 + `[ A ]` 选项各占一行）
  · **34/34 套全部拿到 完形 20 + 阅读 20**
  · 拼写正确（pauses / returns / alternatively …）

**教训**：PDF 文字层是"排版抽取"的产物，噪声难免；而**网页正文是结构化的**。
同一个内容如果既有 PDF 又有网页版，优先用网页版 —— 这一条在政治那边也一样
（当时从 PDF 换成 eol 的网页正文，一次补齐了 5 年）。

用法
----
    .venv/bin/python scripts/import_english_from_site.py --scan
    .venv/bin/python scripts/import_english_from_site.py --write
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

SITE = "https://english-exam.lazynote.cn/kaoyan/paper"
SLUG = {"EN1": "english-one", "EN2": "english-two"}


def fetch_paper(tier, year, pg=None, own_browser=True):
    """
    取一套卷的 paper 页正文。**必须先访问 /kaoyan/ 建会话**，
    否则会被限流（表现为整页内容拿不到）。
    """
    t = None
    if pg is not None:
        pg.goto(f"{SITE}/{year}-{SLUG[tier]}/", wait_until="domcontentloaded",
                timeout=45000)
        pg.wait_for_timeout(2200)
        t = pg.inner_text("body")
        return t
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        page = b.new_context(viewport={"width": 1400, "height": 1200}).new_page()
        page.goto("https://english-exam.lazynote.cn/kaoyan/",
                  wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(1500)
        page.goto(f"{SITE}/{year}-{SLUG[tier]}/", wait_until="domcontentloaded",
                  timeout=45000)
        page.wait_for_timeout(2200)
        t = page.inner_text("body")
        b.close()
    return t


def parse_choice_questions(t, lo, hi):
    """
    解析页面上的选择题。形态极规整：

        1.
        [ A ]
        pauses
        [ B ]
        returns
        [ C ]
        peaks
        [ D ]
        fades

    所以按"题号独立成行 → 紧跟四组（[字母], 文本）"来切。
    """
    lines = [l.strip() for l in t.split("\n")]
    out = {}
    i = 0
    while i < len(lines):
        m = re.fullmatch(r'(\d{1,2})\s*[.、]?', lines[i])
        if m and lo <= int(m.group(1)) <= hi:
            n = int(m.group(1))
            opts, j = {}, i + 1
            while j + 1 < len(lines) and len(opts) < 4:
                lm = re.fullmatch(r'\[\s*([A-D])\s*\]', lines[j])
                if lm:
                    opts[lm.group(1)] = lines[j + 1]
                    j += 2
                else:
                    j += 1
            if len(opts) == 4 and n not in out:
                out[n] = opts
            i = j
        else:
            i += 1
    return out


def parse_paper(t, tier):
    """整套卷 → rec（与 yj.english 的模型一致）。"""
    cz = parse_choice_questions(t, 1, 20)
    rd = parse_choice_questions(t, 21, 40)
    if len(cz) != 20 or len(rd) != 20:
        return None, f"完形 {len(cz)}/20 阅读 {len(rd)}/20"
    rec = {"tier": tier, "篇目": []}
    # 完形：一篇文章 + 20 空（材料取自页面里第一个题号之前）
    body = []
    for l in t.split("\n"):
        s = l.strip()
        if re.fullmatch(r'1\s*[.、]?', s):
            break
        body.append(s)
    rec["篇目"].append({
        "部分": "CLOZE", "材料": "\n".join(body).strip(),
        "小题": [{"题号": n, "题干": "", "选项": cz[n]} for n in sorted(cz)]})
    # 阅读：页面上是 21–40 连排，按每 5 题分 4 篇
    order = sorted(rd)
    for k in range(0, 20, 5):
        chunk = order[k:k + 5]
        if len(chunk) < 5:
            break
        rec["篇目"].append({
            "部分": "READ", "材料": "",
            "小题": [{"题号": n, "题干": "", "选项": rd[n]} for n in chunk]})
    rec["题目数"] = sum(len(p["小题"]) for p in rec["篇目"])
    return rec, f"完整 {rec['题目数']} 题"


def _clean(obj):
    """去掉孤立代理字符（写盘会抛 surrogates not allowed）"""
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean(v) for v in obj]
    if isinstance(obj, str):
        return obj.encode("utf-8", "ignore").decode("utf-8", "ignore")
    return obj


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan", action="store_true")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright
    os.makedirs(en.ENG_DIR, exist_ok=True)
    ok = bad = 0
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        pg = b.new_context(viewport={"width": 1400, "height": 1200}).new_page()
        pg.goto("https://english-exam.lazynote.cn/kaoyan/",
                wait_until="domcontentloaded", timeout=45000)
        pg.wait_for_timeout(1500)
        for tier in ("EN1", "EN2"):
            for y in range(2010, 2027):
                try:
                    t = fetch_paper(tier, y, pg=pg)
                except Exception as e:                      # noqa: BLE001
                    print(f"  {en.TIERS[tier]['简称']} {y}: ❌ {type(e).__name__}")
                    bad += 1
                    time.sleep(1.0)
                    continue
                rec, msg = parse_paper(t, tier)
                tag = f"{en.TIERS[tier]['简称']} {y}"
                if rec is None:
                    bad += 1
                    print(f"  {tag}: ⚠️ {msg}")
                else:
                    ok += 1
                    print(f"  {tag}: ✅ {msg}")
                    if args.write and not args.scan:
                        rec = _clean(rec)
                        rec["年份"] = str(y)
                        rec["来源"] = "懒笔记 paper 页（结构化正文）"
                        p = en.path_of(tier, y)
                        tmp = p + ".tmp"
                        with open(tmp, "w", encoding="utf-8") as f:
                            json.dump(rec, f, ensure_ascii=False, indent=1)
                        os.replace(tmp, p)
                time.sleep(1.2)          # 停顿：否则被限流
        b.close()
    print(f"\n完整 {ok} 套 / 失败 {bad} 套")
    for t in ("EN1", "EN2"):
        print(f"  {en.TIERS[t]['简称']}: {en.years(t)}")


if __name__ == "__main__":
    main()
