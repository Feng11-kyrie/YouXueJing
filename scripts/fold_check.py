#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
首屏体检：用真实浏览器量"用户打开页面第一眼能看到什么"。

为什么需要它
------------
界面好不好看是主观的，但有几条是**客观、可量化**的，而且直接决定体验：

  1. 打开页面时，用户想做的事有没有出现在第一屏？
     —— 学生打开真题卷是想做题。实测过一版：元信息（标题2行+控件3块+
        卷情2行+成绩1行+答题卡5行+跳页1行）把第一道题推到 y=785，
        1440x900 的笔记本上选项和提交按钮全在折叠线以下，
        **一道完整的题都看不到**。
  2. 颜色对比是否够（有无"写了 CSS 但看不出来"）。

用法：.venv/bin/python scripts/fold_check.py
    .venv/bin/python scripts/fold_check.py --url http://localhost:8501 --user demo

输出的是客观数字，不是"我觉得"。
"""
import argparse
import sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8501")
    ap.add_argument("--user", default="demo")
    ap.add_argument("--width", type=int, default=1440, help="常见笔记本宽度")
    ap.add_argument("--height", type=int, default=900, help="常见笔记本高度")
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright

    fails = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(viewport={"width": args.width,
                                            "height": args.height})
        pg = ctx.new_page()
        pg.goto(f"{args.url}/?u={args.user}", wait_until="domcontentloaded")
        pg.wait_for_selector('[data-testid="stSidebar"]', timeout=60000)
        pg.wait_for_timeout(4000)

        r = pg.evaluate("""() => {
          const H = window.innerHeight;
          const cards = [...document.querySelectorAll('div[data-testid="stVerticalBlock"]')]
            .filter(d => parseFloat(getComputedStyle(d).borderTopWidth) > 0
                         && d.offsetWidth > 300);
          const box = e => e ? {top: Math.round(e.getBoundingClientRect().top),
                                bottom: Math.round(e.getBoundingClientRect().bottom)}
                             : null;
          const c0 = cards[0];
          const submit = c0 ? [...c0.querySelectorAll('button')]
                              .find(b => b.innerText.includes('提交')) : null;
          const sb = getComputedStyle(document.querySelector('[data-testid="stSidebar"]'));
          const active = document.querySelector('button[data-testid="stBaseButton-primary"]');
          return {
            viewportH: H,
            firstCard: box(c0),
            submitBottom: submit ? Math.round(submit.getBoundingClientRect().bottom) : null,
            cardsVisible: cards.filter(d => d.getBoundingClientRect().bottom <= H).length,
            sidebarBg: sb.backgroundColor,
            activeBg: active ? getComputedStyle(active).backgroundColor : null,
            activeText: active ? getComputedStyle(active).color : null,
          };
        }""")

        H = r["viewportH"]
        print(f"视口 {args.width}x{args.height}")
        print(f"  第 1 题卡片    top={r['firstCard']['top']}  "
              f"bottom={r['firstCard']['bottom']}")
        print(f"  提交按钮底部   y={r['submitBottom']}")
        print(f"  首屏完整可见题数 {r['cardsVisible']}")
        print(f"  侧栏底色 {r['sidebarBg']}　选中项底色 {r['activeBg']} "
              f"文字 {r['activeText']}")
        print()

        def check(name, ok, detail=""):
            print(f"  {'✓' if ok else '✗'} {name}" + (f"   {detail}" if detail else ""))
            if not ok:
                fails.append(name)

        check("第一道题完整落在首屏内",
              r["submitBottom"] is not None and r["submitBottom"] < H,
              f"提交按钮 y={r['submitBottom']} / 折叠线 {H}")
        check("首屏至少能看到 1 道完整题", r["cardsVisible"] >= 1,
              f"{r['cardsVisible']} 道")
        # 选中态对比：底色不能等于侧栏底色，否则"看不出选中了哪一项"
        check("选中项底色与侧栏底色不同", r["activeBg"] != r["sidebarBg"],
              f"{r['activeBg']} vs {r['sidebarBg']}")

        browser.close()

    print()
    if fails:
        print(f"体检未通过 {len(fails)} 项: {fails}")
        sys.exit(1)
    print("首屏体检通过")


if __name__ == "__main__":
    main()
