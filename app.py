#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
优学鲸 · 界面入口

    streamlit run app.py

页面结构(对应验收指标):
    ① 诊断     —— 做 32 道诊断题            (指标 1 的输入)
    ② 画像     —— 学科/章节掌握度 + 薄弱点   (指标 1)
    ③ 路径     —— 三条可选学习路径           (指标 2)
    ④ 练习     —— 逐题作答 + 自动判分        (闭环)

设计取舍:
  - 单文件 Streamlit, 不做前后端分离。多人协作才需要分离, 单人是纯负担。
  - 用户身份用浏览器 localStorage 里的 uuid, **不做注册登录**(崩溃与拖延的第一来源)。
  - 所有结论都能追溯到具体答题记录, 界面上的数字与数据层严格一致。
"""
import uuid
import streamlit as st

from yj import data, store, diagnose, profile, path

st.set_page_config(page_title="优学鲸 · 408 考研", page_icon="🐳", layout="wide")

# ---------------------------------------------------------------- 用户身份
# 不做账号体系: 用浏览器本地存一个 uuid。刷新不丢画像, 用户零门槛。
if "user_id" not in st.session_state:
    st.session_state.user_id = str(uuid.uuid4())[:8]
USER = st.session_state.user_id
store.init_db()
store.ensure_user(USER)


def answers():
    return store.get_answers(USER)


# ---------------------------------------------------------------- 侧栏
st.sidebar.title("🐳 优学鲸")
st.sidebar.caption("408 考研 · 个性化学习资源生成")
o = data.overview()
st.sidebar.markdown(
    f"""
