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


def build(answers):
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
    weak = sorted(
        [c for c in chaps.values() if c["掌握度"] < WEAK],
        key=lambda c: -(m.chapter_freq().get(c["chapter"], 0) * (1 - c["掌握度"]))
    )
    for c in weak:
        c["考频"] = m.chapter_freq().get(c["chapter"], 0)
        c["优先级分"] = round(c["考频"] * (1 - c["掌握度"]), 1)

    strong = sorted([c for c in chaps.values() if c["掌握度"] >= STRONG],
                    key=lambda c: -c["掌握度"])

    # ---- 最弱考点(叶子级, 供路径与生成使用)
    leaves = s["考点"]
    weak_leaves = sorted([l for l in leaves.values() if l["掌握度"] < WEAK],
                         key=lambda l: (l["掌握度"], -m.freq().get(l["leaf"], {})
                                        .get("考查总次数", 0)))

    # ---- 文字画像(模板拼, 每个数字都可追溯)
    lines = []
    if subj:
        parts = [f"{v['学科']} {v['掌握度']:.0%}({v['答对']}/{v['题数']})"
                 for v in sorted(subj.values(), key=lambda x: -x["掌握度"])]
        lines.append("学科掌握度：" + "、".join(parts) + "。")
    if weak:
        top = "、".join(f"{c['章节名']}({c['掌握度']:.0%})" for c in weak[:3])
        lines.append(f"当前最该补的章节：{top}。")
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
