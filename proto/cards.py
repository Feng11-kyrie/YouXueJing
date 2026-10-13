#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
共享组件：题目卡片（真题页与挑考点练习页共用同一份）。

为什么要单独一个文件
--------------------
两页都要渲染题目和判分。如果各写一份，行为和样式迟早会分叉
（Streamlit 版就吃过这个：同一个判题逻辑在两处各写一遍，
后来加"未选不写库"时要改两个地方）。

这里也说明了一件事：**Streamlit 版的复用更别扭** —— 判题逻辑写在一个
函数里，但"选中状态"要靠 session_state 的键名约定，控件行为又和框架耦合；
NiceGUI 里组件就是普通 Python 对象，直接传参就行。
"""
from nicegui import ui

from yj import data
from proto import store_lite as store

SUBJECT_COLORS = {
    "数据结构": "#2563EB",
    "计算机组成原理": "#7C3AED",
    "操作系统": "#0D9488",
    "计算机网络": "#C2410C",
}


def question_card(q, year, done, user):
    """
    渲染一道题：整行可点的选项 + 即时判分。

    关键行为（与 Streamlit 版对齐，但这里天然做对了）：
      · **默认谁都没选** —— 不需要"请选择"占位项，也没有"第一项被自动选中"的问题
      · 整行可点，不是只能点小圆点
      · 已作答过则回显上次选择，并把正确项标绿、错选项标红
      · 没选就提交 → 提示，且不写库（数据层也会再拦一层）
    """
    is_choice = q["题型"] == "单项选择题"
    prev = done.get(q["id"])
    chosen = {"v": prev["chosen"] if prev else None}
    locked = {"v": bool(prev)}

    with ui.card().classes("qcard w-full p-3 gap-1 shadow-none") \
            .style(f'--sc:{SUBJECT_COLORS.get(q["学科"], "#2563EB")}'):
        with ui.row().classes("items-center gap-2"):
            ui.label(f'第 {q["题号"]} 题').classes("font-semibold")
            ui.label(f'{q["题型"]} · {q.get("分值") or "?"} 分') \
                .classes("text-xs text-gray-500")
            ui.label(data.node_name(q["主考点"])).classes("text-xs") \
                .style("color:#0D9488")
            if year:
                ui.label(f'{year} 年').classes("text-xs text-gray-400")
        ui.label(q["题干"]).classes("text-[15px] leading-6 whitespace-pre-wrap")

        if q.get("需插图") and not q.get("图片"):
            ui.label("原卷有插图，但插图尚未抽取齐全，建议对照原卷。") \
                .classes("text-xs text-amber-700")
        if q.get("图片"):
            ui.image(f'data/{q["图片"]}').classes("max-w-md rounded")

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
            hint.set_text("")

        for k in sorted(opts):
            row = ui.row().classes("opt w-full max-w-3xl items-center gap-2 "
                                   "rounded-lg px-3 py-1 cursor-pointer")
            rows[k] = row
            with row:
                ui.label(k).classes("w-5 font-semibold text-gray-600")
                ui.label(opts[k]).classes("text-[15px] whitespace-pre-wrap "
                                          "flex-1 leading-6")
            row.on("click", lambda _=None, k=k: pick(k))

        # 提示用"空文本 + 需要时才填"而不是 set_visibility 切换显隐：
        # 实测初始隐藏后 set_visibility(True) 不生效（元素一直带 hidden）
        # —— 与其和框架 API 较劲，不如用一个必然可靠的方式：
        # 元素始终可见，只是内容为空。
        hint = ui.label("").classes("text-xs text-amber-700")

        with ui.row().classes("items-center gap-3 mt-1"):
            result = ui.label("").classes("text-sm")

            def do_submit():
                if not chosen["v"]:
                    hint.set_text("还没选选项 —— 请先点一个答案再提交。")
                    return
                ok = chosen["v"] == q["答案"]
                # 数据层也会拦空值；这里再判一次是为了给用户提示
                store.record_answer(user, q["id"], chosen["v"], ok,
                                    source="practice")
                locked["v"] = True
                paint()
                submit.set_enabled(False)
                if ok:
                    result.set_text(f'答对了 ✓　正确答案 {q["答案"]}')
                    result.style("color:#1B5E36")
                else:
                    result.set_text(f'答错了 ✗　你选 {chosen["v"]}，'
                                    f'正确答案 {q["答案"]}')
                    result.style("color:#8C2C2C")

            # 按钮**始终可点**：先前的做法是"未选就 disabled"，结果
            # "请先选一个答案"这个提示永远触发不到（按钮点不动 = 死代码），
            # 用户只会看到一个灰按钮、不知道为什么。改为可点 + 用提示引导，
            # 提交后（无论对错）才禁用。
            submit = ui.button("提交答案", on_click=do_submit)
            submit.set_enabled(not prev)

        paint()
        if prev:
            result.set_text(f'已作答：你选 {prev["chosen"]}，'
                            f'正确答案 {q["答案"]}')
            result.style(f'color:{"#1B5E36" if prev["is_correct"] else "#8C2C2C"}')
