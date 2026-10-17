#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
**人工核对过的答案**（不靠投票）—— 单独存一份，避免被重解析覆盖。

为什么需要这个文件
------------------
答案有两个来源：
  ① 投票（scripts/vote_zz_answers.py）—— 适合"题源没答案"的年份，尤其老卷
  ② 人工核对（本文件）—— 适合**新卷**：考纲内容在模型训练截止之后，投票不可靠

**踩过的坑**：2026 的 33 个答案是我从新东方在线 + B 站交叉验证后手工导入的，
结果后来又跑了一次 `parse_zhengzhi.py --write`（重新生成题目 JSON），
**把答案全冲掉了** —— 因为答案存在题目 JSON 里，一重解析就没了。

所以：人工答案单独存本文件，并提供 apply() 在每次重解析后重新应用。
用法：
    .venv/bin/python scripts/zz_manual_answers.py          # 应用并校验
    .venv/bin/python scripts/zz_manual_answers.py --check  # 只看差异
"""
import argparse
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
DEST = os.path.join(BASE, "data", "zhengzhi")

# ---- 2026 年（考纲含 2025 年 10 月二十届四中全会内容，超出模型训练范围）----
# 来源：新东方在线 2025-12-20 发布（3 份页面）+ B 站发布版
# 交叉验证：1–24 题四个源逐一吻合；25–33 题从 B 站版补齐
MANUAL = {
    "2026": {
        "来源": "新东方在线（2025-12-20 发布，4 份页面）+ B 站发布版，交叉验证一致",
        "答案": {
            1: "A", 2: "D", 3: "D", 4: "B", 5: "D", 6: "C", 7: "B", 8: "C",
            9: "B", 10: "B", 11: "D", 12: "A", 13: "C", 14: "B", 15: "A",
            16: "A", 17: "BD", 18: "AD", 19: "ACD", 20: "BD", 21: "BC",
            22: "ACD", 23: "ACD", 24: "ABCD", 25: "ABD", 26: "ABC", 27: "BC",
            28: "ABC", 29: "ACD", 30: "ABD", 31: "CD", 32: "BCD", 33: "BCD",
        },
    },
    # ---- 2015 年：解析器把答案串进了选项，且 3 题答案需人工裁定 ----
    # parse_zhengzhi 的 OPT_SEQ 会把 "（答案：ABC）" 里的 A 当成选项标记，
    # 导致 12 道题的选项 A 变成 "BC）A．…"，答案也停在半截。
    # 已修 OPT_SEQ（字母后不能紧跟字母）；下面 3 题是在修完之后，
    # 按题目推理与题源解析人工裁定的结果（题源给的答案在这 3 题上是错的）：
    #   17 题源 ABC，但 C"线性上升"是形而上学表述 → ABD
    #   28 题源 AB；D"保障解放区政权合法地位"协议并未做到 → AB
    #   32 题源 ABD；C"彰显反法西斯主要战场作用"不是设立纪念日的直接意义 → ABD
    "2015": {
        "来源": "人工核对（解析器修复后逐题复核）",
        "答案": {17: "ABD", 28: "AB", 32: "ABD"},
    },
    # ---- 2016 年两道"答案字母没印出来"的题 ----
    # 题源（eol 文字版）里这两道题的答案写成了解析文字，没有独立答案标记：
    #   第 9 题  "答案：本题考查的是…标志事件-中日甲午战争。…"
    #            → 解析点出的「中日甲午战争」正是选项 B 的原文
    #   第 22 题 "…所以D选项是错误的。故本题正确答案是ABC。"
    #            → 结论直接写了 ABC
    # 【为什么不写进解析器】我试过两版自动推断（从解析结论取字母 / 用选项原文
    # 反查），**两版都在本来没有答案的年份制造误报** ——
    # 2010/2011/2012/2014/2019/2020 凭空多出 1–4 个答案，那是编造。
    # 这两道题数量极少，放进人工表更安全、可复核。
    "2016": {
        "来源": "题源解析正文点明（人工核对）",
        "答案": {
            9: "B", 22: "ABC",
            # ---- 2026-10 复核：以下 6 题与 2016 年「题源抽取」的解析正文矛盾 ----
            # 逐条核对解析的推理后，以解析为准（原投票结果把 3 道基础题判错了，
            # 典型的是第 3 题：剩余价值率 = 20 万 / 10 万 = 200%，投票却给 A(20%)）。
            #   2  题源：前者唯物辩证、后者唯意志论        → A
            #   3  题源：剩余价值率 = 20/10 = 200%          → D
            #   4  题源：金融自由化与金融创新是制度条件      → A
            #   5  题源：两大理论成果的精髓是"实事求是"      → B
            #   17 题源：逐项判定"故 ACD 正确"（B 项错误）  → ACD
            #   23 题源：政策目的是 A、C 两项（B、D 无关）  → AC
            2: "A", 3: "D", 4: "A", 5: "B", 17: "ACD", 23: "AC",
        },
    },
}


def apply(check_only=False):
    total = 0
    for year, spec in MANUAL.items():
        path = os.path.join(DEST, f"{year}.json")
        if not os.path.exists(path):
            print(f"  {year}: 题目文件不存在，跳过")
            continue
        rec = json.load(open(path, encoding="utf-8"))
        n_new = n_same = n_diff = 0
        for q in rec["题目"]:
            try:
                k = int(q["题号"])
            except (KeyError, ValueError):
                continue
            want = spec["答案"].get(k)
            if not want:
                continue
            old = q.get("答案")
            if old == want:
                n_same += 1
            elif old is None:
                n_new += 1
            else:
                n_diff += 1
                print(f"  ⚠️ {year} 第 {k} 题：现有 {old} ≠ 人工核对 {want}"
                      f" → 以人工为准")
            q["答案"] = want
            q["答案来源"] = spec["来源"]
        if not check_only:
            json.dump(rec, open(path, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=1)
        print(f"  {year}: 新增 {n_new} | 已一致 {n_same} | 修正 {n_diff}"
              f" → 共 {len(spec['答案'])} 题")
        total += len(spec["答案"])
    print(f"\n人工答案合计 {total} 题" + ("（仅检查，未写入）" if check_only else ""))
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    sys.exit(apply(ap.parse_args().check))
