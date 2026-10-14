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
    /* 文字色必须过对比度：实测原来 --mut(#9AA5B1) 在白底只有 2.50:1，
       远低于 4.5:1 可读标准 —— 这就是整页"看着没墨、发灰"的真实原因。
       现在三档都过线：--ink 13.9:1 / --sub 7.0:1 / --mut 4.7:1 */
    --ink:#1B2530; --sub:#3E4C5E; --mut:#5F6E80; --line:#DDE3EC;
    --accent:#2563EB; --accent-weak:#EAF1FE; --warn:#B45309;
    --bg-side:#F7F8FA;
    /* 字号层级：之前到处写 t-xs/[13px]/[15px] 这种字面量，
       结果侧栏导航被写成 14px —— **比浏览器基准 16px 还小**，
       用户反复反馈"字太小"。现在收敛成 5 档，改一处全局生效。
       原则：正文不小于 15px，次要文字不小于 13px，绝不用 11px。 */
    --fs-lead:19px;   /* 页面主标题之外的重点句 */
    --fs-body:16px;   /* 正文 */
    --fs-sm:14px;     /* 次要说明 */
    --fs-xs:13px;     /* 极弱信息（时间戳、字段名） */
    --fs-nav:18px;    /* 侧栏导航：侧栏文字少，明确比正文大一档 */
    --fs-brand:22px;  /* 侧栏品牌名 */
  }
  .t-lead{font-size:var(--fs-lead);}
  .t-body{font-size:var(--fs-body);}
  .t-sm{font-size:var(--fs-sm);}
  .t-xs{font-size:var(--fs-xs);}
  .t-nav{font-size:var(--fs-nav);}
  .t-brand{font-size:var(--fs-brand);}
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
  /* 注意：.navlink 必须自己声明字号。之前它默认 14px，把子元素的
     15px 压回视觉更小 —— 这是"我改了字号但看起来没变"的第二层原因。
     父子统一走 --fs-nav，就不会再打架。 */
  .navlink { display:flex; align-items:center; gap:11px; width:100%;
             border-radius:9px; padding:7px 11px; cursor:pointer;
             text-decoration:none; font-size:var(--fs-nav); line-height:1.4;
             color:var(--sub); }
  .navlink:hover { background:#E9EEF6; color:var(--ink); }
  .navlink.on { background:#fff; color:#123B85; font-weight:700;
                box-shadow:0 1px 3px rgba(15,23,42,.10); }
  .navlink.on .ic { color:var(--accent); opacity:1; }
  .navlink .ic { font-size:21px; opacity:.95; }
  .kpi { font-size:26px; font-weight:700; line-height:1.1; }
  .muted { color:var(--mut); }
  /* ===== 宽屏收紧密度 =====
     用户反馈"100% 缩放有点大"。注意：**不能靠缩小字号解决** ——
     字号一降，中文可读性立刻变差（而且前面几轮刚把对比度和字号调够）。
     正解是收紧**间距与留白**，字号保持不动。
     另外侧栏用 min() 跟随视口：宽屏下按比例略宽（视觉权重不失衡），
     窄屏下不低于 240px。 */
  @media (min-width: 1500px) {
    .qcard { padding: 0.55rem 0.8rem 0.6rem 0.9rem !important; }
    .opt { padding-top: 3px !important; padding-bottom: 3px !important; }
    [class*="gap-3"] { gap: 0.5rem !important; }
    .navlink { padding-top: 6px; padding-bottom: 6px; }
  }

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
        # 侧栏：232 → 264px。17px 的中文在 250px 里仍然挤，而侧栏文字少，
        # 可以给得比正文更宽松。
        # 侧栏高度这件事，两条路各有一个代价，我试过后选了第二个：
        #   ① min-h-screen（拉满整屏）：背景完整，但导航只占 ~300px，
        #      下面 700px 是纯背景色 → 用户两次指出"下方留那么大空白"
        #   ② 贴内容高度（self-start）：高度问题解决了，但**背景色块会断开**，
        #      下面露出白色，看着像侧栏被截断（我实测截图看到了）
        # 最终做法：全高背景 + 内容吸顶。
        # 外层负责"背景铺满整个高度"，内层 sticky 负责"滚动时导航还在"。
        # self-stretch 是必须的：父级 flex 行设了 items-start，
        # 子元素默认不拉伸 → 背景块只有 644px 高（实测），下面露出白色。
        with ui.column().classes("shrink-0 border-r self-stretch") \
                .style("background:var(--bg-side);border-color:var(--line);"
                       "width:min(17vw,300px);min-height:100vh"):
          with ui.column().classes("p-3 pt-4 gap-1 sticky top-0 w-full"):
              # 品牌区：加大 logo 与标题，原来 18px 的标题配 17px 导航没有主次
              with ui.row().classes("items-center gap-3 mb-4 px-1"):
                  ui.label("408").classes("w-10 h-10 rounded-xl text-white font-bold "
                                         "flex items-center justify-center shrink-0") \
                      .style("background:linear-gradient(135deg,#2563EB,#0D9488);"
                             "font-size:14px")
                  with ui.column().classes("gap-0"):
                      ui.label("优学鲸").classes("t-brand font-bold leading-tight")
                      ui.label("408 考研").classes("t-xs sub")

              ui.label("学习功能").classes(
                  "t-xs muted font-semibold tracking-wide mx-1 mb-0.5")
              for href, label, icon in NAV:
                  with ui.link(target=f"{href}?user={user}").classes(
                          "navlink" + (" on" if href == active else "")):
                      ui.icon(icon).classes("ic")
                      ui.label(label).classes("t-nav")

              # 下面这块原来是"846 题·266 考点·339 依赖边 + 演示模式 + 用户 demo"，
              # 全是**给开发看的字段**：
              #   · "依赖边"是图数据库术语，学生看不懂
              #   · "演示模式（未配置 key）"等于开场就说"我还没接真 AI"
              #   · "薄弱考点 0 个"是空数据，没有兜底设计
              # 改成：没有数据时给**行动指引**，不展示空值。
              # 侧栏不再靠"拉满屏幕"占位，但内容本身也该给够：
              # 「我的进度」用进度条式的直观数字（可追溯的原始计数，不用百分比）
              ui.label("我的进度").classes(
                  "t-xs muted font-semibold tracking-wide mx-1 mt-3 mb-0.5")
              if answers:
                  _ok = sum(1 for r in answers.values() if r["is_correct"])
                  with ui.column().classes("gap-1 px-1"):
                      for label, val, total, color in [
                              ("已作答", len(answers), len(data.questions()), "#2563EB"),
                              ("答对", _ok, len(answers), "#1B5E36"),
                              ("待复习", len(answers) - _ok, len(answers), "#B45309")]:
                          with ui.row().classes("items-center gap-2 w-full no-wrap"):
                              ui.label(label).classes("t-xs muted w-12 shrink-0")
                              ui.label(f"{val}").classes("t-sm font-semibold w-8")
                              ui.element("div").classes("h-1.5 rounded flex-1") \
                                  .style(f"background:{color};opacity:.85;"
                                         f"max-width:{int(val / max(total, 1) * 100)}%")
                  if marks:
                      ui.label(f"自报薄弱考点 {len(marks)} 个").classes("t-xs muted mx-1")
              else:
                  ui.label("还没有练习记录").classes("t-xs muted mx-1")

              # 底部：原来只有一行"已作答 32 题"孤零零挂着。
              ui.element("div").classes("flex-1 min-h-4")
              ui.separator().style("border-color:var(--line)")
              with ui.row().classes("items-center gap-2 px-1 pt-2"):
                  ui.label(user[:1].upper()).classes(
                      "w-9 h-9 rounded-full text-white font-bold flex items-center "
                      "justify-center shrink-0").style("background:#5A6B80;font-size:15px")
                  with ui.column().classes("gap-0 min-w-0 flex-1"):
                      ui.label(user).classes("t-sm font-semibold truncate")
                      ui.label(f"已作答 {len(answers)} 题" if answers
                               else "还没有练习记录").classes("t-xs muted")
              with ui.row().classes("gap-1 mt-1"):
                  if not answers and not marks:
                      with ui.link(target=f"/diagnose?user={user}").classes(
                              "t-xs no-underline flex-1 text-center py-1 rounded") \
                              .style("color:var(--accent);background:var(--accent-weak)"):
                          ui.label("先做一次诊断")
                  else:
                      with ui.link(target=f"/profile?user={user}").classes(
                              "t-xs no-underline flex-1 text-center py-1 rounded") \
                              .style("color:var(--accent);background:var(--accent-weak)"):
                          ui.label("看我的画像")
        # 内容区
        with ui.column().classes("flex-1 p-6 gap-3 min-w-0"):
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
        # ---------- 首屏
        # 用户两条要求，都采纳：
        #   ① 删掉"你好，demo" —— demo 是用户 id，不是名字，喊出来很怪
        #   ② 掌握度不上首页 —— 见下方说明
        #
        # 为什么要拿掉掌握度：它来自 32 道诊断题，分摊到 4 科是**每科 8 题**，
        # 章节级更薄：16 个章节只做了 1 题、8 个只做了 2 题。
        # 公式是 (答对+1)/(题数+2) 的平滑 —— 数字是真算的，但 1 题答对就显示
        # "67% 掌握度"属于**伪精确**：看着可信，实际证明不了任何事。
        # 所以首页不再放这个百分比，改为只陈述事实（做了多少、对了多少）。
        # 精确数字留在「我的画像」页，那里会同时标出样本量。
        ui.label("今天练哪几道").classes("text-2xl font-bold")
        ui.label("离 408 还有多少天不重要，重要的是今天练哪几道。") \
            .classes("t-body sub")

        # 注意：删掌握度卡片时不要把下面这两行一起删了 ——
        # weakest 是"今天建议先补"的依据，删掉首页直接 500（实测踩过）。
        prof = profile_mod.build(a, mk)
        weakest = prof["薄弱章节"][0] if prof["薄弱章节"] else None

        # ---------- 主行动点：只有这一个主色按钮
        with ui.card().classes("softcard w-full p-5 gap-2"):
            if weakest:
                ui.label(f'今天建议先补：{weakest["章节名"]}') \
                    .classes("t-lead font-bold")
                # 不写"你的掌握度 XX%"：那一章可能只做过 1 题，百分比没意义。
                # 只给可追溯的事实：这一章 18 年考了多少次。
                # （顺带修一个我的笔误：这段说明被写成了 t-nav，字号比正文小）
                ui.label(f'这一章 18 年考了 {weakest["考频"]} 次，'
                         f'是考频最高的薄弱章节之一 —— 先补它性价比最高。') \
                    .classes("t-body sub")
                ui.button("从这一章开始练",
                          on_click=lambda: ui.navigate.to(
                              f'/practice?subject={weakest.get("学科码", "DS")}'
                              f'&user={user}')).props("unelevated color=primary")
            else:
                # 全科都不弱：给错题复习
                wrong = [qid for qid, r in a.items() if not r["is_correct"]]
                ui.label(f"你有 {len(wrong)} 道错题待复习" if wrong
                         else "目前没有明显薄弱章节").classes("t-lead font-bold")
                ui.label("做错的题最能暴露问题。按年份重做一遍这些题。" if wrong
                         else "可以去真题页按年份刷卷子，或者挑新的考点。") \
                    .classes("t-nav sub")
                ui.button("去真题页错题模式",
                          on_click=lambda: ui.navigate.to(
                              f"/exam?view=只错题&user={user}")) \
                    .props("unelevated color=primary")

        # ---------- 下面两栏
        # 用户第三次指出"留白那么多"。实测（1540x1000）：
        #   内容结束于 y=685，视口 1000 → 下方空 315px
        #   内容区右边界 1434，视口 1540 → 横向空 106px（max-w-6xl 限制）
        # 空白的正确解法不是加装饰，而是放进用户真的想知道的**数据**。
        from collections import Counter
        wrong_n = sum(1 for r in a.values() if not r["is_correct"])
        last7 = [r for r in a.values() if r.get("answered_at", "") >=
                 (datetime.date.today() - datetime.timedelta(days=7)).isoformat()]
        ui.separator().style("border-color:var(--line)")

        with ui.row().classes("w-full items-start gap-10 no-wrap"):
            # 左栏：练习概览 + 题量分布（真数据，不是装饰）
            with ui.column().classes("gap-2 flex-1 min-w-0"):
                ui.label("我的练习").classes("t-sm muted")
                with ui.row().classes("gap-10"):
                    for val, name, color in [
                            (len(a), "累计作答", "var(--ink)"),
                            (len(a) - wrong_n, "答对", "#1B5E36"),
                            (wrong_n, "待复习错题", "#8C2C2C"),
                            (len(last7), "近 7 天", "var(--ink)")]:
                        with ui.column().classes("gap-0"):
                            ui.label(str(val)).classes("kpi") \
                                .style(f"color:{color}"
                                       + (";opacity:.35" if val == 0 else ""))
                            ui.label(name).classes("t-xs muted")

                # 近 14 天练习记录：复习节奏是学生真关心的事，也把这块留白填上
                # （用户第三次指出"留白那么多"，实测内容底 685/视口 1000）
                ui.label("近 14 天练习").classes("t-sm muted mt-1")
                by_day = Counter(str(r.get("answered_at", ""))[:10]
                                 for r in a.values())
                days = [datetime.date.today() - datetime.timedelta(days=i)
                        for i in range(13, -1, -1)]
                mx = max([by_day.get(d.isoformat(), 0) for d in days] + [1])
                with ui.row().classes("gap-1 items-end"):
                    for d in days:
                        n = by_day.get(d.isoformat(), 0)
                        h = 6 + int(n / mx * 30)
                        el = ui.element("div").classes("rounded") \
                            .style(f"width:18px;height:{h}px;"
                                   f"background:{'#2563EB' if n else '#E6EAF0'};"
                                   f"opacity:{0.35 + 0.65 * (n / mx) if n else 1};")
                        el.tooltip(f"{d.strftime('%m-%d')}：{n} 题")
                # 只给一根柱子会让人以为图表坏了（demo 画像 32 题全在今天做的）。
                # 补两条上下文：今天做了多少 + 如果全挤在一天就给一句建议。
                total14 = sum(by_day.get(d.isoformat(), 0) for d in days)
                today_n = by_day.get(datetime.date.today().isoformat(), 0)
                active = sum(1 for d in days if by_day.get(d.isoformat(), 0))
                msg = f"近 14 天共 {total14} 题　·　今天 {today_n} 题"
                if total14 and active == 1:
                    msg += "　·　都集中在一天 —— 分散到几天记得更牢"
                elif not today_n:
                    msg += "　·　今天还没练"
                ui.label(msg).classes("t-xs muted")

                ui.label("题库分布").classes("t-sm muted mt-2")
                freq = data.freq()
                rows = []
                for code, name in data.CODE2NAME.items():
                    leaves = [l for ch, _n in data.chapters()[code]
                              for l in data.chapter_leaves().get(ch, [])]
                    rows.append((name, sum(data.leaf_question_count().get(l, 0)
                                           for l in leaves),
                                 len(leaves)))
                mx = max(r[1] for r in rows) or 1
                for name, n, ln in rows:
                    with ui.row().classes("items-center gap-2 no-wrap"):
                        ui.label(name).classes("t-sm w-32 shrink-0")
                        ui.element("div").classes("h-2 rounded") \
                            .style(f"width:{int(n / mx * 200)}px;"
                                   f"background:{SUBJECT_COLORS.get(name, '#2563EB')};"
                                   f"opacity:.75")
                        ui.label(f"{n} 题 · {ln} 考点").classes("t-xs muted")

                ui.label("其他入口").classes("t-sm muted mt-2")
                # 横排：原来竖排三行占掉 110px 高度，也是留白的一部分
                with ui.row().classes("gap-6"):
                    for href, title in [("/exam", "按年份刷真题"),
                                        ("/paths", "三条学习路径"),
                                        ("/notes", "生成讲义")]:
                        with ui.link(target=f"{href}?user={user}") \
                                .classes("no-underline"):
                            ui.label(f"{title} →").classes("t-body") \
                                .style("color:var(--accent)")

            # 右栏：最近练习（显示更多，填满这一侧）
            with ui.column().classes("gap-1 w-[26rem] shrink-0"):
                ui.label("最近练习").classes("t-sm muted")
                qs = data.questions()
                recent = sorted(a.items(), key=lambda kv: kv[1].get("answered_at", ""),
                                reverse=True)[:10]
                if not recent:
                    ui.label("还没有练习记录").classes("t-sm muted")
                for qid, r in recent:
                    q = qs.get(qid)
                    if not q:
                        continue
                    with ui.row().classes("items-center gap-2 w-full no-wrap"):
                        ui.icon("check_circle" if r["is_correct"] else "cancel") \
                            .classes("shrink-0").style(
                                "font-size:16px;"
                                f'color:{"#1B5E36" if r["is_correct"] else "#8C2C2C"}')
                        ui.label(f'{q["year"]} 年第 {q["题号"]} 题') \
                            .classes("t-sm shrink-0") \
                            .style("white-space:nowrap;min-width:7.5rem")
                        ui.label(data.node_name(q["主考点"])[:16]) \
                            .classes("t-sm muted flex-1 truncate")


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
            ui.label(info).classes("t-sm muted")

        # ---- 答题卡：从左侧竖栏改成**题目区上方的一条横卡**
        # 用户要求"答题卡放第一题上面"。改完有两个实际收益：
        #   ① 题目区宽 +240px（原来左侧那列占 220px + 间距 20px）
        #   ② 综合题页面本来就没有判分状态可显示，那列纯属浪费
        # 横向排布下 47 个格子只占 2 行左右，比竖栏省纵向空间。
        with ui.card().classes("softcard w-full p-2 gap-1"):
            with ui.row().classes("items-center gap-3 w-full no-wrap"):
                ui.label("答题卡").classes("t-sm font-semibold muted shrink-0")
                with ui.element("div").classes("flex flex-wrap gap-1 flex-1"):
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
                            ui.label(q["题号"]).classes("t-xs")
                ui.label("绿=对 · 红=错 · 白=未做").classes("t-xs muted shrink-0")
                ui.button(icon="chevron_left",
                          on_click=lambda: goto(page=max(1, cur - 1))) \
                    .props("flat dense").set_enabled(cur > 1)
                ui.label(f"{cur} / {pages_n}").classes("t-sm shrink-0") \
                    .style("white-space:nowrap")
                ui.button(icon="chevron_right",
                          on_click=lambda: goto(page=min(pages_n, cur + 1))) \
                    .props("flat dense").set_enabled(cur < pages_n)

        with ui.column().classes("w-full gap-2 min-w-0"):
            if not shown:
                ui.label(f"筛选「{view}」下没有题目。").classes("t-sm muted")
                return
            items = shown[(cur - 1) * PER: cur * PER]
            ui.label(f'第 {items[0]["题号"]}–{items[-1]["题号"]} 题') \
                .classes("t-lead font-semibold")
            subj = None
            for q in items:
                if q["学科"] != subj:
                    subj = q["学科"]
                    ui.label(subj).classes("t-body font-semibold mt-1") \
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
                .classes("t-body")
            with ui.row().classes("w-full gap-4 items-stretch"):
                for code in ("DS", "CO", "OS", "CN"):
                    b = _book_meta(code, user)
                    with ui.card().classes("bookcard flex-1 p-4 gap-1 shadow-none"):
                        ui.label(b["name"]).classes("t-lead font-bold")
                        ui.label(f'{b["章数"]} 章 · {b["考点数"]} 个考点') \
                            .classes("t-sm sub")
                        ui.label(f'18 年考频 {b["考频"]} 次 · 题库 {b["可练题"]} 题') \
                            .classes("t-sm sub")
                        # 不显示掌握度百分比，只显示"做过几题"（可追溯）
                        _bm = diagnose.mastery_by_subject(
                            store.get_answers(user)).get(code)
                        ui.label(f'已作答 {_bm["题数"]} 题' if _bm else "还没测过") \
                            .classes("t-sm font-semibold") \
                            .style(f'color:{"#17418F" if _bm else "#9AA5B1"}')
                        if b["已标记"]:
                            ui.label(f'★ 已标记 {b["已标记"]} 个薄弱考点') \
                                .classes("t-xs").style("color:#C2410C")
                        ui.button(f'进入{b["name"]}',
                                  on_click=lambda _=None, c=code:
                                  goto(subject=c, chapter=None)).props("unelevated") \
                            .classes("w-full mt-1")
            return

        bm = _book_meta(subject, user)
        with ui.row().classes("items-center gap-2"):
            ui.label(bm["name"]).classes("t-lead font-bold")
            ui.button("← 换一门", on_click=lambda: goto(subject=None, chapter=None)) \
                .props("flat dense")
        ui.label(f'这门课有 {bm["章数"]} 章 —— 点章名直接进去挑知识点') \
            .classes("t-body")
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
                    .classes("t-sm muted flex-1")
                ui.label(f'做过 {cm["题数"]} 题' if cm else "未测") \
                    .classes("t-sm font-semibold") \
                    .style(f'color:{"#17418F" if cm else "#9AA5B1"}')
            row.on("click", lambda _=None, c=ch: goto(chapter=c))

        if not chapter:
            ui.label("点上面任意一章，展开它的知识点列表。").classes("t-sm muted")
            return

        leaves = cl.get(chapter, [])
        ui.label(f'勾出「{data.node_name(chapter)}」里你觉得薄弱的知识点') \
            .classes("t-lead font-bold")
        ui.label("可以多选；「换章再回来勾选会保留」。标签里的 频N 是它 18 年被考的次数，"
                 "·M题 是题库里能拿它练的题数。").classes("t-sm sub")
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
                        .classes("t-body")
                row.on("click", lambda _=None, x=cb: x.set_value(not x.value))

        marks = store.get_marks(user)
        if not marks:
            ui.label("勾选考点后，这里会出现「开始练习」。").classes("t-sm muted")
            return
        total_q = sum(lqc.get(l, 0) for l in marks)
        ui.separator()
        ui.label(f"你已勾选 {len(marks)} 个考点，题库里共 {total_q} 道真题可练") \
            .classes("t-lead font-bold")
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
            .classes("t-lead font-bold")
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
            .classes("t-body font-semibold")
        # 文案要跟界面一致：这里已经不展示"掌握度百分比"了，
        # 所以不能再承诺"做完会得到章节级掌握度"（承诺了却看不到，更糟）
        ui.label("做完 24 章的作答记录就有了，之后的推荐会更准。这是可选的 —— "
                 "不做也能用：你可以在「挑考点练习」里直接勾选自认薄弱的知识点。") \
            .classes("t-sm sub")
        done_n = sum(1 for x in paper if x["id"] in got)
        ui.linear_progress(value=done_n / len(paper), show_value=False).classes("w-full")
        ui.label(f"进度 {done_n}/{len(paper)}　（未作答不计入掌握度）") \
            .classes("t-sm muted")

        for item in paper:
            q = qs[item["id"]]
            prev = got.get(item["id"], {}).get("chosen")
            with ui.card().classes("w-full p-3 gap-1 shadow-none"):
                ui.label(f'{item["order"]}. [{item["学科"]} · '
                         f'{item["诊断章节名"]} · 难度 {item["难度"]}]') \
                    .classes("t-xs muted")
                ui.label(q["题干"]).classes("t-body leading-6 whitespace-pre-wrap")
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
                .classes("t-sm").style("color:#8A6D3B")
            ui.label("1. 到「挑考点练习」勾选自己觉得薄弱的知识点（最快）").classes("t-sm")
            ui.label("2. 或到「快速诊断」做一次 32 题测试（更准）").classes("t-sm")
            return
        prof = profile_mod.build(a, mk)
        ui.label(prof["文字画像"]).classes("t-body leading-7")
        # 【为什么一个百分比都不显示】
        # 用户质疑"这个掌握度是不是在瞎猜"，随后要求撤掉。核实后他是对的：
        #   学科级每科仅 8 题；章节级 16 个章节只做过 1 题、8 个只做过 2 题。
        #   公式 (答对+1)/(题数+2) 的平滑 → 1 题答对显示 67%，1 题答错显示 33%。
        # 这种数字**看着精确、实际证明不了任何事**，而且答辩时经不起追问。
        # 所以这里只显示原始事实：答对几题 / 做过几题。排序仍然用内部掌握度
        # 计算（算法需要），但不把它摆给用户看。
        ui.label("做题记录").classes("t-lead font-semibold")
        ui.label("只列原始作答数，不做换算 —— 题数少时百分比没有意义。") \
            .classes("t-sm muted")

        if prof["学科掌握度"]:
            with ui.row().classes("gap-8"):
                # 按答对率排序（内部仍用掌握度，只是不显示）
                for code, v in sorted(prof["学科掌握度"].items(),
                                     key=lambda x: -x[1]["掌握度"]):
                    with ui.column().classes("gap-0"):
                        ui.label(v["学科"]).classes("t-sm muted")
                        ui.label(f'{v["答对"]} / {v["题数"]}').classes("text-2xl font-bold") \
                            .style("color:var(--accent)")
                        ui.label("答对 / 做过").classes("t-xs muted")
        if mk:
            ui.label(f"另有你自报的 {len(mk)} 个薄弱考点，已计入下方排序。") \
                .classes("t-sm")

        ui.separator()
        ui.label("各章作答记录").classes("t-lead font-semibold")
        ui.label("按学科分组。右侧是这一章你做过几题、对了几题；"
                 "未测章节表示还没做过题。").classes("t-sm muted")
        m = diagnose.summarize(a)
        for code, name in data.CODE2NAME.items():
            rows = [c for c in m["章节"].values() if c["学科码"] == code]
            if not rows:
                continue
            ui.label(name).classes("t-body font-semibold mt-2")
            # 用表格而不是进度条：进度条本身就是"百分比"的可视化，
            # 留着它等于换个形式继续暗示精度。
            for c in sorted(rows, key=lambda x: (x["题数"], x["答对"])):
                with ui.row().classes("items-center gap-3 w-full no-wrap"):
                    ui.label(c["章节名"]).classes("t-sm flex-1 truncate")
                    ui.label(f'考频 {data.chapter_freq().get(c["chapter"], 0)} 次') \
                        .classes("t-xs muted").style("white-space:nowrap")
                    if c["题数"]:
                        ui.label(f'答对 {c["答对"]} / {c["题数"]} 题') \
                            .classes("t-sm font-semibold").style("white-space:nowrap")
                    else:
                        ui.label("未测").classes("t-sm muted") \
                            .style("white-space:nowrap")

        if prof["薄弱章节"]:
            ui.separator()
            ui.label("最该先补的章节").classes("t-lead font-semibold")
            ui.label("排序依据：考频 ×（1 − 掌握度）。考得越多、你越弱，越该先补。"
                     "（掌握度只用于排序，不对外显示 —— 样本小时它不可靠，"
                     "所以上面只给你原始作答数）") \
                .classes("t-sm muted")
            for c in prof["薄弱章节"]:
                # 同样不显示掌握度百分比；给出考频与来源，都可追溯
                src = f'　·　{c.get("来源", "")}' if c.get("来源") else ""
                ui.label(f'{c["章节名"]}　18 年考频 {c["考频"]} 次{src}') \
                    .classes("t-sm")


# ================================================================ 学习路径
@ui.page("/paths")
def paths_page(user: str = "demo"):
    a, mk = store.get_answers(user), store.get_marks(user)
    with shell("/paths", user):
        _title("学习路径")
        if not a and not mk:
            ui.label("还没有数据。先到「挑考点练习」勾选薄弱知识点，"
                     "或做一次「快速诊断」。").classes("t-sm").style("color:#8A6D3B")
            return
        rec = path_mod.recommend(a, marks=mk)
        if not rec.get("路径"):
            ui.label(rec.get("提示", "暂无推荐")).classes("t-sm")
            return
        ui.label(f'根据你的学情（含你自己勾选的薄弱点），系统找出 '
                 f'{rec["薄弱考点数"]} 个未掌握考点，组织成下面几条路径。') \
            .classes("t-body")
        ui.label("三条路径不互斥，选一条开始就行 —— 差别只在「先补什么」的依据。") \
            .classes("t-sm sub")
        with ui.tabs().classes("w-full") as tabs:
            for p in rec["路径"]:
                ui.tab(p["名称"], label=f'{p["名称"]}（{p["合计分钟"]} 分钟）')
        with ui.tab_panels(tabs, value=rec["路径"][0]["名称"]).classes("w-full"):
            for p in rec["路径"]:
                with ui.tab_panel(p["名称"]):
                    ui.label(f'适合：{p["适用"]}').classes("t-sm font-semibold")
                    ui.label(p["说明"]).classes("t-sm sub")
                    for i, s in enumerate(p["步骤"], 1):
                        with ui.card().classes("w-full p-3 gap-1 shadow-none mt-2"):
                            with ui.row().classes("items-center gap-4"):
                                ui.label(f'{i}. {s["考点名"]}').classes("font-semibold")
                                ui.label(f'{s["学科"]} · {s["章节"]}') \
                                    .classes("t-xs muted")
                            with ui.row().classes("items-center gap-6"):
                                # 不显示"当前掌握度 XX%"：那一章可能只做过 1 题
                                ui.label("尚未测过" if not s["是否已测"]
                                         else f'做过 {s["可练真题"]} 题中的一部分') \
                                    .classes("t-sm")
                                ui.label(f'预计用时 {s["预计分钟"]} 分钟').classes("t-sm")
                                ui.label(f'考频 {s["考频"]} 次 · 可练 {s["可练真题"]} 题') \
                                    .classes("t-sm muted")
                            ui.label(s["推荐理由"]).classes("t-xs muted")
        ui.label("「补根因」的机制：沿知识点依赖图向上追溯，找到最靠前的断裂点再开始补，"
                 "而不是直接练你表面最弱的那一章。").classes("t-xs muted")


# ================================================================ 讲义生成
@ui.page("/notes")
def notes_page(user: str = "demo"):
    snap_name = {"v": None}
    a, mk = store.get_answers(user), store.get_marks(user)
    with shell("/notes", user):
        _title("讲义生成（多智能体）")
        ui.label("这一页跑的是 LangGraph 六 Agent 链路："
                 "准备 → 诊断 → 画像 → 路径 → 生成 → 复核。") \
            .classes("t-body")
        ok, msg = llm.status()
        (ui.label if ok else ui.label)(("● " + msg) if ok else ("● " + msg)) \
            .classes("t-sm").style(f'color:{"#1B5E36" if ok else "#8A6D3B"}')
        if not ok:
            ui.label("页面会照常跑通，但讲义正文是用真实数据填的模板，不是 AI 写的。") \
                .classes("t-sm sub")
        if not a and not mk:
            ui.label("还没有数据。先到「挑考点练习」勾选薄弱知识点。") \
                .classes("t-sm").style("color:#8A6D3B")
            return

        rec = path_mod.recommend(a, marks=mk)
        names = [p["名称"] for p in rec["路径"]] or ["补根因"]
        holder = {"run": None}
        result = ui.column().classes("w-full gap-2")

        def render_run(R):
            result.clear()
            with result:
                # 【默认不展开】用户明确要求："运行的时候过程不要显示，
                # 用户又不会看这个。"（原话）
                # 这个判断是对的：学生只关心讲义内容，"准备 Agent/诊断 Agent…"
                # 那串是给开发看的。但也不删掉 —— 面试/路演被问到"多智能体怎么
                # 调度的"时，展开它是最直接的证据，所以收进默认折叠的技术细节里。
                with ui.expansion("生成过程（技术细节，一般不用看）",
                                  value=False).classes("w-full"):
                    for t in R.get("traced", []):
                        ui.label(f'{t["agent"]} — {t["detail"]}').classes("t-sm")
                rv = R.get("review") or {}
                if rv:
                    ui.label("复核 Agent：考纲校验通过"
                             f'（检查了 {rv.get("检查项数", 0)} 个考点）'
                             if rv.get("通过") else
                             f'复核 Agent：发现 {len(rv.get("越纲项", {}))} 个考点越纲') \
                        .classes("t-sm") \
                        .style(f'color:{"#1B5E36" if rv.get("通过") else "#8C2C2C"}')
                res = R.get("resources") or []
                if not res:
                    ui.label("这条路径上没有需要生成的考点。").classes("t-sm")
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
                                    .classes("t-xs muted")
                            with ui.tab_panel("知识点速记"):
                                ui.markdown(x["速记"])
                            with ui.tab_panel("配套真题"):
                                for i, q in enumerate(x["习题"], 1):
                                    ui.label(f'{i}. {q["年份"]} 年 第 {q["题号"]} 题'
                                             f'（难度 {q["难度"]}）').classes("t-sm")
                                    ui.label(q["题干"]).classes("t-sm")
                                    with ui.expansion("查看答案"):
                                        ui.label(f'正确答案：{q["答案"]}')

        # 【注意】这一块（下拉 + 运行按钮）必须在 run_live 之前创建：
        # run_live 里用到了 sel.value。我上一轮删"回放快照"时用脚本按区间切除，
        # 把这块一起删掉了 —— 表现为页面只剩标题、按钮全无（截图确认）。
        with ui.row().classes("items-center gap-3"):
            sel = ui.select(names, value=names[0], label="要生成的路径") \
                .props("dense outlined").classes("w-56")
            ui.button("▶ 运行多智能体链路", on_click=lambda: run_live()) \
                .props("unelevated")

        def run_live():
            key = {"补根因": "root", "冲高频": "freq", "错题驱动": "wrong"}
            with ui.dialog() as d, ui.card():
                ui.label("多智能体执行中…").classes("font-semibold")
                sp = ui.spinner(size="lg")
            d.open()
            R = graph.run(user, selected_path=key.get(sel.value, "root"))
            d.close()
            render_run(R)



# ================================================================ 小工具
def _title(text):
    ui.label(text).classes("text-2xl font-bold")


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
