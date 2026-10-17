#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
评分标准（rubric）判分的回归测试 —— 不联网、不花钱、不需要 API Key。

为什么单独一份
--------------
`score_by_rubric` 的结论全靠启发式证据（有没有代码/注释/复杂度、复杂度对不对、
与参考答案的重合度）。这些阈值是**调出来的**，很容易被后续改动带偏：
把"好答卷"从 13 分调成 9 分、把"跑题"从 0 分调成 4 分，都不会报错，
但用户会立刻发现分数不对。所以用三份固定答卷把行为钉住。

三个档次的预期（2025 年第 41 题，满分 13）：
    good  完整思路 + 代码 + 注释 + O(n)/O(1)   → 13
    med   暴力解法（O(n²) 双重循环）、无注释   → 7–9
    poor  只有一句"先排序"                    → 0

用法：  .venv/bin/python tests/test_rubric.py
"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from yj import data                                              # noqa: E402
from yj import rubric_checker as rc                              # noqa: E402

GOOD = """（1）算法的基本思想：从数组末尾向前扫描，维护后缀最大值和后缀最小值。
对 A[i]，若 A[i]≥0 则乘后缀最大值，若 A[i]<0 则乘后缀最小值，结果存入 res[i]，
只需一趟扫描，时间复杂度 O(n)，空间复杂度 O(1)。
（2）C/C++ 实现：
void calMulMax(int A[], int res[], int n) {
    int mx = A[n-1], mn = A[n-1];        // 后缀最大/最小值
    res[n-1] = A[n-1] * A[n-1];
    for (int i = n-2; i >= 0; i--) {
        int a = A[i] * mx, b = A[i] * mn; // 正负分别取
        res[i] = a > b ? a : b;
        if (A[i] > mx) mx = A[i];
        if (A[i] < mn) mn = A[i];
    }
}
（3）时间复杂度 O(n)，空间复杂度 O(1)。"""

MED = """（1）基本思想：对每个 i，枚举 j 从 i 到 n-1，把 A[i]*A[j] 的最大值存到 res[i] 中。
（2）实现：
void calMulMax(int A[], int res[], int n) {
    for (int i = 0; i < n; i++) {
        int m = A[i] * A[i];
        for (int j = i; j < n; j++)
            if (A[i] * A[j] > m) m = A[i] * A[j];
        res[i] = m;
    }
}
（3）时间复杂度 O(n^2)，空间复杂度 O(1)。"""

POOR = "我觉得应该先排序，然后找最大的两个数乘起来，放到结果里，这样比较快。"


def main():
    ok = bad = 0

    def check(name, cond, extra=""):
        nonlocal ok, bad
        if cond:
            ok += 1
            print(f"  ✓ {name}")
        else:
            bad += 1
            print(f"  ✗ {name}   {extra}")

    print("· rubric 文件")
    rub = rc.rubric_for(2025, 41)
    check("2025 年第 41 题有 rubric", bool(rub))
    if not rub:
        print("（data/408/rubrics/2025.json 不存在 —— 先跑 "
              "scripts/fetch_408_rubrics.py --year 2025）")
        return 1
    check("满分 13", rub.get("满分") == 13, rub.get("满分"))
    ssum = sum(s["分值"] for s in rub["步骤"])
    check("各步骤分值之和 == 满分（交接文档要求的校验）", ssum == 13, ssum)

    print("· 三份答卷的分档结果")
    ref = ""
    try:
        ref = data.solution(2025, 41)["文本"]
    except Exception:                                        # noqa: BLE001
        pass
    terms = ["线性表的应用", "算法的基本概念"]
    r_good = rc.score_by_rubric(GOOD, rub, reference=ref, terms=terms)
    r_med = rc.score_by_rubric(MED, rub, reference=ref, terms=terms)
    r_poor = rc.score_by_rubric(POOR, rub, reference=ref, terms=terms)
    for nm, r in (("good", r_good), ("med", r_med), ("poor", r_poor)):
        print(f"    {nm}: {r['分数']} / {r['满分']}")
    check("完整正解得满分", r_good["分数"] == 13, r_good["分数"])
    check("暴力解明显低于正解", r_med["分数"] < r_good["分数"] - 3, r_med["分数"])
    check("暴力解仍拿到部分分（方向对）", 5 <= r_med["分数"] <= 10, r_med["分数"])
    check("跑题/空话得 0 分", r_poor["分数"] == 0, r_poor["分数"])
    check("结果标注了来源（界面据此区分）", r_good.get("类型") == "rubric")
    check("每步都有得分记录", len(r_good["分项"]) == 3)

    print("· 边界")
    check("空作答 0 分", rc.score_by_rubric("", rub)["分数"] == 0)
    check("没有 rubric 的题返回 None", rc.rubric_for(2025, 42) is None)
    check("没有 rubric 的年份返回 None", rc.rubric_for(2009, 41) is None)
    # 不分步写也不能崩（整段一起判）
    one = GOOD.replace("（1）", "").replace("（2）", "").replace("（3）", "")
    r_one = rc.score_by_rubric(one, rub, reference=ref)
    check("整段作答也能判分", 0 <= r_one["分数"] <= 13, r_one["分数"])

    print("· 结构体检的全角分点识别（曾经不认（1）（2），分点永远判 0）")
    g = rc.score_generic("（1）甲。（2）乙。（3）丙。", "题干", "", 10, 50)
    fen = [it for it in g["分项"] if it["项"] == "分点"][0]
    check("（1）（2）（3）被识别为分点", "0 处" not in fen["说明"], fen["说明"])

    print(f"\n{ok} 通过 · {bad} 失败")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
