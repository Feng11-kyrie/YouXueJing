#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
优学鲸 · 界面入口

    streamlit run app.py

设计原则（按用户反馈调整）
--------------------------
**不强制诊断。** 首屏就是「选书 → 挑章节 → 挑考点 → 出题」，
用户进来几次点击就能练上题。诊断是**可选**的加分项，不是门槛。

为什么：32 道诊断题要 20-25 分钟，大部分人在那一步就走了。
让用户自己挑他认为薄弱的知识点，摩擦最小、掌控感最强；
他的勾选会直接进入画像，与做题数据同等对待。

页面
----
  ① 挑考点练习   主入口：选书 → 选章 → 选考点 → 出题   （无需任何前置）
  ② 快速诊断     可选：32 题测出章节掌握度，让推荐更准
  ③ 我的画像     作答 + 自报标记的汇总
  ④ 学习路径     三条可选路径（含依赖图追根因）
  ⑤ 我的薄弱点   LangGraph 多智能体链路（原名"讲义生成"）
"""
import os
import json
import uuid
import streamlit as st

from yj import data, store, diagnose, profile, path, llm, graph
from yj import snap as snap_mod

st.set_page_config(page_title="优学鲸 · 408 考研", layout="wide")

# ---------------------------------------------------------------- 样式
# 字号/字体/配色的大头在 .streamlit/config.toml 的原生主题变量里（那里改一次
# 全局生效，也不会随组件改版失效）。这里只补原生变量覆盖不到的两件事：
#   ① 中文正文行高（默认行高对中文偏挤）
#   ② 宽屏下的正文行长（全宽布局行长过长，读起来累）
st.markdown(
    """
    <style>
      /* 中文正文行高：默认对中文偏挤，1.75 更接近阅读习惯 */
      [data-testid="stMarkdownContainer"] p,
      [data-testid="stMarkdownContainer"] li { line-height: 1.75; }

      /* 宽屏行长治理：正文区限宽并居中，避免一行横跨整个 27 寸屏 */
      .block-container { max-width: 1180px; padding-top: 2.4rem; }

      /* ---- 侧栏字号（用户反馈：左侧栏字太小）-----------------------
         【注意】上一轮这里写的是 `font-size: 0.95rem` —— 主题基准是 17px，
            0.95rem(15.3px) **比基准还小**，等于我把侧栏文字改小了。
            这类"用 rem 猜字号"很容易悄悄变小，所以下面改成直接给明确值，
            并且把标题/正文/注释分三档拉开层次。                        */
      [data-testid="stSidebar"] { font-size: 1.05rem; }
      [data-testid="stSidebar"] .stMarkdown p,
      [data-testid="stSidebar"] .stMarkdown li { font-size: 1.05rem; }
      [data-testid="stSidebar"] .stMarkdown h1 { font-size: 1.7rem; }
      [data-testid="stSidebar"] .stMarkdown h2 { font-size: 1.35rem; }
      [data-testid="stSidebar"] .stMarkdown h3 { font-size: 1.2rem; }
      /* 注释/状态行也比默认最小号字大一档 */
      [data-testid="stSidebar"] [data-testid="stCaptionContainer"] { font-size: 0.95rem; }
      /* 导航项：字号 + 可点区域一起放大（原来是最小号字且很挤） */
      [data-testid="stSidebar"] [role="radiogroup"] { gap: 0.35rem; }
      [data-testid="stSidebar"] [role="radiogroup"] label { font-size: 1.05rem; }
      [data-testid="stSidebar"] [role="radiogroup"] label p { font-size: 1.05rem; }
      /* ---- 侧栏导航：卡片式选中态 --------------------------------
         实测数据（playwright 量的，不是猜的）：
           侧栏背景 rgb(242,243,247)，选中卡片 background-color rgb(255,255,255)
         → 白卡配极浅灰 = 对比度接近 0，用户截图里"看不出哪项是选中的"。
         所以选中态不靠白卡，改成**淡蓝底 + 左侧蓝竖条 + 蓝字**，
         这个组合在任何底色上都能看出来。                              */
      [data-testid="stSidebar"] {
        background: #EEF1F5;
        border-right: 1px solid #E1E6ED;
      }
      /* 导航行距收紧：原来每项约 54px（43px 高 + 间距），六项占掉侧栏上半屏 */
      [data-testid="stSidebar"] .stButton {
        margin: 0 !important;
      }
      [data-testid="stSidebar"] .stButton > button {
        justify-content: flex-start;
        text-align: left;
        font-size: 1rem;
        padding: 0.34rem 0.7rem;
        min-height: 0;
        height: auto;
        line-height: 1.5;
        border: none;
        background: transparent;
        color: #45566B;
        font-weight: 500;
        width: 100%;
        border-left: 3px solid transparent;
        border-radius: 0.5rem;
      }
      [data-testid="stSidebar"] .stButton > button:hover {
        background: rgba(37, 99, 235, 0.07);
        color: #1F2933;
      }
      /* 选中项：淡蓝底 + 左侧蓝竖条 + 蓝字（对比明确，不依赖白卡） */
      [data-testid="stSidebar"] button[kind="primary"],
      [data-testid="stSidebar"] button[data-testid="stBaseButton-primary"] {
        background: #DCE8FC !important;
        color: #17418F !important;
        font-weight: 650 !important;
        border-left: 3px solid #2563EB !important;
        box-shadow: none !important;
      }
      /* 图标列对齐：Material 图标固定宽度 + 居中，形成整齐的一列 */
      [data-testid="stSidebar"] .stButton > button p {
        display: flex;
        align-items: center;
        gap: 0.55rem;
      }
      [data-testid="stSidebar"] [data-testid="stIconMaterial"] {
        width: 1.35rem;
        flex: 0 0 1.35rem;
        text-align: center;
        font-size: 1.15rem;
        margin: 0;
        vertical-align: middle;
      }
      /* 分组小标题（"功能" / "存档状态"）低调一点 */
      [data-testid="stSidebar"] .yj-sec {
        font-size: 0.78rem;
        letter-spacing: 0.06em;
        color: #8A94A6;
        margin: 0.9rem 0 0.25rem 0.2rem;
        font-weight: 600;
      }

      /* 选中态/重点行更清楚 */
      [data-testid="stMarkdownContainer"] strong { font-weight: 650; }

      /* ---- 卷面可读性（真题页） ----------------------------------------
         47 道题堆在一页，默认间距会让它变成 47 个一模一样的白框：
         没有节奏、单屏只能放两道题。下面几件事把它压紧并分出层次。

         实测记录的坑：ST 1.65 里带边框的卡片就是
         `div[data-testid="stVerticalBlock"]`（1px 边框、圆角 11.9px、
         padding 16px）。早先我按 `stVerticalBlockBorderWrapper` 写选择器，
         playwright 实测命中 **0 个** —— 那段样式一直没生效。
         精确命中"卡片"的选择器是：
         `div[data-testid="stVerticalBlock"]:has([data-testid="stForm"])`
         （一页 10 张题卡正好命中 10 个）。学科色条则用 st.container 的 key
         生成的 `.st-key-*` class 单独指定（见题目渲染处）。                  */
      div[data-testid="stVerticalBlock"]:has([data-testid="stForm"]) {
        padding: 0.55rem 0.9rem 0.7rem 1rem !important;
      }
      [data-testid="stVerticalBlock"] { gap: 0.55rem !important; }
      [data-testid="stElementContainer"] { margin-bottom: 0.1rem; }
      /* 选项行距：A/B/C/D 挨得太近点不准 */
      [data-testid="stRadio"] [role="radiogroup"] { gap: 0.5rem !important; }
      [data-testid="stRadio"] [role="radiogroup"] label { padding: 0.1rem 0; }

      /* ---- 答题卡 ------------------------------------------------------
         所有方格在一个 flex 容器里自动换行；每页之间用分隔留白替代
         "第 N 页"文字标签（实测：每页一行标签 + 一行格子 + 一行跳页按钮，
         5 页吃掉约 330px，把第一道题推到 y=785）。图例做成有底色的小格子，
         省掉上方一整行说明。 */
      .yj-card {
        display: flex; flex-wrap: wrap; gap: 10px 0;
        align-items: center; margin: 0.1rem 0 0.3rem 0;
      }
      .yj-pgblock { display: inline-flex; flex-wrap: wrap; gap: 4px;
                    padding-right: 12px; }
      .yj-pgblock + .yj-pgblock { border-left: 1px solid #E3E8EF;
                                  padding-left: 12px; }
      .yj-cell {
        min-width: 1.85rem; text-align: center; padding: 0.1rem 0.22rem;
        border: 1px solid #D7DEE8; border-radius: 0.38rem;
        font-size: 0.78rem; font-variant-numeric: tabular-nums;
        background: #FFFFFF; color: #46586D; line-height: 1.45;
        font-style: normal;
      }
      .yj-ok   { background: #E6F6EC; border-color: #7DCB9A; color: #1B5E36; }
      .yj-bad  { background: #FDECEC; border-color: #E9A0A0; color: #8C2C2C; }
      .yj-open { background: #F2F5F9; border-color: #C9D3E0; color: #556072; }
      .yj-cur  { outline: 2px solid #2563EB; outline-offset: 1px; font-weight: 700; }
      /* 图例：三个有底色的小格子 + 一句说明，贴右对齐 */
      .yj-legend {
        display: inline-flex; align-items: center; gap: 5px;
        margin-left: auto; padding-left: 14px;
        font-size: 0.74rem; color: #6B7A8D; white-space: nowrap;
      }
      .yj-legend .yj-cell { min-width: 1.5rem; }
      @media (max-width: 1100px) {
        /* 窄屏时把图例说明藏掉，避免它自己换行把答题卡撑高 */
        .yj-legend-note { display: none; }
      }
      /* 分页按钮收小（分页是附属功能，不该像主按钮一样抢眼） */
      [class*="st-key-pg_"] button {
        min-height: 0 !important;
        padding: 0.2rem 0.5rem !important;
        font-size: 0.85rem !important;
        box-shadow: none !important;
      }
      /* 控制条：让三个控件的标签与输入对齐一致。
         （原来"显示"那一组的标签与单选钮对不齐，看起来像没做完的排版） */
      [data-testid="stSelectbox"] div[data-baseweb="select"] { min-height: 2.4rem; }
      [data-testid="stRadio"] > label { margin-bottom: 0.15rem; }
      /* 宽屏治理：正文区放宽一点，别让右侧留出四分之一屏的空白
         （原 1180px 在 1600px 视口下右侧空约 420px）。
         注意必须带 !important —— 上面第 48 行那条没带，后写的规则虽然靠后
         但同优先级下后者胜，加 !important 是为了避免以后再被别处覆盖时
         出现"改了没效果"这种难查的问题。 */
      .block-container { max-width: 1320px !important; }
    </style>
    """,
    unsafe_allow_html=True,
)

# 学科 → 色条颜色（答题卡、色条共用一套，避免两处不一致）
SUBJECT_COLORS = {
    "数据结构": "#2563EB",
    "计算机组成原理": "#7C3AED",
    "操作系统": "#0D9488",
    "计算机网络": "#C2410C",
}


# ---------------------------------------------------------------- 用户身份
# 不做账号体系：浏览器本地存一个 uuid。支持 ?u=demo 一键切到预置演示画像。
if "user_id" not in st.session_state:
    _qp = st.query_params.get("u")
    st.session_state.user_id = _qp if _qp else str(uuid.uuid4())[:8]
USER = st.session_state.user_id
store.init_db()
store.ensure_user(USER)


def answers():
    return store.get_answers(USER)


def marks():
    return store.get_marks(USER)


def steps(active, items):
    """
    顶部步骤指示：回答"我现在在哪一步、还剩几步"。

    之前界面是"点进去才出现下一步"，用户不知道自己走到哪了 ——
    这是"功能显示不明确"的主要来源之一。用一行文字讲清路径，
    比加导航栏轻，也不影响主流程。
    """
    bar = []
    for i, name in enumerate(items, 1):
        if i == active:
            bar.append(f"**:blue[{i}. {name}]**")
        elif i < active:
            bar.append(f"~~{i}. {name}~~ ✓")
        else:
            bar.append(f":gray[{i}. {name}]")
    st.markdown("　→　".join(bar))
    st.write("")


# ---------------------------------------------------------------- 侧栏
# 导航形态参考用户给的截图（飞书/Notion 那种左侧导航）：
# 选中项是白色圆角卡片、图标在左、行距宽松。
# st.radio 的选中态是圆点，做不出这个形态 —— 所以换成一列 st.button，
# 选中态靠 type="primary" + 侧栏专用 CSS（见文件顶部）实现。
NAV = [
    ("408 历年真题", "description"),
    ("挑考点练习", "school"),
    ("快速诊断", "monitor_heart"),
    ("我的画像", "insights"),
    ("学习路径", "route"),
    ("我的薄弱点", "menu_book"),
]

if "nav" not in st.session_state:
    st.session_state["nav"] = NAV[0][0]

st.sidebar.markdown(
    '<div style="display:flex;align-items:center;gap:0.6rem;margin:0.2rem 0 0.9rem 0">'
    # Logo 用 CSS 画，不再用 emoji —— 否则又要押注某个字符能在用户机器上
    # 正常渲染（上一轮标题的破图就是这么来的）
    '<div style="width:2.2rem;height:2.2rem;border-radius:0.6rem;flex:0 0 auto;'
    'background:linear-gradient(135deg,#2563EB,#0D9488);color:#fff;'
    'display:flex;align-items:center;justify-content:center;'
    'font-weight:700;font-size:0.95rem">408</div>'
    '<div><div style="font-size:1.4rem;font-weight:700;line-height:1.2">优学鲸</div>'
    '<div style="font-size:0.82rem;color:#8A94A6">考研 · 个性化学习</div></div>'
    '</div>', unsafe_allow_html=True)

st.sidebar.markdown('<div class="yj-sec">功能</div>', unsafe_allow_html=True)
for label, icon in NAV:
    if st.sidebar.button(f":material/{icon}:　{label}", key=f"nav_{label}",
                         use_container_width=True,
                         type="primary" if st.session_state["nav"] == label
                         else "secondary"):
        st.session_state["nav"] = label
        st.rerun()

page = st.session_state["nav"]

o = data.overview()
ok_llm, msg_llm = llm.status()

st.sidebar.markdown('<div class="yj-sec">我的进度</div>', unsafe_allow_html=True)
st.sidebar.markdown(
    f"薄弱考点 **{len(marks())}** 个　·　已作答 **{len(answers())}** 题"
)
st.sidebar.caption(f"{o['题目总数']} 题 · {o['叶子考点']} 考点 · {o['依赖边']} 依赖边")
st.sidebar.caption(("● 已连接　" if ok_llm else "● 演示模式　") + msg_llm)
st.sidebar.caption(f"用户 {USER}")

with st.sidebar.expander("设置"):
    if st.button("清空我的全部记录", help="清空标记与作答",
                 use_container_width=True):
        store.reset_user(USER)
        for k in [k for k in st.session_state if k.startswith(("cb_", "pill_",
                                                               "sel_", "practice_",
                                                               "run"))]:
            st.session_state.pop(k, None)
        st.rerun()


# ================================================================ 工具函数
def book_meta(code):
    """一本书的概览数据"""
    chs = data.chapters()[code]
    leaves = [l for ch, _n in chs for l in data.chapter_leaves().get(ch, [])]
    freq, lqc = data.freq(), data.leaf_question_count()
    m = diagnose.mastery_by_subject(answers()).get(code)
    return {
        "code": code, "name": data.CODE2NAME[code], "章数": len(chs),
        "考点数": len(leaves),
        "考频": sum(freq.get(l, {}).get("考查总次数", 0) for l in leaves),
        "可练题": sum(lqc.get(l, 0) for l in leaves),
        "掌握度": m["掌握度"] if m else None,
        "已标记": len([l for l in leaves if l in marks()]),
    }


def render_question(q, leaf, key_prefix, source="practice", done_answers=None):
    """
    渲染一道题并判分。

    done_answers: 该用户已有的作答 {qid: {...}}。传进来才能把**上次的选择**
    回显出来 —— 否则翻回这一页，用户看不到自己当初选了什么。
    """
    if q.get("需插图") and not q.get("图片"):
        st.info("这道题原卷有插图，但插图尚未抽取齐全，建议换一题。", icon=":material/image:")
    if q.get("图片"):
        st.image(f"data/{q['图片']}", width=420)
    opts = q.get("选项") or {}
    keys = sorted(opts.keys())
    pick_key, done_key = f"{key_prefix}_pick", f"{key_prefix}_done"
    submitted = False          # 先定义：首次渲染时下面的 if 不会给变量赋值
    # 【为什么要有"请选择"占位项】
    # st.radio 有个坑：首次渲染时如果没有任何选中值，它会**自动选中第一项**，
    # 于是每道题看起来都默认选了 A —— 用户以为系统替他选了。
    # 更糟的是这时 session_state 里的值其实是空，直接点提交会写入一条
    # `chosen = None` 的空作答：被算进"已作答 N 题"、被计为答错，
    # 而且该题的作答记录被占掉，之后重选也会被覆盖（demo 里实测有 10 条）。
    # 加一个占位项 + index=None，就能做到"默认谁都没选"。
    placeholder = "－ 请选择（先点选项，再提交）－"
    choices = [placeholder] + [f"{k}. {opts[k]}" for k in keys]
    nudge_key = f"{key_prefix}_nudge"
    prev = (done_answers or {}).get(q["id"])
    # 【为什么不要传 index=】
    # 交接文档记过这个坑：同一个控件**既传 index/default 又用 Session State 设值**时，
    # Streamlit 会告警并**清空该键** —— 表现是"选了马上又被重置"。
    # 这次实测又踩到了：加 index=None 之后 AppTest 的 set_value 完全失效
    # （value 恒为 None，提交永远读不到选择）。
    # 正确写法：只传 key，值一律显式写进 session_state。
    if pick_key not in st.session_state:
        st.session_state[pick_key] = (
            next((c for c in choices if prev and c.startswith(prev["chosen"] + ".")),
                 placeholder) if prev and prev.get("chosen") else placeholder)
    elif st.session_state[pick_key] not in choices:
        st.session_state[pick_key] = placeholder
    with st.form(key_prefix):
        st.radio("选项", choices, key=pick_key, label_visibility="collapsed")
        if st.form_submit_button("提交答案", type="primary"):
            val = st.session_state.get(pick_key) or ""
            # 选了占位项 = 没选 → 不写入任何记录（原来会写入一条空作答）
            mine = val[0] if val and val != placeholder else None
            if mine:
                ok = mine == q.get("答案")
                store.record_answer(USER, q["id"], mine, ok, source=source)
                st.session_state[done_key] = {"mine": mine, "ok": ok}
                st.session_state.pop(nudge_key, None)
                submitted = True
            else:
                st.session_state[nudge_key] = True
    # 反馈先渲染完整（st.rerun() 靠抛异常中断脚本，写在它后面的代码不会执行）
    r = st.session_state.get(done_key)
    if r:
        if r["ok"]:
            st.success(f"答对了 ✓　正确答案 {q['答案']}")
        else:
            st.error(f"答错了 ✗　你选 {r['mine']}，正确答案 {q['答案']}")
        st.caption(f"已归因到考点「{data.node_name(leaf)}」，"
                   f"作答会实时更新你的掌握度与路径推荐。")
    elif st.session_state.get(nudge_key):
        st.warning("还没选选项 —— 请先点一个答案再提交。",
                   icon=":material/touch_app:")
    # 再重跑一次，让"已作答 N 题""本卷成绩"这类**在写入之前**算好的统计刷新。
    # 不重跑的表现是"提交了但统计数字没变，要再点一次才对"。
    if submitted:
        st.rerun()


# ================================================================ ⓪ 408 历年真题
# 用户明确要的：一级选「408 历年真题」→ 二级选「2025 年真题」→ 直接看到整套卷子。
# 这里把真题做成**产品功能**（逐题作答 + 判分），不是可下载的 PDF。
#
# 版式取舍：47 道题一次性铺开会有两个问题 ——
#   ① 找不到答题进度（哪些做过、哪些做错了）
#   ② 一页三屏，复习时只能靠滚动
# 所以改成：顶部控制条 + 答题卡（状态+跳转）+ 筛选 + 分页（每页 10 题）。
if page == "408 历年真题":
    papers = data.paper_index()
    years = [p["年份"] for p in papers]

    # ---- 控制条：三个控件挤一行，标签与控件同排（原先是三块各占两行，
    #      加上大标题和两行卷情，实测把第一道题推到 y=785 ——
    #      1440x900 的笔记本上，选项和提交按钮全在折叠线以下，
    #      学生打开卷子连一道完整的题都看不到）。
    c0, c1, c2, c3 = st.columns([2.6, 1.35, 2.2, 1.7])
    with c0:
        st.markdown("### 408 历年真题")
    with c1:
        yr = st.selectbox("年份", years, format_func=lambda y: f"{y} 真题",
                          label_visibility="collapsed")
    with c2:
        mode = st.radio("打开方式", ["作答模式", "浏览模式"], horizontal=True,
                        label_visibility="collapsed",
                        help="作答模式：判分、计入画像；浏览模式：只看不记")
    with c3:
        view = st.radio("显示", ["全部", "未做", "只错题"], horizontal=True,
                        label_visibility="collapsed")

    p = data.paper(yr)
    scoring = mode == "作答模式"
    done = answers()
    choice_ids = [q["id"] for q in p["题目"] if q["题型"] == "单项选择题"]
    rows = [done[i] for i in choice_ids if i in done]
    n_ok = sum(1 for r in rows if r["is_correct"])

    # ---- 卷情 + 成绩 + 缺口说明压成一行小字（原先是两行正文 + 一行成绩）
    info = (f"{p['年份']} 年 · {p['题数']} 题 · {p['总分']} 分 · "
            f"可判分 {p['有答案数']}")
    if p["综合数"]:
        info += f" · 综合 {p['综合数']} 题无答案不计分"
    if p["缺图"]:
        info += f" · {p['缺图']} 题缺插图"
    if scoring and rows:
        info += f"　|　已作答 {len(rows)}/{len(choice_ids)} · 答对 {n_ok} · " \
                f"正确率 {n_ok / len(rows):.0%}"
    st.caption(info)

    # ---- 筛选
    def keep(q):
        st_ = done.get(q["id"])
        if view == "未做":
            return st_ is None
        if view == "只错题":
            return bool(st_ and not st_["is_correct"])
        return True

    shown = [q for q in p["题目"] if keep(q)]
    if view != "全部":
        st.caption(f"筛选「{view}」：{len(shown)}/{p['题数']} 题"
                   + ("　（全部做完了？切回「全部」看卷面）" if not shown else ""))

    # ---- 答题卡：方格底色 = 答题状态；图例并进答题卡同一行（见下方渲染）。
    #      原来在答题卡上方还有一行"答题卡 已答对 答错 未做 蓝框=当前题"，
    #      现在图例直接用有底色的小方块示例，省掉一整行。
    # 分页状态：换年份 / 换筛选 / 换模式都要复位，否则会停在越界的页码上
    ctx = f"{p['年份']}|{view}|{mode}"
    if st.session_state.get("paper_ctx") != ctx:
        st.session_state["paper_ctx"] = ctx
        st.session_state["paper_page"] = 0

    PER = 10
    pages_n = max(1, (len(shown) + PER - 1) // PER)
    cur = min(st.session_state.get("paper_page", 0), pages_n - 1)

    if shown:
        # 答题卡：所有方格在一个 flex 容器里自动换行，每页之间留一点间隔
        # 作为分页的视觉暗示 —— 不再给每页单独一行加"第 N 页"标签。
        # 实测：原来每页一行标签 + 一行格子 + 一行跳页按钮 = 5 页吃掉约 330px，
        # 加上大标题/卷情/成绩/答题卡说明，把第一道题推到 y=785。
        blocks = []
        for pi in range(pages_n):
            group = shown[pi * PER:(pi + 1) * PER]
            cells = []
            for q in group:
                st_ = done.get(q["id"])
                cls = "yj-cell"
                if st_:
                    cls += " yj-ok" if st_["is_correct"] else " yj-bad"
                else:
                    cls += " yj-open"
                if pi == cur:
                    cls += " yj-cur"
                cells.append(f'<span class="{cls}">{q["题号"]}</span>')
            blocks.append(f'<span class="yj-pgblock">' + "".join(cells) + '</span>')
        st.markdown(
            '<div class="yj-card">' + "".join(blocks)
            + '<span class="yj-legend">'
              '<i class="yj-cell yj-ok">对</i>'
              '<i class="yj-cell yj-bad">错</i>'
              '<i class="yj-cell yj-open">未做</i>'
              '<span class="yj-legend-note">＝ 方框底色即答题状态</span>'
              '</span></div>', unsafe_allow_html=True)
        # 分页：只在多页时给，做成"上一页 / 第 N/M 页 / 下一页"的紧凑导航。
        # 原来把 5 个页码按钮平铺成一行（每个撑到 260px 宽），像 5 个主按钮 ——
        # 分页是附属功能，不该抢题目的视觉重量。
        if pages_n > 1:
            # 列宽要给够：按钮文字是"← 上一页"，列太窄会被截成"← 上…"
            # （实测踩过）。所以按钮列用 1.5，中间页信息用 2.2。
            nav1, nav2, nav3, _sp = st.columns([1.5, 2.2, 1.5, 4.8])
            if nav1.button("上一页", key="pg_prev", disabled=(cur == 0),
                           use_container_width=True):
                st.session_state["paper_page"] = cur - 1
                st.rerun()
            # nowrap：列宽不够时这行会折成两行（实测发生过），很难看
            nav2.markdown(
                f"<div style='text-align:center;padding-top:0.4rem;"
                f"white-space:nowrap;font-size:0.88rem;color:#5A6B80'>"
                f"第 <b>{cur + 1}</b> / {pages_n} 页　·　"
                f"第 {shown[cur * PER]['题号']}–"
                f"{shown[min((cur + 1) * PER, len(shown)) - 1]['题号']} 题</div>",
                unsafe_allow_html=True)
            if nav3.button("下一页", key="pg_next", disabled=(cur >= pages_n - 1),
                           use_container_width=True):
                st.session_state["paper_page"] = cur + 1
                st.rerun()


    if not shown:
        st.info("这个筛选下没有题目。", icon=":material/filter_alt_off:")
        st.stop()

    # ---- 当前页的题目
    page_items = shown[cur * PER:(cur + 1) * PER]
    from collections import defaultdict as _dd
    by_subj = _dd(list)
    for q in page_items:
        by_subj[q["学科"]].append(q)

    # 分页导航已经放在答题卡下方（上一页 / 第 N/M 页 / 下一页），
    # 这里不再重复一遍页码和按钮 —— 原来两处都在说"第几页"，
    # 实测占了约 110px，纯属重复。
    for subj_name in sorted(by_subj, key=lambda s: min(int(str(q["题号"]))
                                                      for q in by_subj[s])):
        qs = by_subj[subj_name]
        color = SUBJECT_COLORS.get(subj_name, "#2563EB")
        st.markdown(f"##### {subj_name}　（第 {qs[0]['题号']}–{qs[-1]['题号']} 题）")
        for q in qs:
            is_choice = q["题型"] == "单项选择题"
            st_ = done.get(q["id"])
            # 学科色条怎么传进卡片：
            # st.container 不接受 style，但接受 key —— key 会变成 DOM 上的
            # 稳定 class `st-key-<key>`，于是可以用它精确命名单张卡片。
            # （早先试过在卡片内部写 CSS 变量给卡片自己的 ::before 读，
            #   实测拿不到：自定义属性只向**下**继承，父级 ::before 读不到子级
            #   声明的变量。这条弯路不要再走。）
            with st.container(border=True, key=f"q{q['id']}"):
                flag = ""
                if st_:
                    flag = "　:green[✓ 已答对]" if st_["is_correct"] else \
                           f"　:red[✗ 已答错（你选 {st_['chosen']}）]"
                st.markdown(
                    f'<style>.st-key-q{q["id"]} {{'
                    f'border-left: 4px solid {color} !important;'
                    f'border-radius: 0.55rem !important;'
                    f'padding: 0.55rem 0.9rem 0.7rem 1rem !important;'
                    f'}}</style>', unsafe_allow_html=True)
                # 表头并进一行，减少卡片高度
                st.markdown(f"**第 {q['题号']} 题**　{q['题型']}　"
                            f"{q.get('分值') or '?'} 分　·　"
                            f":gray[`{data.node_name(q['主考点'])}`]{flag}")
                st.markdown(q["题干"])
                if q.get("需插图") and not q.get("图片"):
                    st.caption("原卷有插图，但插图尚未抽取齐全，建议对照原卷。")
                if q.get("图片"):
                    st.image(f"data/{q['图片']}", width=420)

                if not is_choice:
                    st.markdown("**:orange[综合应用题 — 题库暂无答案，本题不计分]**")
                    continue

                if not scoring:
                    with st.expander("查看正确答案"):
                        st.markdown(f"正确答案：**{q['答案']}**")
                    continue

                render_question(q, q["主考点"], done_answers=done,
                                key_prefix=f"paper_{p['年份']}_{q['id']}")


# ================================================================ ① 挑考点练习
elif page == "挑考点练习":
    subj = st.session_state.get("sel_subject")

    # ---------- 第一步：选书 ----------
    if not subj:
        st.title("挑考点练习")
        steps(1, ["选一门课", "挑薄弱知识点", "做真题"])
        st.markdown("先选一门课，再从这门课里挑出**你自己觉得薄弱的知识点**，"
                    "系统就用这些考点给你出真题。**不需要先做任何测试。**")
        st.info("想更准？左侧「快速诊断」可以加做 32 题测出章节掌握度"
                "—— 但那是可选的，不是门槛。", icon=":material/lightbulb:")
        st.divider()
        cols = st.columns(4)
        for col, code in zip(cols, ["DS", "CO", "OS", "CN"]):
            b = book_meta(code)
            with col, st.container(border=True):
                st.markdown(f"### {b['name']}")
                st.markdown(f"**{b['章数']}** 章　·　**{b['考点数']}** 个考点")
                st.markdown(f"18 年考频 **{b['考频']}** 次")
                st.markdown(f"题库 **{b['可练题']}** 题可练")
                if b["掌握度"] is not None:
                    st.metric("我的掌握度", f"{b['掌握度']:.0%}")
                else:
                    st.markdown("我的掌握度：**未测**")
                if b["已标记"]:
                    st.markdown(f"★ 已标记 **{b['已标记']}** 个薄弱考点")
                if st.button(f"① 进入{b['name']}", key=f"go_{code}",
                             use_container_width=True, type="primary"):
                    st.session_state["sel_subject"] = code
                    st.session_state.pop("sel_chapter", None)
                    st.rerun()
        st.stop()

    # ---------- 第二步：选章 ----------
    b = book_meta(subj)
    c1, c2 = st.columns([4, 1])
    c1.markdown(f"## {b['name']}")
    if c2.button("← 换一门", use_container_width=True):
        st.session_state.pop("sel_subject", None)
        st.session_state.pop("sel_chapter", None)
        st.rerun()

    steps(2, ["选一门课", "挑薄弱知识点", "做真题"])

    chs = data.chapters()[subj]
    m_ch = diagnose.mastery_by_chapter(answers())
    freq, lqc, my_marks = data.freq(), data.leaf_question_count(), marks()

    st.markdown(f"### 这门课有 {len(chs)} 章 —— 点章名直接进去挑知识点")
    st.markdown("下面标注了每章的**考频**（18 年考了多少次）、**考点数**"
                "和**你的掌握度**（未测就是还没做过题）。")
    # 章行改成"可点击的整行"：之前只有一行灰色小字，用户不知道该点哪里。
    # 用两列而不是四列 —— 四列会把章名挤到换行，反而更难读。
    for i, (ch, nm) in enumerate(chs):
        cm = m_ch.get(ch)
        n_mark = len([l for l in data.chapter_leaves().get(ch, []) if l in my_marks])
        a1, a2 = st.columns([5, 2])
        with a1:
            label = f"**{nm}**　·　考频 {data.chapter_freq().get(ch, 0)} 次　·　" \
                    f"{len(data.chapter_leaves().get(ch, []))} 个考点" \
                    + (f"　·　★ 已勾选 {n_mark}" if n_mark else "")
            if st.button(label, key=f"ch_{ch}", use_container_width=True):
                st.session_state["sel_chapter"] = ch
                st.rerun()
        with a2:
            if cm:
                st.markdown(f"掌握度 **{cm['掌握度']:.0%}**"
                            f"（{cm['答对']}/{cm['题数']} 题）")
            else:
                st.markdown("掌握度 **未测**")

    st.divider()
    ch = st.session_state.get("sel_chapter")
    if not ch:
        st.info("点上面任意一章，展开它的知识点列表。", icon=":material/touch_app:")

    # ---------- 第三步：选考点 ----------
    if ch:
        leaves = data.chapter_leaves().get(ch, [])
        if leaves:
            st.divider()
            st.markdown(f"### 第 3 步：勾出「{data.node_name(ch)}」里你觉得薄弱的知识点")
            st.markdown("可以多选；**换章再回来勾选会保留**。"
                        "标签上的 `频N` 是它 18 年被考的次数，`·M题` 是题库里"
                        "能拿它练的真题数。")
            st.info("标着 **·0题** 的考点题库里暂时没有对应真题（勾选后没题可练，"
                    "但仍可用它生成讲义）。建议优先勾 `·N题` 且 N 大的。",
                    icon=":material/lightbulb:")
            label2leaf = {}
            for l in leaves:
                f = freq.get(l, {})
                tag = " ★" if l in my_marks else ""
                label2leaf[f"{data.node_name(l)}　频{f.get('考查总次数', 0)}"
                           f"·{lqc.get(l, 0)}题{tag}"] = l
            prev = [lab for lab, l in label2leaf.items() if l in my_marks]
            # 用 checkbox 而不是 pills/multiselect:
            #   pills 多选在本项目的验证环境下, 选中状态无法稳定保留
            #   (控件传了 default 又被 Session State API 设值时会冲突, Streamlit 会清空该键)。
            #   checkbox 语义最简单(布尔), 且同样按"显式初始化 session_state"的写法
            #   避免 default/value 与 key 冲突 —— 主流程必须可靠、可验证。
            ncol = 2
            cols = st.columns(ncol)
            picked = set()
            for i, l in enumerate(leaves):
                f = freq.get(l, {})
                lab = (f"{data.node_name(l)}　频{f.get('考查总次数', 0)}"
                       f"·{lqc.get(l, 0)}题")
                ck = f"cb_{l}"
                if ck not in st.session_state:
                    st.session_state[ck] = l in my_marks
                with cols[i % ncol]:
                    if st.checkbox(lab, key=ck):
                        picked.add(l)
            # 本章的勾选覆盖本章原有标记, 其他章的标记保留
            others = {l for l in my_marks if data.chapter_of(l) != ch}
            new_marks = others | picked
            if new_marks != my_marks:
                store.set_marks(USER, new_marks)
                st.rerun()

    # ---------- 选择汇总 + 出题 ----------
    sel = marks()
    if sel:
        st.divider()
        steps(3, ["选一门课", "挑薄弱知识点", "做真题"])
        by_ch = {}
        for l in sel:
            by_ch.setdefault(data.chapter_of(l), []).append(l)
        total_q = sum(data.leaf_question_count().get(l, 0) for l in sel)
        no_q = [l for l in sel if not data.leaf_question_count().get(l, 0)]
        st.markdown(f"### 你已勾选 {len(sel)} 个考点，题库里共 **{total_q}** 道真题可练")
        if no_q:
            st.markdown("其中 "
                        + "、".join(data.node_name(l) for l in no_q)
                        + f" 共 {len(no_q)} 个考点**暂无题目**，只能用于生成讲义。")
        for c, ls in sorted(by_ch.items(),
                            key=lambda kv: -data.chapter_freq().get(kv[0], 0)):
            st.markdown(f"- **{data.node_name(c)}**："
                        + "、".join(data.node_name(l) for l in ls))

        st.write("")
        b1, b2, b3 = st.columns([2, 2, 3])
        if b1.button("▶ 开始练习（出 5 道真题）", type="primary",
                     use_container_width=True):
            st.session_state["practice_now"] = True
        if b2.button("清空选择", use_container_width=True):
            store.set_marks(USER, set())
            st.session_state.pop("practice_now", None)
            st.rerun()
        b3.markdown("选好后也可以到左侧「我的薄弱点」按这些考点出讲义。")

    # ---------- 就地出题 ----------
    if st.session_state.get("practice_now") and sel:
        st.divider()
        st.markdown(f"### 练习：{len(sel)} 个考点里抽 5 道真题")
        done = answers()
        pool = []
        for l in sorted(sel, key=lambda x: -data.leaf_question_count().get(x, 0)):
            for q in data.questions().values():
                if q["主考点"] == l and q["题型"] == "单项选择题" and q.get("答案"):
                    pool.append((l, q))
        pool.sort(key=lambda lq: (lq[1]["id"] in done, lq[1].get("难度") or 3,
                                  -lq[1]["year"]))
        if not pool:
            st.warning("你选的这些考点在题库里暂时没有对应的真题。"
                       "建议回到上面换几个标着「·N题」的考点。")
        else:
            st.markdown(f"抽题规则：**优先你没做过的、难度低的先来**；"
                        f"你勾的考点共 {len(pool)} 道可选。"
                        f"提交后会立刻判分、把错题归因到考点，并更新掌握度与路径。")
            show = pool[:5]
            for i, (l, q) in enumerate(show, 1):
                with st.container(border=True):
                    st.markdown(f"**第 {i} 题**　·　{q['year']} 年 第 {q['题号']} 题"
                                f"　·　`{data.node_name(l)}`　·　难度 {q.get('难度')}")
                    st.markdown(q["题干"])
                    render_question(q, l, done_answers=done,
                                    key_prefix=f"p_{q['id']}")
            if len(pool) > len(show):
                st.caption(f"还有 {len(pool) - len(show)} 道。"
                           f"再做一轮会优先取出未做过的题。")


# ================================================================ ② 快速诊断
elif page == "快速诊断":
    st.title("快速诊断（可选）")
    st.markdown("32 道题　·　约 20-25 分钟　·　覆盖 408 全部 24 章")
    st.markdown("做完会得到**章节级掌握度**，之后推荐会更准。"
                "这是可选的 —— 不做也能用：你可以在「挑考点练习」里"
                "直接勾选自己认为薄弱的知识点。")
    st.info("界面上的每个数字都能对到具体作答记录；"
            "掌握度用 Laplace 平滑，避免只答 1 题就给出 0% 或 100%。",
            icon=":material/straighten:")

    paper = data.diagnostic()["题目"]
    got = answers()
    st.progress(sum(1 for x in paper if x["id"] in got) / len(paper),
                text=f"进度 {sum(1 for x in paper if x['id'] in got)}/{len(paper)}")
    qs = data.questions()
    with st.form("diag"):
        for item in paper:
            q = qs[item["id"]]
            st.markdown(f"**{item['order']}. [{item['学科']} · "
                        f"{item['诊断章节名']} · 难度 {item['难度']}]** {q['题干']}")
            opts = q.get("选项") or {}
            keys = sorted(opts.keys())
            prev = got.get(item["id"], {}).get("chosen")
            # 与真题页同一个坑：st.radio 首次渲染会自动选中第一项，
            # 看起来像系统替用户选了 A。加占位项做到"默认未作答"。
            # 同样**不传 index**（传了会和 Session State 冲突，set_value/回显失效）。
            ph = "－ 未作答 －"
            rk = f"r{item['id']}"
            choices = [ph] + [f"{k}. {opts[k]}" for k in keys]
            if rk not in st.session_state:
                st.session_state[rk] = (
                    next((c for c in choices if c.startswith(prev + ".")), None)
                    if prev else None)
            elif st.session_state[rk] not in choices:
                st.session_state[rk] = None
            # 诊断页 32 题一次铺开，若每题都默认选中占位项，会出现 32 个蓝点
            # 看着像"系统替我选好了"。这里用 index=None 做到真的一个都不选
            # （实测：真题页用 index 会和 Session State 冲突导致选不中，
            #  但诊断页不依赖 AppTest 的 set_value，所以可以用）。
            st.radio(f"q{item['id']}", choices, key=rk, index=None,
                     label_visibility="collapsed")
            st.divider()
        if st.form_submit_button("提交并生成掌握度", type="primary"):
            n = 0
            for item in paper:
                val = st.session_state.get(f"r{item['id']}")
                # 跳过未作答：原来把空值也写进库记成答错，
                # 于是"没做的题"会被算进掌握度分母（这是错的）
                if not val or val == "－ 未作答 －":
                    continue
                q = qs[item["id"]]
                store.record_answer(USER, item["id"], val[0],
                                    val[0] == q.get("答案"), source="diagnostic")
                n += 1
            left = len(paper) - n
            st.success(f"已记录 {n} 题。到「我的画像」查看结果。"
                       + (f"　还有 {left} 题未作答，未作答不计入掌握度。"
                          if left else ""))
            st.rerun()


# ================================================================ ③ 我的画像
elif page == "我的画像":
    st.title("我的画像")
    a, mk = answers(), marks()
    if not a and not mk:
        st.info("还没有任何数据。你可以：\n\n"
                "1. 到「挑考点练习」勾选自己觉得薄弱的知识点（最快）\n"
                "2. 或到「快速诊断」做一次 32 题测试（更准）")
        st.stop()

    prof = profile.build(a, mk)
    st.markdown("这一页是你当前学情的汇总：**做题数据 + 你自己勾选的薄弱点**。")
    st.markdown(f"> {prof['文字画像']}")
    st.caption("掌握度算法：（答对 + 1）/（题数 + 2），Laplace 平滑，"
               "避免只答 1 题就给出 0% 或 100% 的极端结论。"
               "你自报的薄弱点与做题数据同等计入。")

    if prof["学科掌握度"]:
        cols = st.columns(len(prof["学科掌握度"]))
        for col, (code, v) in zip(cols, sorted(prof["学科掌握度"].items(),
                                              key=lambda x: -x[1]["掌握度"])):
            col.metric(v["学科"], f"{v['掌握度']:.0%}", f"{v['答对']}/{v['题数']} 题")
    if mk:
        st.markdown(f"另有你自报的 **{len(mk)}** 个薄弱考点，已计入下方排序。")

    st.divider()
    st.subheader("各章掌握度")
    st.markdown("按学科分组，**每章一条进度条**（括号里是答对/答过题数）。")
    m = diagnose.summarize(a)
    for code, name in data.CODE2NAME.items():
        rows = [c for c in m["章节"].values() if c["学科码"] == code]
        if not rows:
            continue
        st.markdown(f"**{name}**")
        for c in sorted(rows, key=lambda x: x["掌握度"]):
            st.progress(c["掌握度"],
                        text=f"{c['章节名']} — {c['掌握度']:.0%}"
                             f"（{c['答对']}/{c['题数']}）")

    if prof["薄弱章节"]:
        st.divider()
        st.subheader("最该先补的章节")
        st.markdown("排序依据：**考频 ×（1 − 掌握度）**。"
                    "考得越多、你越弱，性价比越高，越该先补。")
        for c in prof["薄弱章节"]:
            lvl = f"{c['掌握度']:.0%}" if c["掌握度"] is not None else "未测"
            src = f"　·　{c.get('来源', '')}" if c.get("来源") else ""
            st.markdown(f"- **{c['章节名']}**　掌握度 {lvl}　"
                        f"18 年考频 {c['考频']} 次　优先级分 {c['优先级分']}{src}")

    if prof["未测章节"]:
        st.divider()
        st.warning(f"还有 **{len(prof['未测章节'])}** 个章节没有测到："
                   + "、".join(x["章节名"] for x in prof["未测章节"][:8])
                   + "。建议到「快速诊断」加测以完善画像。")


# ================================================================ ④ 学习路径
elif page == "学习路径":
    st.title("学习路径")
    a, mk = answers(), marks()
    if not a and not mk:
        st.info("还没有数据。先到「挑考点练习」勾选薄弱知识点，"
                "或做一次「快速诊断」。")
        st.stop()

    rec = path.recommend(a, marks=mk)
    if not rec.get("路径"):
        st.info(rec.get("提示", "暂无推荐"))
        st.stop()

    st.markdown(f"根据你的学情（含你自己勾选的薄弱点），系统找出 "
                f"**{rec['薄弱考点数']} 个未掌握考点**，组织成下面几条路径。")
    st.markdown("**三条路径不互斥，选一条开始就行** —— 差别只在"
                "「先补什么」的判断依据：")
    tabs = st.tabs([f"{p['名称']}（{p['合计分钟']} 分钟）" for p in rec["路径"]])
    for tab, p in zip(tabs, rec["路径"]):
        with tab:
            st.markdown(f"**适合**：{p['适用']}")
            st.markdown(p["说明"])
            if not p["步骤"]:
                st.info("这条路径当前没有需要补的考点。")
                continue
            for i, s in enumerate(p["步骤"], 1):
                with st.container(border=True):
                    c1, c2, c3 = st.columns([3, 1, 1])
                    c1.markdown(f"**{i}. {s['考点名']}**")
                    c1.markdown(f"{s['学科']} · {s['章节']}")
                    c2.metric("当前掌握度",
                              f"{s['当前掌握度']:.0%}" if s["是否已测"] else "未测")
                    c3.metric("预计用时", f"{s['预计分钟']} 分钟")
                    st.markdown(f"考频 **{s['考频']}** 次　·　题库可练 "
                                f"**{s['可练真题']}** 题　|　{s['推荐理由']}")
    st.divider()
    st.markdown("**「补根因」是怎么算的**：沿知识点依赖图向上追溯，找到最靠前的"
                "**断裂点**再开始补，而不是直接练你表面最弱的那一章。"
                "依赖边来自 18 年真题的考点共现与考纲编排顺序。")


# ================================================================ ⑤ 我的薄弱点
elif page == "我的薄弱点":
    st.title("我的薄弱点")
    st.caption("按你答错和自报的薄弱考点，生成讲义 · 知识点速记 · 配套真题"
               "（只给最该补的几个考点）")
    st.markdown("这一页跑的是 **LangGraph 六 Agent 链路**："
                "准备 → 诊断 → 画像 → 路径 → 生成 → 复核，"
                "按你的薄弱考点产出**讲义 / 知识点速记 / 配套真题**。")
    ok, msg = llm.status()
    if ok:
        st.success(msg, icon=":material/check_circle:")
    else:
        st.warning(msg + " —— 页面会照常跑通，但讲义正文是**用真实数据填的模板**，"
                         "不是 AI 写的。", icon=":material/warning:")

    a, mk = answers(), marks()
    if not a and not mk:
        st.info("还没有数据。先到「挑考点练习」勾选薄弱知识点。")
        st.stop()

    rec = path.recommend(a, marks=mk)
    import glob as _glob
    _snaps = sorted(os.path.basename(x)[:-5] for x in _glob.glob("data/prewarm/*.json"))
    st.markdown("#### 第一步：选运行方式")
    mode = st.radio("运行方式", ["实时运行", "回放预跑快照"], horizontal=True,
                    help="路演兜底：API 不可用时用快照回放，输出与预跑时完全一致。")
    st.caption("「实时运行」当场调 LLM（慢、且依赖网络与额度）；"
               "「回放预跑快照」读提前跑好并落盘的结果（秒出、离线可用、输出一致）。")

    if mode == "回放预跑快照":
        if not _snaps:
            st.warning("还没有快照。先在命令行跑：\n\n"
                       "`python scripts/prewarm.py --name roadshow`")
        else:
            snap = st.selectbox("选择快照", _snaps)
            if st.button("▶ 回放快照", type="primary"):
                # 兜底路径必须比实时路径更稳: 快照文件若损坏(曾出现过写了一半的
                # json), 这里给可读的提示而不是让页面抛异常 —— 路演现场不能崩。
                try:
                    with open(f"data/prewarm/{snap}.json", encoding="utf-8") as f:
                        d = json.load(f)
                    d = snap_mod.to_jsonable(d)
                    st.session_state["run"] = d["结果"]
                    st.session_state["run_meta"] = (
                        f"快照「{snap}」· 预跑于 {d['生成时间']} · "
                        f"当时 LLM {'已配置' if d['LLM已配置'] else '未配置'} · "
                        f"内容来源 {d['内容来源']}")
                except Exception as e:                  # noqa: BLE001
                    st.error(f"快照「{snap}」读取失败，无法回放："
                             f"{type(e).__name__}: {e}。"
                             f"请在命令行重跑 `python scripts/prewarm.py "
                             f"--name {snap} --path root` 重新生成。")
    else:
        names = [p["名称"] for p in rec["路径"]] or ["补根因"]
        st.markdown("#### 第二步：选要生成的路径，然后运行")
        sel_name = st.selectbox("选中要生成的路径", names)
        if not a:
            st.markdown("提示：你没有做题记录，链路会依据**你勾选的薄弱考点**生成。")
        if st.button("▶ 运行多智能体链路", type="primary"):
            with st.spinner("多智能体执行中…"):
                st.session_state["run"] = graph.run(
                    USER, selected_path={"补根因": "root", "冲高频": "freq",
                                         "错题驱动": "wrong"}.get(sel_name, "root"))
                st.session_state.pop("run_meta", None)

    if st.session_state.get("run_meta"):
        st.info("正在回放预跑快照 —— " + st.session_state["run_meta"],
                icon=":material/inventory_2:")

    R = st.session_state.get("run")
    if not R:
        st.markdown("还没有运行 —— 上面选好方式后点「▶ 运行多智能体链路」"
                    "或「▶ 回放快照」。")
        st.stop()

    st.subheader("执行轨迹")
    for t in R.get("traced", []):
        st.markdown(f"- **{t['agent']}** — {t['detail']}")
    rv = R.get("review") or {}
    if rv:
        if rv.get("通过"):
            st.success(f"复核 Agent：考纲校验通过（检查了 {rv.get('检查项数', 0)} 个考点）",
                       icon=":material/check_circle:")
        else:
            st.error(f"复核 Agent：发现 {len(rv.get('越纲项', {}))} 个考点有越纲内容")

    with st.expander("多智能体调度图（LangGraph StateGraph）"):
        st.caption("实际编译出来的图，含一条条件边：没有作答记录时直接要求先诊断。")
        st.code(graph.mermaid(), language="mermaid")

    st.subheader("生成的资源")
    res = R.get("resources") or []
    if not res:
        st.info("这条路径上没有需要生成的考点。")
        st.stop()
    for x in res:
        src = x["讲义"]["source"]
        label = {"llm": "LLM 生成", "cache": "LLM 生成（预跑缓存）",
                 "template": "模板模式（真实数据）",
                 "error": "LLM 失败，已降级为模板"}.get(src, src)
        with st.expander(f"{x['考点名']}　·　{x['章节']}　·　{label}",
                         expanded=(x is res[0])):
            t1, t2, t3 = st.tabs(["讲义", "知识点速记", "配套真题"])
            with t1:
                st.markdown(x["讲义"]["markdown"])
                v = x["讲义"].get("校验") or {}
                st.caption("复核 Agent：内容未越出考纲考点范围 ✓" if v.get("通过")
                           else f"复核 Agent 发现疑似考纲外内容：{v.get('疑似考纲外')}")
            with t2:
                st.markdown(x["速记"])
            with t3:
                if not x["习题"]:
                    st.caption("该考点题库中暂无带答案的选择题。")
                for i, q in enumerate(x["习题"], 1):
                    with st.container(border=True):
                        st.markdown(f"**{i}. {q['年份']} 年 第 {q['题号']} 题**"
                                    f"（难度 {q['难度']}）")
                        st.markdown(q["题干"])
                        if q.get("图片"):
                            st.image(f"data/{q['图片']}", width=360)
                        with st.expander("查看答案"):
                            st.markdown(f"正确答案：**{q['答案']}**")
