#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从中国教育在线（kaoyan.eol.cn）抓考研政治真题 —— **逐年补齐早年（2010–2014）**。

为什么需要这个脚本
------------------
2010–2014 的公开电子版在别的渠道全是扫描件/损毁件（kaoyan.com 那批 19 页只
抽出 379 字水印，渲染出来是歪斜条纹，OCR 也读不出）。但 eol.cn 有**网页正文**，
而且是干净的可复制文字。

关键：**eol 的文章是多页分页的**
    第 1 页  t20120912_843558.shtml      单选 1–16
    第 2 页  t20120912_843558_1.shtml    多选 17–33
    第 3–5 页 _2 / _3 / _4                分析题与答案
只抓第一页会以为"只有单选"（我一开始就误判过）。所以必须按分页把正文拼起来。

用法：
    .venv/bin/python scripts/fetch_eol_zz.py --year 2010 --url <第1页URL>
    .venv/bin/python scripts/fetch_eol_zz.py --year 2010 --url <URL> --write
"""
import argparse
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
DEST = os.path.join(BASE, ".cache", "zhengzhi")


def fetch_pages(first_url, max_pages=16, wait_ms=1500):
    """抓第 1 页 + 后续 _1.._N 页，返回拼接后的正文"""
    from playwright.sync_api import sync_playwright
    base, ext = os.path.splitext(first_url)
    urls = [first_url] + [f"{base}_{i}{ext}" for i in range(1, max_pages)]
    parts = []
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        pg = b.new_context(viewport={"width": 1400, "height": 1000}).new_page()
        for u in urls:
            try:
                pg.goto(u, wait_until="domcontentloaded", timeout=60000)
                pg.wait_for_timeout(wait_ms)
                # 只取正文容器，避开导航/推荐/页脚 —— 否则关键词统计被污染
                txt = pg.evaluate("""() => {
                    const sel = ['.TRS_Editor', '#content', '.article', '.detail',
                                 '.text', 'article'];
                    for (const s of sel) {
                        const el = document.querySelector(s);
                        if (el && el.innerText && el.innerText.length > 500)
                            return el.innerText;
                    }
                    return document.body.innerText;}""")
            except Exception as e:                       # noqa: BLE001
                print(f"    {u} 失败: {type(e).__name__}", file=sys.stderr)
                continue
            has = sum(1 for k in ("单项选择题", "多项选择题", "分析题") if k in txt)
            print(f"    {u.split('/')[-1]}: {len(txt)} 字"
                  + (f"，含 {has} 个题型标题" if has else "（无题型标题）"))
            parts.append(txt)
            # 早停要**保守**：连续 6 页无题型标题才停。
            # 原来阈值是 3，结果 2014 在第 _7/_8/_9 页（题干延续、无题型标题）
            # 就停了，而**第 38 题在 _10 页** —— 表现为"分析题缺 1 道"，
            # 被我误判成题源没有。这类文章的页面内容模式很不规则，不能激进早停。
            if len(parts) >= 7 and all(
                    sum(1 for k in ("单项选择题", "多项选择题", "分析题") if k in p) == 0
                    for p in parts[-6:]):
                print("    （连续 6 页无题型标题，停止翻页）")
                break
        b.close()
    return "\n".join(parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", required=True)
    ap.add_argument("--url", required=True, help="第 1 页 URL")
    ap.add_argument("--max-pages", type=int, default=16,
                    help="文章分页上限。实测每篇 8-13 页 —— 原来默认 8 "
                         "会把分析题截掉（2014 的 36-38 题在 _8/_9/_10 页），"
                         "表现为「分析题缺 3 道」，一度被我误判成题源没有")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    print(f"抓取 {args.year} 年（含分页）：")
    text = fetch_pages(args.url, args.max_pages)
    print(f"  合计 {len(text)} 字")
    for kw in ("单项选择题", "多项选择题", "分析题"):
        print(f"    含「{kw}」{text.count(kw)} 次")

    os.makedirs(DEST, exist_ok=True)
    # 存成"每段一行"，让解析器的题号/选项行锚定生效
    lines = [l.strip() for l in text.split("\n")]
    out = "\n".join(l for l in lines if l)
    dst_txt = os.path.join(DEST, f"{args.year}-eol.txt")
    with open(dst_txt, "w", encoding="utf-8") as f:
        f.write(out)
    print(f"  已存 {os.path.relpath(dst_txt, BASE)}")

    sys.path.insert(0, BASE)
    from scripts.parse_zhengzhi import parse
    items = parse(dst_txt, args.year)
    cnt = {}
    for it in items:
        cnt[it["题型"]] = cnt.get(it["题型"], 0) + 1
    print(f"  解析结果：{cnt}")
    if args.write and items:
        import json
        rec = {"年份": args.year, "题数": len(items), "题目": items,
               "来源": f"中国教育在线 {args.url}"}
        dst = os.path.join(BASE, "data", "zhengzhi", f"{args.year}.json")
        json.dump(rec, open(dst, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print(f"  已写入 {os.path.relpath(dst, BASE)}")


if __name__ == "__main__":
    main()
