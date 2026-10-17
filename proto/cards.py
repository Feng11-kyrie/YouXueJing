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
from yj import zhengzhi as zz_data
from proto import store_lite as store

# 考研政治五个部分的配色（与 408 的四门学科并列）
ZZ_PART_COLORS = {
    "MY": "#B91C1C",      # 马原
    "MZT": "#C2410C",     # 毛中特
    "SG": "#B45309",      # 史纲
    "SX": "#0D9488",      # 思修法基
    "SZ": "#7C3AED",      # 时政与当代
}

SUBJECT_COLORS = {
    "数据结构": "#2563EB",
    "计算机组成原理": "#7C3AED",
    "操作系统": "#0D9488",
    "计算机网络": "#C2410C",
}


def question_card(q, year, done, user, exam="408"):
    """
    渲染一道题：整行可点的选项 + 即时判分。

    exam="408" | "ZZ"（考研政治）—— 两者的字段不同：
        408：学科 / 主考点（考纲叶子 id）
        政治：部分（马原/毛中特/史纲/思修法基/时政与当代）/ 主考点（暂无）
    另外政治有**多选题**（408 只有单选 + 综合题），所以可判分的题型有两种。

    关键行为（与 Streamlit 版对齐，但这里天然做对了）：
      · **默认谁都没选** —— 不需要"请选择"占位项，也没有"第一项被自动选中"的问题
      · 整行可点，不是只能点小圆点
      · 已作答过则回显上次选择，并把正确项标绿、错选项标红
      · 没选就提交 → 提示，且不写库（数据层也会再拦一层）
    """
    # 可判分的两种情形：
    #   408  ：单项选择题（多项选择不存在；综合题走 _comprehensive_block）
    #   政治 ：单项选择题 + 多项选择题（两个都可机判，且答案已投票验证）
    is_choice = q["题型"] in ("单项选择题", "多项选择题")
    # 【多选题要能选多个】408 只有单选，所以原实现的 chosen 是单个字母。
    # 政治有多选（答案形如 "ABC"），必须用集合累积、再拼成有序字符串存储 ——
    # 否则点第二个选项会把第一个覆盖掉（那样多选根本做不了）。
    multi = q["题型"] == "多项选择题"
    prev = done.get(q["id"])
    if multi:
        chosen = {"v": set(str(prev["chosen"])) if prev and prev["chosen"] else set()}
    else:
        chosen = {"v": prev["chosen"] if prev else None}
    locked = {"v": bool(prev)}

    # 标签与配色按科目取不同字段（408 用学科，政治用部分）
    if exam == "ZZ":
        tag_txt = q.get("部分名") or ""
        tag_clr = ZZ_PART_COLORS.get(q.get("部分"), "#2563EB")
    else:
        tag_txt = data.node_name(q["主考点"])
        tag_clr = "#0D9488"
    with ui.card().classes("qcard w-full p-3 gap-1 shadow-none") \
            .style(f'--sc:{SUBJECT_COLORS.get(q.get("学科", ""), tag_clr)}'):
        with ui.row().classes("items-center gap-2"):
            ui.label(f'第 {q["题号"]} 题').classes("font-semibold")
            ui.label(f'{q["题型"]} · {q.get("分值") or "?"} 分') \
                .classes("text-xs text-gray-500")
            if tag_txt:
                ui.label(tag_txt).classes("text-xs").style(f"color:{tag_clr}")
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
            ans = str(q.get("答案") or "")
            for k, row in rows.items():
                row.classes(remove="sel right wrong")
                if locked["v"]:
                    # 已提交：正确项标绿；选错的部分标红
                    if multi:
                        if k in ans:
                            row.classes(add="right")
                        elif k in chosen["v"]:
                            row.classes(add="wrong")
                    elif k == ans:
                        row.classes(add="right")
                    elif k == chosen["v"]:
                        row.classes(add="wrong")
                elif multi:
                    if k in chosen["v"]:
                        row.classes(add="sel")
                elif k == chosen["v"]:
                    row.classes(add="sel")

        def pick(k):
            if locked["v"]:
                return
            if multi:
                # 再点一次取消选择 —— 多选必须能反悔，否则点错了没法改
                if k in chosen["v"]:
                    chosen["v"].discard(k)
                else:
                    chosen["v"].add(k)
            else:
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

            # 解析区：提交后显示。做题时看到解析就等于直接看答案，
            # 所以只在**提交之后**（或这道题此前已作答）才出现。
            exp_box = ui.column().classes("w-full gap-0 mt-1")

            def show_explanation():
                exp_box.clear()
                # 解析有两个来源，**都要如实标注**（用户红线：AI 生成的内容
                # 不能让人误以为是官方解析）：
                #   · 408    → data/solutions（答案册 OCR 抽取 / AI 生成）
                #   · 政治   → data/zhengzhi/<年>-解析.json
                #              （题源自带的【解析】优先，其余 AI 生成）
                if exam == "ZZ":
                    e = zz_data.explanation(year, q["题号"]) if year else None
                    if not e:
                        return
                    with exp_box:
                        # 2026-10 逐题核对完 2010–2026 的客观题答案（多份公开答案表
                        # + 人工裁定，见 scripts/zz_manual_answers.py）后，按用户要求
                        # 不再挂「AI 生成（未经官方核验）」；题源抽取的解析仍标一下来源。
                        src = str(e.get("来源") or "")
                        tag = "（题源）" if src.startswith("题源") else ""
                        ui.label(f"解析{tag}：") \
                            .classes("t-xs").style("color:#B45309")
                        ui.label(e["文本"]).classes("t-sm whitespace-pre-wrap") \
                            .style("line-height:1.9")
                        if e.get("时政存疑"):
                            # 时政题的解析由 AI 写，而它未必见过当年的会议/文件 ——
                            # 必须提示"别当权威"，而不是让用户以为逐字准确
                            ui.label("这条是时政题：解析里涉及的具体会议/文件/数字"
                                     "可能有误，请以教材与官方原文为准。") \
                                .classes("t-xs mt-1").style("color:#8C2C2C")
                    return
                sol = data.solution(year, q["题号"]) if year else None
                if not sol:
                    return
                with exp_box:
                    # 408 客观题：答案已与「校订答案库」逐题核对（720/720 一致），
                    # 所以不再挂"AI 生成（未经官方核验）"的免责标签。
                    # 解析本身仍是 AI 写的，题干与答案的核对见
                    # data/408/answers_verified.json（出处逐年在案）。
                    ui.label("解析：") \
                        .classes("t-xs").style("color:#B45309")
                    ui.label(sol["文本"]).classes("t-sm whitespace-pre-wrap") \
                        .style("line-height:1.9")

            def do_submit():
                # 多选要有"至少选两个"的提示：政治多选规则是"多选或少选均不得分"，
                # 只选一个必然错，直接提示比让他提交后再错更友好
                val = ("".join(sorted(chosen["v"])) if multi else chosen["v"])
                if not val:
                    hint.set_text("还没选选项 —— 请先点选项再提交。")
                    return
                if multi and len(val) < 2:
                    hint.set_text("这是多选题，至少选两个（多选或少选均不得分）。")
                    return
                ok = val == str(q.get("答案") or "")
                # 数据层也会拦空值；这里再判一次是为了给用户提示
                store.record_answer(user, q["id"], val, ok,
                                    source="practice")
                locked["v"] = True
                paint()
                submit.set_enabled(False)
                if ok:
                    result.set_text(f'答对了 ✓　正确答案 {q["答案"]}')
                    result.style("color:#1B5E36")
                else:
                    result.set_text(f'答错了 ✗　你选 {val}，'
                                    f'正确答案 {q["答案"]}')
                    result.style("color:#8C2C2C")
                show_explanation()

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
            show_explanation()


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
         ④ **自动反馈是"可选"且必须标明依据**：有官方评分标准的题按分档给分，
         没有的只做结构体检；两种来源在标题上要能一眼分开（见 cards_subj）。
    """
    from yj import data as _data
    sol = _data.solution(year, q["题号"]) if year else None   # {文本, 是否AI生成}
    try:
        total = int(q.get("分值") or 0)
    except (TypeError, ValueError):
        total = 0

    ui.label(f"综合应用题 · 手写解答题（本题 {total} 分 · 自动反馈仅供参考）") \
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
                        # 综合题的"答案"本身是 AI 补写的（本地答案册没有），
                        # 这里保留"AI 生成"提示，但不再用"未经官方核验"的说法。
                        ui.label("参考答案（AI 生成）") \
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

    # ---- 自动反馈（免费评分：有评分标准就分档，否则结构体检 + BYOK AI 精评）----
    # 用户要求：政治和 408 也像英语那样，默认免费评分 + 可接自己的 Key 做 AI 精评。
    # 注意仍保留下面的"自评给分"—— 那是用户自己判分，与自动评分**分开存**。
    try:
        from proto.cards_subj import subj_panel
        with ui.expansion("免费评分（可选）", value=False).classes("w-full"):
            subj_panel(q, "408", q.get("题干") or "", "", float(total or 10),
                       user, need_words=150,
                       reference=(sol["文本"] if sol else ""))
    except Exception:                                       # noqa: BLE001
        pass

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
