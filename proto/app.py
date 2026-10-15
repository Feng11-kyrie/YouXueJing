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
    /exam                   考研历年真题（科目选择）
    /exam/408?year=2025&page=2   408 历年真题
    /exam/zhengzhi?year=2023     政治历年真题
    /practice?subject=DS&chapter=DS-03   挑考点练习
    /diagnose               快速诊断（32 题）
    /profile                我的画像
    /notes                  我的薄弱点（原"讲义生成"）

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
from yj import llm, graph, zhengzhi as zz           # noqa: E402
from yj import english as en                          # noqa: E402
from proto.cards_en import (passage_card, cloze_card,   # noqa: E402
                            subjective_block, two_col)
from proto import store_lite as store              # noqa: E402
from proto.cards import (question_card, SUBJECT_COLORS,   # noqa: E402
                         ZZ_PART_COLORS)

PER = 10
NAV = [("/", "首页", "home"),
       ("/exam", "考研历年真题", "description"),
       ("/practice", "挑考点练习", "school"),
       ("/diagnose", "快速诊断", "monitor_heart"),
       ("/profile", "我的画像", "insights"),
       ("/notes", "我的薄弱点", "menu_book")]

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
                  ui.label("鲸").classes("w-10 h-10 rounded-xl text-white font-bold "
                                        "flex items-center justify-center shrink-0") \
                      .style("background:linear-gradient(135deg,#2563EB,#0D9488);"
                             "font-size:14px")
                  with ui.column().classes("gap-0"):
                      ui.label("优学鲸").classes("t-brand font-bold leading-tight")
                      # 品牌副标题：从"408 考研"改为"考研智能备考"
                      # （用户决定做考研平台：408 + 政治，而不是只做 408）
                      ui.label("考研智能备考").classes("t-xs sub")

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
    首页 = **我的做题记录**（用户要求："首页去总结用户的做题记录什么的"）。

    为什么改成这个定位
    ------------------
    原来的首页想同时做三件事，结果每件都不彻底，而且**有两处是冗余的**：
      · 「题库分布」（197 题 · 56 考点…）—— 静态数字，与用户无关，用户从不
        需要知道题库有多少题
      · 累计 KPI 四个数字 —— 与「我的画像」页首屏**完全相同**
      · 「最近练习」12 条清单 —— 与真题页"错题模式"重复
    所以现在只做一件事：**把做题记录总结清楚**。

    与「我的画像」页的分工（避免又一次重复）：
        首页     = 我最近在做什么（时间线、节奏、趋势）
        我的画像 = 我现在会什么（章节强弱、知识结构）
    两页都基于同一份作答记录，但视角不同。

    数据前提：演示画像的时间戳必须**分散到多天**。原来 32 条全写在同一秒
    （seed_user 的旧实现），柱图上只有一根柱、"今天 N 题"也是假象 ——
    一个显示不出一周趋势的记录面板比没有更糟。已修见 scripts/prewarm.py。
    """
    store.ensure_user(user)
    a, mk = store.get_answers(user), store.get_marks(user)

    with shell("/", user):
        from collections import Counter
        today = datetime.date.today()
        wrong_ids = [qid for qid, r in a.items() if not r["is_correct"]]
        prof = profile_mod.build(a, mk)
        weakest = prof["薄弱章节"][0] if prof["薄弱章节"] else None

        # ---------- 选科目（用户要求："用户进去可以选择科目"）
        # 设计取舍：**不做问卷**。考研学生一进来若被问"你考哪几科"，
        # 选了英语/数学却发现没有内容，第一印象就坏了；问卷还多一步操作。
        # 改成直接把**已有的科目**摆出来，点哪个进哪个 —— 卡片本身就是说明。
        ui.label("选择科目").classes("text-2xl font-bold")
        ui.label("每科都是独立的考纲图谱与真题库；进度、作答记录按科目分开。") \
            .classes("t-body sub")
        with ui.row().classes("w-full gap-4 items-stretch"):
            for e in data.exam_list():
                with ui.card().classes("softcard flex-1 p-4 gap-1"):
                    with ui.row().classes("items-center gap-2"):
                        ui.label(e["简称"]).classes("t-lead font-bold")
                        ui.label(e["科目类型"]).classes("t-xs muted")
                    ui.label(e["名称"]).classes("t-body font-semibold")
                    ui.label(e["说明"]).classes("t-sm sub")
                    # 如实说明覆盖情况 —— 不写"敬请期待"这种空话，
                    # 也不假装内容已经齐全
                    if e["id"] == "408":
                        ui.label("18 年真题 846 道 · 266 个考点 · 依赖关系图") \
                            .classes("t-xs muted")
                        ui.button("进入 408",
                                  on_click=lambda: ui.navigate.to(
                                      f"/exam/408?user={user}")).props("unelevated")
                    else:
                        from yj import zhengzhi as _zz
                        _ys = _zz.years()
                        ui.label(f"已入库 {len(_ys)} 年真题"
                                 f"（{('、'.join(_ys)) if _ys else '整理中'}）"
                                 f"· 其余年份整理中") \
                            .classes("t-xs muted")
                        ui.label("政治暂无独立页面 —— 内容层正在补齐（考纲图谱 + 历年真题）") \
                            .classes("t-xs").style("color:#B45309")
                    ui.label(f"考生规模 {e['考生规模']}").classes("t-xs muted")

        ui.separator().style("border-color:var(--line)")

        # ---------- 首屏：一句话说清"你最近练了多少"
        ui.label("我的做题记录").classes("text-2xl font-bold")
        if not a:
            ui.label("还没有做题记录。先做一次诊断，或挑几个考点练几道。") \
                .classes("t-body sub")
        else:
            by_day = Counter(str(r.get("answered_at", ""))[:10]
                             for r in a.values())
            wk_start = today - datetime.timedelta(days=6)
            wk = [v for k, v in by_day.items()
                  if k >= wk_start.isoformat()]
            ui.label(f"共 {len(a)} 题　·　答对 {len(a) - len(wrong_ids)} 题　·　"
                     f"近 7 天做了 {sum(wk)} 题") \
                .classes("t-body sub")

        # ---------- 主行动点：仍然只给一个按钮（保留"今天该干嘛"的入口）
        if weakest:
            with ui.card().classes("softcard w-full p-4 gap-1").style("max-width:52rem"):
                ui.label(f'今天建议先补：{weakest["章节名"]}') \
                    .classes("t-lead font-bold")
                # 【措辞修正】原来写"这一章 18 年考了 141 次" —— 会被读成
                # "考了 141 场"。核实：141 是**该章 21 个叶子考点的考查次数之和**
                # （单考点最高才 24 次）。必须说清口径，否则是夸大。
                _ch = weakest.get("chapter")
                _lv = data.chapter_leaves().get(_ch, [])
                _fq = data.freq()
                _q = sum(data.leaf_question_count().get(l, 0) for l in _lv)
                ui.label(f'这一章有 {len(_lv)} 个考点，18 年真题里共出现 '
                         f'{weakest["考频"]} 次（各考点累计）；'
                         f'题库里有 {_q} 道该章的真题可练。') \
                    .classes("t-sm sub")
                ui.label("它是你目前最薄弱、同时考得又多的一章 —— 先补它性价比最高。") \
                    .classes("t-sm sub")
                ui.button("从这一章开始练",
                          on_click=lambda: ui.navigate.to(
                              f'/practice?subject={weakest.get("学科码", "DS")}'
                              f'&user={user}')).props("unelevated")

        if not a:
            return

        # ---------- 学习时间线：近 14 天，同时给"题数"和"当天正确率"
        ui.separator().style("border-color:var(--line)")
        ui.label("近 14 天").classes("t-lead font-semibold")
        ui.label("柱高＝当天做了几题；柱子下方是当天正确率。"
                 "看的是节奏稳不稳、正确率有没有往上走。").classes("t-sm muted")

        days = [today - datetime.timedelta(days=i) for i in range(13, -1, -1)]
        cnt = {d.isoformat(): by_day.get(d.isoformat(), 0) for d in days}
        right = Counter(str(r.get("answered_at", ""))[:10]
                        for r in a.values() if r["is_correct"])
        mx = max(list(cnt.values()) + [1])
        with ui.row().classes("gap-1 items-end"):
            for d in days:
                n = cnt[d.isoformat()]
                ok_n = right.get(d.isoformat(), 0)
                h = 6 + int(n / mx * 34)
                with ui.column().classes("gap-0 items-center"):
                    el = ui.element("div").classes("rounded") \
                        .style(f"width:20px;height:{h}px;"
                               f"background:{'#2563EB' if n else '#E6EAF0'};"
                               f"opacity:{0.35 + 0.65 * (n / mx) if n else 1};")
                    el.tooltip(f"{d.strftime('%m-%d')}：{n} 题"
                               + (f"，答对 {ok_n}" if n else ""))
                    ui.label(d.strftime('%m-%d').replace('-', '/')) \
                        .classes("t-xs muted").style("font-size:10px")
                    ui.label(f"{round(ok_n / n * 100)}%" if n else "—") \
                        .classes("t-xs").style(
                            "font-size:10px;color:"
                            + ("#1B5E36" if n and ok_n / n >= 0.6 else
                               "#8C2C2C" if n else "#9AA5B1"))

        total14 = sum(cnt.values())
        active = sum(1 for v in cnt.values() if v)
        today_n = cnt.get(today.isoformat(), 0)
        msg = f"近 14 天共 {total14} 题"
        if not today_n:
            msg += "　·　今天还没练"
        if active:
            msg += f"　·　{active} 天有练习记录"
        if total14 and active <= 2:
            msg += "　·　都挤在一两天 —— 分散开记得更牢"
        ui.label(msg).classes("t-sm muted")

        # ---------- 分科记录 + 待复习
        ui.separator().style("border-color:var(--line)")
        with ui.row().classes("w-full items-start gap-10 no-wrap"):
            with ui.column().classes("gap-1 flex-1 min-w-0"):
                ui.label("分科记录").classes("t-lead font-semibold")
                ui.label("只列原始事实（做过几题、对了几题），不做百分比换算 —— "
                         "每科题数少时百分比没有意义。").classes("t-sm muted")
                qs = data.questions()
                per = {}
                for qid, r in a.items():
                    q = qs.get(qid)
                    if not q:
                        continue
                    d = per.setdefault(q["学科"], [0, 0])
                    d[0] += 1
                    d[1] += 1 if r["is_correct"] else 0
                for name in data.CODE2NAME.values():
                    if name not in per:
                        continue
                    n, ok_n = per[name]
                    with ui.row().classes("items-center gap-3 no-wrap"):
                        ui.label(name).classes("t-sm w-32 shrink-0")
                        ui.label(f"答对 {ok_n} / 做过 {n} 题") \
                            .classes("t-sm font-semibold")

                # 学习节奏：全部来自作答时间戳，不用"连续打卡"这种没数据的说法
                ui.separator().style("border-color:var(--line)")
                ui.label("学习节奏").classes("t-lead font-semibold")
                _active = sum(1 for v in cnt.values() if v)
                _per = total14 / 14 if total14 else 0
                _best = max(cnt.items(), key=lambda kv: kv[1]) if total14 else None
                rows2 = [
                    ("近 14 天有练习的天数", f"{_active} / 14 天"),
                    ("平均每天", f"{_per:.1f} 题"),
                    ("做题最多的一天",
                     f"{_best[0][5:].replace('-', '/')}（{_best[1]} 题）"
                     if _best and _best[1] else "—"),
                    ("近 7 天", f"{sum(wk)} 题"),
                ]
                for k, v in rows2:
                    with ui.row().classes("items-center gap-3 no-wrap"):
                        ui.label(k).classes("t-sm muted w-44 shrink-0")
                        ui.label(v).classes("t-sm font-semibold")

            with ui.column().classes("gap-1 w-[24rem] shrink-0"):
                ui.label("待复习的错题").classes("t-lead font-semibold")
                if wrong_ids:
                    ui.label(f"{len(wrong_ids)} 道题做错了还没重做。"
                             f"做错的题最能暴露问题。").classes("t-sm muted")
                    # 按考点归组：比列 10 条题号更有用（知道是哪块不行）
                    bad = Counter(data.node_name(qs[qid]["主考点"])
                                  for qid in wrong_ids if qid in qs)
                    for name, n in bad.most_common(6):
                        with ui.row().classes("items-center gap-2 no-wrap"):
                            ui.label(f"{n} 题") \
                                .classes("t-sm font-semibold shrink-0") \
                                .style("color:#8C2C2C;min-width:2.6rem")
                            ui.label(name[:20]).classes("t-sm muted truncate")
                    ui.button("去错题模式重做",
                              on_click=lambda: ui.navigate.to(
                                  f"/exam/408?view=只错题&user={user}")) \
                        .props("flat dense")
                else:
                    ui.label("没有待复习的错题 —— 目前做过的题都对了。") \
                        .classes("t-sm muted")


# ================================================================ 真题页
def _answer_sheet(shown, done, cur, pages_n, goto):
    """
    **答题卡**（真题页共用：408 与政治）。

    用户问过"为什么政治部分没有像 408 那样的答题卡" —— 原来只有 408 有，
    政治页漏了。抽成共享函数，两页行为一致，也避免以后各自改一套。

    形态说明（这是之前按用户要求改过的）：
      · 从左侧竖栏改成**题目区上方的一条横卡** —— 用户要求"答题卡放第一题上面"，
        改完题目区宽 +240px，且 47 个格子横排只占 2 行
      · 格子颜色：绿=答对、红=答错、白=未做、加深边框=当前页
      · 点格子跳到对应页
    """
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
                        ui.label(str(q["题号"])).classes("t-xs")
            ui.label("绿=对 · 红=错 · 白=未做").classes("t-xs muted shrink-0")
            ui.button(icon="chevron_left",
                      on_click=lambda: goto(page=max(1, cur - 1))) \
                .props("flat dense").set_enabled(cur > 1)
            ui.label(f"{cur} / {pages_n}").classes("t-sm shrink-0") \
                .style("white-space:nowrap")
            ui.button(icon="chevron_right",
                      on_click=lambda: goto(page=min(pages_n, cur + 1))) \
                .props("flat dense").set_enabled(cur < pages_n)


def _exam_tabs(active_id, page, user, extra=""):
    """
    科目切换条（真题页与练习页共用）。

    用户要求："分块部分应该在挑考点练习那里，那里也设置一个 408 入口一个政治入口"。

    所以这一条在**两个页面**都要有，且行为一致：
        page="exam"     → 跳到真题路由（由科目注册表的「真题路由」决定）
        page="practice" → 跳到同一页的不同 exam 参数
    以后加数学/英语时，只要在 EXAMS 里把科目设为可用，两处自动出现。
    """
    with ui.row().classes("items-center gap-2 flex-wrap"):
        for e in data.exam_list():
            if not e.get("可用"):
                # 规划中的科目：显示但不可点，并注明 —— 不假装有
                ui.button(f'{e["简称"]}（规划中）').props("flat dense disable")
                continue
            on = (e["id"] == active_id)
            if page == "practice":
                target = f'/practice?exam={e["id"]}&user={user}'
            else:
                target = f'{e.get("真题路由") or "/exam"}?user={user}'
            ui.button(e["简称"],
                      on_click=lambda _=None, t=target: ui.navigate.to(t)) \
                .props("unelevated" if on else "flat dense")


def _practice_english(tier, part, go, user, goto):
    """
    英语练习：**按题型**练（英语的"块"是题型，不是章节）。

    为什么按题型而不是按年：英语的提分点是**题型熟练度** ——
    完形靠词汇与逻辑衔接、阅读靠定位与同义替换、新题型靠衔接词。
    按年份刷整卷适合模考，按题型刷适合专项突破。

    题库来自 yj.english.questions()，**只收有答案的题** ——
    练习必须能判分，否则练了也不知道对错。
    """
    tiers = en.tier_list()
    tier = tier if tier in [t["id"] for t in tiers] else "EN1"
    tn = en.TIERS[tier]["简称"]
    done = store.get_answers(user)

    def tier_bar():
        with ui.row().classes("items-center gap-2 flex-wrap"):
            for t in tiers:
                on = t["id"] == tier
                ui.button(t["简称"], on_click=lambda _=None, x=t["id"]:
                          goto(subject=x, part=None, go=0)) \
                    .props("unelevated" if on else "flat dense")

    # 题型 → 题号区间
    KINDS = [("CLOZE", "完形填空", (1, 20), "词汇与逻辑衔接"),
             ("READ", "阅读理解", (21, 40), "定位与同义替换"),
             ("NEW", "新题型", (41, 45), "段际衔接与匹配")]
    if part:
        kind = next((k for k in KINDS if k[0] == part), KINDS[0])
        pool = [q for q in en.questions(tier).values()
                if kind[2][0] <= int(q["题号"]) <= kind[2][1]
                and (en.explanation(tier, q["year"], q["题号"]) or {}).get("答案")]
        with ui.row().classes("items-center gap-2"):
            ui.label(f'{tn} · {kind[1]}').classes("t-lead font-bold")
            ui.button("← 换题型", on_click=lambda: goto(part=None, go=0)) \
                .props("flat dense")
        tier_bar()
        n_done = sum(1 for q in pool if q["id"] in done)
        ui.label(f'题库 {len(pool)} 道（2010–2026 汇总）· 已作答 {n_done} 道') \
            .classes("t-sm muted")
        ui.button(f"▶ 开始练习（共 {len(pool)} 道）",
                  on_click=lambda: goto(go=1)).props("unelevated")
        if not go:
            return
        pool.sort(key=lambda q: (q["id"] in done, -int(q["year"])))
        ui.separator()
        ui.label(f"练习：共 {len(pool)} 道").classes("t-lead font-bold")
        for q in pool[:60]:                  # 一次最多铺 60 道，避免页面过长
            _en_single(q, tier, done, user)
        if len(pool) > 60:
            ui.label(f'（只显示前 60 道，共 {len(pool)} 道）').classes("t-xs muted")
        return

    tier_bar()
    ui.label("按题型练 —— 英语的提分点是题型熟练度，"
             "不是按年份刷整卷。").classes("t-body")
    all_q = list(en.questions(tier).values())
    with ui.row().classes("w-full gap-3 items-stretch flex-wrap"):
        for code, name, (lo, hi), desc in KINDS:
            pool = [q for q in all_q if lo <= int(q["题号"]) <= hi
                    and (en.explanation(tier, q["year"], q["题号"]) or {}
                         ).get("答案")]
            with ui.card().classes("bookcard p-4 gap-1 shadow-none") \
                    .style("flex:0 0 18.5rem;max-width:18.5rem"):
                with ui.row().classes("items-center gap-2"):
                    ui.label(name).classes("t-lead font-bold")
                    ui.label(f'{lo}–{hi} 题').classes("t-xs muted")
                ui.label(desc).classes("t-sm sub")
                ui.label(f'可练 {len(pool)} 道').classes("t-sm font-semibold")
                ui.button("进入练习", on_click=lambda _=None, c=code:
                          goto(part=c, go=0)).props("unelevated") \
                    .classes("w-full mt-1")


def _en_single(q, tier, done, user):
    """英语练习里的一道题（复用 passage_card 的小题渲染）。"""
    from proto.cards_en import _sub_question
    _sub_question(q, q["year"], tier, done, user)


def _practice_zhengzhi(part, go, user, goto):
    """
    政治练习：**按官方五个部分**出题。

    这是"分块"的正确位置 —— 用户要求真题页按题号平铺、
    把分块放到练习页（"分块部分应该在挑考点练习那里"）。

    题库来自 yj.zhengzhi.part_pool()，只收**有答案且有解析**的题：
    练习必须能判分、能看解析，否则练了也不知道对错。
    """
    summary = zz.part_summary()

    if not part:
        ui.label("按部分练 —— 只练一个部分，而不是刷整卷。"
                 "题量来自 2010–2026 全部 17 年真题。").classes("t-body")
        # 【等宽排布】实测用 flex:1 时，5 张卡片换行后最后一张会独占整行
        # （3+1 的难看布局）。这里固定每张的基准宽度并禁止拉伸，
        # 让它自然排成 3+2 —— 换行后宽度仍一致。
        with ui.row().classes("w-full gap-3 items-stretch flex-wrap"):
            for code in ("MY", "MZT", "SG", "SX", "SZ"):
                v = summary.get(code) or {}
                with ui.card().classes("bookcard p-4 gap-1 shadow-none") \
                        .style("flex:0 0 18.5rem;max-width:18.5rem"):
                    with ui.row().classes("items-center gap-2"):
                        ui.label(v.get("简称", code)).classes("t-lead font-bold")
                        ui.label(f'官方 {v.get("分值", 0)} 分') \
                            .classes("t-xs muted")
                    ui.label(v.get("名称", "")).classes("t-sm sub")
                    ui.label(f'可练 {v.get("可练", 0)} 道'
                             f'（单选 {v.get("单选", 0)} · 多选 {v.get("多选", 0)}）') \
                        .classes("t-sm font-semibold")
                    ui.label(f'覆盖 {v.get("年份数", 0)} 个年份').classes("t-xs muted")
                    ui.button("进入练习",
                              on_click=lambda _=None, c=code:
                              goto(part=c, go=0)).props("unelevated") \
                        .classes("w-full mt-1")
        return

    pool = zz.part_pool(part=part)
    nm = zz.PART_SHORT.get(part, part)
    with ui.row().classes("items-center gap-2"):
        ui.label(f"{nm} · 练习").classes("t-lead font-bold")
        ui.button("← 换一部分", on_click=lambda: goto(part=None, go=0)) \
            .props("flat dense")
    ui.label(zz.PARTS.get(part, "")).classes("t-sm sub")

    done = store.get_answers(user)
    n_done = sum(1 for q in pool if q["id"] in done)
    ui.label(f"题库 {len(pool)} 道（17 年真题汇总）· 已作答 {n_done} 道"
             f'　·　官方分值 {zz.PART_SCORE.get(part, 0)} 分').classes("t-sm muted")

    if not go:
        ui.button(f"▶ 开始练习（共 {len(pool)} 道）",
                  on_click=lambda: goto(go=1)).props("unelevated")
        ui.label("排序：未做过的优先 → 多选在前 → 年份新优先。"
                 "每道题提交后都会给出答案与解析。").classes("t-sm muted")
        return

    # 排序：没做过的优先 → 多选优先（多选更难、更值得练）→ 年份新优先。
    # 【不截断】用户明确要求过"题库里有几道就几道"。
    pool.sort(key=lambda q: (q["id"] in done,
                             q["题型"] != "多项选择题",
                             -int(q["year"])))
    ui.separator()
    ui.label(f"练习：共 {len(pool)} 道").classes("t-lead font-bold")
    ui.label("已做过的题会显示你的作答与解析。").classes("t-sm muted")
    for q in pool:
        question_card(q, q["year"], done, user, exam="ZZ")


def _subject_tabs(active_id, user):
    """
    真题页顶部的**科目切换条**。

    用户要求："408 历年真题 换成 考研历年真题，并且提供 408 真题和政治真题选项。
    以后我还要加入考研数学和考研英语"。

    所以这一条是"以科目为维度"的导航 —— 以后加数学/英语时，
    **只需要在 yj/data.py 的 EXAMS 里把新科目设为可用、填上真题路由**，
    这里和首页会自动出现，不用再改界面代码。
    """
    with ui.row().classes("items-center gap-2 flex-wrap"):
        ui.label("考研历年真题").classes("text-2xl font-bold mr-3")
        for e in data.exam_list():
            if e.get("可用") and e.get("真题路由"):
                on = (e["id"] == active_id)
                ui.button(e["简称"],
                          on_click=lambda _=None, r=e["真题路由"]: ui.navigate.to(
                              f"{r}?user={user}")) \
                    .props("unelevated" if on else "flat dense") \
                    .classes("" if on else "ml-0")
            else:
                # 规划中的科目：显示但**不可点**，并注明"规划中" ——
                # 不假装有，也不隐藏（用户明确说要加数学和英语，展示路线图是诚实的）
                ui.button(f'{e["简称"]}（规划中）').props("flat dense disable")


@ui.page("/exam")
def exam_hub(user: str = "demo"):
    """
    真题总入口：**先选科目**。

    原来导航里是"408 历年真题"，加政治后变成两项并列 —— 那样每加一科
    导航就长一条。改成"考研历年真题"一个入口 + 科目卡片，
    以后加数学/英语只是多一张卡。
    """
    store.ensure_user(user)
    with shell("/exam", user):
        ui.label("考研历年真题").classes("text-2xl font-bold")
        ui.label("按科目进入。每科都是独立的考纲与真题库，作答记录也按科目分开。") \
            .classes("t-body sub")

        ready = [e for e in data.exam_list() if e.get("可用")]
        planned = [e for e in data.exam_list() if not e.get("可用")]

        with ui.row().classes("w-full gap-4 items-stretch mt-2"):
            for e in ready:
                with ui.card().classes("softcard flex-1 p-4 gap-1"):
                    with ui.row().classes("items-center gap-2"):
                        ui.label(e["简称"]).classes("t-lead font-bold")
                        ui.label(e["科目类型"]).classes("t-xs muted")
                    ui.label(e["名称"]).classes("t-body font-semibold")
                    ui.label(e["说明"]).classes("t-sm sub")
                    ui.label(e.get("题量说明", "")).classes("t-xs muted")
                    ui.label(f'考生规模 {e["考生规模"]}').classes("t-xs muted")
                    ui.button(f'进入{e["简称"]}真题',
                              on_click=lambda _=None, r=e["真题路由"]:
                              ui.navigate.to(f"{r}?user={user}")) \
                        .props("unelevated")

        if planned:
            ui.label("规划中").classes("t-lead font-semibold mt-4")
            ui.label("这两科还没入库 —— 列在这里是为了让你知道路线图，"
                     "不是已经能用。").classes("t-sm").style("color:#B45309")
            with ui.row().classes("w-full gap-4 items-stretch"):
                for e in planned:
                    with ui.card().classes("softcard flex-1 p-4 gap-1") \
                            .style("opacity:.65"):
                        with ui.row().classes("items-center gap-2"):
                            ui.label(e["简称"]).classes("t-lead font-bold")
                            ui.label("规划中").classes("t-xs") \
                                .style("color:#B45309")
                        ui.label(e["名称"]).classes("t-body font-semibold")
                        ui.label(e["说明"]).classes("t-sm sub")


@ui.page("/exam/408")
def exam_408(year: str = None, page: int = 1, view: str = "全部", user: str = "demo"):
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
        ui.navigate.to("/exam/408?" + "&".join(f"{k}={v}" for k, v in s.items()))

    with shell("/exam", user):
        _subject_tabs("408", user)
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
            # 【把"筛选后剩几道"说清楚】政治页一直有这一项，408 原来没有 ——
            # 切到"未做/只错题"后看不出筛掉多少，容易让人以为筛选出错了。
            if view != "全部":
                info += f'　|　筛选「{view}」下 {len(shown)} 道'
            ui.label(info).classes("t-sm muted")

        _answer_sheet(shown, done, cur, pages_n, goto)

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


# ================================================================ 考研政治真题
@ui.page("/zz")
def zz_legacy(user: str = "demo"):
    """旧路由 /zz → 跳到新的 /exam/zhengzhi（避免已存的链接失效）"""
    ui.navigate.to(f"/exam/zhengzhi?user={user}")


@ui.page("/exam/zhengzhi/index")
def zz_index(user: str = "demo"):
    """
    政治真题入口：按年份进入。

    为什么先只做"年份 → 做题"这一层
    -------------------------------
    政治的内容积累是渐进的（目前 5 年 190 道，目标 11+ 年）。先把"能看、能练"
    这条路打通，比先建一套考纲图谱更实用 —— 题库本身对学生就有价值，
    而图谱/诊断/讲义都可以在数据齐了之后再加，不必一次做满。
    """
    store.ensure_user(user)
    with shell("/zz", user):
        _title("考研政治 · 历年真题")
        ys = zz.years()
        if not ys:
            ui.label("政治真题还没有入库。").classes("t-body sub")
            return
        rec = zz.paper(ys[-1])
        n_obj = sum(1 for i in rec["题目"]
                    if i["题型"] in ("单项选择题", "多项选择题"))
        ui.label(f"已入库 {len(ys)} 个年份（{'、'.join(ys)}），共 "
                 f"{sum(len(zz.paper(y)['题目']) for y in ys)} 道题。"
                 f"每份试卷 16 道单选 + 17 道多选（可机判）+ 5 道分析题。") \
            .classes("t-body sub")
        ui.label("答案已用多轮独立求解投票校验 —— 政治真题的公开版本错误率不低"
                 "（实测某年多选约 30% 有误），所以没有直接采用题源答案。") \
            .classes("t-sm").style("color:#B45309")

        with ui.row().classes("w-full gap-4 items-stretch mt-2"):
            for y in reversed(ys):
                r = zz.paper(y)
                st = zz.part_stats(y)
                done_n = sum(1 for i in r["题目"]
                             if f"ZZ-{y}-{i['题号']}" in store.get_answers(user))
                with ui.card().classes("softcard flex-1 p-4 gap-1"):
                    ui.label(f"{y} 年").classes("t-lead font-bold")
                    parts = " · ".join(
                        f'{zz.PART_SHORT.get(k, k)} {v["分值"]}'
                        for k, v in sorted(st.items(), key=lambda x: -x[1]["分值"]))
                    ui.label(parts).classes("t-sm sub")
                    ui.label(f"38 道（客观题 33 道可判分）· 已作答 {done_n} 道") \
                        .classes("t-xs muted")
                    ui.button(f"做 {y} 年真题",
                              on_click=lambda yy=y: ui.navigate.to(
                                  f"/exam/zhengzhi?year={yy}&user={user}")) \
                        .props("unelevated")


@ui.page("/exam/zhengzhi")
def exam_zhengzhi(year: str = None, page: int = 1, user: str = "demo",
                  view: str = "全部"):
    """
    政治某年真题：**按题号顺序平铺**（不按部分分块）。

    分块（按部分练）在挑考点练习页 —— 用户要求
    "真题部分要按照题目顺序……分块部分应该在挑考点练习那里"。
    """
    store.ensure_user(user)
    ys = zz.years()
    if not ys:
        with shell("/exam", user):
            _title("考研政治 · 历年真题")
            ui.label("政治真题还没有入库。").classes("t-body sub")
        return
    year = year if year in ys else ys[-1]
    rec = zz.paper(year)
    done = store.get_answers(user)

    # 【筛选用函数参数，不用控件的 .value】原来这里读 ui.toggle 的 .value 做判断，
    # 而切换实际靠 URL 跳转（on update:model-value → navigate.to），
    # 于是"未做/只错题"点进去筛的是**上一帧的值** —— 表现为点"未做"后
    # 显示的结果不对。408 真题页一直是用参数 view 判断的，这里与它对齐。
    def goto(**kw):
        s = {"year": year, "page": cur, "view": view, "user": user}
        s.update(kw)
        s = {k: v for k, v in s.items() if v not in (None, "", 0)}
        ui.navigate.to("/exam/zhengzhi?" + "&".join(f"{k}={v}"
                                                    for k, v in s.items()))

    with shell("/exam", user):
        _subject_tabs("ZZ", user)
        ui.label(f"{year} 年考研政治真题").classes("text-2xl font-bold")
        st = zz.part_stats(year)
        parts = " · ".join(f'{zz.PART_SHORT.get(k, k)} {v["分值"]} 分'
                           for k, v in sorted(st.items(), key=lambda x: -x[1]["分值"]))
        ui.label(parts).classes("t-sm sub")

        # 年份切换 + 筛选（与 408 真题页保持同一套交互）
        with ui.row().classes("items-center gap-3 flex-wrap"):
            ui.select({y: f"{y} 年" for y in reversed(ys)}, value=year,
                      label="年份",
                      on_change=lambda e: goto(year=str(e.value))) \
                .props("dense outlined").classes("w-28")
            ui.toggle(["全部", "未做", "只错题"], value=view,
                      on_change=lambda e: goto(view=e.value)) \
                .props("dense unelevated")

        obj = [i for i in rec["题目"]
               if i["题型"] in ("单项选择题", "多项选择题")]
        ana = [i for i in rec["题目"] if i["题型"] not in
               ("单项选择题", "多项选择题")]
        shown = []
        for it in obj:
            it = dict(it)
            it["id"] = f"ZZ-{year}-{it['题号']}"
            r = done.get(it["id"])
            if view == "未做" and r:
                continue
            if view == "只错题" and (not r or r["is_correct"]):
                continue
            shown.append(it)

        # 分页：33 道客观题按 PER=10 分页，与 408 同一套节奏
        pages_n = max(1, (len(shown) + PER - 1) // PER)
        cur = max(1, min(int(page or 1), pages_n))

        n_ans = sum(1 for i in obj if f"ZZ-{year}-{i['题号']}" in done)
        n_ok = sum(1 for i in obj
                   if (done.get(f"ZZ-{year}-{i['题号']}") or {}).get("is_correct"))
        ui.label(f"客观题 {len(obj)} 道 · 已作答 {n_ans} 道"
                 + (f" · 答对 {n_ok} 道" if n_ans else "")
                 + f"　（当前显示 {len(shown)} 道）") \
            .classes("t-sm muted")

        _answer_sheet(shown, done, cur, pages_n, goto)

        if not shown:
            ui.label(f"筛选「{view}」下没有题目。").classes("t-sm muted")
            return
        # 【按题号顺序平铺，不按部分分块】
        # 用户要求："政治真题部分你要按照题目顺序来啊，在这部分内容不要分块，
        # 分块部分应该在挑考点练习那里。"
        # 理由也站得住：真题是按题号**连续作答**的，拆成五个可折叠块之后
        # 得反复展开/收起，也看不出题号顺序。每题仍带部分标签（马原/毛中特/…），
        # 信息没有丢失；要"按部分针对性练"去挑考点练习页。
        items = shown[(cur - 1) * PER: cur * PER]
        ui.label(f'第 {items[0]["题号"]}–{items[-1]["题号"]} 题'
                 f'（共 {len(shown)} 道）').classes("t-lead font-semibold")
        for it in items:
            question_card(it, year, done, user, exam="ZZ")

        if ana:
            ui.separator().style("border-color:var(--line)")
            ui.label("分析题（主观题，50 分）").classes("t-lead font-semibold")
            ui.label("政治分析题是手写论述题，没有唯一答案，因此不做自动判分 —— "
                     "这里只展示题干，供你对照教材自己组织答案。") \
                .classes("t-sm").style("color:#B45309")
            for it in ana:
                with ui.card().classes("softcard w-full p-3 gap-1"):
                    with ui.row().classes("items-center gap-2"):
                        ui.label(f'第 {it["题号"]} 题').classes("font-semibold")
                        ui.label(f'{it["题型"]} · {it["分值"]} 分') \
                            .classes("text-xs text-gray-500")
                        if it.get("部分名"):
                            ui.label(it["部分名"]).classes("text-xs") \
                                .style(f'color:{ZZ_PART_COLORS.get(it.get("部分"), "#2563EB")}')
                    ui.label(it["题干"]).classes("text-[15px] leading-6 whitespace-pre-wrap")


# ================================================================ 考研英语真题
def _tier_tabs(active_tier, year, view, user):
    """
    **卷种切换条**（英语一 / 英语二）。

    用户指出："英语和数学和政治不同的，他是分英几的" —— 对。
    政治/408 是一科一卷，英语一科两卷种，所以真题页顶部要有这一条。
    以后数学（数一/二/三）复用同一个组件。
    """
    with ui.row().classes("items-center gap-2 flex-wrap"):
        ui.label("考研英语").classes("text-2xl font-bold mr-3")
        for t in en.tier_list():
            on = (t["id"] == active_tier)
            ui.button(t["简称"],
                      on_click=lambda _=None, x=t["id"]: ui.navigate.to(
                          f"/exam/english?tier={x}&user={user}")) \
                .props("unelevated" if on else "flat dense")
        n_years = len(en.years(active_tier))
        tl = next((x for x in en.tier_list() if x["id"] == active_tier), {})
        ui.label(f'{tl.get("适用", "")}　·　已入库 {n_years} 年'
                 f'（{tl.get("首年", "")}–{tl.get("末年", "")}）') \
            .classes("t-sm muted ml-2")


@ui.page("/exam/english")
def exam_english(tier: str = "EN1", year: str = None, view: str = "全部",
                 page: int = 1, user: str = "demo"):
    """
    英语某年真题：**按篇目渲染**（完形 / 阅读 / 新题型 ...）。

    与政治页的关键差别：英语是**复合题** —— 一篇文章挂多道小题，
    所以不能一题一卡地平铺（那样文章会重复 5 次）。
    """
    store.ensure_user(user)
    tiers = [t["id"] for t in en.tier_list()]
    tier = tier if tier in tiers else "EN1"
    ys = en.years(tier)
    if not ys:
        with shell("/exam", user):
            _tier_tabs(tier, None, view, user)
            ui.label("英语真题还没有入库。").classes("t-body sub")
        return
    year = str(year) if str(year) in ys else ys[-1]
    rec = en.paper(tier, year)
    done = store.get_answers(user)
    tn = en.TIERS[tier]["简称"]

    def goto(**kw):
        s = {"tier": tier, "year": year, "view": view, "user": user}
        s.update(kw)
        s = {k: v for k, v in s.items() if v not in (None, "", 0)}
        ui.navigate.to("/exam/english?" + "&".join(f"{k}={v}"
                                                   for k, v in s.items()))

    with shell("/exam", user):
        _tier_tabs(tier, year, view, user)
        ui.label(f"{year} 年{tn}真题").classes("text-2xl font-bold mt-1")

        st = en.part_stats(tier, year)
        parts = " · ".join(
            f'{en.PARTS[c]["简称"]} {v["小题数"]} 题'
            for c, v in st.items() if c in en.PARTS)
        ui.label(parts).classes("t-sm sub")

        with ui.row().classes("items-center gap-3 flex-wrap"):
            ui.select({y: f"{y} 年" for y in reversed(ys)}, value=year,
                      label="年份", on_change=lambda e: goto(year=str(e.value))) \
                .props("dense outlined").classes("w-28")
            ui.toggle(["全部", "未做", "只错题"], value=view,
                      on_change=lambda e: goto(view=e.value)) \
                .props("dense unelevated")

        # 逐篇目收集小题，按 view 过滤
        def keep(q):
            r = done.get(q["id"])
            if view == "未做":
                return not r
            if view == "只错题":
                return bool(r) and not r["is_correct"]
            return True

        shown = []
        for ps in rec.get("篇目", []):
            subs = [q for q in ps.get("小题", []) if keep(q)]
            if subs:
                shown.append({**ps, "小题": subs})
        n_obj = sum(len(ps.get("小题", [])) for ps in rec.get("篇目", []))
        n_done = sum(1 for ps in rec.get("篇目", []) for q in ps.get("小题", [])
                     if q["id"] in done)
        ui.label(f"客观题 {n_obj} 题 · 已作答 {n_done} 道"
                 + (f'　（当前显示 {sum(len(p["小题"]) for p in shown)} 题）'
                    if view != "全部" else "")).classes("t-sm muted")

        if not shown:
            ui.label(f"筛选「{view}」下没有题目。").classes("t-sm muted")
            return
        for ps in shown:
            code = ps.get("部分")
            if code == "CLOZE":
                cloze_card(ps, year, tier, done, user)
            elif code in ("TRANS", "WRITE"):
                # 主观题：不自动判分，走 AI 评阅（cards_en.subjective_block）
                with ui.card().classes("softcard w-full p-2 gap-1 shadow-none"):
                    with ui.row().classes("items-center gap-2"):
                        ui.label(ps.get("部分全称") or ps.get("部分名") or code) \
                            .classes("t-lead font-bold")
                        ui.label("主观题").classes("t-xs muted")
                for q in ps.get("小题", []):
                    subjective_block(q, year, tier, done, user)
            else:
                # 阅读与新题型：**左文章 / 右题目**两栏（用户要求）
                two_col(ps, year, tier, done, user)


# ================================================================ 挑考点练习
@ui.page("/practice")
def practice(exam: str = None, subject: str = None, chapter: str = None,
             part: str = None, go: int = 0, user: str = "demo"):
    """
    挑考点练习 —— **两个入口：408 / 政治**。

    用户要求："分块部分应该在挑考点练习那里，那里也设置一个408入口一个政治入口"。

    两个科目的"块"层级不同，各按自己的结构呈现：
        408  ：4 门课（数据结构 / 组成原理 / 操作系统 / 计算机网络）
               → 章 → 节 → 考点（有依赖图，可勾选薄弱点）
        政治 ：5 个部分（马原 / 毛中特 / 史纲 / 思修法基 / 时政）
               政治**没有 408 那样的考点依赖图**，所以这里只做到"部分"这一层 ——
               界面上不假装有更细的考点选择（那会是编的）。
    """
    store.ensure_user(user)
    marks = store.get_marks(user)

    def goto(**kw):
        s = {"exam": exam, "subject": subject, "chapter": chapter,
             "part": part, "go": go, "user": user}
        s.update(kw)
        s = {k: v for k, v in s.items() if v not in (None, "", 0)}
        ui.navigate.to("/practice?" + "&".join(f"{k}={v}" for k, v in s.items()))

    with shell("/practice", user):
        _title("挑考点练习")
        _exam_tabs(exam, "practice", user)

        # ---------------- 第 0 层：先选科目 ----------------
        if not exam:
            ui.label("先选一科，再挑要练的部分或考点。两科的「块」不一样："
                     "408 有 266 个考点可勾选，政治按官方五个部分划分。") \
                .classes("t-body")
            with ui.row().classes("w-full gap-4 items-stretch"):
                for e in data.exam_list():
                    if not e.get("可用"):
                        continue
                    with ui.card().classes("bookcard flex-1 p-4 gap-1 shadow-none"):
                        ui.label(e["简称"]).classes("t-lead font-bold")
                        ui.label(e["名称"]).classes("t-sm sub")
                        ui.label(e.get("题量说明", "")).classes("t-sm sub")
                        if e["id"] == "408":
                            ui.label("4 门课 → 章 → 节 → 266 个考点可勾选") \
                                .classes("t-xs muted")
                        else:
                            ui.label("5 个部分（马原/毛中特/史纲/思修法基/时政）") \
                                .classes("t-xs muted")
                        ui.button(f'进入{e["简称"]}练习',
                                  on_click=lambda _=None, x=e["id"]:
                                  goto(exam=x)).props("unelevated") \
                            .classes("w-full mt-1")
            return

        # ---------------- 政治分支 ----------------
        if exam == "ZZ":
            _practice_zhengzhi(part, go, user, goto)
            return
        if exam == "ENG":
            _practice_english(subject, part, go, user, goto)
            return

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
            # 按钮文案要给出**真实题数**，不能写死"抽 5 道"（那是旧的截断行为）。
            # 用勾选考点在题库里的单选题总数计算。
            _pool_n = sum(1 for l in marks
                          for q in data.questions().values()
                          if q["主考点"] == l
                          and q["题型"] == "单项选择题" and q.get("答案"))
            ui.button(f"▶ 开始练习（共 {_pool_n} 道真题）",
                      on_click=lambda: goto(go=1)).props("unelevated")
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
        # 【不截断】用户明确要求："题库里有几道就几道"。
        # 原来这里写死 pool[:5] —— 与讲义页同一个毛病（那边也把 5 改成了全量）。
        # 实测规模可控：单考点最多 17 道；勾 5 个热点考点 76 道、勾 10 个 139 道。
        # 排序仍是"没做过的优先 → 难度低优先 → 年份新优先"，越靠前越该先做。
        show = pool
        ui.label(f"练习：共 {len(show)} 道（优先你没做过的、难度低的）") \
            .classes("t-lead font-bold")
        ui.label("按「未做过 → 难度低 → 年份新」排序；已做过的题会显示你的作答与解析。") \
            .classes("t-sm muted")
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

        # 【位置很关键】历史清空入口必须在"没有数据就 return"之前 ——
        # 清空之后本页就没有数据了，如果把入口放在后面，用户清完就再也找不到它，
        # 只能再手动做几道题把页面"喂"出数据才能再来清一次（实测的荒谬循环）。
        _reset_panel(user)

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
        # 【删掉了学科级"7 / 8"那组方块】它与首页的「分科记录」完全重复。
        # 两页分工应当是：
        #     首页「我的做题记录」= 按**时间**看记录（时间线、节奏、趋势）
        #     我的画像           = 按**章节**看知识结构（哪章强、哪章弱）
        # 学科级一行只是章节级的汇总，留在首页即可；这里直接从章节开始。
        if mk:
            ui.label(f"另有你自报的 {len(mk)} 个薄弱考点，已计入下方排序。") \
                .classes("t-sm")

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


# 【已删除】/paths「学习路径」页面 —— 用户判断"感觉不到用处，对用户来讲没多大
# 用处"，要求删除。
# 删的是**用户可见的页面**（三条路径让你自己选）。yj/path.py 算法**保留** ——
# 六 Agent 链路里的「路径 Agent」靠它决定给「我的薄弱点」生成哪几个考点，
# 连算法一起删会让那个页面不知道生成什么（已确认依赖，见 yj/graph.py）。
# 若要恢复该页面：git show 6d0d528:proto/app.py（或本次提交的父提交）


@ui.page("/notes")
def notes_page(user: str = "demo"):
    snap_name = {"v": None}
    a, mk = store.get_answers(user), store.get_marks(user)
    with shell("/notes", user):
        # 【改名理由】原名"讲义生成"是实现视角（生成是工具的动作），
        # 而且把最有价值的部分盖住了 —— 整条链路的重点是"前面的诊断决定给你
        # 生成哪几个考点"。用户提议的"个人薄弱点追踪"定位更好，但"追踪"描述
        # 的不是这页在做的事（追踪在「我的画像」那页）：
        #   画像   = 我现在的数据长什么样
        #   薄弱点 = 针对这些弱点，给我讲义/速记/配套真题
        # 所以采用"我的薄弱点"作名字，用副标题说清产出与链路。
        _title("我的薄弱点")
        # 用 ui.label 就**不能写 Markdown 加粗** —— 星号会原样显示出来
        # （实测：副标题里出现了字面的 **）。要加粗得改用 ui.markdown。
        # 这里选择不加粗：靠 ui.label 的体量已经够突出。
        ui.label("按你答错和自报的薄弱考点，生成讲义 · 知识点速记 · 配套真题"
                 "（只给系统算出来最该补的那几个考点，不是把 266 个考点全生成）。") \
            .classes("t-body")
        # 【只报异常】原来这里始终显示"● 已配置：请求模型 deepseek-chat @ …"，
        # 用户明确要求删掉 —— 对使用者没有价值（模型名、base_url 是技术细节）。
        # 但**未配置时必须警告**：那时正文会降级成模板，不说明就等于拿模板冒充 AI。
        # 技术细节挪到下方"生成过程"折叠项里，需要时可查。
        ok, _msg = llm.status()
        if not ok:
            ui.label("⚠ 未配置 LLM —— 生成的内容会是「用真实数据填的模板」，"
                     "不是 AI 写的。") \
                .classes("t-sm").style("color:#8A6D3B")
        if not a and not mk:
            ui.label("还没有数据。先到「挑考点练习」勾选薄弱知识点。") \
                .classes("t-sm").style("color:#8A6D3B")
            return

        # 不再让用户选路径（三条路径高度重合、还得用户自己判断，用户已否掉这个
        # 交互形式）。内部仍跑路径 Agent，自动取第一条作为生成依据。
        rec = path_mod.recommend(a, marks=mk)
        _picked = (rec["路径"] or [{}])[0]
        names = [_picked.get("名称", "补根因")]
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
                    # 模型与接口信息挪到这里 —— 页面上不显示（用户明确要求），
                    # 但被问"你用的什么模型"时能当场展开给出来。
                    _ok, _msg = llm.status()
                    ui.label(_msg).classes("t-xs muted")
                    ui.label("链路：准备 → 诊断 → 画像 → 路径 → 生成 → 复核"
                             "（LangGraph 六 Agent）").classes("t-xs muted")
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
                            ui.tab(f'配套真题（{len(x["习题"])}）'
                                   if x.get("习题") else '配套真题')
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
                            with ui.tab_panel(f'配套真题（{len(x["习题"])}）'
                                              if x.get("习题") else '配套真题'):
                                # 【一键全展开】用户反复强调"不用一个 一个查找"。
                                #
                                # 我第一版让每题返回一个 set_shown 函数、总开关循环调用
                                # 它们 —— 实测**只有第一题的 handler 生效**（服务端日志
                                # 显示 items=1，而循环确实 append 了 5 次）。这是 NiceGUI
                                # 客户端事件绑定的内部行为，不值得继续挖。
                                #
                                # 改成不依赖多个 handler：每题的展开按钮带一个统一的
                                # CSS 类，总开关用 run_javascript 在浏览器端一次性点击
                                # 所有按钮。状态由每个按钮自己的文案判断（"查看答案" vs
                                # "收起答案"），所以展开/收起都不会错。
                                ui.label("这些题都来自该考点的历年真题，题干与选项"
                                         "直接列出，答案与解析默认收起。") \
                                    .classes("t-sm muted")
                                ui.button("显示全部答案与解析", on_click=lambda: ui.run_javascript(
                                    """document.querySelectorAll('button.exam-reveal')
                                         .forEach(b => { if (b.innerText.trim() === '查看答案') b.click(); })""")) \
                                    .props("flat dense")
                                ui.button("全部收起", on_click=lambda: ui.run_javascript(
                                    """document.querySelectorAll('button.exam-reveal')
                                         .forEach(b => { if (b.innerText.trim() === '收起答案') b.click(); })""")) \
                                    .props("flat dense")

                                if not x.get("习题"):
                                    # 有的考点确实一道真题都没有（266 个考点里
                                    # 有 65 个是 0 道）。空页签会让人以为坏了，
                                    # 所以如实说明并指向可用的替代。
                                    ui.label("这个考点在 18 年真题里没有出过单选题，"
                                             "所以没有配套真题。可以看「讲义」页签里的"
                                             "考频数据，或到「408 历年真题」按学科浏览。") \
                                        .classes("t-sm muted")
                                for i, q in enumerate(x["习题"], 1):
                                    _exam_item(q, i, user)

        with ui.row().classes("items-center gap-3"):
            # 「要生成的路径」下拉框已删除：内部自动选第一条路径，
            # 用户只需要点一个按钮。
            ui.button("▶ 生成我的学习资料", on_click=lambda: run_live()) \
                .props("unelevated")

        def run_live():
            # 路径不再由用户选：不传 selected_path，graph 内部会取路径 Agent
            # 给出的第一条（见 yj/graph.py: agent_recommend）。
            with ui.dialog() as d, ui.card():
                ui.label("多智能体执行中…").classes("font-semibold")
                sp = ui.spinner(size="lg")
            d.open()
            R = graph.run(user)
            d.close()
            render_run(R)



def _reset_panel(user):
    """
    历史记录清空面板（用户要求："一键刷新历史纪录的选项，
    这样我测评的时候就不会有脏数据出现了"）。

    三个必须做对的地方：
      ① **绝不碰 cache 表** —— 那里是 742 条 LLM 生成结果（讲义、解析），
         清掉等于把花过钱和时间生成的内容扔了，下次运行要重新生成。
      ② **二次确认** —— 清空不可撤销，用对话框明确说出"将删除 N 条作答记录"，
         而不是点一下就没了。
      ③ **如实报告删了什么** —— 清空后显示"已清空 X 条作答、Y 个勾选"，
         不用"操作成功"这种什么都没说的话糊过去。
    """
    st = store.stats()
    n_my_a = len(store.get_answers(user))
    n_my_m = len(store.get_marks(user))

    with ui.expansion("⚙ 历史记录管理（测评前清空脏数据）").classes("w-full"):
        ui.label(f'当前库内：用户 {st["用户数"]} 个 · 作答 {st["作答条数"]} 条 · '
                 f'勾选 {st["勾选条数"]} 条 · LLM 缓存 {st["LLM缓存条数"]} 条') \
            .classes("t-sm muted")
        ui.label(f'你（{user}）名下：作答 {n_my_a} 条 · 勾选 {n_my_m} 个') \
            .classes("t-sm font-semibold")
        ui.label("清空只影响作答记录与考点勾选 —— "
                 "LLM 生成的讲义与解析缓存会保留（否则要重新花钱生成）。") \
            .classes("t-xs").style("color:#B45309")

        result = ui.label("").classes("t-sm")
        radio = ui.radio(
            {"me": f"只清空我自己（{user}）的历史",
             "others": "清空所有测试账号（保留 demo 演示画像）"},
            value="me").props("dense")

        def do_reset():
            if radio.value == "me":
                na, nm = store.reset_user(user)
                result.set_text(f"已清空 {user}：作答 {na} 条、勾选 {nm} 个")
            else:
                d = store.purge_others(keep=("demo",))
                result.set_text(f'已清空其他账号：作答 {d["作答"]} 条、'
                                f'勾选 {d["勾选"]} 个、用户 {d["用户"]} 个')
            result.style("color:#1B5E36")
            ui.navigate.reload()

        def ask():
            with ui.dialog() as d, ui.card():
                ui.label("确认清空？").classes("t-lead font-semibold")
                if radio.value == "me":
                    ui.label(f"将删除你（{user}）的 {n_my_a} 条作答记录"
                             f"和 {n_my_m} 个考点勾选。此操作不可撤销。").classes("t-sm")
                else:
                    ui.label(f'将删除除 demo 外所有账号的数据'
                             f'（共 {st["作答条数"] - n_my_a} 条作答）。'
                             f"此操作不可撤销。").classes("t-sm")
                ui.label("LLM 缓存（讲义、解析）不会被删除。") \
                    .classes("t-xs muted")
                with ui.row().classes("gap-2"):
                    ui.button("取消", on_click=d.close).props("flat")
                    ui.button("确认清空", on_click=lambda: (d.close(), do_reset())) \
                        .props("unelevated color=negative")
            d.open()

        ui.button("清空历史记录", on_click=ask).props("outline color=negative")


# ================================================================ 小工具
def _exam_item(q, idx, user):
    """
    讲义页「配套真题」里的一道题。

    用户的要求（原话）：
      "希望讲义生成中的相关真题中直接把这些题目以及答案解析（如果用户点了
       答案这个选项再显示）直接显示出来，不用让用户再去一个个查找"

    所以这里不再只给"年份 + 题号"让人自己去翻，而是**题干、选项全部铺出来**；
    答案与解析默认隐藏，点按钮才显示 —— 保留自测空间。

    解析来源分三种，界面分别标注（诚实红线）：
      · 综合题 41–47  → 答案册抽取 / AI 生成（data/solutions）
      · 单选题        → 目前没有解析，只显示正确答案（不编造）
    """
    from yj import data as _data
    with ui.card().classes("softcard w-full p-3 gap-1"):
        with ui.row().classes("items-center gap-2 no-wrap"):
            ui.label(f'{idx}. {q["年份"]} 年 第 {q["题号"]} 题').classes("t-sm font-semibold")
            ui.label(f'难度 {q.get("难度")}').classes("t-xs muted")
            if q.get("需插图") and not q.get("图片"):
                ui.label("原卷有插图（未抽取）").classes("t-xs").style("color:#B45309")

        ui.label(q["题干"]).classes("t-sm whitespace-pre-wrap").style("line-height:1.9")
        if q.get("图片"):
            ui.image(f'data/{q["图片"]}').classes("max-w-md rounded")

        opts = q.get("选项") or {}
        if opts:
            with ui.column().classes("gap-0 mt-1"):
                for k in sorted(opts):
                    ui.label(f'{k}. {opts[k]}').classes("t-sm").style("line-height:1.8")

        holder = ui.column().classes("w-full gap-1 mt-1")
        shown = {"v": False}

        def render():
            holder.clear()
            if not shown["v"]:
                return
            with holder:
                ui.label(f'正确答案：{q["答案"]}') \
                    .classes("t-sm font-semibold").style("color:#1B5E36")
                sol = _data.solution(q["年份"], q["题号"])
                if sol:
                    ui.label(f'解析（{sol["来源标注"]}）：') \
                        .classes("t-xs").style("color:#B45309")
                    ui.label(sol["文本"]).classes("t-sm whitespace-pre-wrap") \
                        .style("line-height:1.9")
                else:
                    # 还没有解析时如实说明，不编造
                    ui.label("这道题暂无解析。可对照教材或题库自行核对。") \
                        .classes("t-xs muted")

        def set_shown(v, from_bulk=False):
            """展开/收起这道题的答案。from_bulk=True 表示由"全部显示"触发
            （此时按钮文案也要跟着变，否则会出现"已经显示了却写着查看答案"）"""
            shown["v"] = v
            btn.set_text("收起答案" if v else "查看答案")
            render()

        def toggle():
            set_shown(not shown["v"])

        btn = ui.button("查看答案", on_click=toggle) \
            .props("flat dense").classes("exam-reveal")


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
    ui.run(port=args.port, title="优学鲸 · 考研智能备考",
           reload=False, favicon="🐳", show=False)


if __name__ in {"__main__", "__mp_main__"}:
    main()
