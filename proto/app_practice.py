#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
优学鲸 · NiceGUI 原型（第二页：挑考点练习）

这是五页里**最复杂**的一页，用它来验证"整站迁移到底要多少工作量"：
    选书（4 张卡）→ 选章（可点击整行）→ 勾考点（跨章保留）→ 就地出题 → 判分

跑法：
    .venv/bin/python proto/app_practice.py --port 8898

状态怎么存（和 Streamlit 版的关键差别）
--------------------------------------
Streamlit 版把"选了哪门课、哪一章"存在 st.session_state 里 —— 那是**会话级**的，
一刷新就没了，也没法分享链接。
这里全部走 URL：?subject=DS&chapter=DS-02&user=demo
  · 刷新不丢、可以直接分享"数据结构 › 线性表"这一页
  · 勾选的考点仍然落库（marks 表），因为那是**用户数据**而不是界面状态

"换章再回来勾选会保留"这条最容易被搬丢：勾选必须**立即写入 marks**，
而不是存在界面状态里等"提交"。
"""
import argparse
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from nicegui import ui                            # noqa: E402
from yj import data, diagnose                      # noqa: E402
from proto import store_lite as store              # noqa: E402
from proto.cards import question_card, SUBJECT_COLORS   # noqa: E402

ui.add_head_html("""
<style>
  body { font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif; }
  .bookcard { border: 1px solid #E3E8EF; transition: box-shadow .15s, transform .15s; }
  .bookcard:hover { box-shadow: 0 4px 14px rgba(15,23,42,.09); transform: translateY(-1px); }
  .chaprow { border: 1px solid transparent; transition: background .12s; cursor: pointer; }
  .chaprow:hover { background: #F3F6FB; border-color: #DCE3EC; }
  .leafrow { border: 1px solid transparent; transition: background .12s; cursor: pointer; }
  .leafrow:hover { background: #F3F6FB; }
  .leafrow.on { background: #E7F0FE; border-color: #2563EB; }
</style>
""", shared=True)

STEPS = ["选一门课", "挑薄弱知识点", "做真题"]


def _steps(active):
    with ui.row().classes("items-center gap-3 text-sm"):
        for i, name in enumerate(STEPS, 1):
            if i == active:
                ui.label(f"{i}. {name}").classes("font-semibold") \
                    .style("color:#17418F")
            elif i < active:
                ui.label(f"{i}. {name} ✓").classes("text-gray-400 line-through")
            else:
                ui.label(f"{i}. {name}").classes("text-gray-400")
            if i < len(STEPS):
                ui.label("→").classes("text-gray-300")


def _book_meta(code, user):
    chs = data.chapters()[code]
    leaves = [l for ch, _n in chs for l in data.chapter_leaves().get(ch, [])]
    freq, lqc = data.freq(), data.leaf_question_count()
    m = diagnose.mastery_by_subject(store.get_answers(user)).get(code)
    my_marks = store.get_marks(user)
    return {"code": code, "name": data.CODE2NAME[code], "章数": len(chs),
            "考点数": len(leaves),
            "考频": sum(freq.get(l, {}).get("考查总次数", 0) for l in leaves),
            "可练题": sum(lqc.get(l, 0) for l in leaves),
            "掌握度": m["掌握度"] if m else None,
            "已标记": len([l for l in leaves if l in my_marks])}


@ui.page("/")
def practice(subject: str = None, chapter: str = None,
             practice: int = 0, user: str = "demo"):
    store.ensure_user(user)
    marks = store.get_marks(user)

    def goto(**kw):
        cur = {"subject": subject, "chapter": chapter,
               "practice": practice, "user": user}
        cur.update(kw)
        q = {k: v for k, v in cur.items() if v not in (None, "", 0)}
        ui.navigate.to("/?" + "&".join(f"{k}={v}" for k, v in q.items()))

    with ui.row().classes("w-full items-center gap-4 px-6 py-3 "
                         "border-b border-gray-200 bg-white"):
        ui.label("挑考点练习").classes("text-xl font-bold")
        ui.label(f"已勾选 {len(marks)} 个薄弱考点") \
            .classes("text-sm ml-auto").style("color:#17418F")

    with ui.column().classes("w-full max-w-6xl mx-auto p-6 gap-4"):

        # ---------------------------------------------- 第一步：选书
        if not subject:
            _steps(1)
            ui.label("先选一门课，再从这门课里挑出你自己觉得薄弱的知识点，"
                     "系统就用这些考点给你出真题。不需要先做任何测试。") \
                .classes("text-[15px] leading-7")
            with ui.row().classes("w-full gap-4 items-stretch"):
                for code in ("DS", "CO", "OS", "CN"):
                    b = _book_meta(code, user)
                    with ui.card().classes("bookcard flex-1 p-4 gap-1 shadow-none"):
                        ui.label(b["name"]).classes("text-lg font-bold")
                        ui.label(f'{b["章数"]} 章 · {b["考点数"]} 个考点') \
                            .classes("text-sm text-gray-600")
                        ui.label(f'18 年考频 {b["考频"]} 次') \
                            .classes("text-sm text-gray-600")
                        ui.label(f'题库 {b["可练题"]} 题可练') \
                            .classes("text-sm text-gray-600")
                        if b["掌握度"] is not None:
                            ui.label(f'我的掌握度 {b["掌握度"]:.0%}') \
                                .classes("text-base font-semibold") \
                                .style("color:#17418F")
                        else:
                            ui.label("我的掌握度：未测") \
                                .classes("text-sm text-gray-400")
                        if b["已标记"]:
                            ui.label(f'★ 已标记 {b["已标记"]} 个薄弱考点') \
                                .classes("text-xs").style("color:#C2410C")
                        ui.button(f'进入{b["name"]}',
                                  on_click=lambda _=None, c=code:
                                  goto(subject=c, chapter=None)).props("unelevated") \
                            .classes("w-full mt-1")
            return

        # ---------------------------------------------- 第二步：选章
        _steps(2)
        bm = _book_meta(subject, user)
        with ui.row().classes("w-full items-center gap-3"):
            ui.label(bm["name"]).classes("text-lg font-bold")
            ui.button("← 换一门", on_click=lambda: goto(subject=None, chapter=None)) \
                .props("flat dense")
        ui.label(f'这门课有 {bm["章数"]} 章 —— 点章名直接进去挑知识点') \
            .classes("text-[15px]")
        chs = data.chapters()[subject]
        m_ch = diagnose.mastery_by_chapter(store.get_answers(user))
        cf = data.chapter_freq()
        cl = data.chapter_leaves()
        for ch, nm in chs:
            cm = m_ch.get(ch)
            n_mark = len([l for l in cl.get(ch, []) if l in marks])
            with ui.row().classes("chaprow w-full items-center gap-3 rounded-lg "
                                  "px-3 py-2") as row:
                ui.label(nm).classes("font-semibold w-40 shrink-0")
                ui.label(f'考频 {cf.get(ch, 0)} 次 · {len(cl.get(ch, []))} 个考点'
                         + (f' · ★ 已勾选 {n_mark}' if n_mark else "")) \
                    .classes("text-sm text-gray-500 flex-1")
                if cm:
                    ui.label(f'掌握度 {cm["掌握度"]:.0%}') \
                        .classes("text-sm font-semibold").style("color:#17418F")
                else:
                    ui.label("掌握度 未测").classes("text-sm text-gray-400")
            row.on("click", lambda _=None, c=ch: goto(chapter=c))

        # ---------------------------------------------- 第三步：勾考点
        if not chapter:
            ui.label("点上面任意一章，展开它的知识点列表。") \
                .classes("text-sm text-gray-500")
            return

        leaves = cl.get(chapter, [])
        ui.label(f'勾出「{data.node_name(chapter)}」里你觉得薄弱的知识点') \
            .classes("text-lg font-bold")
        # 注意：ui.label 是纯文本，写 **加粗** 只会原样显示星号（实测踩过）。
        # 要富文本得用 ui.markdown。这里用「」强调，简单可靠。
        ui.label("可以多选；「换章再回来勾选会保留」（勾选立即保存到账号）。"
                 "标签里的 频N 是它 18 年被考的次数，·M题 是题库里能拿它练的题数。") \
            .classes("text-sm text-gray-600")
        freq, lqc = data.freq(), data.leaf_question_count()
        with ui.row().classes("w-full gap-x-6 gap-y-0"):
            for i, l in enumerate(leaves):
                f = freq.get(l, {})
                n = lqc.get(l, 0)
                on = l in marks
                with ui.row().classes("leafrow items-center gap-2 rounded-lg "
                                      "px-2 py-1 min-w-[19rem]"
                                      + (" on" if on else "")) as row:
                    cb = ui.checkbox(value=on).props("dense")

                    def toggle(e, leaf=l):
                        cur = store.get_marks(user)
                        if e.value:
                            cur.add(leaf)
                        else:
                            cur.discard(leaf)
                        store.set_marks(user, cur)
                        ui.navigate.reload()

                    cb.on_value_change(toggle)
                    ui.label(f'{data.node_name(l)}　频{f.get("考查总次数", 0)}'
                             f'·{n}题').classes("text-[15px]")
                    if on:
                        ui.label("★").classes("text-xs") \
                            .style("color:#C2410C")
                row.on("click", lambda _=None, x=cb: x.set_value(not x.value))

        # ---------------------------------------------- 汇总 + 出题
        marks = store.get_marks(user)
        if not marks:
            ui.label("勾选考点后，这里会出现「开始练习」。") \
                .classes("text-sm text-gray-400 mt-2")
            return

        total_q = sum(lqc.get(l, 0) for l in marks)
        ui.separator()
        ui.label(f"你已勾选 {len(marks)} 个考点，题库里共 {total_q} 道真题可练") \
            .classes("text-lg font-bold")
        no_q = [l for l in marks if not lqc.get(l, 0)]
        if no_q:
            ui.label("其中 " + "、".join(data.node_name(l) for l in no_q)
                     + f" 共 {len(no_q)} 个考点暂无题目，只能用于生成讲义。") \
                .classes("text-sm text-amber-700")

        with ui.row().classes("gap-3 items-center"):
            ui.button("▶ 开始练习（抽 5 道）",
                      on_click=lambda: goto(practice=1)).props("unelevated")
            ui.button("清空选择",
                      on_click=lambda: (store.set_marks(user, set()),
                                        ui.navigate.reload())).props("flat")

        if not practice:
            return

        # ---------------------------------------------- 就地出题
        done = store.get_answers(user)
        pool = []
        for l in sorted(marks, key=lambda x: -lqc.get(x, 0)):
            for q in data.questions().values():
                if q["主考点"] == l and q["题型"] == "单项选择题" and q.get("答案"):
                    pool.append((l, q))
        pool.sort(key=lambda lq: (lq[1]["id"] in done,
                                  lq[1].get("难度") or 3, -lq[1]["year"]))
        ui.separator()
        if not pool:
            ui.label("你选的这些考点在题库里暂时没有对应的真题。"
                     "建议换几个标着「·N题」的考点。") \
                .classes("text-sm text-orange-700")
            return

        show = pool[:5]
        ui.label(f"练习：抽 {len(show)} 道（优先你没做过的、难度低的）") \
            .classes("text-lg font-bold")
        ui.label("提交后会立刻判分、把错题归因到考点，并更新掌握度与路径。") \
            .classes("text-sm text-gray-600")
        # 复用真题页的题卡组件（proto/cards.py，同一份代码 → 两页行为不会分叉）
        for l, q in show:
            question_card(q, q["year"], done, user)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8898)
    args = ap.parse_args()
    ui.run(port=args.port, title="优学鲸 · 挑考点练习（NiceGUI 原型）",
           reload=False, favicon="🐳", show=False)


if __name__ in {"__main__", "__mp_main__"}:
    main()
