#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成 408 真题「校订答案库」 data/408/answers_verified.json

来源分两类, 全部记录出处以便审计:
  [视觉核对] 11 年: 答案表版式复杂(表格网格/纯扫描件), 已人工逐行读图录入并两次复核
  [自动+交叉校验] 7 年: 版式确定, 由 parse_408 自动提取, 且与解析正文交叉校验 0 处不一致

同时做一次审计: 对 11 个视觉核对年份, 把自动提取结果与人工录入对比,
输出解析器准确率 —— 这是「答案准确性」的证据。
"""
import os
import json

from parse_408 import (pdf_text, pdf_layout_text, parse_answers,
                       verify_against_explanations)

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(BASE, ".cache", "408")
OUT = os.path.join(BASE, "data", "408")

# ---- 人工读图录入(40 个字母, 题号 1..40 顺序) ----
# 版式: 2009-2019 每年 8 个/行; 2021 为 6 个/行; 2024-2026 为 5 个/行
MANUAL = {
    2009: "BCDBCBAD" "ABCDDCDC" "AADBDADD" "CACBAABA" "BBCADDCA",
    2010: "DCDCBACB" "BDADBBDA" "DBADADAC" "BADBBCCB" "CCDCBDAA",
    2011: "ABBCCDAC" "DABDABDA" "CDCCDCBA" "DBDDACBC" "ABBDDCCB",
    2012: "BAABCCCA" "DADDBDDA" "CCCDDBCB" "BADABCAB" "BCABCADD",
    2014: "CBADCDDD" "DBCDCAAD" "ACCCDBAB" "DAACBACD" "CBDCBABD",
    2016: "DDCBCDBB" "BADCDACC" "CBBAAAAB" "CABDACDA" "CCDBBDCC",
    2019: "BBCACADC" "BDBCADDD" "BCBCADBC" "CBCBCBAC" "CABBBCDB",
    2021: "DDBCBDAC" "ACBDDACA" "DCCABABB" "CCDCBACC" "BABBDBDC",
    2024: "DAABD" "ADABC" "DBBCD" "DCBCB" "ACAAD" "AABAC" "CCBCD" "BDDCD",
    2025: "BDDBD" "CCCAD" "ADDDC" "BCBAA" "BADCC" "BDCCA" "CBBCC" "CBABA",
    2026: "ADCBD" "DBDBA" "ACABA" "DACAA" "DCCDD" "ACCDB" "DDBDB" "BBACD",
}

# 自动提取 + 交叉校验干净的年份
AUTO_OK = [2013, 2015, 2017, 2018, 2020, 2022, 2023]


def main():
    for y, s in MANUAL.items():
        assert len(s) == 40, f"{y} 长度 {len(s)} != 40"
        assert set(s) <= set("ABCD"), f"{y} 含非法字符"

    key = {}          # year -> {题号: 答案}
    meta = {}         # year -> 出处
    audit = []

    # 1) 人工录入年份
    for y, s in sorted(MANUAL.items()):
        key[y] = {i + 1: c for i, c in enumerate(s)}
        meta[y] = "视觉核对(读答案表图片录入)"

    # 2) 自动年份
    for y in AUTO_OK:
        ap = pdf_text(os.path.join(CACHE, f"{y}-answer.pdf"), decrypt=True)
        ans, mode = parse_answers(ap, pdf_layout_text(os.path.join(CACHE, f"{y}-answer.pdf")))
        agree, dis = verify_against_explanations(ap, ans)
        key[y] = {n: ans[n] for n in sorted(ans)}
        meta[y] = f"自动提取({mode}) + 解析交叉校验一致{agree}/不一致{len(dis)}"

    # 3) 审计: 自动提取 vs 人工录入
    print("=== 审计: 自动提取结果 vs 人工读图录入 ===")
    print(f"{'年':>5} {'一致':>5} {'不一致':>6}  不一致题号(自动/人工)")
    tot_same = tot_diff = 0
    for y in sorted(MANUAL):
        p = os.path.join(CACHE, f"{y}-answer.pdf")
        ans, mode = parse_answers(pdf_text(p, decrypt=True), pdf_layout_text(p))
        diffs = [(n, ans.get(n), key[y][n]) for n in range(1, 41)
                 if n in ans and ans[n] != key[y][n]]
        same = sum(1 for n in range(1, 41) if n in ans and ans[n] == key[y][n])
        missing = sum(1 for n in range(1, 41) if n not in ans)
        tot_same += same
        tot_diff += len(diffs)
        flag = "" if not diffs else "  <-- 自动提取有误"
        print(f"{y:>5} {same:>5} {len(diffs):>6}  缺失{missing}  {diffs[:4]}{flag}")
        audit.append({"year": y, "auto_mode": mode, "一致": same,
                      "不一致": len(diffs), "缺失": missing,
                      "不一致明细": diffs})
    print(f"\n合计: 一致 {tot_same} / 不一致 {tot_diff} "
          f"(自动提取在人工核对年份的准确率 {tot_same/max(1,tot_same+tot_diff)*100:.1f}%)")

    # 4) 落盘
    out = {
        "说明": "408 真题校订答案库。用于自动判题, 准确性优先。",
        "覆盖": f"{min(key)}-{max(key)} 共 {len(key)} 套",
        "总题数": sum(len(v) for v in key.values()),
        "年份出处": {str(y): meta[y] for y in sorted(key)},
        "答案": {str(y): {str(n): c for n, c in sorted(key[y].items())} for y in sorted(key)},
    }
    os.makedirs(OUT, exist_ok=True)
    dst = os.path.join(OUT, "answers_verified.json")
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    adst = os.path.join(OUT, "answer_audit.json")
    with open(adst, "w", encoding="utf-8") as f:
        json.dump({"审计": audit, "人工录入年份准确率":
                   f"{tot_same/max(1,tot_same+tot_diff)*100:.1f}%"}, f,
                  ensure_ascii=False, indent=2)

    print(f"\n输出: {dst}  ({out['覆盖']}, {out['总题数']} 个答案)")
    print(f"审计: {adst}")


if __name__ == "__main__":
    main()
