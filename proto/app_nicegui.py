#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
优学鲸 · NiceGUI 原型（只做「408 历年真题」一页，用于和 Streamlit 版对比）

跑起来：
    .venv/bin/python proto/app_nicegui.py --port 8080

为什么做这个原型
----------------
用户想评估"要不要从 Streamlit 换掉"。判断依据不该是我说哪个好，
而是把同一页做出来对着看。数据层复用 yj/（一行没改），只有界面重写。

这一页刻意展示 Streamlit 做不到 / 很别扭的几件事：
  1. **真正的 URL 路由**：?year=2025&page=2 —— 可以直接分享"2025 年第 2 页"
  2. **选项行整行可点**（不是只能点小圆点），并且默认谁都没选
  3. **布局用普通 CSS/Tailwind 控制**，不用猜框架内部 DOM（对比 Streamlit 版
     我为了改样式反复试 data-testid）
  4. **只更新局部**：点一个选项不会重跑整个页面脚本
"""
import argparse
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from nicegui import ui                            # noqa: E402
from yj import data                                # noqa: E402
from proto import store_lite as store             # noqa: E402

SUBJECT_COLORS = {
    "数据结构": "#2563EB",
    "计算机组成原理": "#7C3AED",
    "操作系统": "#0D9488",
    "计算机网络": "#C2410C",
}
PER = 10

# 主题（原生 Tailwind 类，不需要覆盖框架样式）
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
          background: #fff; color: #46586D; }
  .cell.ok { background: #E6F6EC; border-color: #7DCB9A; color: #1B5E36; }
  .cell.bad { background: #FDECEC; border-color: #E9A0A0; color: #8C2C2C; }
  .cell.cur { outline: 2px solid #2563EB; outline-offset: 1px; font-weight: 700; }
</style>
""", shared=True)


