#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
英语真题的**复合题卡片** —— 与 `cards.question_card` 并列的另一个组件。

为什么不复用 `question_card`
--------------------------
`question_card` 的模型是"**一道题 = 一问一答**"，题干独立、选项挂在题干下。
英语是**复合题**，装不进那个模型：

    · 完形   ：20 个空**嵌在一篇文章里**，题目本身没有独立题干
    · 阅读   ：一篇文章 + 5 道题，题**共享材料**
    · 新题型 ：一组材料 + 5 个匹配项

所以这里按"篇目（材料 + 小题）"渲染：
    篇目卡片 ─┬─ 材料区（文章 / 提示）
              └─ 小题区（每题：题干? + 选项 + 提交）

完形特殊：它的"题"是文章里的空，所以材料区要**把空渲染成可点的位置**，
点开才显示 4 个选项 —— 否则 20 个空的 80 个选项全铺出来，页面会很长。

答案与解析
----------
客观题的答案来自 `yj.english.explanation()`（懒笔记），**提交后才显示**。
主观题（翻译/写作）不走这里，见 `subjective_block`。
"""
from nicegui import ui

from yj import english as en
from proto import store_lite as store

CORRECT = "#1B5E36"
WRONG = "#8C2C2C"


def _opt_row(q, letter, text, chosen, multi, locked, on_pick):
    """一行选项。整行可点（与 question_card 的行为一致）。"""
    sel = letter in chosen["v"] if multi else chosen["v"] == letter
    cls = "opt w-full items-center gap-2 rounded-lg px-3 py-1 cursor-pointer"
    row = ui.row().classes(cls)
    if sel:
        row.style("background:#EAF2FB")
    if locked:
        ans = (q.get("_ans") or "")
        if letter in ans:
            row.style("background:#E8F5E9")
        elif sel and letter not in ans:
            row.style("background:#FDECEA")
    with row:
        ui.label(letter).classes("w-5 font-semibold text-gray-600")
        ui.label(text).classes("text-[15px] whitespace-pre-wrap flex-1 leading-6")
    if not locked:
        row.on("click", lambda: on_pick(letter))
    return row


def answer_of(q, tier, year):
    """
    取一道英语题的**正确答案**。

    **必须从解析文件读，不能读 `q["答案"]`** —— 试题与答案分开存放：
    试题来自懒笔记 paper 页（只有题目），答案来自分节页（另有文件）。
    重新导入试题时答案不会跟着来（实测：题目文件里 0/40 有答案，
    而解析文件里 40/40 有）。踩过这个坑：界面用 `q["答案"]` 判分，
    结果每题都判"暂无答案"。
    """
    e = en.explanation(tier, year, q["题号"])
    return str((e or {}).get("答案") or "")


def _sub_question(q, year, tier, done, user):
    """
    一道小题（阅读 21–40 / 新题型 41–45 用）。
    与政治/408 的题卡行为一致：可点选项、即时判分、提交后显示答案与解析。
    """
    qid = q["id"]
    ans = answer_of(q, tier, year)
    q["_ans"] = ans          # 供 _opt_row 渲染对错颜色时读取
    prev = done.get(qid)
    chosen = {"v": ""}
    locked = {"v": bool(prev)}

    card = ui.card().classes("softcard w-full p-3 gap-2 shadow-none")
    with card:
        with ui.row().classes("items-center gap-2"):
            ui.label(f'第 {q["题号"]} 题').classes("font-semibold")
            ui.label(f'{q.get("分值", 2)} 分').classes("text-xs text-gray-500")
            if not ans:
                # 【如实标注】2026 的阅读 21–25 在来源站点是下载直链，拿不到答案。
                # 这类题不能"看起来能判分" —— 直接说明只能看题。
                ui.label("暂无答案（来源缺失）").classes("text-xs") \
                    .style("color:#B45309")
        if q.get("题干"):
            ui.label(q["题干"]).classes("text-[15px] leading-6 whitespace-pre-wrap")

        opts_box = ui.column().classes("w-full gap-1")
        hint = ui.label("").classes("text-xs text-amber-700")
        with ui.row().classes("items-center gap-3 mt-1"):
            result = ui.label("").classes("text-sm")
            exp_box = ui.column().classes("w-full gap-0 mt-1")

        def show_explanation():
            exp_box.clear()
            e = en.explanation(tier, year, q["题号"])
            if not e:
                return
            with exp_box:
                ui.label('解析（懒笔记）：').classes("t-xs") \
                    .style("color:#B45309")
                if e.get("解析"):
                    ui.label(e["解析"]).classes("t-sm whitespace-pre-wrap") \
                        .style("line-height:1.9")

        def paint():
            opts_box.clear()
            with opts_box:
                for L, T in sorted((q.get("选项") or {}).items()):
                    _opt_row(q, L, T, chosen, False, locked["v"], pick)

        def pick(letter):
            if locked["v"]:
                return
            chosen["v"] = letter
            paint()

        def submit():
            val = chosen["v"]
            if not val:
                hint.set_text("还没选选项 —— 请先点选项再提交。")
                return
            if not ans:
                hint.set_text("这道题暂无答案，无法判分（来源站点缺该节）。")
                return
            ok = (val == ans)
            store.record_answer(user, qid, val, ok, source="exam")
            locked["v"] = True
            paint()
            submit_btn.set_enabled(False)
            if ok:
                result.set_text(f'答对了 ✓　正确答案 {ans}')
                result.style(f"color:{CORRECT}")
            else:
                result.set_text(f'答错了 ✗　你选 {val}，正确答案 {ans}')
                result.style(f"color:{WRONG}")
            show_explanation()

        submit_btn = ui.button("提交答案", on_click=submit)
        submit_btn.set_enabled(not prev)

        paint()
        if prev:
            chosen["v"] = prev.get("chosen") or ""
            paint()
            if ans:
                result.set_text(f'已作答：你选 {prev["chosen"]}，'
                                f'正确答案 {ans}')
                result.style(f'color:{CORRECT if prev["is_correct"] else WRONG}')
            show_explanation()


def passage_card(passage, year, tier, done, user, compact_material=True):
    """
    渲染一个**篇目**：材料区 + 小题区。

    材料区的呈现按部分不同：
      · READ / NEW ：材料是文章，直接展示（可折叠以省空间）
      · CLOZE      ：文章里嵌着 20 个空 —— 见 cloze_card（单独实现，因为它
                     要把空渲染成可点的位置）
    """
    code = passage.get("部分")
    name = passage.get("部分名") or code
    subs = passage.get("小题") or []
    mat = (passage.get("材料") or "").strip()

    with ui.card().classes("softcard w-full p-3 gap-2 shadow-none"):
        with ui.row().classes("items-center gap-2"):
            ui.label(name).classes("t-lead font-bold")
            ui.label(f'{len(subs)} 题').classes("t-xs muted")
        if mat:
            if compact_material:
                with ui.expansion("文章", value=True).classes("w-full"):
                    ui.label(mat).classes("text-[15px] leading-7 whitespace-pre-wrap") \
                        .style("font-family:Georgia,'Times New Roman',serif")
            else:
                ui.label(mat).classes("text-[15px] leading-7 whitespace-pre-wrap")
    for q in subs:
        _sub_question(q, year, tier, done, user)


# ---------------------------------------------------------------------------
# 完形填空：文章 + 20 个空
# ---------------------------------------------------------------------------
# 完形与阅读的关键差别：它**没有独立题干** —— 题目就是文章里的空。
# 所以不能"文章 + 20 张题卡"那样排（20 题会把页面拉得很长），
# 而是把空渲染成可点的位置，点开才显示 4 个选项。
#
# 实测材料里空以**数字**标出：`There's nothing more welcoming than a door
# opening for you.   1   the need to be touched to open or close, ...`
# 所以用"独立出现的 1–20 数字"作为空的锚点。
def _split_cloze(text, lo=1, hi=20):
    """
    把完形文章切成 [文本片段, 空号, 文本片段, 空号, ...]。

    返回 (片段列表, 空号列表)，两者交替；片段数 = 空数 + 1。
    匹配不到足够的空就返回 (None, []) —— 由调用方退化处理。
    """
    import re
    parts, nums = [], []
    pos = 0
    for m in re.finditer(r'(?<![\d.])(\d{1,2})(?![\d.])', text):
        n = int(m.group(1))
        if not (lo <= n <= hi):
            continue
        # 空号必须**单调递增**（正文里也会有数字，如年份、百分比）
        if nums and n != nums[-1] + 1:
            continue
        if not nums and n != lo:
            continue
        parts.append(text[pos:m.start()])
        nums.append(n)
        pos = m.end()
    parts.append(text[pos:])
    if len(nums) < 10:            # 空太少说明匹配错了，不硬用
        return None, []
    return parts, nums


def cloze_card(passage, year, tier, done, user):
    """
    完形篇目：文章里的空可点，**选项在文章下方内联显示**。

    为什么不用弹层：我第一版用 ui.dialog 做选项弹层，实测出现
    "后端已 `set_text`、前端不更新"的现象（闭包捕获的元素与页面上查询到的
    不是同一个），排查成本高。改成内联后：**选中的空与选项区在同一层渲染**，
    更新路径短、行为可预测。

    交互：点文章里的数字 → 下方出现该空的 4 个选项 → 点选项**立即提交并判分**。
    """
    subs = {str(q["题号"]): q for q in (passage.get("小题") or [])}
    for _q in subs.values():
        _q["_ans"] = answer_of(_q, tier, year)
    mat = (passage.get("材料") or "").strip()
    parts, nums = _split_cloze(mat)

    # 每个空的状态：已选字母（已作答的从库里回显）
    picked = {}
    for n in nums:
        q = subs.get(str(n))
        prev = done.get(q["id"]) if q else None
        picked[n] = (prev or {}).get("chosen") or ""

    active = {"n": None}
    card = ui.card().classes("softcard w-full p-3 gap-2 shadow-none")
    with card:
        with ui.row().classes("items-center gap-2"):
            ui.label("完形填空").classes("t-lead font-bold")
            ui.label(f'{len(subs)} 空 · 点文章里的数字作答').classes("t-xs muted")

        if parts is None:
            ui.label("（这篇文章的空位置没能自动识别，下面按题号列出）") \
                .classes("t-xs").style("color:#B45309")
            ui.label(mat).classes("text-[15px] leading-7 whitespace-pre-wrap")
            for n in sorted(subs, key=int):
                _sub_question(subs[n], year, tier, done, user)
            return

        slots = {}
        opts_area = ui.column().classes("w-full gap-1 mt-2")

        def render_opts():
            opts_area.clear()
            n = active["n"]
            if n is None:
                ui.label("↑ 点文章里的数字，这里会出现该空的选项。") \
                    .classes("t-xs muted")
                return
            q = subs.get(str(n))
            if q is None:
                ui.label(f"第 {n} 空没有对应题目。").classes("t-xs muted")
                return
            ans = q.get("_ans") or ""
            cur = picked.get(n) or ""
            with ui.row().classes("items-center gap-2"):
                ui.label(f'第 {n} 空').classes("font-semibold")
                if ans and cur:
                    ok = (cur == ans)
                    ui.label(("答对了 ✓" if ok else f'答错了 ✗ 你选 {cur}')
                             + f'　正确答案 {ans}').classes("text-sm") \
                        .style(f'color:{"#1B5E36" if ok else "#8C2C2C"}')
                elif not ans:
                    ui.label("暂无答案（来源缺失）").classes("text-xs") \
                        .style("color:#B45309")

            with ui.column().classes("w-full gap-1"):
                for L, T in sorted((q.get("选项") or {}).items()):
                    row = ui.row().classes(
                        "opt w-full items-center gap-2 rounded-lg px-3 py-1 "
                        "cursor-pointer")
                    if cur == L:
                        row.style("background:#EAF2FB")
                    if ans and cur:
                        if L == ans:
                            row.style("background:#E8F5E9")
                        elif cur == L and L != ans:
                            row.style("background:#FDECEA")
                    with row:
                        ui.label(L).classes("w-5 font-semibold text-gray-600")
                        ui.label(T).classes("text-[15px] flex-1")
                    if not (ans and cur):          # 已作答的不再改
                        row.on("click", lambda _=None, L=L, n=n: commit(n, L))
            if ans and cur:
                e = en.explanation(tier, year, q["题号"])
                if e and e.get("解析"):
                    ui.label("解析（懒笔记）：").classes("t-xs mt-1") \
                        .style("color:#B45309")
                    ui.label(e["解析"]).classes("t-sm whitespace-pre-wrap") \
                        .style("line-height:1.9")

        def commit(n, L):
            q = subs.get(str(n))
            if q is None:
                return
            ans = q.get("_ans") or ""
            if not ans:
                ui.notify("这道题暂无答案，无法判分。", color="warning")
                return
            ok = (L == ans)
            store.record_answer(user, q["id"], L, ok, source="exam")
            picked[n] = L
            paint_slots()
            render_opts()
            ui.notify("答对了 ✓" if ok else f'答错了 ✗ 正确答案 {ans}',
                      color=("positive" if ok else "negative"))

        def paint_slots():
            for k, el in slots.items():
                v = picked.get(k) or ""
                el.set_text(v or str(k))
                if v:
                    el.style("background:#EAF2FB;color:#17418F;"
                             "border-bottom:2px solid #93B4E0")
                else:
                    el.style("color:#5B7FBF;border-bottom:2px solid #93B4E0")

        def activate(n):
            active["n"] = n
            paint_slots()
            # 高亮当前空
            for k, el in slots.items():
                if k == n and not picked.get(k):
                    el.style("background:#FFF7E6;color:#B45309;"
                             "border-bottom:2px solid #F0B429")
            render_opts()

        with ui.element("div").classes("w-full leading-7") \
                .style("font-family:Georgia,'Times New Roman',serif;"
                       "font-size:15px"):
            for i, seg in enumerate(parts):
                if seg.strip():
                    ui.label(seg).classes("inline whitespace-pre-wrap")
                if i < len(nums):
                    n = nums[i]
                    el = ui.label(str(n)).classes(
                        "blankslot inline-block min-w-[2.6rem] text-center "
                        "mx-1 px-1 rounded cursor-pointer font-semibold")
                    el.props(f'data-blank={n}')
                    slots[n] = el
                    el.on("click", lambda _=None, n=n: activate(n))

        paint_slots()
        render_opts()
        ui.label("提示：点空 → 下面选答案（选完立即判分）。已作答的空会显示字母。") \
            .classes("t-xs muted")
