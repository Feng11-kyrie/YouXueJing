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
            _comprehensive_block(q, year, user)
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
            # 这里原来有 max-w-3xl(768px) —— 题卡宽 950px 而选项行只到 768px，
            # 右边空出 180px，看起来像"内容只占一半"（用户两次指出右侧留白）。
            #
            # 我上次把这条改动写进了 proto/app.py，但题卡组件其实在**本文件**，
            # 所以那次"修好了"是假的（浏览器实测选项行仍是 768px 才发现）。
            # 教训：改样式前先用 --style 量实际生效的元素，别只看改了哪个文件。
            row = ui.row().classes("opt w-full items-center gap-2 "
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


def _comprehensive_block(q, year, user):
    """
    综合应用题（41–47）的作答区：参考答案 + 自评给分。

    设计依据（用户明确要求）：
        "显示一个解析选项，点了就把这道题的答案、以及每个步骤给多少分
         显示出来供用户自评；再弄一个给分的输入框，自评完输入得多少分保存"

    三点说明：
      ① **不提供打字作答框** —— 上一版我做过输入框，被用户点破：
         408 综合题是"写出算法设计思想 + 用 C/C++ 描述算法"，考场上就是手写，
         在输入框里敲伪代码既不现实也偏离真实形态。所以只提示"在纸上作答"。
      ② **步骤分值不做程序化解析** —— 它已经印在题干里（"(1) …（4 分）"），
         界面直接显示题干即有；我只需要给出该题总分作为打分上限。
         （题库 JSON 里那份被清洗掉了，但页面渲染的是含分值的原文。）
      ③ **自评分与自动判分严格分开存**：source='selfscore'，
         界面也绝不说成"判分结果" —— 这是用户自己给的判断。
    """
    from yj import data as _data
    sol = _data.solution(year, q["题号"]) if year else None   # {文本, 是否AI生成}
    try:
        total = int(q.get("分值") or 0)
    except (TypeError, ValueError):
        total = 0

    ui.label(f"综合应用题 · 手写解答题（本题 {total} 分，不做自动判分）") \
        .classes("t-sm font-semibold").style("color:#B45309")

    # ---- 作答提示 + 「查看解析」按钮（用户要的那个入口）
    show = {"v": False}
    holder = ui.column().classes("w-full gap-2")

    with ui.element("div").classes("w-full rounded-lg").style(
            "border:1px dashed #D7DEE8;background:#FBFCFE;padding:10px 14px"):
        ui.label("在纸上作答").classes("t-sm font-semibold") \
            .style("color:var(--sub)")
        ui.label("这题按步骤给分（各步骤分值见题干括号，如「（1）…（4 分）」）。"
                 "先在纸上写完整答案，再点下面的按钮对照解析、给自己打分。") \
            .classes("t-sm muted").style("line-height:1.7")
        if not sol:
            ui.label("注：这一年的答案册是纯扫描件，没有文字层，取不到参考答案 —— "
                     "请对照教材自行核对后给分。") \
                .classes("t-xs").style("color:#B45309")

    def render_detail():
        holder.clear()
        if not show["v"]:
            return
        with holder:
            if sol:
                with ui.card().classes("softcard w-full p-3 gap-1"):
                    # 来源标注必须分开：答案册抽取 ≠ AI 生成。
                    # 把 AI 写的解法说成官方答案就是编造，这条是红线。
                    if sol["是否AI生成"]:
                        ui.label("参考答案（AI 生成，未经官方核验）") \
                            .classes("t-sm font-semibold") \
                            .style("color:#B45309")
                        ui.label("这道题本地答案册没有可提取的解析（扫描件残缺或倾斜"
                                 "无法识别），下面这份是 AI 依据题干与分值结构生成的，"
                                 "**可能有错**。请以教材与老师讲解为准，"
                                 "不要把它当成标准答案。") \
                            .classes("t-xs").style("color:#B45309")
                    else:
                        ui.label("参考答案（答案册抽取）") \
                            .classes("t-sm font-semibold") \
                            .style("color:var(--accent)")
                        ui.label("抽取自答案册 PDF 的文字层（OCR），可能有错字或符号"
                                 "误识别（如「于」被识别成「千」、数字 1 与字母 l 混用）。"
                                 "请以教材为准，不要当成逐字准确的官方解析。") \
                            .classes("t-xs").style("color:#B45309")
                    ui.label(sol["文本"]).classes("t-sm whitespace-pre-wrap") \
                        .style("line-height:1.9")
            ui.label(f"对照题干括号里的步骤分值逐项给分，把总分填到下面并保存。"
                     f"本题满分 {total} 分。").classes("t-sm muted")

    def toggle_detail():
        show["v"] = not show["v"]
        btn.set_text("收起解析" if show["v"] else "查看解析")
        render_detail()

    # 【UX 修正】没有解析的年份，按钮要**明确标出来**，不能做成可点却点开是空的。
    # 用户就是这么踩到的：他在 2026 年卷（默认年份）点「查看解析」，
    # 而 2026 的答案册是纯扫描件 —— 点了没有任何内容，看起来像功能坏了。
    # 实测：2019/2021/2024/2025/2026 五年既没有答案册文字层，
    # 试卷 PDF 里也没有解析（只有题目），本地确实无解析可用。
    if sol:
        btn = ui.button("查看解析", on_click=toggle_detail).props("unelevated")
    else:
        btn = ui.button("无解析（见下方说明）").props("unelevated disable")
        ui.label("这一年的答案册是纯扫描图片、试卷里也只有题目，"
                 "所以本地没有参考答案可显示 —— 不是按钮坏了。"
                 "请对照教材自行核对后给分。") \
            .classes("t-xs").style("color:#B45309")

    # ---- 自评给分：输入框 + 保存（用户要求的那个输入框）
    prev = store.get_selfscore(user).get(q["id"])
    with ui.row().classes("items-center gap-2 no-wrap"):
        ui.label("自评得分：").classes("t-sm shrink-0")
        inp = ui.input(value=(f"{prev:g}" if prev is not None else "")) \
            .props(f'dense outlined type=number min=0 max={total} step=0.5') \
            .classes("w-24")
        ui.label(f"/ {total} 分").classes("t-sm muted shrink-0")
        msg = ui.label("").classes("t-sm shrink-0")

        def save():
            ok, err = store.set_selfscore(user, q["id"], inp.value, total)
            if ok:
                msg.set_text(f"已保存：自评 {float(inp.value):g} / {total} 分")
                msg.style("color:#1B5E36")
            else:
                msg.set_text(err)
                msg.style("color:#8C2C2C")

        ui.button("保存自评", on_click=save).props("unelevated")
    if prev is not None:
        msg.set_text(f"已保存：自评 {prev:g} / {total} 分")
        msg.style("color:#1B5E36")

    render_detail()