@ui.page("/")
def exam_page(year: str = None, page: int = 1, user: str = "demo"):
    """真题页。参数走真实 URL，可直接分享/刷新保持状态。"""
    papers = data.paper_index()
    years = [p["年份"] for p in papers]
    year = str(year) if year in years else years[0]
    p = data.paper(year)
    store.ensure_user(user)

    state = {"year": year, "page": max(1, min(page, 5)), "user": user}
    done = store.get_answers(user)

    # ---------------------------------------------------------- 顶栏
    with ui.row().classes("w-full items-center gap-4 px-6 py-3 "
                         "border-b border-gray-200 sticky top-0 bg-white z-10"):
        ui.label("408 历年真题").classes("text-xl font-bold")

        def goto(**kw):
            state.update(kw)
            ui.navigate.to(f"/?year={state['year']}&page={state['page']}"
                           f"&user={state['user']}")

        ui.select(years, value=year, label="年份",
                  on_change=lambda e: goto(year=str(e.value), page=1)) \
            .classes("w-36").props("dense outlined")

        ui.label(f"{p['题数']} 题 · {p['总分']} 分 · 可判分 {p['有答案数']}") \
            .classes("text-sm text-gray-500")

        answered = [q for q in p["题目"] if q["id"] in done]
        n_ok = sum(1 for q in answered if done[q["id"]]["is_correct"])
        if answered:
            ui.label(f"已作答 {len(answered)}/{p['单选数']} · 答对 {n_ok} · "
                     f"正确率 {n_ok / len(answered):.0%}") \
                .classes("text-sm ml-auto").style("color:#17418F")

    # ---------------------------------------------------------- 两栏主体
    with ui.row().classes("w-full items-start gap-5 px-6 py-4"):

        # ---------- 左：答题卡（吸顶）----------
        with ui.column().classes("w-64 shrink-0 sticky top-20 gap-2"):
            ui.label("答题卡").classes("text-sm font-semibold text-gray-500")
            with ui.element("div").classes("flex flex-wrap gap-1"):
                for i, q in enumerate(p["题目"]):
                    st_ = done.get(q["id"])
                    cls = "cell"
                    if st_:
                        cls += " ok" if st_["is_correct"] else " bad"
                    if i // PER + 1 == state["page"]:
                        cls += " cur"
                    cell = ui.element("div").classes(cls)
                    cell.on("click", lambda _=None, n=i // PER + 1: goto(page=n))
                    with cell:
                        ui.label(q["题号"]).classes("text-xs")
            with ui.row().classes("gap-2 items-center mt-1"):
                ui.button(icon="chevron_left",
                          on_click=lambda: goto(page=max(1, state["page"] - 1))) \
                    .props("flat dense").set_enabled(state["page"] > 1)
                ui.label(f"第 {state['page']} / 5 页").classes("text-sm")
                ui.button(icon="chevron_right",
                          on_click=lambda: goto(page=min(5, state["page"] + 1))) \
                    .props("flat dense").set_enabled(state["page"] < 5)
            ui.separator()
            ui.label("底色 = 答题状态：绿对 · 红错 · 白未做") \
                .classes("text-xs text-gray-400")

        # ---------- 右：题目 ----------
        with ui.column().classes("flex-1 gap-2 min-w-0"):
            items = p["题目"][(state["page"] - 1) * PER: state["page"] * PER]
            ui.label(f"第 {items[0]['题号']}–{items[-1]['题号']} 题") \
                .classes("text-lg font-semibold")

            subj = None
            for q in items:
                if q["学科"] != subj:
                    subj = q["学科"]
                    ui.label(subj).classes("text-base font-semibold mt-2") \
                        .style(f"color:{SUBJECT_COLORS.get(subj, '#2563EB')}")
                _question_card(q, p, done, state, user)


def _question_card(q, p, done, state, user):
    """一道题：整行可点的选项 + 即时判分。"""
    is_choice = q["题型"] == "单项选择题"
    prev = done.get(q["id"])
    chosen = {"v": prev["chosen"] if prev else None}
    locked = {"v": bool(prev)}          # 已作答的题：显示结果，不再重复提交

    with ui.card().classes("qcard w-full p-3 gap-1 shadow-none") \
            .style(f"--sc:{SUBJECT_COLORS.get(q['学科'], '#2563EB')}"):
        with ui.row().classes("items-center gap-2"):
            ui.label(f"第 {q['题号']} 题").classes("font-semibold")
            ui.label(f"{q['题型']} · {q.get('分值') or '?'} 分") \
                .classes("text-xs text-gray-500")
            ui.label(data.node_name(q["主考点"])).classes("text-xs") \
                .style("color:#0D9488")
        ui.label(q["题干"]).classes("text-[15px] leading-6 whitespace-pre-wrap")

        if q.get("需插图") and not q.get("图片"):
            ui.label("原卷有插图，但插图尚未抽取齐全，建议对照原卷。") \
                .classes("text-xs text-amber-700")
        if q.get("图片"):
            ui.image(f"data/{q['图片']}").classes("max-w-md rounded")

        if not is_choice:
            ui.label("综合应用题 — 题库暂无答案，本题不计分") \
                .classes("text-xs font-semibold text-orange-700")
            return

        opts = q.get("选项") or {}
        rows = {}

        def paint():
            for k, row in rows.items():
                row.classes(remove="sel right wrong")
                if locked["v"]:
                    if k == q["答案"]:
                        row.classes(add="right")
                    elif k == chosen["v"]:
                        row.classes(add="wrong")
                elif k == chosen["v"]:
                    row.classes(add="sel")

        def pick(k):
            if locked["v"]:
                return
            chosen["v"] = k
            paint()
            submit.set_enabled(True)
            hint.set_visibility(False)

        for k in sorted(opts):
            # 限宽到 760px：原来一行拉到近 1000px，长选项读起来要横跳
            row = ui.row().classes("opt w-full max-w-3xl items-center gap-2 "
                                   "rounded-lg px-3 py-1 cursor-pointer")
            rows[k] = row
            with row:
                ui.label(k).classes("w-5 font-semibold text-gray-600")
                ui.label(opts[k]).classes("text-[15px] whitespace-pre-wrap flex-1 leading-6")
            row.on("click", lambda _=None, k=k: pick(k))

        hint = ui.label("请先点一个选项再提交。").classes("text-xs text-amber-700")
        hint.set_visibility(False)

        with ui.row().classes("items-center gap-3 mt-1"):
            submit = ui.button("提交答案", on_click=lambda: _submit(
                q, chosen, locked, user, rows, paint, hint, submit, result))
            submit.set_enabled(bool(prev))
            result = ui.label("").classes("text-sm")
        paint()
        if prev:
            result.set_text(f"已作答：你选 {prev['chosen']}，"
                            f"正确答案 {q['答案']}")
            result.style(f"color:{'#1B5E36' if prev['is_correct'] else '#8C2C2C'}")


def _submit(q, chosen, locked, user, rows, paint, hint, submit, result):
    if not chosen["v"]:
        hint.set_visibility(True)
        return
    ok = chosen["v"] == q["答案"]
    store.record_answer(user, q["id"], chosen["v"], ok, source="practice")
    locked["v"] = True
    paint()
    submit.set_enabled(False)
    if ok:
        result.set_text(f"答对了 ✓　正确答案 {q['答案']}")
        result.style("color:#1B5E36")
    else:
        result.set_text(f"答错了 ✗　你选 {chosen['v']}，正确答案 {q['答案']}")
        result.style("color:#8C2C2C")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--show", action="store_true")
    args = ap.parse_args()
    ui.run(port=args.port, title="优学鲸 · NiceGUI 原型",
           show=args.show, reload=False, favicon="🐳")


if __name__ in {"__main__", "__mp_main__"}:
    main()
