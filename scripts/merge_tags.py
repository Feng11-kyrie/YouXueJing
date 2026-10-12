#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
合并重打标签 → 校验全量 → 统计 18 年考点频次

输出:
  data/408/question_tags.json   846 题合并后的标签(权威)
  data/408/exam_freq.json       每个叶子考点的 18 年频次统计
  data/408/tag_report.md        校验与频次报告
"""
import os
import json
import glob
from collections import Counter, defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "data", "408")

CODE2NAME = {"DS": "数据结构", "CO": "计算机组成原理", "OS": "操作系统", "CN": "计算机网络"}
NAME2CODE = {v: k for k, v in CODE2NAME.items()}


def main():
    leaves_doc = json.load(open(os.path.join(OUT, "syllabus_leaves.json"), encoding="utf-8"))
    leaf2subj, leafname, leafpath = {}, {}, {}
    for code, v in leaves_doc["学科"].items():
        for l in v["叶子"]:
            leaf2subj[l["id"]] = code
            leafname[l["id"]] = l["name_plain"]
            leafpath[l["id"]] = l["path"]

    # ---- 载入并合并
    tags = {}   # (year, 题号) -> tag
    for f in sorted(glob.glob(os.path.join(OUT, "tags", "20*.json"))):
        y = int(os.path.basename(f)[:4])
        for t in json.load(open(f, encoding="utf-8"))["标注"]:
            tags[(y, t["题号"])] = t

    # 人工复核后的修正(可多批, 每批一个文件, 键均为 "重打")
    n_fix = 0
    for fixf in sorted(glob.glob(os.path.join(OUT, "tags_fix", "*.json"))):
        doc = json.load(open(fixf, encoding="utf-8"))
        for t in doc.get("重打", []):
            tags[(t["year"], t["题号"])] = t
            n_fix += 1

    # ---- 校验
    problems, ok = [], 0
    for (y, n), t in sorted(tags.items()):
        q = json.load(open(os.path.join(OUT, f"{y}.json"), encoding="utf-8"))
        qq = {r["题号"]: r for r in q["题目"]}[n]
        want = NAME2CODE[qq["学科"]]
        ids = [t["主考点"]] + list(t.get("次考点") or [])
        miss = [i for i in ids if i not in leaf2subj]
        wrong = [i for i in ids if i in leaf2subj and leaf2subj[i] != want]
        if miss or wrong or len(t.get("次考点") or []) > 2:
            problems.append((y, n, miss, [f"{i}({CODE2NAME[leaf2subj[i]]})" for i in wrong]))
        else:
            ok += 1

    # ---- 汇编权威标签
    merged = []
    for (y, n), t in sorted(tags.items()):
        q = json.load(open(os.path.join(OUT, f"{y}.json"), encoding="utf-8"))
        qq = {r["题号"]: r for r in q["题目"]}[n]
        merged.append({
            "id": qq["id"], "year": y, "题号": n, "题型": qq["题型"], "学科": qq["学科"],
            "分值": qq["分值"], "需插图": qq.get("需插图", False),
            "主考点": t["主考点"], "主考点名": leafname.get(t["主考点"], ""),
            "次考点": list(t.get("次考点") or []),
            "次考点名": [leafname.get(i, "") for i in (t.get("次考点") or [])],
            "难度": t.get("难度"), "置信度": t.get("置信度"),
            "图片": qq.get("图片"), "图片依据": qq.get("_图片依据"), "缺图": qq.get("_缺图", False),
            "题干": qq["题干"], "选项": qq.get("选项") or {}, "答案": qq.get("答案"),
        })

    json.dump({
        "说明": "846 道 408 真题的结构化标签(叶子级)。主考点为封闭候选集(266 个叶子)中的 id。",
        "总题数": len(merged),
        "字段": ["id", "year", "题号", "题型", "学科", "分值", "主考点", "次考点", "难度", "置信度"],
        "题目": merged,
    }, open(os.path.join(OUT, "question_tags.json"), "w", encoding="utf-8"),
        ensure_ascii=False, indent=2)

    # ---- 考点频次
    freq = defaultdict(lambda: {"主考点次数": 0, "次考点次数": 0, "年份": Counter(), "题型": Counter()})
    for r in merged:
        f = freq[r["主考点"]]
        f["主考点次数"] += 1
        f["年份"][r["year"]] += 1
        f["题型"][r["题型"]] += 1
        for s in r["次考点"]:
            freq[s]["次考点次数"] += 1
            freq[s]["年份"][r["year"]] += 1

    subj_total = Counter(r["学科"] for r in merged)
    subj_score = Counter()
    for r in merged:
        subj_score[r["学科"]] += (r["分值"] or 0)

    freqs = []
    for lid, f in freq.items():
        if lid not in leaf2subj:
            continue
        code = leaf2subj[lid]
        total = f["主考点次数"] + f["次考点次数"]
        freqs.append({
            "id": lid, "name": leafname[lid], "path": leafpath[lid], "学科": CODE2NAME[code],
            "考查总次数": total, "主考点次数": f["主考点次数"], "次考点次数": f["次考点次数"],
            "覆盖年份数": len(f["年份"]),
            "逐年": dict(sorted(f["年份"].items())),
            "占本学科题量比": round(total / subj_total[CODE2NAME[code]], 4) if subj_total[CODE2NAME[code]] else 0,
            "冷门(18年未考或仅作次考点)": total == 0,
        })
    freqs.sort(key=lambda x: -x["考查总次数"])

    never = [l["id"] for code, v in leaves_doc["学科"].items()
             for l in v["叶子"] if l["id"] not in freq]
    covered = sum(1 for x in freqs if x["考查总次数"] > 0)

    json.dump({
        "说明": "408 考纲叶子考点 × 2009-2026 共 18 套真题的频次统计。用于学习路径排序(优先高频考点)。",
        "叶子总数": len(leaf2subj),
        "被考到的考点数": covered,
        "从未被考的考点数": len(never),
        "从未被考的考点": sorted(never),
        "考点": freqs,
    }, open(os.path.join(OUT, "exam_freq.json"), "w", encoding="utf-8"),
        ensure_ascii=False, indent=2)

    # ---- 报告
    L = ["# 408 打标与考点频次报告", "",
         f"- 题目总数: **{len(merged)}**（合并重打 {n_fix} 条）",
         f"- 标签校验通过: **{ok}/{len(tags)}**",
         f"- 主考点所属叶子总数: **{len(leaf2subj)}**",
         f"- 被考到的考点: **{covered}**（{covered/len(leaf2subj)*100:.1f}%）",
         f"- 18 年从未被考的考点: **{len(never)}**", "",
         "## 学科题量与分值", "",
         "| 学科 | 题量 | 分值合计 |", "|---|---|---|"]
    for s in ["数据结构", "计算机组成原理", "操作系统", "计算机网络"]:
        L.append(f"| {s} | {subj_total[s]} | {subj_score[s]} |")
    L += ["", "## 最高频考点 Top 20（按考查总次数）", "",
          "| 排名 | 考点 | 学科 | 总次数 | 主考点 | 覆盖年份 |", "|---|---|---|---|---|---|"]
    for i, x in enumerate(freqs[:20], 1):
        L.append(f"| {i} | {x['name']} | {x['学科']} | {x['考查总次数']} | "
                 f"{x['主考点次数']} | {x['覆盖年份数']}/18 |")
    if problems:
        L += ["", "## 校验问题", ""]
        for p in problems:
            L.append(f"- {p[0]} Q{p[1]}  缺失{p[2]}  学科不符{p[3]}")
    open(os.path.join(OUT, "tag_report.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")

    print(f"合并 {len(merged)} 题(含重打 {n_fix} 条)")
    print(f"校验通过 {ok}/{len(tags)}   问题 {len(problems)}")
    for p in problems[:10]:
        print("   ✗", p)
    print(f"\n叶子考点 {len(leaf2subj)} 个, 被考到 {covered} 个, 从未考 {len(never)} 个")
    print("\n最高频 Top 12:")
    for i, x in enumerate(freqs[:12], 1):
        print(f"  {i:>2}. {x['name'][:30]:<32} {x['学科'][:4]:<5} 总{x['考查总次数']:>3} 次 "
              f"(主{x['主考点次数']:>2} 次) 覆盖 {x['覆盖年份数']}/18 年")


if __name__ == "__main__":
    main()