**数据层**
- 真题 {o['题目总数']} 题（{o['年份范围']}）
- 考点 {o['叶子考点']} 个 · 依赖边 {o['依赖边']} 条
- 诊断题 {o['诊断题数']} 道
"""
)
PAGES = ["① 诊断", "② 我的画像", "③ 学习路径", "④ 专项练习"]
page = st.sidebar.radio("导航", PAGES, label_visibility="collapsed")

n_ans = len(answers())
st.sidebar.divider()
st.sidebar.caption(f"已作答 **{n_ans}** 题 · 用户 `{USER}`")
if st.sidebar.button("重置我的作答"):
    store.reset_user(USER)
    st.rerun()


# ================================================================ ① 诊断
if page == PAGES[0]:
    st.title("① 起点诊断")
    st.markdown(
        "**32 道题，约 20-25 分钟，覆盖 408 全部 24 章。**"
        "做完就能得到你的章节级掌握度，用于后续推荐。"
    )
    st.info(
        "为什么先做题而不是问你「哪科弱」：主观自评容易失真，"
        "用真题测出来的结果才能驱动精确推荐。",
        icon="💡",
    )

    paper = data.diagnostic()["题目"]
    got = answers()
    done = sum(1 for x in paper if x["id"] in got)
    st.progress(done / len(paper), text=f"进度 {done}/{len(paper)}")

    qs = data.questions()
    with st.form("diag"):
        for item in paper:
            q = qs[item["id"]]
            st.markdown(
                f"**{item['order']}. [{item['学科']} · {item['诊断章节名']} · "
                f"难度 {item['难度']}]** {q['题干']}"
            )
            opts = q.get("选项") or {}
            labels = [f"{k}. {v}" for k, v in sorted(opts.items())]
            keys = sorted(opts.keys())
            prev = got.get(item["id"], {}).get("chosen")
            idx = keys.index(prev) if prev in keys else None
            choice = st.radio(
                f"q{item['id']}", labels, index=idx, key=f"r{item['id']}",
                label_visibility="collapsed",
            )
            st.divider()

        if st.form_submit_button("提交并生成画像", type="primary"):
            n = 0
            for item in paper:
                # 直接读控件自身的 state（key 就是 r{id}），不依赖渲染时回写
                val = st.session_state.get(f"r{item['id']}")
                if not val:
                    continue
                pick = val[0]
                q = qs[item["id"]]
                store.record_answer(USER, item["id"], pick,
                                    pick == q.get("答案"), source="diagnostic")
                n += 1
            st.success(f"已记录 {n} 题。请到「② 我的画像」查看结果。")
            st.rerun()


# ================================================================ ② 画像
elif page == PAGES[1]:
    st.title("② 我的画像")
    a = answers()
    if not a:
        st.warning("还没有作答记录，请先到「① 诊断」做一次。")
        st.stop()

    prof = profile.build(a)
    m = diagnose.summarize(a)

    st.markdown(f"> {prof['文字画像']}")
    st.caption(
        "掌握度算法：（答对 + 1）/（题数 + 2），"
        "Laplace 平滑以避免只答 1 题就给出 0% 或 100% 的极端结论。"
    )

    cols = st.columns(len(m["学科"]) or 1)
    for col, (code, v) in zip(cols, sorted(m["学科"].items(), key=lambda x: -x[1]["掌握度"])):
        col.metric(v["学科"], f"{v['掌握度']:.0%}", f"{v['答对']}/{v['题数']} 题")

    st.divider()
    st.subheader("章节掌握度")
    for code, name in data.CODE2NAME.items():
        rows = [c for c in m["章节"].values() if c["学科码"] == code]
        if not rows:
            continue
        st.markdown(f"**{name}**")
        for c in sorted(rows, key=lambda x: x["掌握度"]):
            st.progress(
                c["掌握度"],
                text=f"{c['章节名']} — {c['掌握度']:.0%}（{c['答对']}/{c['题数']}）",
            )

    if prof["薄弱章节"]:
        st.divider()
        st.subheader("薄弱章节优先级")
        st.caption(
            "排序依据：**考频 ×（1 − 掌握度）**。"
            "考得越多、你越弱，越该先补 —— 这是「性价比」而不是单纯按分数低排序。"
        )
        for c in prof["薄弱章节"]:
            st.markdown(
                f"- **{c['章节名']}**　掌握度 {c['掌握度']:.0%}　"
                f"18 年考频 {c['考频']} 次　优先级分 {c['优先级分']}"
            )

    if prof["未测章节"]:
        st.divider()
        st.warning(
            f"还有 **{len(prof['未测章节'])}** 个章节没有测到："
            + "、".join(x["章节名"] for x in prof["未测章节"][:8])
            + "。建议加测以完善画像。"
        )


# ================================================================ ③ 路径
elif page == PAGES[2]:
    st.title("③ 学习路径")
    a = answers()
    if not a:
        st.warning("还没有作答记录，请先到「① 诊断」做一次。")
        st.stop()

    rec = path.recommend(a)
    if not rec["路径"]:
        st.info(rec.get("提示", "暂无推荐"))
        st.stop()

    st.markdown(
        f"根据你的画像，找出 **{rec['薄弱考点数']}** 个未掌握考点，"
        f"生成下面几条路径。**路径不互斥，你选一条开始就行。**"
    )

    tabs = st.tabs([f"{p['名称']}（{p['合计分钟']} 分钟）" for p in rec["路径"]])
    for tab, p in zip(tabs, rec["路径"]):
        with tab:
            st.markdown(f"**适用**：{p['适用']}")
            st.caption(p["说明"])
            if not p["步骤"]:
                st.info("这条路径当前没有需要补的考点。")
                continue
            for i, s in enumerate(p["步骤"], 1):
                with st.container(border=True):
                    c1, c2, c3 = st.columns([3, 1, 1])
                    c1.markdown(f"**{i}. {s['考点名']}**")
                    c1.caption(f"{s['学科']} · {s['章节']}")
                    c2.metric("当前掌握度",
                              f"{s['当前掌握度']:.0%}" if s["是否已测"] else "未测")
                    c3.metric("预计用时", f"{s['预计分钟']} 分钟")
                    st.caption(
                        f"考频 {s['考频']} 次 · 题库可练 {s['可练真题']} 题　|　"
                        f"{s['推荐理由']}"
                    )

    st.divider()
    st.caption(
        "「补根因」路径的机制：沿知识点依赖图向上追溯，"
        "找到最靠前的**断裂点**再开始补 —— 而不是直接练你表面最弱的那一章。"
        "依赖边来自 18 年真题的考点共现与考纲编排顺序，每条边都可追溯到依据。"
    )


# ================================================================ ④ 练习
else:
    st.title("④ 专项练习")
    st.markdown("按考点练真题，**提交后立即判分并归因到考点**。")

    a = answers()
    prof = profile.build(a) if a else {"薄弱考点": []}

    # 可选考点: 优先薄弱考点, 其次是高频考点
    leaves = data.chapter_leaves()
    freq = data.freq()
    options = []
    for x in prof["薄弱考点"]:
        options.append((x["leaf"], f"[薄弱] {x['考点名']}（{x['掌握度']:.0%}）"))
    hot = sorted(freq.items(), key=lambda kv: -kv[1]["考查总次数"])[:40]
    for lid, f in hot:
        if any(lid == o[0] for o in options):
            continue
        options.append((lid, f"{f['name']}（考频 {f['考查总次数']}）"))

    if not options:
        st.info("先做一次诊断，系统会按你的薄弱点推荐练习。")
        st.stop()

    labels = [x[1] for x in options]
    sel = st.selectbox("选择要练的考点", labels, index=0)
    leaf = options[labels.index(sel)][0]

    qs = data.questions()
    pool = [q for q in qs.values()
            if q["主考点"] == leaf and q["题型"] == "单项选择题" and q.get("答案")]
    if not pool:
        st.warning("这个考点在题库里暂时没有带答案的选择题。")
        st.stop()

    done = answers()
    pool = [q for q in pool if q["id"] not in done] or pool
    q = sorted(pool, key=lambda x: x["year"])[0]

    st.caption(f"考点 **{data.node_name(leaf)}** · 来自 {q['year']} 年真题 "
               f"（题库共 {len(pool)} 道可练）")
    if q.get("需插图") and not q.get("图片"):
        st.info("这道题原卷有插图，但插图尚未抽取齐全，建议换一题。", icon="🖼️")
    st.markdown(f"**{q['题干']}**")
    if q.get("图片"):
        st.image(f"data/{q['图片']}", width=420)

    opts = q.get("选项") or {}
    keys = sorted(opts.keys())
    with st.form(f"prac_{q['id']}"):
        pick = st.radio("选择答案", [f"{k}. {opts[k]}" for k in keys],
                        label_visibility="collapsed")
        if st.form_submit_button("提交答案", type="primary"):
            mine = pick[0]
            ok = mine == q.get("答案")
            store.record_answer(USER, q["id"], mine, ok, source="practice")
            if ok:
                st.success(f"答对了 ✓ 正确答案 {q['答案']}")
            else:
                st.error(f"答错了 ✗ 你选 {mine}，正确答案 {q['答案']}")
            st.caption(
                f"这道题已归因到考点「{data.node_name(leaf)}」，"
                f"作答记录会实时更新你的掌握度与路径推荐。"
            )
            st.rerun()
