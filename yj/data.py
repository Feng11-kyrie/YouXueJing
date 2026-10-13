#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据层读取与索引。

对外只暴露"业务视角"的接口, 上层模块不必关心 JSON 结构。
所有数据来自 ../data/408/, 由 scripts/ 下的构建脚本产出。
"""
import os
import json
from functools import lru_cache

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data", "408")

SUBJECTS = ["数据结构", "计算机组成原理", "操作系统", "计算机网络"]
CODE2NAME = {"DS": "数据结构", "CO": "计算机组成原理",
             "OS": "操作系统", "CN": "计算机网络"}
NAME2CODE = {v: k for k, v in CODE2NAME.items()}


def _load(name):
    with open(os.path.join(DATA, name), encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def questions():
    """题目 id -> 题目记录(含主考点/答案/插图字段)"""
    doc = _load("question_tags.json")
    return {q["id"]: q for q in doc["题目"]}


@lru_cache(maxsize=1)
def syllabus():
    return _load("syllabus_tree.json")


@lru_cache(maxsize=1)
def freq():
    """叶子考点 id -> 频次记录"""
    return {x["id"]: x for x in _load("exam_freq.json")["考点"]}


@lru_cache(maxsize=1)
def depends():
    """依赖边列表, 按置信度降序"""
    edges = _load("depends_graph.json")["边"]
    return sorted(edges, key=lambda e: -e["置信度"])


@lru_cache(maxsize=1)
def diagnostic():
    return _load("diagnostic.json")


@lru_cache(maxsize=1)
def nodes():
    """
    展平考纲树: 节点 id -> {id, name, level, subject, chapter, parent}
    便于按 章节/学科 聚合。
    """
    out = {}

    def walk(n, subj, chapter, parent, level):
        out[n["id"]] = {
            "id": n["id"], "name": n.get("name_plain") or n["name_official"],
            "name_official": n["name_official"],
            "level": level, "subject": subj, "chapter": chapter, "parent": parent,
        }
        # 章(level 2)自己的 chapter 就是自己; 更深层沿用所属章。
        # 早先这里写成 n["id"] if level == 1 else chapter —— 用的是**父节点**的 level,
        # 导致所有章节都被标成了学科 id, 界面上的章节名全变成学科名。
        my_chapter = n["id"] if level == 2 else chapter
        for c in n.get("children") or []:
            walk(c, subj, my_chapter, n["id"], level + 1)

    for s in syllabus()["学科"]:
        walk(s, s["id"], None, None, 1)
    return out


@lru_cache(maxsize=1)
def leaf_ids():
    """叶子节点 id 集合(打标候选集)"""
    return {i for i, n in nodes().items()
            if not any(c["parent"] == i for c in nodes().values())}


@lru_cache(maxsize=1)
def chapters():
    """学科码 -> [(章 id, 章名)]"""
    out = {}
    for s in syllabus()["学科"]:
        out[s["id"]] = [(c["id"], c["name_official"]) for c in s["children"]]
    return out


@lru_cache(maxsize=1)
def chapter_leaves():
    """章 id -> 该章下的叶子考点 id 列表"""
    out = {}
    for i, n in nodes().items():
        if n["level"] >= 2 and i in leaf_ids():
            out.setdefault(n["chapter"], []).append(i)
        elif n["level"] == 2 and i in leaf_ids():      # 章本身就是叶子(理论可能)
            out.setdefault(i, []).append(i)
    return out


@lru_cache(maxsize=1)
def leaf_question_count():
    """考点 -> 题库里有多少道**带答案的单选题**可练(界面选题时显示用)"""
    out = {}
    for q in questions().values():
        if q["题型"] == "单项选择题" and q.get("答案"):
            out[q["主考点"]] = out.get(q["主考点"], 0) + 1
    return out


def chapter_of(node_id):
    n = nodes().get(node_id)
    return n["chapter"] if n else None


def subject_of(node_id):
    n = nodes().get(node_id)
    return n["subject"] if n else None


def node_name(node_id):
    n = nodes().get(node_id)
    return n["name"] if n else node_id


@lru_cache(maxsize=1)
def prereqs():
    """节点 -> 它的前置节点列表(只取置信度 >= 0.7 的高置信边)"""
    out = {}
    for e in depends():
        if e["置信度"] >= 0.7:
            out.setdefault(e["to"], []).append(e["from"])
    return out


@lru_cache(maxsize=1)
def successors():
    """
    节点 -> 以它为前置的节点列表(即 prereqs 的反向)。

    用途: 讲义里回答"学完这个考点, 后面哪些考点要用到它" ——
    依赖图此前只有向上的根因追溯, 这是第一个向下的用途。
    同样只取置信度 >= 0.7 的高置信边。
    """
    out = {}
    for e in depends():
        if e["置信度"] >= 0.7:
            out.setdefault(e["from"], []).append(e["to"])
    return out


@lru_cache(maxsize=1)
def chapter_prereqs():
    """
    章 -> 前置章列表, 每项 {chapter, 依据, 置信度}。

    两个来源:
      依赖证据(0.9) —— 由**叶子级高置信依赖边**跨章聚合而来, 有真题共现支撑
      考纲顺序(0.6) —— 考纲章节的编排顺序本身隐含学习顺序(弱先验)

    为什么要聚合成章级:
      依赖边建在叶子考点上, 但诊断只有 32 题、每章 1-2 题, 叶子级掌握度极稀疏,
      直接做叶子级追溯几乎没有信号; 聚合成 24 个章后才能用于冷启动画像。

    为什么需要"考纲顺序"这个弱先验:
      跨章高置信边实测只有 10 条(如 数据链路层->网络层 的证据不足 0.7),
      只靠它会让追溯大量落地失败。考纲顺序是可靠的结构信号, 但**明确标注为弱依据**,
      便于上层按需降权或只作解释。
    """
    agg = {}
    for e in depends():
        if e["置信度"] < 0.7:
            continue
        cf, ct = chapter_of(e["from"]), chapter_of(e["to"])
        if cf and ct and cf != ct:
            cur = agg.setdefault(ct, {})
            if cf not in cur or cur[cf]["置信度"] < 0.9:
                cur[cf] = {"chapter": cf, "依据": "依赖证据", "置信度": 0.9}

    # 补考纲相邻章顺序(仅同科目内相邻)
    for code, chs in chapters().items():
        for (a, _na), (b, _nb) in zip(chs, chs[1:]):
            cur = agg.setdefault(b, {})
            cur.setdefault(a, {"chapter": a, "依据": "考纲顺序", "置信度": 0.6})

    return {k: sorted(v.values(), key=lambda x: (-x["置信度"], x["chapter"]))
            for k, v in agg.items()}


@lru_cache(maxsize=1)
def chapter_freq():
    """章 id -> 该章所有考点的考查总次数之和"""
    f, cl = freq(), chapter_leaves()
    out = {}
    for ch, leaves in cl.items():
        out[ch] = sum(f.get(l, {}).get("考查总次数", 0) for l in leaves)
    return out


@lru_cache(maxsize=1)
def years():
    """有真题的年份, 从新到旧(界面默认给人看最新一套)"""
    return sorted({q["year"] for q in questions().values()}, reverse=True)


@lru_cache(maxsize=1)
def paper(year):
    """
    某一年的整套卷子。

    返回 {年份, 题目:[...], 题数, 单选数, 综合数, 有答案数, 总分, 需插图, 缺图}
    题目按题号排序(卷面顺序), 而不是按考点/难度 —— 看"某一年的真题卷"要的是
    原卷顺序。

    注意: 综合应用题目前没有答案(846 题里只有 720 道单选有答案),
    界面必须如实标注, 不能让人以为可以判分。
    """
    year = str(year)
    qs = [q for q in questions().values() if str(q["year"]) == year]

    def num(q):
        # 题号在数据里是字符串, 直接排会得到 1,10,11,2… 的顺序
        try:
            return int(str(q["题号"]).strip())
        except (TypeError, ValueError):
            return 999

    qs.sort(key=num)

    def score(q):
        try:
            return int(str(q.get("分值") or 0).strip())
        except (TypeError, ValueError):
            return 0

    choice = [q for q in qs if q["题型"] == "单项选择题"]
    return {
        "年份": year,
        "题目": qs,
        "题数": len(qs),
        "单选数": len(choice),
        "综合数": len(qs) - len(choice),
        "有答案数": sum(1 for q in qs if q.get("答案")),
        "总分": sum(score(q) for q in qs),
        "需插图": sum(1 for q in qs if q.get("需插图")),
        "缺图": sum(1 for q in qs if q.get("缺图")),
    }


@lru_cache(maxsize=1)
def paper_index():
    """全部年份的卷子概览(年份选择列表用), 从新到旧"""
    return [paper(y) for y in years()]


def overview():
    """给界面用的一句话概览"""
    q = questions()
    return {
        "题目总数": len(q),
        "年份范围": f"{min(x['year'] for x in q.values())}-{max(x['year'] for x in q.values())}",
        "有答案的单选题": sum(1 for x in q.values()
                              if x["题型"] == "单项选择题" and x.get("答案")),
        "叶子考点": len(leaf_ids()),
        "依赖边": len(depends()),
        "诊断题数": len(diagnostic()["题目"]),
    }


if __name__ == "__main__":
    print(json.dumps(overview(), ensure_ascii=False, indent=2))
    print(f"章节数: {sum(len(v) for v in chapters().values())}")
    print(f"高置信前置关系: {sum(len(v) for v in prereqs().values())} 条")
