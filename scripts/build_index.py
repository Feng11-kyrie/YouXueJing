#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把 data/408/{year}.json 合并成可检索的题库索引, 并输出逐年覆盖率报告。

用法: python build_index.py
输出:
  data/408/index.json          全部题目扁平索引(供前端/检索用)
  data/408/coverage.md         逐年覆盖率报告
"""
import os
import json
import glob
from collections import Counter, defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(BASE, "data", "408")


def main():
    files = sorted(glob.glob(os.path.join(SRC, "[0-9][0-9][0-9][0-9].json")))
    if not files:
        raise SystemExit("没有找到 data/408/{year}.json, 请先运行 parse_408.py")

    all_q = []
    rows = []
    for f in files:
        d = json.load(open(f, encoding="utf-8"))
        y = d["year"]
        qs = d["题目"]
        ch = [r for r in qs if r["题型"] == "单项选择题"]
        opt_ok = sum(1 for r in ch if len(r.get("选项") or {}) == 4)
        ans_ok = sum(1 for r in ch if r.get("答案"))
        fig = [r for r in ch if r["需插图"]]
        rows.append(
            {
                "year": y,
                "题目总数": len(qs),
                "单选题": len(ch),
                "综合题": len(qs) - len(ch),
                "选项完整": opt_ok,
                "答案已获": ans_ok,
                "需插图": len(fig),
                "纯文字单选": len(ch) - len(fig),
            }
        )
        all_q.extend(qs)

    # 扁平索引(按年份倒序, 题号升序 -> 前端默认最新年份优先)
    all_q.sort(key=lambda r: (-r["year"], r["题号"]))
    idx = {
        "题库": "408 考研真题",
        "来源": "neville-studio/408-exam-paper (MIT) — 文字重排版, 已结构化",
        "年份范围": f"{min(r['year'] for r in rows)}-{max(r['year'] for r in rows)}",
        "总题数": len(all_q),
        "索引字段": ["id", "year", "题号", "题型", "学科", "题干", "选项", "答案", "分值", "需插图"],
        "题目": all_q,
    }
    with open(os.path.join(SRC, "index.json"), "w", encoding="utf-8") as f:
        json.dump(idx, f, ensure_ascii=False, indent=2)

    # 覆盖率报告
    lines = ["# 408 真题库覆盖率报告", "",
             f"数据源: neville-studio/408-exam-paper (MIT) — 文字重排版",
             f"年份范围: {idx['年份范围']}  共 {len(rows)} 套  总题数 {len(all_q)}", "",
             "| 年份 | 题目 | 单选 | 综合 | 选项完整 | 答案已获 | 需插图 | 纯文字单选 |",
             "|---|---|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda x: x["year"]):
        lines.append(
            f"| {r['year']} | {r['题目总数']} | {r['单选题']} | {r['综合题']} | "
            f"{r['选项完整']}/{r['单选题']} | {r['答案已获']}/{r['单选题']} | "
            f"{r['需插图']} | {r['纯文字单选']}/{r['单选题']} |"
        )
    tot_ch = sum(r["单选题"] for r in rows)
    lines += ["", "## 汇总", "",
              f"- 套数: **{len(rows)}**",
              f"- 总题数: **{len(all_q)}** ({tot_ch} 单选 + {len(all_q)-tot_ch} 综合)",
              f"- 答案完整年度: **{sum(1 for r in rows if r['答案已获']==r['单选题'])}/{len(rows)}**",
              f"- 纯文字单选题合计: **{sum(r['纯文字单选'] for r in rows)}/{tot_ch}**"
              f" ({sum(r['纯文字单选'] for r in rows)/tot_ch*100:.1f}%) <- 可自动判题",
              f"- 学科分布(全部题目): {dict(Counter(r['学科'] for r in all_q))}",
              ]
    open(os.path.join(SRC, "coverage.md"), "w", encoding="utf-8").write("\n".join(lines) + "\n")

    print(f"合并 {len(rows)} 套 / {len(all_q)} 题 -> data/408/index.json")
    print(f"覆盖率报告 -> data/408/coverage.md")
    for r in sorted(rows, key=lambda x: x["year"]):
        flag = "" if r["答案已获"] == r["单选题"] else "  <-- 答案不全"
        print(f"  {r['year']}  题{r['题目总数']:>3}  选项{r['选项完整']:>3}/{r['单选题']}"
              f"  答案{r['答案已获']:>3}/{r['单选题']}  纯文字{r['纯文字单选']:>3}/{r['单选题']}{flag}")


if __name__ == "__main__":
    main()
