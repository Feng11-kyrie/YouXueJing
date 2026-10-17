#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数学真题的题目卡片（选择 / 填空 / 解答）。

三种题型的能力**不一样**，界面上要如实区分：

    选择题  点选项 → 立即判对错、给答案与解析（可自动判分）
    填空题  输入答案 → 先做符号归一化比对；对不上时给出参考答案，
            让用户自己判"我写对了 / 写错了"（LaTeX 答案没法 100% 自动比对）
    解答题  手写题：看解析 + 自评得分；另有「免费评分」（结构体检）
            和「AI 精评」（用户自带 Key）

公式渲染见 yj/mathrender.py（服务端转 MathML，不依赖 JS/CDN）。
"""
import json
import re

from nicegui import ui

from yj import ai_grade as aig
from yj import llm
from yj import math as math_data
from yj import mathrender as mr
from yj import math_checker as mc
from proto import llm_key
from proto import store_lite as store


def q_id(tier, year, q):
    return f"MATH-{tier}-{year}-{q['题号']}"


# ---------------------------------------------------------------- 填空比对
_LATEX_MAP = [
    (r"\\frac\s*\{([^{}]+)\}\s*\{([^{}]+)\}", r"(\1)/(\2)"),
    (r"\\sqrt\s*\{([^{}]+)\}", r"sqrt(\1)"),
    (r"\\pi", "pi"), (r"\\ln", "ln"), (r"\\log", "log"),
    (r"\\sin", "sin"), (r"\\cos", "cos"), (r"\\tan", "tan"),
    (r"\\le", "<="), (r"\\ge", ">="), (r"\\ne", "!="),
    (r"\\times", "*"), (r"\\cdot", "*"), (r"\\pm", "+-"),
    (r"\\infty", "oo"), (r"\\alpha", "alpha"), (r"\\beta", "beta"),
    (r"\\lambda", "lambda"), (r"\\mu", "mu"), (r"\\sigma", "sigma"),
    (r"\\theta", "theta"), (r"\\rho", "rho"), (r"\\varphi", "phi"),
    (r"\\mathrm\s*\{([^{}]+)\}", r"\1"), (r"\\text\s*\{([^{}]+)\}", r"\1"),
    (r"\\left", ""), (r"\\right", ""), (r"\\,", ""), (r"\\;", ""),
    (r"\\!", ""), (r"\\ ", ""), (r"\\_", "_"),
]


def norm_answer(s):
    """把学生输入/参考答案都压成可比的字符串。

    只处理**常见的 LaTeX 写法**（分数、根号、希腊字母、比较符）；
    压完仍可能对不上 —— 所以界面上永远保留"手工判定"这条路。
    """
    s = str(s or "").strip()
    s = s.replace("$", "").replace("\\$", "")
    for a, b in _LATEX_MAP:
        s = re.sub(a, b, s)
    s = s.replace("（", "(").replace("）", ")").replace("，", ",")
    s = s.replace("＋", "+").replace("－", "-").replace("＝", "=")
    s = re.sub(r"\s+", "", s)
    s = s.strip("。.;；,")
    return s.lower()


def _same_answer(user, ref):
    a, b = norm_answer(user), norm_answer(ref)
    if not a or not b:
        return False
    if a == b:
        return True
    # 括号差异：参考答案的 \frac{1}{2} 会转成 (1)/(2)，学生通常写 1/2
    if a.replace("(", "").replace(")", "") == b.replace("(", "").replace(")", ""):
        return True
    # 参考结果是"f(1)=...=2"这种整式时，比对最后一个等号右边的值
    if "=" in b:
        tail = b.rsplit("=", 1)[1].strip(".,;。")
        if a == tail:
            return True
    return False


# ---------------------------------------------------------------- 卡片
def math_card(q, tier, year, done, user):
    qid = q_id(tier, year, q)
    rec = done.get(qid)
    full = math_data.q_score(q, year)
    kind = q.get("题型")

    card = ui.card().classes("softcard w-full p-3 gap-2")
    card.props(f'data-mq="{q["题号"]}"')

    with card:
        with ui.row().classes("items-center gap-2 no-wrap"):
            ui.label(f'第 {q["题号"]} 题').classes("t-lead font-semibold")
            ui.label(f'{kind} · {full} 分').classes("t-xs muted")
            if rec:
                if rec.get("source") == "selfscore":
                    ui.label("已自评").classes("t-xs").style("color:#17418F")
                else:
                    ui.label("已作答").classes("t-xs").style(
                        "color:#1B5E36" if rec["is_correct"] else "color:#8C2C2C")

        stem = q.get("题干") or ""
        if stem and "题干见下方原题图" not in stem:
            ui.html(mr.to_html(stem)).classes("w-full math")
        if q.get("图片"):
            # 题源文档缺题干/选项时，用真题墙的原题图兜底（公式不会丢）
            ui.image(f'data/{q["图片"]}').classes("rounded-lg w-full") \
                .style("max-width:52rem")

        out = ui.column().classes("w-full gap-1")

        if kind == "单项选择题":
            opts = q.get("选项") or {}
            if not opts and q.get("答案"):
                # 选项在图片里：只给 A–D 四个按钮，不再重复选项文字
                opts = {L: "" for L in "ABCD"}
            chosen = {"v": None}
            boxes = {}

            def pick(letter):
                if rec:
                    return
                chosen["v"] = letter
                for L, box in boxes.items():
                    box.classes(add="opt sel" if L == letter else None,
                                remove="opt sel" if L != letter else None)
                grade()

            def grade():
                if not chosen["v"]:
                    return
                ok = chosen["v"] == (q.get("答案") or "")
                store.record_answer(user, qid, chosen["v"], ok, source="practice")
                for L, box in boxes.items():
                    if L == q.get("答案"):
                        box.classes(add="opt right")
                    elif L == chosen["v"]:
                        box.classes(add="opt wrong")
                show_result(chosen["v"], q.get("答案"), ok)

            with ui.column().classes("w-full gap-1"):
                for L in sorted(opts):
                    box = ui.element("div").classes("opt w-full rounded-lg p-2")
                    box.on("click", lambda _=None, x=L: pick(x))
                    boxes[L] = box
                    with box:
                        with ui.row().classes("items-start gap-2 no-wrap"):
                            ui.label(f"{L}").classes("t-sm font-semibold shrink-0") \
                                .style("width:1.1rem")
                            ui.html(mr.to_html(opts[L])).classes("math flex-1")

            def show_result(user_ans, right, ok):
                out.clear()
                with out:
                    ui.label(("✓ 回答正确" if ok else f"✗ 回答错误，正确答案 {right}"))
                    ui.html(mr.to_html(q.get("解析") or "")).classes("math t-sm")

        elif kind == "填空题":
            ref = q.get("答案") or ""

            def submit():
                val = (inp.value or "").strip()
                if not val:
                    ui.notify("先填写答案", color="warning")
                    return
                ok = _same_answer(val, ref)
                store.record_answer(user, qid, val, ok, source="practice")
                show_fill(val, ok)

            def self_judge(ok):
                store.record_answer(user, qid, (inp.value or "").strip() or "（手判）",
                                    ok, source="practice")
                show_fill(inp.value or "", ok, decided=True)

            def show_fill(val, ok, decided=False):
                out.clear()
                with out:
                    with ui.row().classes("items-center gap-2 flex-wrap"):
                        ui.label("参考答案：").classes("t-sm font-semibold")
                        ui.html(mr.to_html(ref)).classes("math t-sm")
                    if not decided:
                        ui.label("系统比对结果：" + ("一致" if ok else "不一致"))
                    ui.label("如果系统没认出来（公式写法不同），可以自己判：") \
                        .classes("t-xs muted")
                    with ui.row().classes("gap-2"):
                        ui.button("我写对了", on_click=lambda: self_judge(True)) \
                            .props("outline dense")
                        ui.button("写错了", on_click=lambda: self_judge(False)) \
                            .props("flat dense")
                    ui.html(mr.to_html(q.get("解析") or "")).classes("math t-sm")

            with ui.row().classes("items-center gap-2 w-full no-wrap"):
                inp = ui.input(placeholder="填写答案（可用 1/2、sqrt(2)、pi 等写法）") \
                    .props("outlined dense").classes("flex-1")
                ui.button("提交", on_click=submit).props("unelevated dense")

        else:  # 解答题
            ui.label("解答题：在纸上作答，再对照解析自评；也可以把要点录进来让系统体检。") \
                .classes("t-xs muted")
            ans = ui.textarea(placeholder="可把手写答案的要点照录进来（用于免费评分 / AI 精评）") \
                .props("outlined autogrow").classes("w-full")
            holder = ui.column().classes("w-full gap-1")
            score_holder = ui.column().classes("w-full gap-1")
            show = {"v": False}

            def toggle():
                show["v"] = not show["v"]
                btn.set_text("收起解析" if show["v"] else "查看解析")
                render()

            def render():
                holder.clear()
                if not show["v"]:
                    return
                with holder:
                    ui.label("参考解析").classes("t-sm font-semibold") \
                        .style("color:var(--accent)")
                    ui.html(mr.to_html(q.get("解析") or "")).classes("math t-sm")

            btn = ui.button("查看解析", on_click=toggle).props("unelevated dense")

            prev_self = None
            if rec and str(rec.get("chosen", "")).startswith("score:"):
                try:
                    prev_self = float(str(rec["chosen"]).split(":", 1)[1])
                except ValueError:
                    prev_self = None
            with ui.row().classes("items-center gap-2 flex-wrap"):
                sc = ui.input(placeholder=f"自评得分（0–{full}）",
                              value=(f"{prev_self:g}" if prev_self is not None else "")) \
                    .props("dense outlined").classes("w-40")

                def save_self():
                    ok, msg = store.set_selfscore(user, qid, sc.value, full)
                    if ok:
                        ui.notify("已保存自评得分", color="positive")
                    else:
                        ui.notify(msg or "保存失败", color="warning")

                ui.button("保存自评", on_click=save_self).props("outline dense")

            with ui.row().classes("items-center gap-2 flex-wrap"):
                def free_score():
                    text = (ans.value or "").strip()
                    if len(text) < 10:
                        ui.notify("先把作答要点写进输入框再评分", color="warning")
                        return
                    r = mc.score_math(text, q.get("解析") or "",
                                      q.get("题干") or "", float(full))
                    r["依据"] = "结构体检"
                    render_score(score_holder, r, full)

                ui.button("免费评分", on_click=free_score).props("outline dense")
                # 不按"当前有没有 Key"禁用：Key 可以在页面打开后再接，
                # 点击时再检查并提示（禁用按钮会让人以为功能不存在）。
                ui.button("AI 精评",
                          on_click=lambda: run_ai(ans.value, score_holder, q, full, user, qid)) \
                    .props("outline dense")

        # 已有记录：直接把解析亮出来
        if rec:
            out.clear()
            with out:
                if kind == "解答题" and str(rec.get("chosen", "")).startswith("score:"):
                    ui.label(f'已自评 {str(rec["chosen"]).split(":", 1)[1]} 分'
                             f'（满分 {full:g}）') \
                        .classes("t-sm font-semibold").style("color:#17418F")
                if kind == "单项选择题":
                    ok = rec["chosen"] == (q.get("答案") or "")
                    ui.label(("✓ 你上次选 " + rec["chosen"]) if ok
                             else f'✗ 你上次选 {rec["chosen"]}，正确答案 {q.get("答案")}')
                elif kind == "填空题":
                    ui.label(f'你上次填：{rec["chosen"]}').classes("t-sm")
                    with ui.row().classes("items-center gap-2"):
                        ui.label("参考答案：").classes("t-sm font-semibold")
                        ui.html(mr.to_html(q.get("答案") or "")).classes("math t-sm")
                ui.html(mr.to_html(q.get("解析") or "")).classes("math t-sm")


def render_score(box, r, full):
    box.clear()
    with box:
        ui.label(f'免费评分 · 结构体检　{r.get("分数")} / {full:g}') \
            .classes("t-lead font-bold").style("color:#17418F")
        ui.label(r.get("来源", "")).classes("t-xs").style("color:#6B7280")
        for it in r.get("分项") or []:
            ui.label(f'　{it["项"]}：{it["得分"]} / {it["满分"]} —— {it["说明"]}') \
                .classes("t-sm")
        for i, p in enumerate(r.get("问题") or [], 1):
            ui.label(f"{i}. {p}").classes("t-sm")


def run_ai(answer, holder, q, full, user, qid):
    """解答题的 AI 精评（用户自带 Key）。"""
    k = llm_key.get()
    if not k.get("key"):
        ui.notify("先在顶部接入自己的 API Key", color="warning")
        return
    text = (answer or "").strip()
    if len(text) < 10:
        ui.notify("先把作答要点写进输入框", color="warning")
        return
    prompt = f"""你是考研数学阅卷老师。请按步骤给下面这道解答题打分（满分 {full} 分）。

【题目】{q.get('题干')}
【参考答案与解析】{(q.get('解析') or '')[:3000]}
【学生作答】{text}

要求：
1. 先判断关键步骤是否做到（列出得分点），再给总分；
2. 总分不得超过 {full}；
3. 最后一行严格输出：得分：X
4. 用中文，简洁。"""
    r = llm.complete("math_grade", prompt, use_cache=False,
                     api_key=k["key"], base_url=k["base"] or None,
                     model=k["model"] or None)
    txt = r.get("text") or ""
    m = re.search(r"得分[:：]\s*([0-9.]+)", txt)
    score = float(m.group(1)) if m else None
    holder.clear()
    with holder:
        ui.label("AI 精评（参考，非官方得分）").classes("t-lead font-bold") \
            .style("color:#B45309")
        ui.html(mr.to_html(txt)).classes("math t-sm")
    try:
        store.save_ai_grade(user, qid, "MATH", "", "", score, float(full),
                            json.dumps({"文本": txt}, ensure_ascii=False), "ai")
    except Exception:                                       # noqa: BLE001
        pass
