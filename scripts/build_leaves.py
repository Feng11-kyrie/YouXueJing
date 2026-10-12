#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从考纲树抽取「叶子节点」候选清单, 供打标使用。

叶子 = 没有子节点的节点。本树的深度是变长的:
  数据结构   叶子多在 L3(节)       —— 大纲只细化到节
  计算机网络 叶子多在 L4(考点)     —— 大纲细化到考点
因此候选集按学科分别为 56-80 个, 且每条都带「路径」以便消歧
(四门课都有"地址""调度""Cache"这类同名概念)。

输出: data/408/syllabus_leaves.json
"""
import os
import json

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "data", "408")


def walk(node, path, leaves):
    """深度优先收集叶子。path 为 (id, name) 祖先链。"""
    kids = node.get("children") or []
    if not kids:
        leaves.append({
            "id": node["id"],
            "name": node["name_official"],
            "name_plain": node["name_plain"],
            "level": node["level"],
            "path": " › ".join(n for _, n in path + [(node["id"], node["name_official"])]),
            "path_ids": [i for i, _ in path],
        })
        return
    for k in kids:
        walk(k, path + [(node["id"], node["name_official"])], leaves)


def main():
    tree = json.load(open(os.path.join(OUT, "syllabus_tree.json"), encoding="utf-8"))
    out = {}
    for subj in tree["学科"]:
        leaves = []
        for ch in subj["children"]:
            walk(ch, [(subj["id"], subj["name_official"])], leaves)
        out[subj["id"]] = {
            "学科": subj["name_official"],
            "满分": subj["满分"],
            "叶子数": len(leaves),
            "叶子": leaves,
        }

    # 题号区间 -> 学科(考纲固定结构, 已由 18 年真题验证一致)
    ranges = {
        "DS": {"单选": [1, 11], "综合": [41, 42]},
        "CO": {"单选": [12, 22], "综合": [43, 44]},
        "OS": {"单选": [23, 32], "综合": [45, 46]},
        "CN": {"单选": [33, 40], "综合": [47, 47]},
    }

    dst = os.path.join(OUT, "syllabus_leaves.json")
    with open(dst, "w", encoding="utf-8") as f:
        json.dump({
            "说明": "打标候选集(叶子节点)。做题时先按题号区间定学科, 再在该学科叶子中选。",
            "题号区间": ranges,
            "总叶子数": sum(v["叶子数"] for v in out.values()),
            "学科": out,
        }, f, ensure_ascii=False, indent=2)

    print(f"总叶子数: {sum(v['叶子数'] for v in out.values())}")
    for k, v in out.items():
        lv = {}
        for l in v["叶子"]:
            lv[l["level"]] = lv.get(l["level"], 0) + 1
        print(f"  {k} {v['学科']:<10} {v['叶子数']:>3} 个   层级分布 {dict(sorted(lv.items()))}")
    print(f"\n输出: {dst}")


if __name__ == "__main__":
    main()
