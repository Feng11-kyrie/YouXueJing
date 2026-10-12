#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
画像 + 依赖图 → 推荐学习路径。

这是整个产品的差异化所在, 对应验收指标 2「基于画像推荐学习路径, 为用户生成
多条可选学习路径, 供其自主选择」。

三条路径, 三种取舍(用户自己选):
  A 补根因  —— 沿依赖图向上追溯断裂点, 从最靠前的前置开始补。适合基础不牢。
  B 冲高频  —— 只挑考频最高的薄弱考点。适合时间紧、要快速提分。
  C 错题驱动 —— 从做错的题反推考点。适合已经练过、想精准补漏。

关键机制: **断裂点追溯**
  用户说"红黑树弱", 但根因可能是"二叉搜索树"。所以不能直接推薄弱点,
  要沿依赖边向上走, 直到找到一个已经掌握的节点 —— 那才是该开始补的地方。
"""
from functools import lru_cache

from . import data

WEAK = 0.60
TARGET = 0.85            # 补到这个水平算"可以过了"
MAX_DEPTH = 3            # 依赖追溯的最大深度, 防止路径过长


@lru_cache(maxsize=1)
def _leaf_question_count():
    """考点 -> 题库里有多少道真题可练"""
    out = {}
    for q in data.questions().values():
        if q["题型"] == "单项选择题" and q.get("答案"):
            out[q["主考点"]] = out.get(q["主考点"], 0) + 1
    return out


def _est_minutes(current):
    """
    预估补课时长(启发式, 不是精确值)。

    公式: (0.85 - 当前掌握度) / 0.05 × 5 分钟 —— 即每提升 5 个百分点约 5 分钟。
    下限 15 分钟, 取整到 5 分钟。
    说明: 这是基于经验的经验值, 用于给出量级感, 不代表精确预测。
    """
    raw = (TARGET - current) / 0.05 * 5
    return max(15, int(round(raw / 5.0) * 5))


def _step(leaf, mastery, reason):
    f = data.freq().get(leaf, {})
    m = mastery.get(leaf, {}).get("掌握度")
    ch = data.chapter_of(leaf)
    return {
        "考点": leaf, "考点名": data.node_name(leaf),
        "章节": data.node_name(ch), "章节id": ch,
        "学科": data.CODE2NAME.get(data.subject_of(leaf), ""),
        "当前掌握度": m if m is not None else 0.0,
        "是否已测": m is not None,
        "考频": f.get("考查总次数", 0),
        "可练真题": _leaf_question_count().get(leaf, 0),
        "预计分钟": _est_minutes(m if m is not None else 0.0),
        "推荐理由": reason,
    }


def trace_chapter(ch, chapter_mastery, depth=0, seen=None):
    """
    沿**章级**前置向上追溯根因, 返回 (该从哪个章开始, 追溯链说明)。

    规则: 若某前置章也薄弱, 说明问题在更前面 —— 继续上溯。
          未测的前置**不作为上溯依据**(不知道它弱, 不能假设它弱)。
          已掌握的前置直接跳过。
    只在章级追溯的原因见 data.chapter_prereqs() 的说明。
    """
    seen = set(seen or ())
    if depth >= MAX_DEPTH or ch in seen:
        return ch, []
    seen.add(ch)
    for pre in data.chapter_prereqs().get(ch, []):
        pc = pre["chapter"]
        pm = chapter_mastery.get(pc, {}).get("掌握度")
        if pm is None or pm >= WEAK:
            continue
        note = f"{data.node_name(pc)}({pm:.0%})"
        up, ups = trace_chapter(pc, chapter_mastery, depth + 1, seen)
        return up, [note] + ups
    return ch, []


def _weakest_leaf_in(ch, mastery_leaf):
    """
    章内挑一个"最该先练"的叶子考点:
      优先已测且掌握度最低的; 若都没测, 取该章考频最高的那个。
    """
    leaves = data.chapter_leaves().get(ch, [])
    if not leaves:
        return None
    tested = [(mastery_leaf[l]["掌握度"], l) for l in leaves if l in mastery_leaf]
    if tested:
        return min(tested)[1]
    f = data.freq()
    return max(leaves, key=lambda l: f.get(l, {}).get("考查总次数", 0))


def _path_补根因(chapter_mastery, mastery_leaf, weak_chapters, topn=5):
    """
    先沿章级依赖追溯根因, 再在该章内挑最该练的叶子作为起点。
    这是与「冲高频」的核心区别: **不是直接练表面最弱的章, 而是从断裂点开始。**
    """
    steps, used_ch = [], set()
    for w in weak_chapters:
        start_ch, chain = trace_chapter(w["chapter"], chapter_mastery)
        if start_ch in used_ch:
            continue
        leaf = _weakest_leaf_in(start_ch, mastery_leaf)
        if not leaf:
            continue
        used_ch.add(start_ch)
        if chain:
            reason = ("根因追溯：" + " → ".join(chain)
                      + f" → 因此从「{data.node_name(start_ch)}」开始补")
        else:
            reason = "该章本身已是链条最前端，直接从它开始"
        if start_ch != w["chapter"]:
            reason += f"（你表面最弱的是「{w['章节名']}」，但前置没打牢）"
        steps.append(_step(leaf, mastery_leaf, reason))
        if len(steps) >= topn:
            break
    return steps


def _path_冲高频(mastery_leaf, weak_leaves, topn=6):
    """只挑考频最高的薄弱考点, 不考虑依赖顺序。"""
    steps = []
    for w in sorted(weak_leaves, key=lambda x: -data.freq().get(x["leaf"], {})
                    .get("考查总次数", 0))[:topn]:
        steps.append(_step(w["leaf"], mastery_leaf,
                           f"18 年考了 {data.freq().get(w['leaf'], {}).get('考查总次数', 0)} 次，"
                           f"你目前 {w['掌握度']:.0%}"))
    return steps


def _path_错题驱动(mastery_leaf, wrong_ids):
    """从做错的题反推考点, 按错题数排序。"""
    from collections import Counter
    qs = data.questions()
    cnt = Counter(qs[i]["主考点"] for i in wrong_ids if i in qs)
    steps = []
    for leaf, n in cnt.most_common(8):
        s = _step(leaf, mastery_leaf, f"你有 {n} 道错题落在这个考点")
        s["错题数"] = n
        steps.append(s)
    return steps


def recommend(answers, wrong_ids=None, weak_threshold=WEAK):
    """
    主入口。返回 2-4 条可选路径。

    参数
    ----
    answers   : {question_id: {'is_correct': bool, ...}}
    wrong_ids : 做错的题目 id 列表(不传则从 answers 推导)
    """
    from .diagnose import mastery_by_leaf, mastery_by_chapter
    mastery_leaf = mastery_by_leaf(answers)
    chapter_mastery = mastery_by_chapter(answers)
    prof = __import__("yj.profile", fromlist=["build"]).build(answers)
    weak_leaves = prof["薄弱考点"]
    weak_chapters = prof["薄弱章节"]

    if wrong_ids is None:
        wrong_ids = [qid for qid, a in answers.items() if not a["is_correct"]]

    if not mastery_leaf:
        return {"提示": "还没有作答记录，请先完成诊断。", "路径": []}

    paths = []

    if weak_chapters:
        steps = _path_补根因(chapter_mastery, mastery_leaf, weak_chapters)
        if steps:
            paths.append({
                "id": "root", "名称": "补根因",
                "适用": "基础不牢，想把链条从头理顺",
                "说明": "沿知识点依赖图向上追溯，找到最靠前的断裂点，从那里开始补 —— "
                        "而不是直接练你表面最弱的那一章。",
                "步骤": steps,
                "合计分钟": sum(s["预计分钟"] for s in steps),
            })

    if weak_leaves:
        steps = _path_冲高频(mastery_leaf, weak_leaves)
        if steps:
            paths.append({
                "id": "freq", "名称": "冲高频",
                "适用": "时间紧，想按考频优先提分",
                "说明": "只挑 18 年真题里考得最多、而你又没掌握的考点，按频次从高到低练。",
                "步骤": steps,
                "合计分钟": sum(s["预计分钟"] for s in steps),
            })

    if wrong_ids:
        steps = _path_错题驱动(mastery_leaf, wrong_ids)
        if steps:
            paths.append({
                "id": "wrong", "名称": "错题驱动",
                "适用": "已经练过题，想精准补漏",
                "说明": "按你的错题分布定位考点，错得多的先补。",
                "步骤": steps,
                "合计分钟": sum(s["预计分钟"] for s in steps),
            })

    if not paths:
        paths.append({
            "id": "none", "名称": "暂无需补强",
            "适用": "各章都已在阈值以上",
            "说明": f"你已测章节的掌握度都在 {weak_threshold:.0%} 以上，"
                    f"可以去做完整套真题检验，或加测尚未覆盖的章节。",
            "步骤": [], "合计分钟": 0,
        })
    return {"路径": paths, "薄弱考点数": len(weak_leaves)}
