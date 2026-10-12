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
  ⑤ 讲义生成     LangGraph 多智能体链路
"""
import os
import json
import uuid
import streamlit as st

from yj import data, store, diagnose, profile, path, llm, graph
from yj import snap as snap_mod

st.set_page_config(page_title="优学鲸 · 408 考研", page_icon="🐳", layout="wide")

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


# ---------------------------------------------------------------- 侧栏
st.sidebar.title("🐳 优学鲸")
st.sidebar.caption("408 考研 · 个性化学习资源生成")

o = data.overview()
ok_llm, msg_llm = llm.status()
st.sidebar.markdown(
    f"""
**数据层**
- 真题 {o['题目总数']} 题（{o['年份范围']}）
- 考点 {o['叶子考点']} 个 · 依赖边 {o['依赖边']} 条
"""
)
st.sidebar.caption(("🟢 " if ok_llm else "🟡 ") + msg_llm)

st.sidebar.divider()
st.sidebar.caption(f"已标记 **{len(marks())}** 个薄弱考点 · "
                   f"已作答 **{len(answers())}** 题")
st.sidebar.caption(f"用户 `{USER}`")
if st.sidebar.button("清空我的全部记录", help="清空标记与作答"):
    store.reset_user(USER)
    for k in [k for k in st.session_state if k.startswith(("cb_", "pill_", "sel_",
                                                           "practice_", "run"))]:
        st.session_state.pop(k, None)
    st.rerun()

PAGES = ["🎯 挑考点练习", "🧭 快速诊断", "📊 我的画像", "🛣 学习路径", "📘 讲义生成"]
page = st.sidebar.radio("导航", PAGES, label_visibility="collapsed")


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


def render_question(q, leaf, key_prefix, source="practice"):
    """渲染一道题并判分。"""
    if q.get("需插图") and not q.get("图片"):
        st.info("这道题原卷有插图，但插图尚未抽取齐全，建议换一题。", icon="🖼️")
    if q.get("图片"):
        st.image(f"data/{q['图片']}", width=420)
    opts = q.get("选项") or {}
    keys = sorted(opts.keys())
    pick_key, done_key = f"{key_prefix}_pick", f"{key_prefix}_done"
    with st.form(key_prefix):
        st.radio("选项", [f"{k}. {opts[k]}" for k in keys],
                 key=pick_key, label_visibility="collapsed")
        if st.form_submit_button("提交答案", type="primary"):
            val = st.session_state.get(pick_key) or ""
            mine = val[0] if val else None
            if mine:
                ok = mine == q.get("答案")
                store.record_answer(USER, q["id"], mine, ok, source=source)
                st.session_state[done_key] = {"mine": mine, "ok": ok}
    r = st.session_state.get(done_key)
    if r:
        if r["ok"]:
            st.success(f"答对了 ✓ 正确答案 {q['答案']}")
        else:
            st.error(f"答错了 ✗ 你选 {r['mine']}，正确答案 {q['答案']}")
        st.caption(f"已归因到考点「{data.node_name(leaf)}」，"
                   f"作答会实时更新你的掌握度与路径推荐。")


# ================================================================ ① 挑考点练习
if page == PAGES[0]:
    subj = st.session_state.get("sel_subject")

    # ---------- 第一步：选书 ----------
    if not subj:
        st.title("挑考点练习")
        st.markdown("**先选一门课，再挑你觉得薄弱的知识点，系统从这些考点给你出真题。**"
                    "不需要先做任何测试。")
        st.caption("想更准？也可以先做一次「🧭 快速诊断」—— 但那是可选的，不是门槛。")
        st.divider()
        cols = st.columns(4)
        for col, code in zip(cols, ["DS", "CO", "OS", "CN"]):
            b = book_meta(code)
            with col, st.container(border=True):
                st.markdown(f"### {b['name']}")
                st.caption(f"{b['章数']} 章 · {b['考点数']} 个考点")
                st.caption(f"18 年考频 {b['考频']} 次 · 题库 {b['可练题']} 题可练")
                if b["掌握度"] is not None:
                    st.metric("我的掌握度", f"{b['掌握度']:.0%}")
                else:
                    st.caption("我的掌握度：未测")
                if b["已标记"]:
                    st.caption(f"已标记 {b['已标记']} 个薄弱考点")
                if st.button(f"进入 {b['name']}", key=f"go_{code}",
                             use_container_width=True):
                    st.session_state["sel_subject"] = code
                    st.session_state.pop("sel_chapter", None)
                    st.rerun()
        st.stop()

    # ---------- 第二步：选章 ----------
    b = book_meta(subj)
    c1, c2 = st.columns([4, 1])
    c1.markdown(f"## 📚 {b['name']}")
    if c2.button("← 换一门", use_container_width=True):
        st.session_state.pop("sel_subject", None)
        st.session_state.pop("sel_chapter", None)
        st.rerun()

    chs = data.chapters()[subj]
    m_ch = diagnose.mastery_by_chapter(answers())
    freq, lqc, my_marks = data.freq(), data.leaf_question_count(), marks()

    st.caption("各章概况。掌握度未测的章节，就按你勾选的考点来推荐。")
    for ch, nm in chs:
        cm = m_ch.get(ch)
        n_mark = len([l for l in data.chapter_leaves().get(ch, []) if l in my_marks])
        a1, a2, a3 = st.columns([3, 3, 1])
        a1.markdown(f"**{nm}**")
        a2.caption(f"考频 {data.chapter_freq().get(ch, 0)} 次 · "
                   f"{len(data.chapter_leaves().get(ch, []))} 个考点"
                   + (f" · 已标记 {n_mark}" if n_mark else ""))
        a3.caption(f"掌握度 {cm['掌握度']:.0%}" if cm else "未测")

    st.divider()
    st.markdown("#### 选择章节")
    ch_labels = {nm: ch for ch, nm in chs}
    sel_label = st.pills("章节", list(ch_labels.keys()), selection_mode="single",
                         key=f"pill_ch_{subj}", label_visibility="collapsed")
    if sel_label:
        st.session_state["sel_chapter"] = ch_labels[sel_label]
    ch = st.session_state.get("sel_chapter")

    # ---------- 第三步：选考点 ----------
    if ch:
        leaves = data.chapter_leaves().get(ch, [])
        if leaves:
            st.divider()
            st.markdown(f"#### {data.node_name(ch)} — 勾选你觉得薄弱的知识点")
            st.caption("可多选。换章再回来，之前的勾选会保留。"
                       "标 **·0题** 的考点题库里暂无对应真题，勾选后不会有题可练"
                       "（但仍可用来生成讲义）。")
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
        by_ch = {}
        for l in sel:
            by_ch.setdefault(data.chapter_of(l), []).append(l)
        total_q = sum(data.leaf_question_count().get(l, 0) for l in sel)
        no_q = [l for l in sel if not data.leaf_question_count().get(l, 0)]
        st.markdown(f"### 已选 **{len(sel)}** 个考点 · 题库共 **{total_q}** 道真题可练")
        if no_q:
            st.caption("其中 "
                       + "、".join(data.node_name(l) for l in no_q)
                       + f" 共 {len(no_q)} 个考点暂无题目，只能用于生成讲义。")
        for c, ls in sorted(by_ch.items(),
                            key=lambda kv: -data.chapter_freq().get(kv[0], 0)):
            st.caption(f"　{data.node_name(c)}："
                       + "、".join(data.node_name(l) for l in ls))

        b1, b2, b3 = st.columns([2, 2, 3])
        if b1.button("▶ 开始练习", type="primary", use_container_width=True):
            st.session_state["practice_now"] = True
        if b2.button("清空选择", use_container_width=True):
            store.set_marks(USER, set())
            st.session_state.pop("practice_now", None)
            st.rerun()
        b3.caption("选好后也可以到左侧「📘 讲义生成」按这些考点生成讲义。")

    # ---------- 就地出题 ----------
    if st.session_state.get("practice_now") and sel:
        st.divider()
        st.markdown("### 开始练习")
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
            st.caption(f"从你选的考点里抽题：优先没做过的、难度较低的先来。"
                       f"共 {len(pool)} 道可选。")
            show = pool[:5]
            for i, (l, q) in enumerate(show, 1):
                with st.container(border=True):
                    st.markdown(f"**{i}. {q['year']} 年 第 {q['题号']} 题**"
                                f"　·　{data.node_name(l)}　·　难度 {q.get('难度')}")
                    st.markdown(q["题干"])
                    render_question(q, l, key_prefix=f"p_{q['id']}")
            if len(pool) > len(show):
                st.caption(f"还有 {len(pool) - len(show)} 道。"
                           f"再做一轮会优先取出未做过的题。")


# ================================================================ ② 快速诊断
elif page == PAGES[1]:
    st.title("🧭 快速诊断（可选）")
    st.markdown("**32 道题，约 20-25 分钟，覆盖 408 全部 24 章。**"
                "做完会得到章节级掌握度，让推荐更准。")
    st.info("这一步是**可选**的。不做也能用 —— 你可以在「🎯 挑考点练习」里"
            "直接勾选自己认为薄弱的知识点。", icon="💡")

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
            st.radio(f"q{item['id']}", [f"{k}. {opts[k]}" for k in keys],
                     index=keys.index(prev) if prev in keys else None,
                     key=f"r{item['id']}", label_visibility="collapsed")
            st.divider()
        if st.form_submit_button("提交并生成掌握度", type="primary"):
            n = 0
            for item in paper:
                val = st.session_state.get(f"r{item['id']}")
                if not val:
                    continue
                q = qs[item["id"]]
                store.record_answer(USER, item["id"], val[0],
                                    val[0] == q.get("答案"), source="diagnostic")
                n += 1
            st.success(f"已记录 {n} 题。到「📊 我的画像」查看结果。")
            st.rerun()


# ================================================================ ③ 我的画像
elif page == PAGES[2]:
    st.title("📊 我的画像")
    a, mk = answers(), marks()
    if not a and not mk:
        st.info("还没有任何数据。你可以：\n\n"
                "1. 到「🎯 挑考点练习」勾选自己觉得薄弱的知识点（最快）\n"
                "2. 或到「🧭 快速诊断」做一次 32 题测试（更准）")
        st.stop()

    prof = profile.build(a, mk)
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
        st.caption(f"另有你自报的 {len(mk)} 个薄弱考点，已计入下方排序。")

    st.divider()
    st.subheader("章节掌握度")
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
        st.subheader("薄弱优先级")
        st.caption("排序依据：**考频 ×（1 − 掌握度）**。考得越多、你越弱，越该先补。")
        for c in prof["薄弱章节"]:
            lvl = f"{c['掌握度']:.0%}" if c["掌握度"] is not None else "未测"
            src = f"　·　{c.get('来源', '')}" if c.get("来源") else ""
            st.markdown(f"- **{c['章节名']}**　掌握度 {lvl}　"
                        f"18 年考频 {c['考频']} 次　优先级分 {c['优先级分']}{src}")

    if prof["未测章节"]:
        st.divider()
        st.warning(f"还有 **{len(prof['未测章节'])}** 个章节没有测到："
                   + "、".join(x["章节名"] for x in prof["未测章节"][:8])
                   + "。建议到「🧭 快速诊断」加测以完善画像。")


# ================================================================ ④ 学习路径
elif page == PAGES[3]:
    st.title("🛣 学习路径")
    a, mk = answers(), marks()
    if not a and not mk:
        st.info("还没有数据。先到「🎯 挑考点练习」勾选薄弱知识点，"
                "或做一次「🧭 快速诊断」。")
        st.stop()

    rec = path.recommend(a, marks=mk)
    if not rec.get("路径"):
        st.info(rec.get("提示", "暂无推荐"))
        st.stop()

    st.markdown(f"根据你的画像（含自报薄弱点），找出 **{rec['薄弱考点数']}** 个未掌握考点，"
                f"生成下面几条路径。**路径不互斥，选一条开始就行。**")
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
                    st.caption(f"考频 {s['考频']} 次 · 题库可练 {s['可练真题']} 题　|　"
                               f"{s['推荐理由']}")
    st.divider()
    st.caption("「补根因」的机制：沿知识点依赖图向上追溯，找到最靠前的**断裂点**再开始补，"
               "而不是直接练你表面最弱的那一章。依赖边来自 18 年真题的考点共现与考纲编排顺序。")


# ================================================================ ⑤ 讲义生成
else:
    st.title("📘 讲义生成（多智能体）")
    ok, msg = llm.status()
    if ok:
        st.success(msg, icon="🟢")
    else:
        st.warning(msg + " —— 页面会照常跑通，但讲义正文是**用真实数据填的模板**，"
                         "不是 AI 写的。", icon="🟡")

    a, mk = answers(), marks()
    if not a and not mk:
        st.info("还没有数据。先到「🎯 挑考点练习」勾选薄弱知识点。")
        st.stop()

    rec = path.recommend(a, marks=mk)
    import glob as _glob
    _snaps = sorted(os.path.basename(x)[:-5] for x in _glob.glob("data/prewarm/*.json"))
    mode = st.radio("运行方式", ["实时运行", "回放预跑快照"], horizontal=True,
                    help="路演兜底：API 不可用时用快照回放，输出与预跑时完全一致。")

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
        sel_name = st.selectbox("选中要生成的路径", names)
        if not a:
            st.caption("提示：你没有做题记录，链路会依据**你勾选的薄弱考点**生成。")
        if st.button("▶ 运行多智能体链路", type="primary"):
            with st.spinner("多智能体执行中…"):
                st.session_state["run"] = graph.run(
                    USER, selected_path={"补根因": "root", "冲高频": "freq",
                                         "错题驱动": "wrong"}.get(sel_name, "root"))
                st.session_state.pop("run_meta", None)

    if st.session_state.get("run_meta"):
        st.info("正在回放预跑快照 —— " + st.session_state["run_meta"], icon="📦")

    R = st.session_state.get("run")
    if not R:
        st.caption("还没有运行。")
        st.stop()

    st.subheader("执行轨迹")
    for t in R.get("traced", []):
        st.markdown(f"- **{t['agent']}** — {t['detail']}")
    rv = R.get("review") or {}
    if rv:
        if rv.get("通过"):
            st.success(f"复核 Agent：考纲校验通过（检查了 {rv.get('检查项数', 0)} 个考点）",
                       icon="✅")
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
        with st.expander(f"📘 {x['考点名']}　·　{x['章节']}　·　{label}",
                         expanded=(x is res[0])):
            t1, t2, t3 = st.tabs(["讲义", "知识点速记", "配套真题"])
            with t1:
                st.markdown(x["讲义"]["markdown"])
                v = x["讲义"].get("校验") or {}
                st.caption("✅ 复核 Agent：内容未越出考纲考点范围" if v.get("通过")
                           else f"⚠️ 疑似考纲外内容：{v.get('疑似考纲外')}")
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
