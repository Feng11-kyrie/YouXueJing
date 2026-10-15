#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
考研政治真题试卷的质量审计 —— 检查"入库的卷子是否真的正确、完整"。

为什么要专门审计
----------------
来源五花八门（高校 PDF、docx、门户网页），而实测每一类都出过问题：
  · 网页分页只抓第一页 → 以为"只有单选"
  · 门户页面的正文容器选错 → 抓到导航栏
  · docx 整卷重复两遍 → 题号重复
  · 各种源都可能截断（分析题跨页丢失）

五个体检项（都能程序化判定，不靠人眼）：
  ① **结构完整性**：官方是 16 单选 / 17 多选 / 5 分析。缺哪题要列出来
  ② **题干完整性**：题干过短（<15 字）说明被截断；
     政治题干常以"这表明""原因是"等收尾，若在句子中间断掉也是截断
  ③ **选项完整性**：客观题必须 4 个选项，且选项内容不能为空或过短
  ④ **答案合法性**：答案字母必须都在选项里；单选恰好 1 个字母；
     多选 2–4 个字母（政治的规则是"多选或少选均不得分"，所以至少 2 个）
  ⑤ **重复检测**：同一题号出现两次、或两道题题干完全相同

用法：
    .venv/bin/python scripts/audit_zz_papers.py
    .venv/bin/python scripts/audit_zz_papers.py --year 2012
"""
import argparse
import collections
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from yj import zhengzhi as zz                          # noqa: E402

EXPECT = {"单项选择题": 16, "多项选择题": 17}
ANALYSIS = 5
# 政治题干常见的收尾词 —— 缺了这些且末尾没有标点，多半是截断。
#
# 【误报说明】第一版只列了"这表明/因为/是"等，结果把大量**正常**题干报成截断：
# 政治题干常以「有」「认为」「包括」等结尾（如"下列条约有""杰出人物的历史作用,
# 认为"），这些在中文里是自然的题干收尾。所以列表要放宽 ——
# 审计的价值在于**少报不漏报关键问题**，误报太多会让人忽略真正的截断。
TAIL_HINTS = ("这表明", "这说明", "因为", "在于", "是", "有", "认为", "包括",
              "表现", "属于", "正确的", "错误", "原因", "内容", "特点",
              "？", "?", "。", "：", ":", "）", ")", "，", ",")


def audit(year):
    rec = zz.paper(year)
    items = rec["题目"]
    issues = []
    by_type = collections.Counter(i["题型"] for i in items)

    # ① 结构
    for t, n in EXPECT.items():
        got = by_type.get(t, 0)
        if got != n:
            have = {i["题号"] for i in items if i["题型"] == t}
            miss = [str(k) for k in range(
                1 if t == "单项选择题" else 17,
                (16 if t == "单项选择题" else 33) + 1) if str(k) not in have]
            issues.append(f"结构：{t} 应有 {n} 道，实际 {got} 道（缺 {','.join(miss)}）")
    ana = by_type.get("分析题", 0) + by_type.get("材料分析题", 0)
    if ana != ANALYSIS:
        have = {i["题号"] for i in items
                if i["题型"] in ("分析题", "材料分析题")}
        miss = [str(k) for k in range(34, 39) if str(k) not in have]
        issues.append(f"结构：分析题应有 {ANALYSIS} 道，实际 {ana} 道"
                      f"（缺 {','.join(miss)}）")

    # ②③④⑤ 逐题
    seen_num = set()
    stems = {}
    for it in items:
        n, t = it["题号"], it["题型"]
        if (t, n) in seen_num:
            issues.append(f"重复：{t} 第 {n} 题出现两次")
        seen_num.add((t, n))

        stem = (it.get("题干") or "").strip()
        if len(stem) < 15:
            issues.append(f"题干过短：第 {n} 题只有 {len(stem)} 字 —— 疑似截断")
        elif not stem.endswith(TAIL_HINTS) and len(stem) < 40:
            issues.append(f"题干存疑：第 {n} 题末尾为「{stem[-12:]}」—— 疑似截断")
        if stem in stems and len(stem) > 20:
            issues.append(f"题干重复：第 {n} 题与第 {stems[stem]} 题完全相同")
        stems.setdefault(stem, n)

        if t in ("单项选择题", "多项选择题"):
            opts = it.get("选项") or {}
            if len(opts) != 4:
                issues.append(f"选项数：第 {n} 题有 {len(opts)} 个选项（应 4 个）")
            for k, v in opts.items():
                if len((v or "").strip()) < 2:
                    issues.append(f"选项过短：第 {n} 题 {k} 选项内容为空/极短")
            ans = str(it.get("答案") or "")
            if ans:
                if not set(ans) <= set(opts):
                    issues.append(f"答案越界：第 {n} 题答案 {ans} 不在选项 "
                                  f"{''.join(sorted(opts))} 中")
                if t == "单项选择题" and len(ans) != 1:
                    issues.append(f"答案格式：第 {n} 题是单选，答案却是 {ans}")
                if t == "多项选择题" and not (2 <= len(ans) <= 4):
                    issues.append(f"答案格式：第 {n} 题是多选，答案 {ans} "
                                  f"（{len(ans)} 个字母，应 2–4 个）")
    return items, issues


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", default=None)
    args = ap.parse_args()

    years = [args.year] if args.year else zz.years()
    total_issues = 0
    for y in years:
        items, issues = audit(y)
        n_ans = sum(1 for i in items if i.get("答案"))
        n_obj = sum(1 for i in items
                    if i["题型"] in ("单项选择题", "多项选择题"))
        flag = "✅" if not issues else f"⚠️ {len(issues)} 项"
        print(f"{y}: {len(items)} 道（客观题 {n_obj}，有答案 {n_ans}）  {flag}")
        for s in issues:
            print(f"    · {s}")
        total_issues += len(issues)
    print(f"\n合计 {total_issues} 项问题")
    return 0 if total_issues == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
