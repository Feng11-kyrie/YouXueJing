#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
界面截图 + 真实 DOM 探针（开发/评审用，不属于产品运行时）。

为什么需要它
------------
前几轮改界面是"盲改"：看不到渲染结果，只能反复猜 CSS 选择器有没有命中，
结果就是用户反复说"还是不对"。这个脚本让改样式这件事变成可验证的：

    .venv/bin/python scripts/shot.py                     # 截 6 个页面
    .venv/bin/python scripts/shot.py --page 408 --full    # 只截真题页，整页长图
    .venv/bin/python scripts/shot.py --dom .stButton      # 打印真实 DOM 属性

用法要点
--------
- 必须先把 Streamlit 跑起来（http://localhost:8501）。脚本只负责"看"，不改应用。
- Streamlit 是 SPA，页面内容靠 WebSocket 推过来，所以必须**等**到侧栏真实
  渲染出来再截图（`wait_for_selector`）。用固定 sleep 会截到加载动画。
- `--dom` 用来确认 CSS 选择器写对没有：属性名猜错是这类"改了没效果"的常见原因
  （Streamlit 的按钮真实属性是 data-testid="stBaseButton-primary"，不是 .stButton button）。
"""
import argparse
import os
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "_shots")

NAV = ["408 历年真题", "挑考点练习", "快速诊断", "我的画像", "我的薄弱点"]
# 注：「学习路径」页已按用户要求删除；页面名"讲义生成"也已改为"我的薄弱点"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8501")
    # 默认用一次性探针用户，不要默认 demo：
    # 截图脚本会真的驱动应用（点击等），用 demo 就可能动到演示画像的数据。
    # 要看有数据的页面时显式传 --user demo，看完用
    # `.venv/bin/python .workbuddy/reseed_demo.py --check` 核对数据还在。
    ap.add_argument("--user", default="shot_probe", help="?u= 的值")
    ap.add_argument("--page", default=None, help="只截这一页（导航名，可写部分匹配）")
    ap.add_argument("--full", action="store_true", help="截整页长图")
    ap.add_argument("--width", type=int, default=1600)
    ap.add_argument("--height", type=int, default=1000)
    ap.add_argument("--dom", default=None, help="打印匹配该 CSS 选择器的元素 outerHTML")
    ap.add_argument("--style", default=None, help="打印匹配该选择器的元素计算样式")
    ap.add_argument("--clock", default=None, help="用固定时间渲染，截图可比对")
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright

    os.makedirs(OUT, exist_ok=True)
    pages = [p for p in NAV if args.page and args.page in p] or \
            ([args.page] if args.page else NAV)

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(viewport={"width": args.width,
                                            "height": args.height},
                                  device_scale_factor=2)
        pg = ctx.new_page()
        url = f"{args.url}/?u={args.user}"
        pg.goto(url, wait_until="domcontentloaded")

        # 必须等真实渲染：侧栏出现 + 导航按钮就位。
        # 注意：不能用 button[data-testid^="stBaseButton"] 当等待条件 ——
        # 页面里第一个匹配到的是隐藏的 headerNoPadding 按钮，playwright 等它
        # "visible" 会一直超时（第一次跑就踩了）。改用 attached 状态 + 侧栏。
        pg.wait_for_selector('[data-testid="stSidebar"]', timeout=60000)
        pg.wait_for_selector('button[data-testid="stBaseButton-primary"]',
                             state="attached", timeout=60000)
        pg.wait_for_timeout(1500)

        if args.dom:
            els = pg.query_selector_all(args.dom)
            print(f"选择器 {args.dom!r} 命中 {len(els)} 个")
            for e in els[:4]:
                html = e.evaluate("el => el.outerHTML")
                print("-" * 70)
                print(html[:900])
            if not els:
                print("!! 没命中 —— 这就是 CSS 写了却没效果的原因")
            browser.close()
            return

        if args.style:
            els = pg.query_selector_all(args.style)
            print(f"选择器 {args.style!r} 命中 {len(els)} 个")
            props = ["background-color", "color", "font-size", "font-weight",
                     "padding", "margin", "border", "border-radius", "box-shadow",
                     "border-left", "width", "height", "row-gap", "line-height"]
            for e in els[:6]:
                cs = e.evaluate(
                    "(el, props) => { const s = getComputedStyle(el);"
                    " const o = {}; for (const p of props) o[p] = s.getPropertyValue(p);"
                    " return o; }", props)
                rect = e.evaluate("el => { const r = el.getBoundingClientRect();"
                                  " return [Math.round(r.x), Math.round(r.y),"
                                  " Math.round(r.width), Math.round(r.height)] }")
                print("-" * 70)
                txt = (e.inner_text() or "").replace("\n", " ")[:34]
                print(f"[{txt}] 位置/尺寸 x,y,w,h = {rect}")
                for k, v in cs.items():
                    if v and v not in ("none", "normal", "auto", "0px"):
                        print(f"    {k:<16} {v}")
            browser.close()
            return

        for name in pages:
            # 点导航切页（导航是按钮，不是 radio）
            btn = pg.query_selector(f'button[data-testid="stBaseButton-secondary"]:has-text("{name}")') \
                or pg.query_selector(f'button:has-text("{name}")')
            if btn:
                btn.click()
                pg.wait_for_timeout(2500)
            fname = os.path.join(OUT, f"{name.replace(' ', '_')}.png")
            pg.screenshot(path=fname, full_page=args.full)
            print(f"✓ {name}  ->  {fname}")

        browser.close()


if __name__ == "__main__":
    main()
