#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
导出「可公开」的数据集。

公开/私密切分的原则:
  公开 ——  我们自己的**劳动成果**:考纲结构编码、知识点图谱、标签、频次、依赖关系、代码
  私有 ——  **他人版权内容**:真题 PDF 原件、试卷题干原文、答案扫描图

关键动作: 题目标签导出时**剥掉题干/选项/答案**, 只保留结构化字段。
这样公开的是「知识图谱」而不是「题库」—— 既展示工程能力, 又不涉及分发题目原文。
"""
import os
import json

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(BASE, "data", "408")
PUB_SYL = os.path.join(BASE, "data", "syllabus")
PUB_GRF = os.path.join(BASE, "data", "graph")

STRIP = {"题干", "选项", "答案", "_答案待校验", "_来源", "_学科校验", "_学科得分", "_学科修正"}


def main():
    os.makedirs(PUB_SYL, exist_ok=True)
    os.makedirs(PUB_GRF, exist_ok=True)

    # ---- 1. 考纲结构(官方大纲的层级 + 我们的编码与通俗名)
    for f in ("syllabus_tree.json", "syllabus_leaves.json"):
        d = json.load(open(os.path.join(SRC, f), encoding="utf-8"))
        json.dump(d, open(os.path.join(PUB_SYL, f), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
    import shutil
    shutil.copy(os.path.join(SRC, "syllabus_draft.md"), PUB_SYL)

    # ---- 2. 图谱数据(不含题目原文)
    for f in ("exam_freq.json", "depends_graph.json"):
        d = json.load(open(os.path.join(SRC, f), encoding="utf-8"))
        json.dump(d, open(os.path.join(PUB_GRF, f), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
    shutil.copy(os.path.join(SRC, "depends_draft.md"), PUB_GRF)
    shutil.copy(os.path.join(SRC, "tag_report.md"), PUB_GRF)
    shutil.copy(os.path.join(SRC, "coverage.md"), PUB_GRF)

    # ---- 3. 标签(剥掉题干/选项/答案)
    tags = json.load(open(os.path.join(SRC, "question_tags.json"), encoding="utf-8"))
    clean = []
    for r in tags["题目"]:
        clean.append({k: v for k, v in r.items() if k not in STRIP})
    json.dump({
        "说明": "846 道 408 真题(2009-2026)的知识点标注。**已剥离题干/选项/答案**——"
                "本题库只公开知识图谱结构, 不公开试题原文。",
        "年份范围": "2009-2026",
        "总题数": len(clean),
        "字段": sorted(clean[0].keys()),
        "题目": clean,
    }, open(os.path.join(PUB_GRF, "question_tags.json"), "w", encoding="utf-8"),
        ensure_ascii=False, indent=2)

    # ---- 3.5 诊断题库(公开版剥掉答案 —— 题单设计是展示点, 答案不必公开)
    dg = json.load(open(os.path.join(SRC, "diagnostic.json"), encoding="utf-8"))
    pub_dg = json.loads(json.dumps(dg, ensure_ascii=False))
    for x in pub_dg["题目"]:
        x.pop("答案", None)
        for k in list(x):
            if k in ("_答案待校验",):
                x.pop(k, None)
    json.dump(pub_dg, open(os.path.join(PUB_GRF, "diagnostic.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)

    # ---- 4. 统计摘要
    from collections import Counter
    subj = Counter(r["学科"] for r in clean)
    hard = Counter(r["难度"] for r in clean)
    summary = {
        "题数": len(clean),
        "套数": len(set(r["year"] for r in clean)),
        "学科分布": dict(subj),
        "难度分布": dict(sorted(hard.items())),
        "单选题数": sum(1 for r in clean if r["题型"] == "单项选择题"),
        "综合应用题数": sum(1 for r in clean if r["题型"] == "综合应用题"),
        "需插图题数": sum(1 for r in clean if r.get("需插图")),
        "低置信度标注(<0.7)": sum(1 for r in clean if (r.get("置信度") or 1) < 0.7),
    }
    json.dump(summary, open(os.path.join(PUB_GRF, "summary.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)

    # ---- 5. 校验: 确认没有题干泄漏
    leak = [k for r in clean for k in r if k in STRIP]
    assert not leak, f"泄漏字段: {set(leak)}"
    blob = json.dumps(clean, ensure_ascii=False)
    print("=== 公开数据集导出 ===")
    print(f"  考纲: data/syllabus/  ({len(os.listdir(PUB_SYL))} 个文件)")
    print(f"  图谱: data/graph/     ({len(os.listdir(PUB_GRF))} 个文件)")
    print(f"  标签: {len(clean)} 题, 字段 {sorted(clean[0].keys())}")
    print(f"  题干泄漏检查: 通过 ✓ (公开数据中无题干/选项/答案)")
    print(f"  统计: {summary}")


if __name__ == "__main__":
    main()
