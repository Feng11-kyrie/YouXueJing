#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成 408 诊断题库 —— 用于「画像 + 章节掌握度」的冷启动。

为什么需要它
------------
个性化推荐的前提是知道用户弱在哪。但新用户没有任何作答记录, 掌握度是空的。
靠聊天问「你哪科弱」主观且失真;靠做题测出来才客观。

设计
----
- **每科 8 题, 共 32 题**(预计 20-25 分钟)—— 太短覆盖不足, 太长用户放弃
- **两轮选章**: 第一轮每章 1 题(覆盖全部 24 章);第二轮按考频补足到每科 8 题
  → 既保证覆盖面, 又在高频章节加密
- **只用纯文字单选**: 排除需插图的题, 避免用户看不到图而误答(插图缺失与能力无关)
- **难度优先 2-3**: 诊断不是选拔, 避免一上来就打击;允许 1-4 兜底
- **尽量跨年份**: 避免某一年扎堆导致难度偏移

产出
----
data/408/diagnostic.json  —— 题单 + 章节覆盖 + 评分规则
"""
import os
import re
import json
import glob
from collections import defaultdict, Counter

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "data", "408")

PER_SUBJECT = 8            # 每科题数
DIFF_PREF = (2, 3)         # 首选难度
DIFF_OK = (1, 2, 3, 4)     # 可接受难度


def main():
    # ---- 题目: 以 question_tags.json 为单一数据源(含主考点/答案/插图字段)
    qs = json.load(open(os.path.join(OUT, "question_tags.json"), encoding="utf-8"))["题目"]

    # ---- 考纲树: 叶子 -> 章
    tree = json.load(open(os.path.join(OUT, "syllabus_tree.json"), encoding="utf-8"))
    leaf2ch, ch_name, subj_chs = {}, {}, defaultdict(list)
    for s in tree["学科"]:
        for c in s["children"]:
            subj_chs[s["id"]].append((c["id"], c["name_official"]))
            for sec in c["children"]:
                leaf2ch[sec["id"]] = c["id"]
                for p in sec.get("children") or []:
                    leaf2ch[p["id"]] = c["id"]
            ch_name[c["id"]] = c["name_official"]

    # ---- 章考频 = 该章下所有考点的考查总次数之和
    freq = {x["id"]: x["考查总次数"] for x in
            json.load(open(os.path.join(OUT, "exam_freq.json"), encoding="utf-8"))["考点"]}
    ch_freq = Counter()
    for lid, cnt in freq.items():
        if lid in leaf2ch:
            ch_freq[leaf2ch[lid]] += cnt

    # ---- 候选: 纯文字单选 + 有答案
    cand = [r for r in qs
            if r["题型"] == "单项选择题" and r.get("答案")
            and not r.get("需插图") and not r.get("图片")]

    used, picked = set(), []
    used_years = defaultdict(set)      # 学科 -> 已用年份(用于年份分散)

    def pick(code, ch, n=1):
        """
        从某章挑 n 道未使用的题。

        排序意图:
          1. 难度优先落在 2-3
          2. **年份分散** —— 优先该学科还没用过的年份
             最新两年的真题是学生最可能已经刷过的, 集中使用会虚高掌握度
          3. 同档内优先较新年份(贴近当前考法)
        """
        pool = [r for r in cand
                if leaf2ch.get(r["主考点"]) == ch and r["id"] not in used]
        if not pool:
            return 0
        pool.sort(key=lambda r: (
            0 if r.get("难度") in DIFF_PREF else (1 if r.get("难度") in DIFF_OK else 2),
            1 if r["year"] in used_years[code] else 0,
            -r["year"],
        ))
        got = 0
        for r in pool:
            if got >= n:
                break
            used.add(r["id"])
            used_years[code].add(r["year"])
            picked.append(r)
            got += 1
        return got

    # 第一轮: 每章 1 题
    for code, chs in subj_chs.items():
        for ch, _nm in chs:
            pick(code, ch, 1)

    # 第二轮: 按考频补足到每科 PER_SUBJECT 题
    for code, chs in subj_chs.items():
        cnt = sum(1 for r in picked if r["学科"] ==
                  {"DS": "数据结构", "CO": "计算机组成原理",
                   "OS": "操作系统", "CN": "计算机网络"}[code])
        for ch, _nm in sorted(chs, key=lambda x: -ch_freq[x[0]]):
            if cnt >= PER_SUBJECT:
                break
            cnt += pick(code, ch, 1)

    # ---- 组卷: 按学科分组, 题内随机顺序固定为学科序
    NAME2CODE = {"数据结构": "DS", "计算机组成原理": "CO",
                 "操作系统": "OS", "计算机网络": "CN"}
    picked.sort(key=lambda r: (["DS", "CO", "OS", "CN"].index(NAME2CODE[r["学科"]]),
                               leaf2ch.get(r["主考点"], ""), r["year"]))
    items = []
    for i, r in enumerate(picked, 1):
        ch = leaf2ch.get(r["主考点"], "")
        items.append({
            "order": i, "id": r["id"], "year": r["year"], "题号": r["题号"],
            "学科": r["学科"], "学科码": NAME2CODE[r["学科"]],
            "诊断章节": ch, "诊断章节名": ch_name.get(ch, ""),
            "主考点": r["主考点"], "主考点名": r["主考点名"],
            "难度": r["难度"], "答案": r["答案"], "分值": r["分值"],
        })

    # ---- 统计与评分规则
    subj_cnt = Counter(x["学科"] for x in items)
    ch_cover = Counter(x["诊断章节"] for x in items)
    total_ch = sum(len(v) for v in subj_chs.values())
    doc = {
        "说明": "408 诊断题库。用于新用户冷启动：做题 → 得到章节级掌握度 → 驱动推荐。",
        "设计": {
            "每科题数": PER_SUBJECT,
            "总题数": len(items),
            "预计时长": "20-25 分钟",
            "选题约束": "纯文字单选(排除需插图题) + 有标准答案 + 难度优先 2-3 + 尽量跨年份",
            "选章策略": "第一轮每章 1 题覆盖全部章；第二轮按 18 年考频补足到每科 8 题",
        },
        "覆盖": {
            "章总数": total_ch,
            "被覆盖章数": len(ch_cover),
            "学科题量": dict(subj_cnt),
            "各章题数": {ch_name.get(k, k): v for k, v in sorted(ch_cover.items())},
        },
        "评分规则": {
            "章节掌握度": "该章答对数 / 该章题数(Laplace 平滑: (答对+1)/(题数+2)，避免 0% 与 100% 极端)",
            "学科掌握度": "该学科所有题答对率(同样平滑)",
            "初始画像": "学科掌握度 + 各章掌握度 → 作为画像的初始值",
            "说明": "只做章节级粗粒度聚合；不做知识追踪模型(申报表明确不做精细化学分诊断)",
        },
        "题目": items,
    }
    dst = os.path.join(OUT, "diagnostic.json")
    json.dump(doc, open(dst, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    print(f"诊断题库: {len(items)} 题(预计 20-25 分钟)")
    print(f"  学科题量: {dict(subj_cnt)}")
    print(f"  覆盖章节: {len(ch_cover)}/{total_ch}")
    miss = [ch_name[c] for _s, chs in subj_chs.items() for c, _n in chs if c not in ch_cover]
    print(f"  未覆盖  : {miss if miss else '无'}")
    print(f"  难度分布: {dict(sorted(Counter(x['难度'] for x in items).items()))}")
    print(f"  年份跨度: {min(x['year'] for x in items)}-{max(x['year'] for x in items)}"
          f"  涉及 {len(set(x['year'] for x in items))} 个年份")
    print(f"\n输出: {dst}")


if __name__ == "__main__":
    main()
