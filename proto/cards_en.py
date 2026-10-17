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
import re

from nicegui import ui

from yj import english as en
from yj import ai_grade as aig
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
    # 答题卡点击跳转用的锚点（英语没有分页，只能靠 scrollIntoView）
    card.props(f'data-q="{q["题号"]}"')
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


def passage_card(passage, year, tier, done, user, compact_material=True,
                 material_only=False):
    """
    渲染一个**篇目**：材料区 + 小题区。

    材料区的呈现按部分不同：
      · READ / NEW ：材料是文章，直接展示（可折叠以省空间）
      · CLOZE      ：文章里嵌着 20 个空 —— 见 cloze_card（单独实现，因为它
                     要把空渲染成可点的位置）

    material_only=True 时**只渲染材料、不渲染小题** —— 两栏布局要用：
    左栏放文章、右栏放题目（用户要求"左侧放文章右侧放问题"，
    理由是"一个文章直接占了一页，看问题还要回来继续阅读，上下翻页很麻烦"）。
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
    if material_only:
        return
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
    完形填空：**左文章（空可点）/ 右题目（每 5 空一组翻页）**。

    用户要求（原话）：
      "完形能不能也按照这样，但完形的问题有点多，可以按照点第几题右侧出来
       上下五道题。"
    即：与阅读一样两栏；但完形有 20 空，右侧不能一次铺 20 道，
    所以**按 5 道一组翻页**（1–5 / 6–10 / 11–15 / 16–20）。

    左栏：文章，空渲染成可点位置（点一下把右侧切到该空所在的那组）
    右栏：当前组的 5 空，各带 4 个选项；选完立即判分、显示对错与解析；
          已作答的空在左栏显示字母（一眼看出做过哪些）
    """
    subs = {str(q["题号"]): q for q in (passage.get("小题") or [])}
    for _q in subs.values():
        _q["_ans"] = answer_of(_q, tier, year)
    mat = (passage.get("材料") or "").strip()
    parts, nums = _split_cloze(mat)

    picked = {}
    for n in nums:
        q = subs.get(str(n))
        prev = done.get(q["id"]) if q else None
        picked[n] = (prev or {}).get("chosen") or ""

    PER = 5                      # 右侧每组几道（用户指定的量）
    page = {"i": 0}
    slots = {}

    with ui.card().classes("softcard w-full p-3 gap-2 shadow-none"):
        with ui.row().classes("items-center gap-2"):
            ui.label("完形填空").classes("t-lead font-bold")
            ui.label(f'{len(subs)} 空').classes("t-xs muted")
            ui.label("点左侧空作答 · 右侧每 5 空一组").classes("t-xs muted ml-auto")

        if parts is None:
            ui.label("（这篇文章的空位置没能自动识别，下面按题号列出）") \
                .classes("t-xs").style("color:#B45309")
            ui.label(mat).classes("text-[15px] leading-7 whitespace-pre-wrap")
            for n in sorted(subs, key=int):
                _sub_question(subs[n], year, tier, done, user)
            return

        # 【right 必须在 grid 内部创建】我原来在 grid 外先建了它（为了给
        # render_page 引用），结果它不属于 grid —— **grid 只有 1 个子元素**，
        # 右栏被挤到 grid 外面去，截图里只剩题目占满全宽、左栏消失。
        # 用 holder 在 grid 内占位，再把真正的列放进去。
        with ui.element("div").classes("w-full").style(
                "display:grid;grid-template-columns:minmax(0,48fr) minmax(0,52fr);"
                "gap:16px;align-items:start"):
            # ---- 左栏：文章（sticky + 独立滚动）----
            with ui.card().classes("softcard p-3 gap-2 shadow-none") \
                    .style("position:sticky;top:12px;"
                           "max-height:calc(100vh - 90px);overflow:auto"):
                with ui.row().classes("items-center gap-2"):
                    ui.label("文章").classes("t-lead font-bold")
                    ui.label("点数字答题").classes("t-xs muted")
                with ui.element("div").classes("w-full leading-7").style(
                        "font-family:Georgia,'Times New Roman',serif;"
                        "font-size:15px"):
                    for i, seg in enumerate(parts):
                        if seg.strip():
                            ui.label(seg).classes("inline whitespace-pre-wrap")
                        if i < len(nums):
                            n = nums[i]
                            el = ui.label(str(n)).classes(
                                "blankslot inline-block min-w-[2.6rem] "
                                "text-center mx-1 px-1 rounded cursor-pointer "
                                "font-semibold")
                            el.props(f'data-blank={n}')
                            slots[n] = el
                            el.on("click", lambda _=None, n=n: jump(n))

            # ---- 右栏：必须在 grid 内创建（见上）----
            right = ui.column().classes("w-full gap-2 min-w-0")

        # ---------- 内部函数 ----------
        def paint_slots():
            for k, el in slots.items():
                v = picked.get(k) or ""
                el.set_text(v or str(k))
                if v:
                    el.style("background:#EAF2FB;color:#17418F;"
                             "border-bottom:2px solid #93B4E0")
                else:
                    el.style("color:#5B7FBF;border-bottom:2px solid #93B4E0")

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
            render_page()
            ui.notify("答对了 ✓" if ok else f'答错了 ✗ 正确答案 {ans}',
                      color=("positive" if ok else "negative"))

        def jump(n):
            """点左侧的空 → 右侧切到它那一组，并高亮该空。"""
            page["i"] = (n - 1) // PER
            paint_slots()
            for k, el in slots.items():
                if k == n and not picked.get(k):
                    el.style("background:#FFF7E6;color:#B45309;"
                             "border-bottom:2px solid #F0B429")
            render_page()

        def render_page():
            """渲染右侧**当前组**的 5 道题。"""
            right.clear()
            n_pages = max(1, (len(nums) + PER - 1) // PER)
            page["i"] = max(0, min(page["i"], n_pages - 1))
            i0 = page["i"] * PER
            group = nums[i0:i0 + PER]
            with right:
                with ui.row().classes("items-center gap-2 flex-wrap"):
                    for k in range(n_pages):
                        lo = nums[k * PER]
                        hi = nums[min(len(nums) - 1, k * PER + PER - 1)]
                        on = (k == page["i"])
                        ui.button(f'{lo}–{hi}',
                                  on_click=lambda _=None, k=k:
                                  (page.update(i=k), render_page())) \
                            .props("unelevated" if on else "flat dense")
                    ui.label(f'{len(nums)} 空 · 每 {PER} 空一组') \
                        .classes("t-xs muted ml-auto")

                for n in group:
                    q = subs.get(str(n))
                    if q is None:
                        continue
                    cur = picked.get(n) or ""
                    ans = q.get("_ans") or ""
                    with ui.card().classes("softcard w-full p-2 gap-1 shadow-none"):
                        with ui.row().classes("items-center gap-2"):
                            ui.label(f'第 {n} 空').classes("font-semibold")
                            if ans and cur:
                                ok = (cur == ans)
                                ui.label(("答对了 ✓" if ok
                                          else f'答错了 ✗ 你选 {cur}')
                                         + f'　正确答案 {ans}') \
                                    .classes("text-sm") \
                                    .style(f'color:{"#1B5E36" if ok else "#8C2C2C"}')
                            elif not ans:
                                ui.label("暂无答案（来源缺失）").classes("text-xs") \
                                    .style("color:#B45309")
                        for L, T in sorted((q.get("选项") or {}).items()):
                            row = ui.row().classes(
                                "opt w-full items-center gap-2 rounded-lg "
                                "px-2 py-0 cursor-pointer")
                            if cur == L:
                                row.style("background:#EAF2FB")
                            if ans and cur:
                                if L == ans:
                                    row.style("background:#E8F5E9")
                                elif cur == L:
                                    row.style("background:#FDECEA")
                            with row:
                                ui.label(L).classes(
                                    "w-5 font-semibold text-gray-600")
                                ui.label(T).classes("text-[15px] flex-1")
                            if not (ans and cur):
                                row.on("click", lambda _=None, L=L, n=n:
                                       commit(n, L))
                        if ans and cur:
                            e = en.explanation(tier, year, q["题号"])
                            if e and e.get("解析"):
                                ui.label(e["解析"][:300]).classes(
                                    "t-xs whitespace-pre-wrap mt-1") \
                                    .style("color:#6B7280;line-height:1.7")

        paint_slots()
        render_page()
        ui.label("提示：点左侧文章里的数字跳到该空；右侧每 5 空一组，"
                 "可点上方按钮换组。").classes("t-xs muted")


def _band_to_score(band, full, rubric):
    """
    **档次 → 分数**。这是"AI 评分能加入总分"的关键一步。

    为什么需要它：AI 输出的是**档名**（`第二档`），不是分数；
    考研阅卷也是**按档给分**。所以折算规则必须来自官方档位本身，
    不能自己编一个换算表。

    做法：
      1. 在 rubric 里按档名找到该档的区间（如 `第五档` → `17–20`）
      2. 取区间**中值**（AI 说不清"17 还是 19"，报中值是诚实的）
      3. 按该题满分缩放 —— 档位区间是**按题型全额**给的
         （英语一写作 `17–20` 是 20 分制），小作文满分只有 10 分，
         不缩放会把 18.5 算到一道 10 分的题上。

    实测过的坑：
      · 档位区间在 rubric 的 **score 字段**里，不在档名里
        （`("第五档", "17–20", …)`）—— 从档名找数字会得到 0
      · 只取档名匹配才能对上（`第二档` 是完整档名，无数字）
    """
    if not band or not full or not rubric:
        return 0.0
    band = str(band)
    top = 0.0
    hit = None
    for name, score, _desc in rubric.get("档次", []):
        nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", str(score))]
        if nums:
            top = max(top, nums[-1])
        # 档名匹配：AI 可能返回 `第二档` 或 `第二档（5–8 分）`
        if hit is None and (str(name) == band or band.startswith(str(name))):
            hit = nums
    if hit is None:
        # 退一步：直接按受支持的最小档给 0 分（宁可低估，不虚高）
        return 0.0
    if len(hit) >= 2:
        mid = (hit[0] + hit[-1]) / 2
    elif hit:
        mid = hit[0]
    else:
        return 0.0
    if top <= 0:
        return 0.0
    return round(mid / top * full, 2)


def subjective_block(q, year, tier, done, user):
    """
    一道主观题（翻译 46–50 / 写作 51–52）。
    """
    code = q.get("部分") or ("TRANS" if q.get("题型") == "翻译" else "WRITE")
    task = "TRANSLATION" if code == "TRANS" else "WRITING"
    rb = aig.rubric_for(task, tier)
    qid = q["id"]
    ref = (en.explanation(tier, year, q.get("题号")) or {})
    # 该题满分：写作按题号（小作文 10 / 大作文 20），翻译按部分均摊
    score_max = en.score_of(q.get("题号"), tier) or float(q.get("分值") or 0)

    with ui.card().classes("softcard w-full p-3 gap-2 shadow-none"):
        with ui.row().classes("items-center gap-2"):
            ui.label(f'第 {q["题号"]} 题 · {q.get("题型")}').classes("font-semibold")
            ui.label(f'{q.get("分值", 10)} 分').classes("text-xs text-gray-500")
            ui.label("主观题 · 不自动判分").classes("text-xs") \
                .style("color:#B45309")

        # 题目要求 / 篇章
        if q.get("材料"):
            with ui.expansion("材料 / 题目", value=True).classes("w-full"):
                ui.label(q["材料"]).classes(
                    "text-[15px] leading-7 whitespace-pre-wrap") \
                    .style("font-family:Georgia,'Times New Roman',serif")
        if q.get("题干"):
            ui.label(q["题干"]).classes("text-[15px] leading-6 whitespace-pre-wrap")

        ans = ui.textarea(
            label=("你的译文" if task == "TRANSLATION" else "你的作文")).props(
            "outlined autogrow").classes("w-full")
        ans.style("font-size:15px")

        out_box = ui.column().classes("w-full gap-1")
        with ui.row().classes("items-center gap-2"):
            btn = ui.button("提交并请 AI 评阅", on_click=lambda: run())

        # 【参考材料要**一开始就能看**，不能只在评阅后出现】
        # 学生做题时需要对照参考译文/范文，而不是评阅完才给。
        # 我第一版把它放在评阅结果里，实测页面上根本看不到。
        if ref.get("_参考译文"):
            with ui.expansion("参考译文（机构整理，仅供参考）") \
                    .classes("w-full"):
                ui.label(ref["_参考译文"]).classes(
                    "t-sm whitespace-pre-wrap").style("line-height:1.9")
        if ref.get("参考范文"):
            _word = ref.get("词数")
            _title = (f'参考范文（{_word} 词 · 机构整理，非官方标准答案）'
                      if _word else "参考范文（机构整理，非官方标准答案）")
            with ui.expansion(_title).classes("w-full"):
                ui.label(ref["参考范文"]).classes(
                    "t-sm whitespace-pre-wrap").style(
                    "line-height:1.9;"
                    "font-family:Georgia,'Times New Roman',serif")

        def show_rubric():
            """官方评分标准 —— 必须露出，学生才知道真实尺度。"""
            with ui.expansion("官方评分标准", value=False).classes("w-full"):
                ui.label(rb["名称"]).classes("t-sm font-semibold")
                for name, score, desc in rb["档次"]:
                    ui.label(f'{name}（{score} 分）：{desc}').classes("t-sm")

        def run():
            text = (ans.value or "").strip()
            if len(text) < 15:
                ui.notify("作答太短 —— 至少写一两句再提交。", color="warning")
                return
            out_box.clear()
            with out_box:
                ui.label("AI 评阅中…（约 10–20 秒）").classes("t-sm muted")
            btn.set_enabled(False)
            ui.timer(0.1, lambda: _do(text), once=True)

        def _do(text):
            try:
                r = aig.grade(task, tier, q.get("题干") or "", text,
                              reference=(ref.get("_参考译文") or ""))
            except Exception as e:                          # noqa: BLE001
                r = {"error": f"{type(e).__name__}: {str(e)[:80]}"}

            # 【落库】用户要求"AI 评分可以加入总分"，那就必须存下来。
            # 不存的话刷新就没了：既算不进成绩单，也看不到上次写成什么样。
            if not r.get("error"):
                try:
                    import hashlib
                    import json as _json
                    sig = hashlib.sha256(
                        (text + (ref.get("_参考译文") or "")).encode(
                            "utf-8")).hexdigest()[:16]
                    band_score = _band_to_score(r.get("档次"), score_max, rb)
                    store.save_ai_grade(
                        user, qid, task, r.get("档次"), r.get("位置"),
                        band_score, float(q.get("分值") or score_max),
                        _json.dumps(r, ensure_ascii=False), sig)
                except Exception:                       # noqa: BLE001
                    pass      # 落库失败不影响本次展示
            out_box.clear()
            with out_box:
                if r.get("error"):
                    ui.label(f'评阅失败：{r["error"]}').classes("t-sm") \
                        .style("color:#8C2C2C")
                else:
                    # 【红线】明确标注这是参考、不是官方得分
                    ui.label(f'AI 评阅（{r.get("来源", "参考，非官方得分")}）') \
                        .classes("t-sm font-semibold mt-1") \
                        .style("color:#B45309")
                    with ui.row().classes("items-center gap-3"):
                        ui.label(f'档次：{r.get("档次") or "—"}').classes("t-body font-semibold")
                        if r.get("位置"):
                            ui.label(r["位置"]).classes("t-sm muted")
                    if r.get("问题"):
                        ui.label("主要问题").classes("t-sm font-semibold mt-1")
                        for i, p in enumerate(r["问题"], 1):
                            ui.label(f'{i}. {p}').classes(
                                "t-sm whitespace-pre-wrap").style("line-height:1.8")
                    if r.get("建议"):
                        ui.label(f'建议：{r["建议"]}').classes("t-sm mt-1") \
                            .style("color:#17418F")
                show_rubric()
            btn.set_enabled(True)

        show_rubric()
        # 注意：ui.label **不解析 Markdown**（写 **粗体** 会原样显示星号）
        ui.label("说明：AI 评阅用于自查，不是官方得分 —— "
                 "考研翻译/写作是人工分档给分，同一篇不同阅卷人也可能差一档。") \
            .classes("t-xs muted")


def questions_only(passage, year, tier, done, user):
    """只渲染小题（两栏布局的右栏用）。"""
    for q in passage.get("小题") or []:
        _sub_question(q, year, tier, done, user)


def two_col(passage, year, tier, done, user, left=None):
    """
    **两栏布局**：左文章 / 右题目。

    用户要求（原话）："英语我看了一下不太符合人做题的习惯，因为一个文章或者
    完形文章直接占了一页，我去看问题还要回到文章继续阅读那就要一直上下翻页
    很麻烦。我觉得可以分成两侧吧，左侧放文章右侧放问题这样观看以及做题的感觉
    要好很多。"

    所以：
      · 左栏放材料（阅读文章 / 新题型的句子库 + 材料）
      · 右栏放小题（各自独立提交、判分、显示解析）
      · 左栏 sticky —— 右栏往下滚时文章留在视野内，不用来回翻

    CLOZE 不走这里：它的题目就是文章里的空，两边必须在一起（见 cloze_card）。
    """
    mat = (passage.get("材料") or "").strip()
    subs = passage.get("小题") or []
    name = passage.get("部分名") or passage.get("部分") or ""

    with ui.element("div").classes("w-full").style(
            "display:grid;grid-template-columns:minmax(0,45fr) minmax(0,55fr);"
            "gap:16px;align-items:start"):
        # 左栏：材料（sticky，跟随滚动）
        with ui.card().classes("softcard p-3 gap-2 shadow-none") \
                .style("position:sticky;top:12px;"
                       "max-height:calc(100vh - 90px);overflow:auto"):
            with ui.row().classes("items-center gap-2"):
                ui.label(name).classes("t-lead font-bold")
                ui.label(f'{len(subs)} 题').classes("t-xs muted")
                ui.label("左文章 · 右题目").classes("t-xs muted ml-auto")
            if mat:
                ui.label(mat).classes(
                    "text-[15px] leading-7 whitespace-pre-wrap") \
                    .style("font-family:Georgia,'Times New Roman',serif")
            else:
                ui.label("（这一篇没有材料）").classes("t-sm muted")

        # 右栏：小题
        with ui.column().classes("w-full gap-2 min-w-0"):
            for q in subs:
                _sub_question(q, year, tier, done, user)


# ---------------------------------------------------------------------------
# 英语答题卡（与 408/政治的分页式不同）
# ---------------------------------------------------------------------------
def answer_sheet_en(tier, year, done, total=45):
    """
    英语答题卡：**一行 45 格**，点格子滚动到对应题目。

    为什么与 `app._answer_sheet` 不共用：
      · 那个是**分页式**的（408/政治真题页每页 10 题，点格子翻页）
      · 英语是**一页长滚动**（完形+阅读+新题型+主观题连排），无"页"可翻
    所以这里点格子用 `scrollIntoView` 跳到题目锚点 `[data-q=N]`。

    颜色：绿=答对、红=答错、灰白=未做。
    """
    obj = []
    for ps in (en.paper(tier, year) or {}).get("篇目", []):
        if ps.get("部分") in ("TRANS", "WRITE"):
            continue
        obj.extend(ps.get("小题") or [])
    obj.sort(key=lambda q: int(q["题号"]))

    def status(q):
        r = done.get(q["id"])
        if not r:
            return "todo"
        return "ok" if r.get("is_correct") else "bad"

    n_ok = sum(1 for q in obj if status(q) == "ok")
    n_bad = sum(1 for q in obj if status(q) == "bad")
    n_todo = len(obj) - n_ok - n_bad

    with ui.card().classes("softcard w-full p-2 gap-1"):
        with ui.row().classes("items-center gap-3 flex-wrap w-full"):
            ui.label("答题卡").classes("t-sm font-semibold muted")
            ui.label(f'对 {n_ok} · 错 {n_bad} · 未做 {n_todo}').classes("t-xs muted")
            with ui.element("div").classes("flex flex-wrap gap-1 flex-1"):
                for q in obj:
                    st = status(q)
                    bg = {"ok": "#E8F5E9", "bad": "#FDECEA",
                          "todo": "#FFFFFF"}[st]
                    bd = {"ok": "#8BC79B", "bad": "#E3A8A8",
                          "todo": "#D5DBE3"}[st]
                    cell = ui.label(str(q["题号"])).classes(
                        "text-center cursor-pointer rounded")
                    cell.style(f"min-width:2rem;padding:1px 4px;font-size:13px;"
                               f"background:{bg};border:1px solid {bd}")
                    cell.on("click", lambda _=None, n=q["题号"]: ui.run_javascript(
                        f'''(() => {{
                            const el = document.querySelector('[data-q="{n}"]');
                            if (el) el.scrollIntoView({{behavior:'smooth', block:'center'}});
                        }})()'''))


# ---------------------------------------------------------------------------
# 交卷成绩单
# ---------------------------------------------------------------------------
def score_report(tier, year, user):
    """
    交卷成绩单。

    **口径（用户明确认可）**：
      · 没做完 → **不给总分**，只给「已作答部分得分 + 正确率」
      · 做完了 → 给总分
      · AI 评阅的分**计入总分**（用户要求更直观），
        但必须把「客观题得分」和「AI 评阅得分」**分开列** ——
        混成一个数就分不清哪部分是机器判的

    为什么没做完不给总分：只做完形（0.5 分/题、较易）和只做阅读（2 分/题、
    较难）的折算分完全不可比，给一个"38/100"会误导成"你只有 38 分水平"。
    """
    done = store.get_answers(user)
    grades = store.get_ai_grades(user)
    r = en.report(tier, year, done, grades)
    tn = en.TIERS[tier]["简称"]

    with ui.card().classes("softcard w-full p-4 gap-2"):
        with ui.row().classes("items-center gap-3 flex-wrap"):
            ui.label(f"{year} 年{tn} · 成绩单").classes("t-lead font-bold")
            if not r["complete"]:
                ui.label("未完成").classes("t-xs font-semibold") \
                    .style("color:#B45309;background:#FFF3E0;"
                           "padding:1px 8px;border-radius:10px")

        # ---- 完成度 ----
        pct = round(r["done"] / r["total"] * 100) if r["total"] else 0
        ui.label(f'已作答 {r["done"]}/{r["total"]} 题（{pct}%）') \
            .classes("t-sm sub")

        # ---- 客观题 ----
        ui.label("客观题（自动判分）").classes("t-sm font-semibold mt-1")
        ui.label(f'已作答 {r["obj_done"]}/{r["obj_total"]} 题 · '
                 f'答对 {sum(p["答对"] for p in r["parts"] if not p["主观"])} 题 · '
                 f'已作答部分得分 {r["obj_score"]:g} / {r["obj_max"]:g}') \
            .classes("t-sm")
        for p in r["parts"]:
            if p["主观"]:
                continue
            if p["已作答"] == 0:
                ui.label(f'　{p["名称"]}　未作答').classes("t-xs muted")
            else:
                ui.label(f'　{p["名称"]}　{p["已作答"]}/{p["题数"]} 题 · '
                         f'答对 {p["答对"]} · {p["得分"]:g}/{p["满分"]:g} 分') \
                    .classes("t-xs")

        # ---- 主观题 ----
        ui.label("主观题（AI 评阅 · 参考，非官方得分）") \
            .classes("t-sm font-semibold mt-2").style("color:#B45309")
        if not any(x.get("band") for x in r["sub_list"]):
            ui.label("　还没有 AI 评阅 —— 在下面翻译/写作题里提交作答即可").classes("t-xs muted")
        for x in r["sub_list"]:
            if x.get("band"):
                ui.label(f'　第 {x["题号"]} 题（{x.get("题型") or ""}）　'
                         f'{x["band"]} {x.get("position") or ""} · '
                         f'{x["score"]:g}/{x["score_max"]:g} 分').classes("t-xs")
            else:
                ui.label(f'　第 {x["题号"]} 题（{x.get("题型") or ""}）　未评阅') \
                    .classes("t-xs muted")

        # ---- 总分 ----
        ui.separator()
        if r["complete"]:
            ui.label(f'总分 {r["total_score"]:g} / {r["total_max"]:g}').classes(
                "text-2xl font-bold")
            ui.label(f'　客观题 {r["obj_score"]:g} + AI 评阅 {r["sub_total"]:g}') \
                .classes("t-xs muted")
            ui.label("说明：主观题分数由 AI 按官方评分标准评定，仅供参考 —— "
                     "真实考试是人工分档给分。").classes("t-xs muted")
        else:
            ui.label("未完成，不显示总分").classes("t-lead font-bold") \
                .style("color:#B45309")
            ui.label(
                f'还有 {r["total"] - r["done"]} 题没做 —— 只做完形和只做阅读的'
                f'折算分完全不可比，报一个总分反而误导。').classes("t-sm sub")
            ui.label(
                f'你可以参考：已作答部分得分 {r["obj_score"]:g} / {r["obj_max"]:g}（客观题）'
                + (f' + AI 评阅 {r["sub_total"]:g} 分' if r["sub_total"] else "")
            ).classes("t-sm")


# ---------------------------------------------------------------------------
# 新题型 Part B：句子库只显示一次
# ---------------------------------------------------------------------------
def partb_block(passage, year, tier, done, user):
    """
    新题型：**左材料+句子库（只显示一次）/ 右 41–45 作答位**。

    为什么不用 `two_col`：Part B 的 5 道题**共用同一个 A–G 句子库**。
    直接用 `_sub_question` 会把 7 个选项在每道题里各铺一遍 =
    5 × 7 = 35 行，页面极长且重复。用户要求"选项去重"。

    做法：
      · 左栏：材料（正文/评论）+ **句子库 A–G 列一次**
      · 右栏：41–45 各一行**字母选择器**（A–G 小按钮），提交后显示对错与解析
    """
    subs = sorted(passage.get("小题") or [], key=lambda q: int(q["题号"]))
    mat = (passage.get("材料") or "").strip()
    # 句子库：所有小题的选项应该相同（同一个 A–G 池）
    bank = (subs[0].get("选项") or {}) if subs else {}

    with ui.element("div").classes("w-full").style(
            "display:grid;grid-template-columns:minmax(0,46fr) minmax(0,54fr);"
            "gap:16px;align-items:start"):
        # ---- 左栏：材料 + 句子库 ----
        with ui.card().classes("softcard p-3 gap-2 shadow-none") \
                .style("position:sticky;top:12px;"
                       "max-height:calc(100vh - 90px);overflow:auto"):
            with ui.row().classes("items-center gap-2"):
                ui.label("新题型").classes("t-lead font-bold")
                ui.label(f'{len(subs)} 题').classes("t-xs muted")
                ui.label("左材料 · 右作答").classes("t-xs muted ml-auto")
            if mat:
                ui.label(mat).classes(
                    "text-[15px] leading-7 whitespace-pre-wrap") \
                    .style("font-family:Georgia,'Times New Roman',serif")
            if bank:
                ui.label("备选句（A–G）").classes("t-sm font-semibold mt-2")
                for L, T in sorted(bank.items()):
                    with ui.row().classes("items-start gap-2 w-full"):
                        ui.label(L).classes(
                            "font-semibold shrink-0 w-5 text-center rounded") \
                            .style("background:#EEF3FA;color:#17418F")
                        ui.label(T).classes(
                            "text-[15px] flex-1 whitespace-pre-wrap") \
                            .style("line-height:1.75")

        # ---- 右栏：41–45 字母选择 ----
        right = ui.column().classes("w-full gap-2 min-w-0")
        with right:
            for q in subs:
                _partb_row(q, year, tier, done, user)


def _partb_row(q, year, tier, done, user):
    """
    一道 Part B 题：**只给 A–G 字母按钮**，不再重复句子文本。

    句子文本已经在左栏列过一次，这里只选字母 —— 与真实卷面一致
    （卷面上 41–45 就是填字母）。
    """
    qid = q["id"]
    ans = answer_of(q, tier, year)
    prev = done.get(qid)
    chosen = {"v": (prev or {}).get("chosen") or ""}
    locked = {"v": bool(prev)}
    letters = sorted((q.get("选项") or {}).keys()) or list("ABCDEFG")

    with ui.card().classes("softcard w-full p-2 gap-1 shadow-none"):
        with ui.row().classes("items-center gap-2 flex-wrap"):
            ui.label(f'第 {q["题号"]} 题').classes("font-semibold")
            ui.label(f'{q.get("题号")} → ').classes("t-xs muted")
            if not ans:
                ui.label("暂无答案").classes("t-xs").style("color:#B45309")
        row = ui.row().classes("items-center gap-1 flex-wrap")
        with row:
            for L in letters:
                btn = ui.button(L, on_click=lambda _=None, L=L: pick(L)) \
                    .props("flat dense")
                btn.style("min-width:2.1rem")

        result = ui.label("").classes("t-sm")
        exp_box = ui.column().classes("w-full gap-0")

        def paint():
            for child in row.default_slot.children:
                pass
            # 重画按钮状态
            row.clear()
            with row:
                for L in letters:
                    on = (chosen["v"] == L)
                    b = ui.button(L, on_click=lambda _=None, L=L: pick(L))
                    b.props("unelevated" if on else "flat dense")
                    b.style("min-width:2.1rem")
                    if locked["v"] and ans:
                        if L == ans:
                            b.style("background:#E8F5E9")
                        elif on and L != ans:
                            b.style("background:#FDECEA")

        def pick(L):
            if locked["v"]:
                return
            chosen["v"] = L
            paint()

        def submit():
            if not chosen["v"]:
                ui.notify("请先选一个字母。", color="warning")
                return
            if not ans:
                ui.notify("这道题暂无答案，无法判分。", color="warning")
                return
            ok = (chosen["v"] == ans)
            store.record_answer(user, qid, chosen["v"], ok, source="exam")
            locked["v"] = True
            paint()
            submit_btn.set_enabled(False)
            result.set_text(("答对了 ✓" if ok else f'答错了 ✗ 你选 {chosen["v"]}')
                            + f'　正确答案 {ans}')
            result.style(f'color:{"#1B5E36" if ok else "#8C2C2C"}')
            show_exp()

        submit_btn = ui.button("提交", on_click=submit).props("dense")
        submit_btn.set_enabled(not prev)

        def show_exp():
            exp_box.clear()
            e = en.explanation(tier, year, q["题号"]) or {}
            if e.get("解析"):
                with exp_box:
                    ui.label("解析（懒笔记）：").classes("t-xs") \
                        .style("color:#B45309")
                    ui.label(e["解析"][:1200]).classes(
                        "t-xs whitespace-pre-wrap").style("line-height:1.8")

        paint()
        if prev:
            if ans:
                result.set_text(f'已作答：{prev["chosen"]}　正确答案 {ans}')
                result.style(f'color:{"#1B5E36" if prev.get("is_correct") else "#8C2C2C"}')
            show_exp()
