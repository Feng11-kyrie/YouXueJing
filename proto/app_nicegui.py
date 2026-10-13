#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
优学鲸 · NiceGUI 原型 — 第 1 页：408 历年真题

跑起来：
    .venv/bin/python proto/app_nicegui.py --port 8899

为什么做这个原型
----------------
用户想评估"要不要从 Streamlit 换掉"。判断依据不该是我说哪个好，
而是把同一页做出来对着看。数据层复用 yj/（一行没改），只有界面重写。

这一页刻意展示 Streamlit 做不到 / 很别扭的几件事：
  1. **真正的 URL 路由**：?year=2025&page=2 —— 可直接分享"2025 年第 2 页"
  2. **选项行整行可点**，默认谁都没选（Streamlit 的 radio 会自动选中第一项，
     就是用户反馈的"每道题 A 都是蓝的"）
  3. **布局用普通 CSS/Tailwind 控制**，不用猜框架内部 DOM
  4. **只更新局部**：点一个选项不会重跑整个页面脚本

题卡组件在 proto/cards.py，与「挑考点练习」页**共用同一份** —— 两页行为不会分叉。
"""
import argparse
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from nicegui import ui                            # noqa: E402
from yj import data                                # noqa: E402
from proto import store_lite as store              # noqa: E402
from proto.cards import question_card, SUBJECT_COLORS   # noqa: E402

PER = 10

ui.add_head_html("""
<style>
  body { font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif; }
  .qcard { border-left: 4px solid var(--sc, #2563EB); }
  .opt { transition: background .12s; cursor: pointer; border: 1px solid #E3E8EF; }
  .opt:hover { background: #F5F8FF; border-color: #B9CCF5; }
  .opt.sel { background: #E7F0FE; border-color: #2563EB; }
  .opt.right { background: #E6F6EC; border-color: #7DCB9A; }
  .opt.wrong { background: #FDECEC; border-color: #E9A0A0; }
  .cell { width: 26px; height: 24px; line-height: 24px; text-align: center;
          font-size: 11px; border-radius: 5px; border: 1px solid #D7DEE8;
          background: #fff; color: #46586D; cursor: pointer; }
  .cell.ok { background: #E6F6EC; border-color: #7DCB9A; color: #1B5E36; }
  .cell.bad { background: #FDECEC; border-color: #E9A0A0; color: #8C2C2C; }
  .cell.cur { outline: 2px solid #2563EB; outline-offset: 1px; font-weight: 700; }
</style>
""", shared=True)


@ui.page("/")
def exam_page(year: str = None, page: int = 1, view: str = "全部",
              user: str = "demo"):
    """真题页。参数走真实 URL，刷新不丢、可直接分享。"""
    papers = data.paper_index()
    years = [p["年份"] for p in papers]
    year = str(year) if str(year) in years else years[0]
    p = data.paper(year)
    store.ensure_user(user)
    done = store.get_answers(user)

    if view == "未做":
        shown = [q for q in p["题目"] if q["id"] not in done]
    elif view == "只错题":
        shown = [q for q in p["题目"]
                 if q["id"] in done and not done[q["id"]]["is_correct"]]
    else:
        shown = list(p["题目"])
    pages_n = max(1, (len(shown) + PER - 1) // PER)
    cur = max(1, min(int(page or 1), pages_n))

    def goto(**kw):
        s = {"year": year, "page": cur, "view": view, "user": user}
        s.update(kw)
        s = {k: v for k, v in s.items() if v not in (None, "", 0)}
        ui.navigate.to("/?" + "&".join(f"{k}={v}" for k, v in s.items()))

    with ui.row().classes("w-full items-center gap-4 px-6 py-2 "
                         "border-b border-gray-200 sticky top-0 bg-white z-10"):
        ui.label("408 历年真题").classes("text-xl font-bold")
        ui.select(years, value=year,
                  on_change=lambda e: goto(year=str(e.value), page=1)) \
            .props("dense outlined").classes("w-32")
        ui.toggle(["全部", "未做", "只错题"], value=view,
                  on_change=lambda e: goto(view=e.value, page=1)) \
            .props("dense unelevated")

        answered = [q for q in p["题目"] if q["id"] in done]
        n_ok = sum(1 for q in answered if done[q["id"]]["is_correct"])
        info = (f'{p["题数"]} 题 · {p["总分"]} 分 · 可判分 {p["有答案数"]}'
                + (f'　|　已作答 {len(answered)}/{p["单选数"]} · 答对 {n_ok} · '
                   f'正确率 {n_ok / len(answered):.0%}' if answered else ""))
        ui.label(info).classes("text-sm text-gray-500 ml-auto")

    with ui.row().classes("w-full items-start gap-5 px-6 py-4"):

        with ui.column().classes("w-60 shrink-0 sticky top-16 gap-1"):
            ui.label("答题卡").classes("text-sm font-semibold text-gray-500")
            with ui.element("div").classes("flex flex-wrap gap-1"):
                for i, q in enumerate(shown):
                    st_ = done.get(q["id"])
                    cls = "cell"
                    if st_:
                        cls += " ok" if st_["is_correct"] else " bad"
                    if i // PER + 1 == cur:
                        cls += " cur"
                    cell = ui.element("div").classes(cls)
                    cell.on("click", lambda _=None, n=i // PER + 1: goto(page=n))
                    with cell:
                        ui.label(q["题号"]).classes("text-xs")
            with ui.row().classes("gap-2 items-center"):
                ui.button(icon="chevron_left",
                          on_click=lambda: goto(page=max(1, cur - 1))) \
                    .props("flat dense").set_enabled(cur > 1)
                ui.label(f"{cur} / {pages_n} 页").classes("text-sm")
                ui.button(icon="chevron_right",
                          on_click=lambda: goto(page=min(pages_n, cur + 1))) \
                    .props("flat dense").set_enabled(cur < pages_n)
            ui.label("绿=对 · 红=错 · 白=未做").classes("text-xs text-gray-400")

        with ui.column().classes("flex-1 gap-2 min-w-0"):
            if not shown:
                ui.label(f"筛选「{view}」下没有题目。") \
                    .classes("text-sm text-gray-500")
                return
            items = shown[(cur - 1) * PER: cur * PER]
            ui.label(f'第 {items[0]["题号"]}–{items[-1]["题号"]} 题') \
                .classes("text-lg font-semibold")
            subj = None
            for q in items:
                if q["学科"] != subj:
                    subj = q["学科"]
                    ui.label(subj).classes("text-base font-semibold mt-1") \
                        .style(f'color:{SUBJECT_COLORS.get(subj, "#2563EB")}')
                question_card(q, p["年份"], done, user)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8899)
    ap.add_argument("--show", action="store_true")
    args = ap.parse_args()
    ui.run(port=args.port, title="优学鲸 · NiceGUI 原型",
           show=args.show, reload=False, favicon="🐳")


if __name__ in {"__main__", "__mp_main__"}:
    main()
