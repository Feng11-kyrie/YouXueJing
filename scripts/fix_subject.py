#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
修正 408 真题的学科归属错误。

背景
----
我最初假设「学科由题号区间唯一确定」:
  单选 1-11 DS / 12-22 CO / 23-32 OS / 33-40 CN
  综合 41-42 DS / 43-44 CO / 45-46 OS / 47 CN
**这个假设对 15 年成立, 但对 4 年不成立。** 是打标阶段的多智能体独立发现的。

裁决依据(两道独立证据, 互相印证)
------------------------------------------------
1. **官方分值硬约束**: 单选 40 题固定 80 分 → 综合题必为
   数据结构 2题23分 / 组成原理 2题23分 / 操作系统 2题15分 / 计算机网络 1题9分
   (因为官方总分固定为 DS45 / CO45 / OS35 / CN25)
   这是纯算术, 先穷举所有满足题数与分值约束的分配, 再看哪些年份题号区间规则不成立。
2. **题干内容判定**: 逐题读题干判断属于哪门课(如"路由表/TTL转发"必属网络,
   "PV操作/哲学家就餐"必属操作系统)。两份独立判定结果一致。

结果: 2009 / 2014 / 2016 / 2019 四年需要修正, 共 10 道题。
其余 14 年题号区间规则成立, 保持不变。

另有 3 年真题题干的分值被 OCR 弄错(2015/2018/2021), 已在下方 SCORE_FIX 中订正。
"""
import os
import json
import re

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "data", "408")

# ---------------------------------------------------------------- 学科修正表
# 格式: year -> {题号: 正确学科}
CORRECTIONS = {
    2009: {
        11: "计算机组成原理",
        # 2009 单选边界是 10/12/10/8 而非 11/11/10/8:
        # Q11「冯·诺依曼机中CPU区分指令和数据的依据」属组成原理。
        # 校验: DS 20+25=45 ✓  CO 24+21=45 ✓  OS 20+15=35 ✓  CN 16+9=25 ✓
    },
    2014: {
        43: "计算机网络",      # R1 路由表、IP 分组 TTL 转发 → 网络
        45: "计算机组成原理",  # Cache 数据区容量与命中率 → 组成
        47: "操作系统",        # 多生产者/多消费者环形缓冲区 P、V 操作 → OS
    },
    2016: {
        41: "计算机网络",      # TCP 连接与拥塞窗口 → 网络
        43: "数据结构",        # 集合划分算法设计 → 数据结构
        45: "计算机组成原理",  # 页式虚存+TLB+Cache 组相联/写策略 → 组成
        47: "操作系统",        # 链接分配/FAT 文件系统 → OS
    },
    2019: {
        43: "操作系统",        # 哲学家就餐 / PV 操作 → OS
        45: "计算机组成原理",  # C 函数递归的机器级代码 → 组成
    },
}

# ---------------------------------------------------------------- 分值订正
# 真题题干里被 OCR 弄错的分值(按官方分值约束反推)
SCORE_FIX = {
    2015: {46: 6},          # 题干无分值标记; OS 综合须 15 分, Q45=9 → Q46=6
    2018: {42: 10, 47: 9},  # Q42 含 2 分网络小问, 计入后 DS 13+10=23、CN 9
    2021: {44: 10},         # 题干显示 8 分, CO 须 43+44=23 → Q44=10
}

PAT = re.compile(r"[（(]\s*(?:本题\s*)?(\d{1,2})\s*分\s*[)）]")


def main():
    changed = []
    # 逐年应用修正
    for y, fixes in CORRECTIONS.items():
        p = os.path.join(OUT, f"{y}.json")
        d = json.load(open(p, encoding="utf-8"))
        for r in d["题目"]:
            n = r["题号"]
            if n in fixes and r["学科"] != fixes[n]:
                changed.append((y, n, r["学科"], fixes[n]))
                r["学科"] = fixes[n]
                r["_学科修正"] = "打标阶段发现题号区间规则不适用, 已按内容+分值约束修正"
        json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    # 补综合题分值
    n_score = 0
    for f in sorted(os.listdir(OUT)):
        if not re.fullmatch(r"20\d\d\.json", f):
            continue
        y = int(f[:4])
        p = os.path.join(OUT, f)
        d = json.load(open(p, encoding="utf-8"))
        for r in d["题目"]:
            if r["题号"] < 41:
                continue
            m = PAT.search(r["题干"])
            v = SCORE_FIX.get(y, {}).get(r["题号"]) or (int(m.group(1)) if m else None)
            if v and r.get("分值") != v:
                r["分值"] = v
                n_score += 1
        json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    print("=== 学科修正 ===")
    for y, n, old, new in changed:
        print(f"  {y}  Q{n:<2} {old} → {new}")
    print(f"共修正 {len(changed)} 道题的学科")
    print(f"\n=== 综合题分值 ===\n补全/订正 {n_score} 处")

    # 校验: 每年综合题分值合计应为 70
    print("\n=== 校验: 综合题分值合计 ===")
    for f in sorted(os.listdir(OUT)):
        if not re.fullmatch(r"20\d\d\.json", f):
            continue
        d = json.load(open(os.path.join(OUT, f), encoding="utf-8"))
        s = sum(r["分值"] or 0 for r in d["题目"] if r["题号"] >= 41)
        flag = "OK" if s == 70 else f"!! 合计 {s}"
        if s != 70:
            print(f"  {f[:4]}  {flag}")


if __name__ == "__main__":
    main()
