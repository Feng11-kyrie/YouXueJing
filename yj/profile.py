#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
掌握度 → 用户画像。

画像 = 三层掌握度 + 薄弱点排序 + 强项 + 未测提示。

刻意不用 LLM 生成: 画像的每个数字都应可追溯到具体答题记录,
让 LLM 去"描述"它只会引入不可验证的说法。文字部分用模板拼,
保证与数据严格一致 —— 这在验收时很重要(结论必须可核对)。
"""
from . import data

WEAK = 0.60          # 薄弱阈值
STRONG = 0.85        # 强项阈值


def build(answers, marks=None):
    """
    answers : 作答记录(可为空)
    marks   : 用户自己勾选的薄弱考点集合(可为空)

    两条来源都能独立支撑画像 —— 用户不答题、只勾选, 也能得到推荐。
    """
    m = data  # 别名, 便于阅读
    from .diagnose import summarize
    s = summarize(answers)
    chaps = s["章节"]
    subj = s["学科"]

    # ---- 未测章节
    all_ch = {ch: (nm, code) for code, chs in m.chapters().items() for ch, nm in chs}
    tested = set(chaps.keys())
    untested = [{"chapter": ch, "章节名": all_ch[ch][0],
                 "学科码": all_ch[ch][1],
                 "学科": m.CODE2NAME[all_ch[ch][1]],
                 "考频": m.chapter_freq().get(ch, 0)}
                for ch in all_ch if ch not in tested]

    # ---- 薄弱章节: 按「考频 × (1 - 掌握度)」排序
    #      这个排序的含义是"性价比": 考得越多、你越弱, 越该优先补
    weak = {c["chapter"]: dict(c) for c in chaps.values() if c["掌握度"] < WEAK}
    for c in weak.values():
        c["来源"] = "作答"

    # ---- 并入「自报薄弱」: 用户勾选的考点 -> 它们所属的章
    marks = set(marks or ())
    if marks:
        marked_ch = {}
        for leaf in marks:
            ch = m.chapter_of(leaf)
            if ch:
                marked_ch.setdefault(ch, []).append(leaf)
        for ch, leaves in marked_ch.items():
            if ch in weak:
                weak[ch]["来源"] = "作答+自报"
                weak[ch]["自报考点数"] = len(leaves)
            else:
                nm = m.nodes().get(ch, {})
                weak[ch] = {
                    "chapter": ch, "章节名": nm.get("name", ch),
                    "学科": m.CODE2NAME.get(nm.get("subject"), ""),
                    "学科码": nm.get("subject"),
                    "掌握度": None,            # 未测 -> 不知道具体水平
                    "题数": 0, "答对": 0,
                    "来源": "自报", "自报考点数": len(leaves),
                }

    weak = sorted(weak.values(),
                  key=lambda c: -(m.chapter_freq().get(c["chapter"], 0)
                                  * (1 - (c["掌握度"] if c["掌握度"] is not None else 0.0))))
    for c in weak:
        c["考频"] = m.chapter_freq().get(c["chapter"], 0)
        c["优先级分"] = round(c["考频"] * (1 - (c["掌握度"] if c["掌握度"] is not None else 0.0)), 1)

    strong = sorted([c for c in chaps.values() if c["掌握度"] >= STRONG],
                    key=lambda c: -c["掌握度"])

    # ---- 最弱考点(叶子级, 供路径与生成使用)
    leaves = s["考点"]
    weak_leaves = {l["leaf"]: dict(l) for l in leaves.values() if l["掌握度"] < WEAK}
    for leaf in marks:                              # 自报的也纳入(可能未测)
        if leaf in weak_leaves:
            weak_leaves[leaf]["来源"] = "作答+自报"
            continue
        weak_leaves[leaf] = {
            "leaf": leaf, "考点名": m.node_name(leaf),
            "学科": m.CODE2NAME.get(m.subject_of(leaf), ""),
            "章节": m.node_name(m.chapter_of(leaf)),
            "掌握度": None, "题数": 0, "答对": 0, "来源": "自报",
        }
    weak_leaves = sorted(weak_leaves.values(),
                         key=lambda l: ((l["掌握度"] if l["掌握度"] is not None else 0.0),
                                        -m.freq().get(l["leaf"], {}).get("考查总次数", 0)))

    # ---- 文字画像(模板拼, 每个数字都可追溯)
    #
    # 【为什么不写百分比】
    # 用户质疑过"掌握度是不是在瞎猜"，核实后他判断对了一半：
    # 数字是真算的（Laplace 平滑），但样本太小 —— 学科级每科仅 8 题，
    # 章节级 16 个章节只做过 1 题。1 题答对显示 67% 属于**伪精确**，
    # 答辩时经不起追问。所以文字画像只陈述原始作答数：
    #   "数据结构 答对 7 / 做过 8 题"  ← 无可辩驳
    # 内部排序仍使用掌握度（算法需要），只是不摆给用户看。
    lines = []
    if subj:
        parts = [f"{v['学科']} 答对 {v['答对']} / 做过 {v['题数']} 题"
                 for v in sorted(subj.values(), key=lambda x: -x["掌握度"])]
        lines.append("做题记录：" + "、".join(parts) + "。")
    if weak:
        def _fmt(c):
            s = f"{c['章节名']}"
            if c["题数"]:
                s += f"(答对 {c['答对']}/{c['题数']} 题)"
            if c.get("来源") == "自报":
                s += "(你标记的)"
            return s
        lines.append("当前最该补的章节：" + "、".join(_fmt(c) for c in weak[:3]) + "。")
    elif marks:
        lines.append(f"你标记了 {len(marks)} 个薄弱考点，系统会从这些考点出题。")
    if strong:
        lines.append("已掌握较好：" +
                     "、".join(c["章节名"] for c in strong[:3]) + "。")
    if untested:
        lines.append(f"还有 {len(untested)} 个章节没测过，建议加测以完善画像。")

    return {
        "学科掌握度": subj,
        "章节掌握度": chaps,
        "薄弱章节": weak,
        "强项章节": strong,
        "薄弱考点": weak_leaves[:10],
        "未测章节": untested,
        "作答数": s["作答数"],
        "文字画像": " ".join(lines) if lines else "还没有作答记录，请先做一次诊断。",
    }


if __name__ == "__main__":
    import json
    print(json.dumps(build({}), ensure_ascii=False, indent=2))
