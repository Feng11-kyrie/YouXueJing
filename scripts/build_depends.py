#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
构建 408 知识点依赖图(前置关系 DAG)

依赖边 = 「必须先掌握 A 才能学 B」, 与树上的父子(分类)关系不同, 它是跨章节的有向边。

两个来源, 每条边都记录依据以便人工审核:
  [A] 同节链式 —— 考纲在同一节内按学习顺序列出子考点, 相邻两者构成前置链。
      例: 二叉搜索树 → 平衡二叉树 → 红黑树; 程序查询 → 程序中断 → DMA
      依据充分(考纲自身的编排顺序), 置信度高。
  [B] 跨节共现 —— 从 846 道真题的「主考点 + 次考点」共现挖掘:
      若考点 Y 反复作为考点 X 的"次考点"出现, 且 Y 在考纲顺序上位于 X 之前,
      则 Y 很可能是 X 的前置(考 X 的题总要动用 Y 的知识)。
      证据 = 出现次数 + 覆盖年份数。次数越多越可信。

输出:
  data/408/depends_graph.json   依赖图(节点 + 边 + 依据)
  data/408/depends_draft.md     人工审核草案
"""
import os
import json
from collections import Counter, defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "data", "408")


def main():
    tree = json.load(open(os.path.join(OUT, "syllabus_tree.json"), encoding="utf-8"))
    tags = json.load(open(os.path.join(OUT, "question_tags.json"), encoding="utf-8"))

    # ---- 叶子全序 + 路径 + 所属学科
    order, path, subj_of, parent_of = {}, {}, {}, {}

    def walk(node, p, key):
        kids = node.get("children") or []
        if not kids:
            order[node["id"]] = key
            path[node["id"]] = " › ".join(n for _, n in p + [(node["id"], node["name_official"])])
            return
        for i, ch in enumerate(kids, 1):
            parent_of[ch["id"]] = node["id"]
            walk(ch, p + [(node["id"], node["name_official"])], key + (i,))

    for si, s in enumerate(tree["学科"], 1):
        for ci, c in enumerate(s["children"], 1):
            for sec_i, sec in enumerate(c["children"], 1):
                subj_of[sec["id"]] = s["id"]
                for ch in sec.get("children") or []:
                    subj_of[ch["id"]] = s["id"]
                if not (sec.get("children") or []):
                    order[sec["id"]] = (si, ci, sec_i)
                    path[sec["id"]] = " › ".join(
                        [s["name_official"], c["name_official"], sec["name_official"]])
                walk(sec, [(s["id"], s["name_official"]), (c["id"], c["name_official"])],
                     (si, ci, sec_i))

    edges = {}   # (from, to) -> dict

    def add(f, t, kind, evidence, conf):
        if f == t or f not in order or t not in order:
            return
        if subj_of.get(f) != subj_of.get(t):
            return          # 先只建同学科依赖(跨学科依赖另论)
        if order[f] >= order[t]:
            return          # 前置必须在顺序上更早, 保证无环
        k = (f, t)
        if k in edges:
            if kind not in edges[k]["类型"]:
                edges[k]["类型"].append(kind)
            edges[k]["依据"] += "；" + evidence
            edges[k]["置信度"] = max(edges[k]["置信度"], conf)
        else:
            edges[k] = {"from": f, "to": t, "类型": [kind], "依据": evidence, "置信度": conf}

    # ---- [A] 同节链式: 同一父节点下相邻的两个叶子
    n_a = 0
    for s in tree["学科"]:
        for c in s["children"]:
            for sec in c["children"]:
                kids = [k for k in (sec.get("children") or []) if not (k.get("children") or [])]
                for x, y in zip(kids, kids[1:]):
                    add(x["id"], y["id"], "同节链式",
                        f"考纲在同一节「{sec['name_official']}」内按学习顺序列出, {x['name_official']} 先于 {y['name_official']}",
                        0.9)
                    n_a += 1

    # ---- [B] 跨节共现
    pair_cnt, pair_yrs = Counter(), defaultdict(set)
    for r in tags["题目"]:
        X = r["主考点"]
        for Y in r["次考点"]:
            if subj_of.get(X) != subj_of.get(Y):
                continue
            if order.get(Y, (9,)) < order.get(X, (9,)):
                pair_cnt[(Y, X)] += 1
                pair_yrs[(Y, X)].add(r["year"])
    n_b = 0
    for (Y, X), n in pair_cnt.items():
        conf = 0.85 if n >= 4 else (0.7 if n >= 2 else 0.5)
        add(Y, X, "跨节共现",
            f"18 年真题中共现 {n} 次({len(pair_yrs[(Y, X)])} 个年份):考 {path[X].split(' › ')[-1]} 的题常同时涉及 {path[Y].split(' › ')[-1]}",
            conf)
        n_b += 1

    # ---- 无环校验(理论上按序定向必无环, 仍做一次)
    adj = defaultdict(list)
    for (f, t) in edges:
        adj[f].append(t)
    color = {}

    def has_cycle(u):
        color[u] = 1
        for v in adj[u]:
            if color.get(v) == 1:
                return True
            if color.get(v) is None and has_cycle(v):
                return True
        color[u] = 2
        return False

    cycle = any(has_cycle(n) for n in list(adj) if color.get(n) is None)

    # ---- 统计与输出
    el = []
    CODE2NAME = {"DS": "数据结构", "CO": "计算机组成原理", "OS": "操作系统", "CN": "计算机网络"}
    for (f, t), e in edges.items():
        el.append({
            "from": f, "from_name": path[f].split(" › ")[-1], "from_path": path[f],
            "to": t, "to_name": path[t].split(" › ")[-1], "to_path": path[t],
            "学科": CODE2NAME[subj_of[f]],
            "类型": e["类型"], "依据": e["依据"], "置信度": e["置信度"],
        })
    el.sort(key=lambda x: (-x["置信度"], x["学科"], x["from"]))

    by_type = Counter(t for e in el for t in e["类型"])
    by_conf = Counter(e["置信度"] for e in el)
    indeg = Counter(e["to"] for e in el)
    outdeg = Counter(e["from"] for e in el)

    json.dump({
        "说明": "408 知识点前置依赖图(DAG)。边 A→B 表示必须掌握 A 才能有效学习 B。",
        "与父子关系的区别": "父子=分类(树), 依赖=学习顺序(跨章节有向图)",
        "边数": len(el),
        "节点数": len(order),
        "有环": cycle,
        "来源": {"同节链式": n_a, "跨节共现": n_b},
        "边": el,
    }, open(os.path.join(OUT, "depends_graph.json"), "w", encoding="utf-8"),
        ensure_ascii=False, indent=2)

    L = ["# 408 知识点依赖图 · 审核草案", "",
         f"- 节点(叶子考点) {len(order)} 个, **依赖边 {len(el)} 条**",
         f"- 有环: {'**是(需修)**' if cycle else '否 ✓'}",
         f"- 来源: 同节链式 {n_a} 条(置信度 0.9) / 跨节共现 {n_b} 条(按证据分级)",
         f"- 置信度分布: {dict(sorted(by_conf.items(), reverse=True))}", "",
         "> 边 A→B 含义: **必须先掌握 A, 才能有效学习 B**。",
         "> 每条边都写了「依据」——依据讲不通的边请直接删掉。", "",
         "## 跨节共现(数据挖掘,证据可查)", ""]
    for e in [x for x in el if "跨节共现" in x["类型"]]:
        L.append(f"- **{e['from_name']}** → **{e['to_name']}**　`{e['from']}`→`{e['to']}`　"
                 f"置信度 {e['置信度']}")
        L.append(f"    - {e['依据']}")
    L += ["", "## 同节链式(考纲编排顺序)", ""]
    for e in [x for x in el if "同节链式" in x["类型"] and "跨节共现" not in x["类型"]]:
        L.append(f"- **{e['from_name']}** → **{e['to_name']}**　`{e['from']}`→`{e['to']}`")
    open(os.path.join(OUT, "depends_draft.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")

    print(f"依赖边 {len(el)} 条 | 有环: {cycle}")
    print(f"  同节链式 {n_a} 条 / 跨节共现 {n_b} 条")
    print(f"  置信度分布: {dict(sorted(by_conf.items(), reverse=True))}")
    print(f"  入度最高(前置最多的考点, 即最基础的):")
    for lid, n in indeg.most_common(6):
        print(f"    {n:>2} 条前置  {path[lid].split(' › ')[-1][:34]}")
    print(f"  出度最高(最多考点依赖它, 即最关键的基石):")
    for lid, n in outdeg.most_common(6):
        print(f"    被 {n:>2} 个考点依赖  {path[lid].split(' › ')[-1][:30]}")
    print(f"\n输出: data/408/depends_graph.json")
    print(f"草案: data/408/depends_draft.md")


if __name__ == "__main__":
    main()
