#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多智能体编排(LangGraph StateGraph)。

六个节点, 每个是一个职责单一的 Agent:

    ┌──────────────────────────────────────────────────────────────┐
    │  load       准备 Agent   读取作答记录                        │
    │    ↓ (条件边: 没作答就要求先诊断)                             │
    │  diagnose   诊断 Agent   作答 → 章节/学科掌握度              │
    │    ↓                                                        │
    │  profile    画像 Agent   掌握度 → 薄弱点排序 + 文字画像       │
    │    ↓                                                        │
    │  recommend  路径 Agent   画像 + 依赖图 → 三条可选路径         │
    │    ↓                                                        │
    │  generate   生成 Agent   对路径上的考点生成讲义/总结          │
    │    ↓                                                        │
    │  review     复核 Agent   **程序化**校验生成内容未越出考纲      │
    └──────────────────────────────────────────────────────────────┘

为什么用 LangGraph 而不是顺序函数调用:
  1. 状态在节点间显式传递, 每一步的输入输出都可检查 —— 便于定位问题
  2. 条件边让"数据不足就走另一条路"成为图的一部分, 而不是散落的 if
  3. 可配 checkpoint, 中断后能恢复到同一状态

注意 review 节点**不用 LLM**: 它检查生成文本里的小标题是否都能在考纲 266 个叶子
考点中找到。这是可重复、可验证的防幻觉措施, 比"再让一个 LLM 审一遍"可靠得多。
"""
from typing import TypedDict, Literal

from . import data, store, diagnose, profile as profile_mod, path as path_mod
from . import generate as gen_mod

try:
    from langgraph.graph import StateGraph, START, END
    HAS_LANGGRAPH = True
except Exception:                                   # noqa: BLE001
    HAS_LANGGRAPH = False


class YJState(TypedDict, total=False):
    user_id: str
    answers: dict
    marks: set            # 用户自报的薄弱考点(与作答同等重要)
    mastery: dict
    profile: dict
    path: dict
    selected_path: str
    resources: list
    review: dict
    notes: list
    llm_ready: bool
    traced: list          # 每个节点的执行轨迹, 界面上可展示"多智能体在做什么"


def _trace(state, agent, detail):
    t = list(state.get("traced") or [])
    t.append({"agent": agent, "detail": detail})
    return t


# ---------------------------------------------------------------- 各 Agent
def agent_load(state: YJState) -> YJState:
    """准备 Agent：读作答记录 + 用户自报的薄弱考点。"""
    a = store.get_answers(state["user_id"])
    mk = store.get_marks(state["user_id"])
    return {"answers": a, "marks": mk,
            "notes": [f"读取到 {len(a)} 条作答、{len(mk)} 个自报薄弱考点"],
            "traced": _trace(state, "准备 Agent",
                             f"读取作答 {len(a)} 条 / 自报薄弱 {len(mk)} 个")}


def agent_diagnose(state: YJState) -> YJState:
    """诊断 Agent：作答 → 三层掌握度。"""
    m = diagnose.summarize(state["answers"])
    return {"mastery": m,
            "notes": state.get("notes", []) +
                     [f"算出 {len(m['章节'])} 个章节、{len(m['考点'])} 个考点的掌握度"],
            "traced": _trace(state, "诊断 Agent",
                             f"章节 {len(m['章节'])} 个 / 考点 {len(m['考点'])} 个")}


def agent_profile(state: YJState) -> YJState:
    """画像 Agent：掌握度 + 自报薄弱 → 薄弱点排序与文字画像。"""
    p = profile_mod.build(state["answers"], state.get("marks"))
    return {"profile": p,
            "notes": state.get("notes", []) + [p["文字画像"]],
            "traced": _trace(state, "画像 Agent",
                             f"薄弱章节 {len(p['薄弱章节'])} 个, "
                             f"强项 {len(p['强项章节'])} 个")}


def agent_recommend(state: YJState) -> YJState:
    """路径 Agent：画像 + 依赖图 → 三条可选路径。"""
    r = path_mod.recommend(state["answers"], marks=state.get("marks"))
    sel = state.get("selected_path")
    if not sel and r["路径"]:
        sel = r["路径"][0]["id"]
    return {"path": r, "selected_path": sel,
            "traced": _trace(state, "路径 Agent",
                             f"生成 {len(r['路径'])} 条路径, 选中「{sel}」")}


def agent_generate(state: YJState) -> YJState:
    """生成 Agent：对选中路径上的考点生成讲义与速记。"""
    r = state.get("path") or {}
    picked = next((p for p in r.get("路径", [])
                   if p["id"] == state.get("selected_path")), None)
    if not picked:
        return {"resources": [], "traced": _trace(state, "生成 Agent", "无路径可生成")}
    out = []
    for s in picked["步骤"][:4]:                    # 控制长度, 路演友好
        leaf = s["考点"]
        out.append({
            "leaf": leaf,
            "考点名": s["考点名"],
            "章节": s["章节"],
            "讲义": gen_mod.lesson(leaf, state["answers"],
                                   marks=state.get("marks")),
            "速记": gen_mod.summary(leaf),
            "习题": gen_mod.exercises(leaf),   # 默认全量（见 generate.EXERCISE_MAX）
        })
    srcs = {x["讲义"]["source"] for x in out}
    return {"resources": out,
            "traced": _trace(state, "生成 Agent",
                             f"为 {len(out)} 个考点生成资源, 内容来源 {sorted(srcs)}")}


def agent_review(state: YJState) -> YJState:
    """
    复核 Agent：程序化校验生成内容是否越出考纲。

    刻意不用 LLM —— 用可重复的规则检查, 结论可复核。
    """
    bad = {}
    for r in state.get("resources", []):
        v = r["讲义"].get("校验") or {}
        if not v.get("通过"):
            bad[r["考点名"]] = v.get("疑似考纲外", [])
    return {"review": {"通过": not bad, "越纲项": bad,
                       "检查项数": len(state.get("resources", []))},
            "traced": _trace(state, "复核 Agent",
                             "考纲校验通过" if not bad else f"{len(bad)} 个考点有越纲项")}


# ---------------------------------------------------------------- 条件边
def route_after_load(state: YJState) -> Literal["diagnose", "need_diagnosis"]:
    """
    两条数据来源任一存在就继续:
      - 作答记录(诊断/练习)
      - 用户自报的薄弱考点
    两者都没有才要求先给点输入 —— 这就是条件边的用处。

    (早期只看作答记录, 导致"只勾选不作答"的用户被挡在链路外。)
    """
    return ("diagnose" if (state.get("answers") or state.get("marks"))
            else "need_diagnosis")


def agent_need_diagnosis(state: YJState) -> YJState:
    return {"notes": state.get("notes", []) +
                     ["既没有作答记录, 也没有标记薄弱考点, 请先给一个输入"],
            "traced": _trace(state, "准备 Agent",
                             "无作答且无标记 → 要求先给输入")}


# ---------------------------------------------------------------- 组装
def build_graph():
    if not HAS_LANGGRAPH:
        return None
    g = StateGraph(YJState)
    g.add_node("load", agent_load)
    g.add_node("need_diagnosis", agent_need_diagnosis)
    g.add_node("diagnose", agent_diagnose)
    g.add_node("profile", agent_profile)
    g.add_node("recommend", agent_recommend)
    g.add_node("generate", agent_generate)
    g.add_node("review", agent_review)

    g.add_edge(START, "load")
    g.add_conditional_edges("load", route_after_load,
                            {"diagnose": "diagnose",
                             "need_diagnosis": "need_diagnosis"})
    g.add_edge("need_diagnosis", END)
    g.add_edge("diagnose", "profile")
    g.add_edge("profile", "recommend")
    g.add_edge("recommend", "generate")
    g.add_edge("generate", "review")
    g.add_edge("review", END)
    return g.compile()


_APP = None


def run(user_id, selected_path=None):
    """跑一次完整链路。LangGraph 不可用时退回顺序执行(结果一致)。"""
    global _APP
    init = {"user_id": user_id, "selected_path": selected_path,
            "notes": [], "traced": [], "llm_ready": True}
    if _APP is None:
        _APP = build_graph()
    if _APP is not None:
        return _APP.invoke(init)
    # ---- 降级: 顺序执行同样的节点
    st = dict(init)
    st.update(agent_load(st))
    if route_after_load(st) == "need_diagnosis":
        st.update(agent_need_diagnosis(st))
        return st
    for fn in (agent_diagnose, agent_profile, agent_recommend,
               agent_generate, agent_review):
        st.update(fn(st))
    return st


def mermaid():
    """导出图结构(界面展示"多智能体调度图"用)"""
    app = _APP or build_graph()
    if app is None:
        return "LangGraph 未安装，使用顺序执行降级路径"
    try:
        return app.get_graph().draw_mermaid()
    except Exception as e:                          # noqa: BLE001
        return f"（图形导出不可用：{type(e).__name__}）"


if __name__ == "__main__":
    print("LangGraph 可用:", HAS_LANGGRAPH)
    print(mermaid())
