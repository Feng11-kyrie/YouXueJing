#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
优学鲸 · 完整版（NiceGUI，6 页）—— 一版可直接用的应用

跑起来：
    .venv/bin/python proto/app.py --port 8890

这是把 Streamlit 版（app.py）整站搬到 NiceGUI 的成果，用于回答
"要不要换掉 Streamlit"。数据层完全复用 yj/（一行没改）。

六页（各自是真实 URL，可分享/刷新不丢）：
    /                       首页
    /exam?year=2025&page=2  408 历年真题
    /practice?subject=DS&chapter=DS-03   挑考点练习
    /diagnose               快速诊断（32 题）
    /profile                我的画像
    /paths                  学习路径
    /notes                  讲义生成（多智能体）

与 Streamlit 版的能力对应关系写在 README 段落里；本文件不删旧版，
两条路并存便于对照与回退。
"""
import argparse
import contextlib
import datetime
import os
import sys
from collections import Counter, defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from nicegui import ui                            # noqa: E402
from yj import data, diagnose, profile as profile_mod, path as path_mod  # noqa: E402
from yj import llm, graph                          # noqa: E402
from proto import store_lite as store              # noqa: E402
from proto.cards import question_card, SUBJECT_COLORS   # noqa: E402

PER = 10
NAV = [("/", "首页", "home"),
       ("/exam", "408 历年真题", "description"),
       ("/practice", "挑考点练习", "school"),
       ("/diagnose", "快速诊断", "monitor_heart"),
       ("/profile", "我的画像", "insights"),
       ("/paths", "学习路径", "route"),
       ("/notes", "讲义生成", "menu_book")]

ui.add_head_html("""
<style>
  /* ===== 设计变量：一处改，全局生效 =====
     之前的毛病是颜色到处硬编码（侧栏 #EEF1F5、按钮 #2563EB、说明 #8A6D3B…），
     结果"全是同一个半死不活的灰蓝、没有主次"。现在收敛成这几个 token：
       --ink   正文主色（深灰，不用纯黑）
       --sub   次要文字
       --mut   弱化/辅助
       --line  分割线
       --accent 唯一主色（只给"主要行动点"和选中态用，不滥用）
       --accent-weak 主色的浅底
       --warn  提醒（缺数据、未配置）
     规则：**一屏只允许一个主色按钮**，其余用描边/文字按钮 —— 视觉平权等于没有引导。 */
  :root {
    --ink:#1F2933; --sub:#5A6B80; --mut:#9AA5B1; --line:#E6EAF0;
    --accent:#2563EB; --accent-weak:#EAF1FE; --warn:#B45309;
    --bg-side:#F7F8FA;
  }
  body { font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;
         color:var(--ink); }
  a { color:inherit; }
  .qcard { border-left:4px solid var(--sc, var(--accent)); }
  .opt { transition:background .12s; cursor:pointer; border:1px solid var(--line); }
  .opt:hover { background:#F5F8FF; border-color:#B9CCF5; }
  .opt.sel { background:var(--accent-weak); border-color:var(--accent); }
  .opt.right { background:#E6F6EC; border-color:#7DCB9A; }
  .opt.wrong { background:#FDECEC; border-color:#E9A0A0; }
  .cell { width:26px; height:24px; line-height:24px; text-align:center;
          font-size:11px; border-radius:5px; border:1px solid #D7DEE8;
          background:#fff; color:#46586D; cursor:pointer; }
  .cell.ok { background:#E6F6EC; border-color:#7DCB9A; color:#1B5E36; }
  .cell.bad { background:#FDECEC; border-color:#E9A0A0; color:#8C2C2C; }
  .cell.cur { outline:2px solid var(--accent); outline-offset:1px; font-weight:700; }
  /* 卡片：不再用"细灰框+白底"（像 Excel 导出的表格），改成无边框+浅底+悬停浮起 */
  .softcard { background:#fff; border:1px solid var(--line); border-radius:12px;
              transition:box-shadow .16s, transform .16s, border-color .16s; }
  .softcard:hover { box-shadow:0 6px 20px rgba(15,23,42,.08);
                    transform:translateY(-2px); border-color:#D3DCE8; }
  /* 侧栏导航：整行可点 + 选中态明确 */
  .navlink { display:flex; align-items:center; gap:10px; width:100%;
             border-radius:8px; padding:7px 10px; cursor:pointer; text-decoration:none; }
  .navlink:hover { background:#EDF1F7; }
  .navlink.on { background:var(--accent-weak); color:#17418F; font-weight:650;
                box-shadow:inset 3px 0 0 var(--accent); }
  .navlink .ic { font-size:18px; opacity:.75; }
  .kpi { font-size:26px; font-weight:700; line-height:1.1; }
  .muted { color:var(--mut); }
  .sub { color:var(--sub); }
</style>
""", shared=True)


# ================================================================ 公共外壳
@contextlib.contextmanager
def shell(active: str, user: str):
    """
    左侧导航 + 顶栏的公共外壳。

    为什么要抽出来：六页都需要同样的导航，如果每页各写一遍，
    加一个新页面要改六处（Streamlit 版就是这样：PAGES 列表 + 六段 if/elif）。

    【框架差异，实测踩到】这里必须加 @contextlib.contextmanager。
    Streamlit 的 st.container() 本身就能直接 `with`；而 NiceGUI 里我自己写的
    生成器函数不能直接 `with` —— 报 "generator object does not support the
    context manager protocol"，**六个页面全部 500**。
    这是迁移时真实会遇到的坑：换个框架，"能 with 的东西"的规则变了。
    """
    answers = store.get_answers(user)
    marks = store.get_marks(user)
    with ui.row().classes("w-full no-wrap items-start"):
        # 侧栏
        with ui.column().classes("w-52 shrink-0 p-3 gap-1 min-h-screen "
                                "border-r").style("background:var(--bg-side);"
                                                  "border-color:var(--line)"):
            with ui.row().classes("items-center gap-2 mb-3"):
                ui.label("408").classes("w-9 h-9 rounded-lg text-white text-xs "
                                       "font-bold flex items-center justify-center") \
                    .style("background:linear-gradient(135deg,#2563EB,#0D9488)")
                with ui.column().classes("gap-0"):
                    ui.label("优学鲸").classes("text-lg font-bold leading-tight")
                    ui.label("408 考研").classes("text-[11px] muted")

            for href, label, icon in NAV:
                with ui.link(target=f"{href}?user={user}").classes(
                        "navlink" + (" on" if href == active else "")):
                    ui.icon(icon).classes("ic")
                    ui.label(label).classes("text-[14px]")

            # 下面这块原来是"846 题·266 考点·339 依赖边 + 演示模式 + 用户 demo"，
            # 全是**给开发看的字段**：
            #   · "依赖边"是图数据库术语，学生看不懂
            #   · "演示模式（未配置 key）"等于开场就说"我还没接真 AI"
            #   · "薄弱考点 0 个"是空数据，没有兜底设计
            # 改成：没有数据时给**行动指引**，不展示空值。
            ui.separator().classes("mt-4").style("border-color:var(--line)")
            if marks:
                ui.label(f"已标记 {len(marks)} 个薄弱考点").classes("text-[12px] sub")
            if answers:
                ui.label(f"已作答 {len(answers)} 题").classes("text-[12px] sub")
            if not marks and not answers:
                # 空状态：告诉用户"先做什么"，而不是把 0 摆出来
                ui.label("还没有学习记录").classes("text-[12px] sub")
                with ui.link(target=f"/diagnose?user={user}").classes(
                        "text-[12px] no-underline").style("color:var(--accent)"):
                    ui.label("先花 20 分钟做一次诊断 →")
        # 内容区
        with ui.column().classes("flex-1 p-6 gap-3 min-w-0 max-w-6xl"):
            yield


# ================================================================ 首页
@ui.page("/")
def home(user: str = "demo"):
    """
    首页。这一版是重做的，针对四条批评：

      ① "首屏 2/3 死白" —— 真 bug：那行漏了 w-full，卡片按内容收缩撑不开
      ② "没有任何个性化内容" —— 现在首屏就是**你自己的学情**（掌握度/薄弱章/错题）
      ③ "三张卡片平级罗列，不知道点哪个" —— 改成一个**主行动点** + 次选项；
         一屏只有一个主色按钮，其余是文字链接
      ④ "文案是申报书/操作说明/技术术语" —— 全部改成学生话：
         · 不说"依赖边"（图数据库术语）
         · 不说"多智能体生成讲义"（学生不关心几个 agent）
         · 不说"面向 408 考研的 AI 个性化学习资源生成平台"（申报书语言）
    """
    store.ensure_user(user)
    a, mk = store.get_answers(user), store.get_marks(user)

    with shell("/", user):
        # ---------- 首屏：自我介绍 + 我现在的学情 ----------
        ui.label(f"你好，{user}").classes("text-2xl font-bold")
        ui.label("离 408 还有多少天不重要，重要的是今天练哪几道。") \
            .classes("text-[15px] sub")

        if not a and not mk:
            # ============ 空状态：给一个明确的第一步，而不是三张平级卡片
            with ui.card().classes("softcard w-full p-6 gap-2 mt-2"):
                ui.label("先花 20 分钟，让我知道你的底子") \
                    .classes("text-xl font-bold")
                ui.label("32 道题覆盖 408 全部 24 章。做完你会拿到："
                         "四科掌握度、最该补的章节、以及三条学习路径。") \
                    .classes("text-[15px] sub")
                ui.label("也可以跳过测试，直接挑你觉得薄弱的知识点练 —— "
                         "只是推荐会没那么准。").classes("text-[13px] muted")
                with ui.row().classes("gap-3 mt-2"):
                    ui.button("开始诊断（32 题）",
                              on_click=lambda: ui.navigate.to(f"/diagnose?user={user}")) \
                        .props("unelevated color=primary")
                    ui.button("直接挑考点练习",
                              on_click=lambda: ui.navigate.to(f"/practice?user={user}")) \
                        .props("flat")
            return

        # ============ 有数据：首屏就是学情 + 一个主行动点
        prof = profile_mod.build(a, mk)
        m = diagnose.summarize(a)
        weakest = prof["薄弱章节"][0] if prof["薄弱章节"] else None

        # 三科掌握度并排（有数据才显示）
        if prof["学科掌握度"]:
            with ui.row().classes("w-full gap-3"):
                for code, v in sorted(prof["学科掌握度"].items(),
                                     key=lambda x: -x[1]["掌握度"]):
                    with ui.card().classes("softcard flex-1 p-4 gap-0"):
                        ui.label(v["学科"]).classes("text-[13px] sub")
                        ui.label(f'{v["掌握度"]:.0%}').classes("kpi mt-1") \
                            .style("color:var(--accent)")
                        ui.label(f'{v["答对"]}/{v["题数"]} 题') \
                            .classes("text-[12px] muted")

        # ---------- 主行动点：只有这一个主色按钮
        with ui.card().classes("softcard w-full p-5 gap-2"):
            if weakest:
                ui.label(f'今天建议先补：{weakest["章节名"]}') \
                    .classes("text-lg font-bold")
                ui.label(f'这一章 18 年考了 {weakest["考频"]} 次，'
                         f'你的掌握度 {weakest["掌握度"]:.0%} —— '
                         f'考得多、你又弱，性价比最高。').classes("text-[14px] sub")
                ui.button("从这一章开始练",
                          on_click=lambda: ui.navigate.to(
                              f'/practice?subject={weakest.get("学科码", "DS")}'
                              f'&user={user}')).props("unelevated color=primary")
            else:
                # 全科都不弱：给错题复习
                wrong = [qid for qid, r in a.items() if not r["is_correct"]]
                ui.label(f"你有 {len(wrong)} 道错题待复习" if wrong
                         else "目前没有明显薄弱章节").classes("text-lg font-bold")
                ui.label("做错的题最能暴露问题。按年份重做一遍这些题。" if wrong
                         else "可以去真题页按年份刷卷子，或者挑新的考点。") \
                    .classes("text-[14px] sub")
                ui.button("去真题页错题模式",
                          on_click=lambda: ui.navigate.to(
                              f"/exam?view=只错题&user={user}")) \
                    .props("unelevated color=primary")

        # ---------- 下面两栏：左边"还能做什么"，右边"最近练了什么"
        # 原来这里只有三个文字链接挤在左上角，下面 600px 全是空白
        # （用户的第 1 条批评）。空白不该用装饰填，要用**用户想知道的东西**填。
        from collections import Counter
        wrong_n = sum(1 for r in a.values() if not r["is_correct"])
        last7 = [r for r in a.values() if r.get("answered_at", "") >=
                 (datetime.date.today() - datetime.timedelta(days=7)).isoformat()]
        ui.separator().style("border-color:var(--line)")
        with ui.row().classes("w-full items-start gap-10 no-wrap"):
            # 左：学习概览 + 其他入口
            with ui.column().classes("gap-2 flex-1 min-w-0"):
                ui.label("我的练习").classes("text-[13px] muted")
                with ui.row().classes("gap-8"):
                    with ui.column().classes("gap-0"):
                        ui.label(f'{len(a)}').classes("kpi")
                        ui.label("累计作答").classes("text-[12px] muted")
                    with ui.column().classes("gap-0"):
                        ui.label(f'{len(a) - wrong_n}').classes("kpi") \
                            .style("color:#1B5E36")
                        ui.label("答对").classes("text-[12px] muted")
                    with ui.column().classes("gap-0"):
                        ui.label(f'{wrong_n}').classes("kpi") \
                            .style("color:#8C2C2C")
                        ui.label("待复习错题").classes("text-[12px] muted")
                    with ui.column().classes("gap-0"):
                        ui.label(f'{len(last7)}').classes("kpi")
                        ui.label("近 7 天").classes("text-[12px] muted")
                ui.label("其他入口").classes("text-[13px] muted mt-2")
                for href, title, sub in [
                        ("/exam", "按年份刷真题", "2009–2026 共 18 套，单选题就地判分"),
                        ("/paths", "三条学习路径", "补根因 / 冲高频 / 错题驱动"),
                        ("/notes", "生成讲义", "按薄弱考点出讲义和配套真题")]:
                    with ui.column().classes("gap-0"):
                        with ui.link(target=f"{href}?user={user}").classes("no-underline"):
                            ui.label(f"{title} →").classes("text-[14px]") \
                                .style("color:var(--accent)")
                        ui.label(sub).classes("text-[12px] muted")

            # 右：最近练了什么（用真实作答记录，不是占位装饰）
            with ui.column().classes("gap-1 w-96 shrink-0"):
                ui.label("最近练习").classes("text-[13px] muted")
                qs = data.questions()
                recent = sorted(a.items(), key=lambda kv: kv[1].get("answered_at", ""),
                                reverse=True)[:6]
                if not recent:
                    ui.label("还没有练习记录").classes("text-[13px] muted")
                for qid, r in recent:
                    q = qs.get(qid)
                    if not q:
                        continue
                    # 列宽给够 + nowrap：否则"2019 年第 26 题"会把"题"字挤到第二行
                    # （实测踩过，很难看）
                    with ui.row().classes("items-center gap-2 w-full no-wrap"):
                        ui.icon("check_circle" if r["is_correct"] else "cancel") \
                            .classes("text-[15px] shrink-0").style(
                                f'color:{"#1B5E36" if r["is_correct"] else "#8C2C2C"}')
                        ui.label(f'{q["year"]} 年第 {q["题号"]} 题') \
                            .classes("text-[13px] shrink-0") \
                            .style("white-space:nowrap;min-width:7.5rem")
                        ui.label(data.node_name(q["主考点"])[:14]) \
                            .classes("text-[12px] muted flex-1 truncate")


# ================================================================ 真题页
@ui.page("/exam")
def exam(year: str = None, page: int = 1, view: str = "全部", user: str = "demo"):
    papers = data.paper_index()
    years = [p["年份"] for p in papers]
    year = str(year) if str(year) in years else years[0]
    p = data.paper(year)
    store.ensure_user(user)
    done = store.get_answers(user)

    if view == "未做":
        shown = [q for q in p["题目"] if q["id"] not in done]
    elif view == "只错题":
        shown = [q for q in p["题目"] if q["id"] in done and not done[q["id"]]["is_correct"]]
    else:
        shown = list(p["题目"])
    pages_n = max(1, (len(shown) + PER - 1) // PER)
    cur = max(1, min(int(page or 1), pages_n))

    def goto(**kw):
        s = {"year": year, "page": cur, "view": view, "user": user}
        s.update(kw)
        s = {k: v for k, v in s.items() if v not in (None, "", 0)}
        ui.navigate.to("/exam?" + "&".join(f"{k}={v}" for k, v in s.items()))

    with shell("/exam", user):
        _title("408 历年真题")
        with ui.row().classes("items-center gap-3 w-full"):
            ui.select(years, value=year,
                      on_change=lambda e: goto(year=str(e.value), page=1)) \
                .props("dense outlined").classes("w-28")
            ui.toggle(["全部", "未做", "只错题"], value=view,
                      on_change=lambda e: goto(view=e.value, page=1)) \
                .props("dense unelevated")
            answered = [q for q in p["题目"] if q["id"] in done]
            n_ok = sum(1 for q in answered if done[q["id"]]["is_correct"])
            info = (f'{p["题数"]} 题 · {p["总分"]} 分 · 可判分 {p["有答案数"]}'
                    + (f'　|　已作答 {len(answered)}/{p["单选数"]} · 答对 {n_ok} · '
                       f'正确率 {n_ok / len(answered):.0%}' if answered else ""))
            ui.label(info).classes("text-sm text-gray-500")

        with ui.row().classes("w-full items-start gap-5"):
            with ui.column().classes("w-56 shrink-0 sticky top-2 gap-1"):
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
                    ui.label(f"筛选「{view}」下没有题目。").classes("text-sm text-gray-500")
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


# ================================================================ 挑考点练习
@ui.page("/practice")
def practice(subject: str = None, chapter: str = None,
             go: int = 0, user: str = "demo"):
    store.ensure_user(user)
    marks = store.get_marks(user)

    def goto(**kw):
        s = {"subject": subject, "chapter": chapter, "go": go, "user": user}
        s.update(kw)
        s = {k: v for k, v in s.items() if v not in (None, "", 0)}
        ui.navigate.to("/practice?" + "&".join(f"{k}={v}" for k, v in s.items()))

    with shell("/practice", user):
        _title("挑考点练习")
        _steps(1 if not subject else 2)
        if not subject:
            ui.label("先选一门课，再从这门课里挑出你自己觉得薄弱的知识点，"
                     "系统就用这些考点给你出真题。不需要先做任何测试。") \
                .classes("text-[15px]")
            with ui.row().classes("w-full gap-4 items-stretch"):
                for code in ("DS", "CO", "OS", "CN"):
                    b = _book_meta(code, user)
                    with ui.card().classes("bookcard flex-1 p-4 gap-1 shadow-none"):
                        ui.label(b["name"]).classes("text-lg font-bold")
                        ui.label(f'{b["章数"]} 章 · {b["考点数"]} 个考点') \
                            .classes("text-sm text-gray-600")
                        ui.label(f'18 年考频 {b["考频"]} 次 · 题库 {b["可练题"]} 题') \
                            .classes("text-sm text-gray-600")
                        ui.label(f'我的掌握度 {b["掌握度"]:.0%}'
                                 if b["掌握度"] is not None else "我的掌握度：未测") \
                            .classes("text-sm font-semibold") \
                            .style(f'color:{"#17418F" if b["掌握度"] is not None else "#9AA5B1"}')
                        if b["已标记"]:
                            ui.label(f'★ 已标记 {b["已标记"]} 个薄弱考点') \
                                .classes("text-xs").style("color:#C2410C")
                        ui.button(f'进入{b["name"]}',
                                  on_click=lambda _=None, c=code:
                                  goto(subject=c, chapter=None)).props("unelevated") \
                            .classes("w-full mt-1")
            return

        bm = _book_meta(subject, user)
        with ui.row().classes("items-center gap-2"):
            ui.label(bm["name"]).classes("text-lg font-bold")
            ui.button("← 换一门", on_click=lambda: goto(subject=None, chapter=None)) \
                .props("flat dense")
        ui.label(f'这门课有 {bm["章数"]} 章 —— 点章名直接进去挑知识点') \
            .classes("text-[15px]")
        chs = data.chapters()[subject]
        m_ch = diagnose.mastery_by_chapter(store.get_answers(user))
        cf, cl = data.chapter_freq(), data.chapter_leaves()
        for ch, nm in chs:
            cm = m_ch.get(ch)
            n_mark = len([l for l in cl.get(ch, []) if l in marks])
            with ui.row().classes("chaprow w-full items-center gap-3 rounded-lg px-3 py-2") as row:
                ui.label(nm).classes("font-semibold w-40 shrink-0")
                ui.label(f'考频 {cf.get(ch, 0)} 次 · {len(cl.get(ch, []))} 个考点'
                         + (f' · ★ 已勾选 {n_mark}' if n_mark else "")) \
                    .classes("text-sm text-gray-500 flex-1")
                ui.label(f'掌握度 {cm["掌握度"]:.0%}' if cm else "掌握度 未测") \
                    .classes("text-sm font-semibold") \
                    .style(f'color:{"#17418F" if cm else "#9AA5B1"}')
            row.on("click", lambda _=None, c=ch: goto(chapter=c))

        if not chapter:
            ui.label("点上面任意一章，展开它的知识点列表。").classes("text-sm text-gray-500")
            return

        leaves = cl.get(chapter, [])
        ui.label(f'勾出「{data.node_name(chapter)}」里你觉得薄弱的知识点') \
            .classes("text-lg font-bold")
        ui.label("可以多选；「换章再回来勾选会保留」。标签里的 频N 是它 18 年被考的次数，"
                 "·M题 是题库里能拿它练的题数。").classes("text-sm text-gray-600")
        freq, lqc = data.freq(), data.leaf_question_count()
        with ui.row().classes("gap-x-6 gap-y-0"):
            for l in leaves:
                f = freq.get(l, {})
                n = lqc.get(l, 0)
                on = l in marks
                with ui.row().classes("leafrow items-center gap-2 rounded-lg px-2 py-1 "
                                      "min-w-[19rem]" + (" on" if on else "")) as row:
                    cb = ui.checkbox(value=on).props("dense")

                    def toggle(e, leaf=l):
                        cur = store.get_marks(user)
                        (cur.add if e.value else cur.discard)(leaf)
                        store.set_marks(user, cur)
                        ui.navigate.reload()

                    cb.on_value_change(toggle)
                    ui.label(f'{data.node_name(l)}　频{f.get("考查总次数", 0)}·{n}题') \
                        .classes("text-[15px]")
                row.on("click", lambda _=None, x=cb: x.set_value(not x.value))

        marks = store.get_marks(user)
        if not marks:
            ui.label("勾选考点后，这里会出现「开始练习」。").classes("text-sm text-gray-400")
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
            ui.button("▶ 开始练习（抽 5 道）", on_click=lambda: goto(go=1)) \
                .props("unelevated")
            ui.button("清空选择", on_click=lambda: (store.set_marks(user, set()),
                                                  ui.navigate.reload())).props("flat")
        if not go:
            return

        done = store.get_answers(user)
        pool = []
        for l in sorted(marks, key=lambda x: -lqc.get(x, 0)):
            for q in data.questions().values():
                if q["主考点"] == l and q["题型"] == "单项选择题" and q.get("答案"):
                    pool.append((l, q))
        pool.sort(key=lambda lq: (lq[1]["id"] in done, lq[1].get("难度") or 3,
                                  -lq[1]["year"]))
        ui.separator()
        if not pool:
            ui.label("你选的这些考点在题库里暂时没有对应的真题。"
                     "建议换几个标着「·N题」的考点。").classes("text-sm text-orange-700")
            return
        show = pool[:5]
        ui.label(f"练习：抽 {len(show)} 道（优先你没做过的、难度低的）") \
            .classes("text-lg font-bold")
        for l, q in show:
            question_card(q, q["year"], done, user)


# ================================================================ 快速诊断
@ui.page("/diagnose")
def diagnose_page(user: str = "demo"):
    store.ensure_user(user)
    got = store.get_answers(user)
    paper = data.diagnostic()["题目"]
    qs = data.questions()
    picks = {}

    with shell("/diagnose", user):
        _title("快速诊断（可选）")
        ui.label("32 道题　·　约 20-25 分钟　·　覆盖 408 全部 24 章") \
            .classes("text-[15px] font-semibold")
        ui.label("做完会得到章节级掌握度，之后的推荐会更准。这是可选的 —— "
                 "不做也能用：你可以在「挑考点练习」里直接勾选自认薄弱的知识点。") \
            .classes("text-sm text-gray-600")
        done_n = sum(1 for x in paper if x["id"] in got)
        ui.linear_progress(value=done_n / len(paper), show_value=False).classes("w-full")
        ui.label(f"进度 {done_n}/{len(paper)}　（未作答不计入掌握度）") \
            .classes("text-sm text-gray-500")

        for item in paper:
            q = qs[item["id"]]
            prev = got.get(item["id"], {}).get("chosen")
            with ui.card().classes("w-full p-3 gap-1 shadow-none"):
                ui.label(f'{item["order"]}. [{item["学科"]} · '
                         f'{item["诊断章节名"]} · 难度 {item["难度"]}]') \
                    .classes("text-xs text-gray-500")
                ui.label(q["题干"]).classes("text-[15px] leading-6 whitespace-pre-wrap")
                opts = q.get("选项") or {}
                # 用 radio，且 value 默认 None → 不预选任何一项
                r = ui.radio({k: f'{k}. {opts[k]}' for k in sorted(opts)},
                             value=prev).props("dense")
                picks[item["id"]] = r

        def submit():
            n = 0
            for item in paper:
                v = picks[item["id"]].value
                if not v:
                    continue
                q = qs[item["id"]]
                store.record_answer(user, item["id"], v, v == q.get("答案"),
                                    source="diagnostic")
                n += 1
            ui.notify(f"已记录 {n} 题（未作答不计入）", type="positive")
            ui.navigate.to(f"/profile?user={user}")

        ui.button("提交并生成掌握度", on_click=submit).props("unelevated")


# ================================================================ 我的画像
@ui.page("/profile")
def profile_page(user: str = "demo"):
    a, mk = store.get_answers(user), store.get_marks(user)
    with shell("/profile", user):
        _title("我的画像")
        if not a and not mk:
            ui.label("还没有任何数据。你可以：") \
                .classes("text-sm").style("color:#8A6D3B")
            ui.label("1. 到「挑考点练习」勾选自己觉得薄弱的知识点（最快）").classes("text-sm")
            ui.label("2. 或到「快速诊断」做一次 32 题测试（更准）").classes("text-sm")
            return
        prof = profile_mod.build(a, mk)
        ui.label(prof["文字画像"]).classes("text-[15px] leading-7")
        ui.label("掌握度算法：（答对+1）/（题数+2），Laplace 平滑，"
                 "避免只答 1 题就给出 0% 或 100%。你自报的薄弱点与做题数据同等计入。") \
            .classes("text-xs text-gray-500")

        if prof["学科掌握度"]:
            with ui.row().classes("gap-8"):
                for code, v in sorted(prof["学科掌握度"].items(),
                                     key=lambda x: -x[1]["掌握度"]):
                    with ui.column().classes("gap-0"):
                        ui.label(v["学科"]).classes("text-sm text-gray-500")
                        ui.label(f'{v["掌握度"]:.0%}').classes("text-2xl font-bold")
                        ui.label(f'{v["答对"]}/{v["题数"]} 题') \
                            .classes("text-xs").style("color:#1B5E36")
        if mk:
            ui.label(f"另有你自报的 {len(mk)} 个薄弱考点，已计入下方排序。") \
                .classes("text-sm")

        ui.separator()
        ui.label("各章掌握度").classes("text-lg font-semibold")
        ui.label("按学科分组；括号里是答对/答过题数。").classes("text-sm text-gray-500")
        m = diagnose.summarize(a)
        for code, name in data.CODE2NAME.items():
            rows = [c for c in m["章节"].values() if c["学科码"] == code]
            if not rows:
                continue
            ui.label(name).classes("font-semibold mt-1")
            for c in sorted(rows, key=lambda x: x["掌握度"]):
                ui.linear_progress(value=c["掌握度"], show_value=False).classes("w-full")
                ui.label(f'{c["章节名"]} — {c["掌握度"]:.0%}'
                         f'（{c["答对"]}/{c["题数"]}）').classes("text-xs text-gray-600")

        if prof["薄弱章节"]:
            ui.separator()
            ui.label("最该先补的章节").classes("text-lg font-semibold")
            ui.label("排序依据：考频 ×（1 − 掌握度）。考得越多、你越弱，越该先补。") \
                .classes("text-sm text-gray-500")
            for c in prof["薄弱章节"]:
                lvl = f'{c["掌握度"]:.0%}' if c["掌握度"] is not None else "未测"
                src = f'　·　{c.get("来源", "")}' if c.get("来源") else ""
                ui.label(f'{c["章节名"]}　掌握度 {lvl}　18 年考频 {c["考频"]} 次　'
                         f'优先级分 {c["优先级分"]}{src}').classes("text-sm")


# ================================================================ 学习路径
@ui.page("/paths")
def paths_page(user: str = "demo"):
    a, mk = store.get_answers(user), store.get_marks(user)
    with shell("/paths", user):
        _title("学习路径")
        if not a and not mk:
            ui.label("还没有数据。先到「挑考点练习」勾选薄弱知识点，"
                     "或做一次「快速诊断」。").classes("text-sm").style("color:#8A6D3B")
            return
        rec = path_mod.recommend(a, marks=mk)
        if not rec.get("路径"):
            ui.label(rec.get("提示", "暂无推荐")).classes("text-sm")
            return
        ui.label(f'根据你的学情（含你自己勾选的薄弱点），系统找出 '
                 f'{rec["薄弱考点数"]} 个未掌握考点，组织成下面几条路径。') \
            .classes("text-[15px]")
        ui.label("三条路径不互斥，选一条开始就行 —— 差别只在「先补什么」的依据。") \
            .classes("text-sm text-gray-600")
        with ui.tabs().classes("w-full") as tabs:
            for p in rec["路径"]:
                ui.tab(p["名称"], label=f'{p["名称"]}（{p["合计分钟"]} 分钟）')
        with ui.tab_panels(tabs, value=rec["路径"][0]["名称"]).classes("w-full"):
            for p in rec["路径"]:
                with ui.tab_panel(p["名称"]):
                    ui.label(f'适合：{p["适用"]}').classes("text-sm font-semibold")
                    ui.label(p["说明"]).classes("text-sm text-gray-600")
                    for i, s in enumerate(p["步骤"], 1):
                        with ui.card().classes("w-full p-3 gap-1 shadow-none mt-2"):
                            with ui.row().classes("items-center gap-4"):
                                ui.label(f'{i}. {s["考点名"]}').classes("font-semibold")
                                ui.label(f'{s["学科"]} · {s["章节"]}') \
                                    .classes("text-xs text-gray-500")
                            with ui.row().classes("items-center gap-6"):
                                ui.label("当前掌握度 "
                                         + (f'{s["当前掌握度"]:.0%}'
                                            if s["是否已测"] else "未测")) \
                                    .classes("text-sm")
                                ui.label(f'预计用时 {s["预计分钟"]} 分钟').classes("text-sm")
                                ui.label(f'考频 {s["考频"]} 次 · 可练 {s["可练真题"]} 题') \
                                    .classes("text-sm text-gray-500")
                            ui.label(s["推荐理由"]).classes("text-xs text-gray-500")
        ui.label("「补根因」的机制：沿知识点依赖图向上追溯，找到最靠前的断裂点再开始补，"
                 "而不是直接练你表面最弱的那一章。").classes("text-xs text-gray-500")


# ================================================================ 讲义生成
@ui.page("/notes")
def notes_page(user: str = "demo"):
    snap_name = {"v": None}
    a, mk = store.get_answers(user), store.get_marks(user)
    with shell("/notes", user):
        _title("讲义生成（多智能体）")
        ui.label("这一页跑的是 LangGraph 六 Agent 链路："
                 "准备 → 诊断 → 画像 → 路径 → 生成 → 复核。") \
            .classes("text-[15px]")
        ok, msg = llm.status()
        (ui.label if ok else ui.label)(("● " + msg) if ok else ("● " + msg)) \
            .classes("text-sm").style(f'color:{"#1B5E36" if ok else "#8A6D3B"}')
        if not ok:
            ui.label("页面会照常跑通，但讲义正文是用真实数据填的模板，不是 AI 写的。") \
                .classes("text-sm text-gray-600")
        if not a and not mk:
            ui.label("还没有数据。先到「挑考点练习」勾选薄弱知识点。") \
                .classes("text-sm").style("color:#8A6D3B")
            return

        rec = path_mod.recommend(a, marks=mk)
        names = [p["名称"] for p in rec["路径"]] or ["补根因"]
        holder = {"run": None, "meta": None}
        result = ui.column().classes("w-full gap-2")

        def render_run(R):
            result.clear()
            with result:
                if holder["meta"]:
                    ui.label(holder["meta"]).classes("text-sm") \
                        .style("color:#1B5E36")
                with ui.expansion("执行轨迹", value=True).classes("w-full"):
                    for t in R.get("traced", []):
                        ui.label(f'{t["agent"]} — {t["detail"]}').classes("text-sm")
                rv = R.get("review") or {}
                if rv:
                    ui.label("复核 Agent：考纲校验通过"
                             f'（检查了 {rv.get("检查项数", 0)} 个考点）'
                             if rv.get("通过") else
                             f'复核 Agent：发现 {len(rv.get("越纲项", {}))} 个考点越纲') \
                        .classes("text-sm") \
                        .style(f'color:{"#1B5E36" if rv.get("通过") else "#8C2C2C"}')
                res = R.get("resources") or []
                if not res:
                    ui.label("这条路径上没有需要生成的考点。").classes("text-sm")
                    return
                for x in res:
                    src = x["讲义"]["source"]
                    label = {"llm": "LLM 生成", "cache": "LLM 生成（预跑缓存）",
                             "template": "模板模式（真实数据）",
                             "error": "LLM 失败，已降级为模板"}.get(src, src)
                    with ui.expansion(f'{x["考点名"]}　·　{x["章节"]}　·　{label}') \
                            .classes("w-full"):
                        with ui.tabs().classes("w-full") as t2:
                            ui.tab("讲义")
                            ui.tab("知识点速记")
                            ui.tab("配套真题")
                        with ui.tab_panels(t2, value="讲义").classes("w-full"):
                            with ui.tab_panel("讲义"):
                                ui.markdown(x["讲义"]["markdown"])
                                v = x["讲义"].get("校验") or {}
                                ui.label("复核 Agent：内容未越出考纲考点范围"
                                         if v.get("通过") else
                                         f'疑似考纲外内容：{v.get("疑似考纲外")}') \
                                    .classes("text-xs text-gray-500")
                            with ui.tab_panel("知识点速记"):
                                ui.markdown(x["速记"])
                            with ui.tab_panel("配套真题"):
                                for i, q in enumerate(x["习题"], 1):
                                    ui.label(f'{i}. {q["年份"]} 年 第 {q["题号"]} 题'
                                             f'（难度 {q["难度"]}）').classes("text-sm")
                                    ui.label(q["题干"]).classes("text-sm")
                                    with ui.expansion("查看答案"):
                                        ui.label(f'正确答案：{q["答案"]}')

        def run_live():
            key = {"补根因": "root", "冲高频": "freq", "错题驱动": "wrong"}
            with ui.dialog() as d, ui.card():
                ui.label("多智能体执行中…").classes("font-semibold")
                sp = ui.spinner(size="lg")
            d.open()
            R = graph.run(user, selected_path=key.get(sel.value, "root"))
            d.close()
            holder["meta"] = None
            render_run(R)

        def replay():
            if not snaps:
                ui.notify("没有预跑快照，请先跑 scripts/prewarm.py", type="warning")
                return
            import json
            with open(f'data/prewarm/{snap_sel.value}.json', encoding="utf-8") as f:
                d = json.load(f)
            holder["meta"] = (f'快照「{snap_sel.value}」· 预跑于 {d["生成时间"]} · '
                              f'当时 LLM {"已配置" if d["LLM已配置"] else "未配置"} · '
                              f'内容来源 {d["内容来源"]}')
            render_run(d["结果"])

        import glob
        snaps = sorted(os.path.basename(x)[:-5]
                       for x in glob.glob("data/prewarm/*.json"))
        with ui.row().classes("items-center gap-3"):
            sel = ui.select(names, value=names[0], label="要生成的路径") \
                .props("dense outlined").classes("w-56")
            ui.button("▶ 运行多智能体链路", on_click=run_live).props("unelevated")
        if snaps:
            with ui.row().classes("items-center gap-3"):
                snap_sel = ui.select(snaps, value=snaps[0], label="预跑快照") \
                    .props("dense outlined").classes("w-56")
                ui.button("回放快照（路演兜底）", on_click=replay).props("flat")
        render_run({"traced": [], "review": {}, "resources": []})


# ================================================================ 小工具
def _title(text):
    ui.label(text).classes("text-xl font-bold")


def _steps(active):
    names = ["选一门课", "挑薄弱知识点", "做真题"]
    with ui.row().classes("items-center gap-3 text-sm"):
        for i, name in enumerate(names, 1):
            if i == active:
                ui.label(f"{i}. {name}").classes("font-semibold") \
                    .style("color:#17418F")
            elif i < active:
                ui.label(f"{i}. {name} ✓").classes("text-gray-400 line-through")
            else:
                ui.label(f"{i}. {name}").classes("text-gray-400")
            if i < len(names):
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8890)
    args = ap.parse_args()
    ui.run(port=args.port, title="优学鲸", reload=False, favicon="🐳", show=False)


if __name__ in {"__main__", "__mp_main__"}:
    main()
