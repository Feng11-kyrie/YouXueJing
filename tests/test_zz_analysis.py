#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
政治材料分析题（34–38）参考要点 + 免费评分的回归测试。

为什么单独一份：
  分析题的「参考要点」是服务端 LLM 生成的（非官方），很容易在重新导入数据时
  被覆盖掉；免费评分也会因为 _split_points / 权重的改动悄悄退化。
  这里把「每年 5 题都有参考要点」和「评分能拆出要点覆盖项」钉住。

用法：  .venv/bin/python tests/test_zz_analysis.py
"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from yj import rubric_checker as rc                             # noqa: E402
from yj import zhengzhi as zz                                   # noqa: E402


def check_refs():
    missing = []
    for y in zz.years():
        for n in range(34, 39):
            e = zz.explanation(y, n) or {}
            txt = (e.get("文本") or "").strip()
            if len(txt) < 100:
                missing.append(f"{y}-{n}")
    assert not missing, f"缺参考要点：{missing}"


def check_scoring():
    ref = ("（1）实践是认识的来源和检验真理的唯一标准，调查只提供感性材料，"
           "必须经过加工才能上升为理性认识。\n"
           "（2）感性认识有待于发展为理性认识，不能停留在现象罗列。\n"
           "（3）坚持一切从实际出发、实事求是，把调查和科学理论结合起来。")
    good = ("（1）实践是认识的来源，调查只是获取感性材料，必须经过加工才能形成理性认识。\n"
            "（2）感性认识要上升为理性认识，不能停留在现象罗列。\n"
            "（3）坚持实事求是，把调查和科学理论结合起来。")
    r = rc.score_politics(good, "如何理解调查并不自然产生科学结论", ref, 10, 150)
    assert 0 <= r["分数"] <= 10
    assert any(i["项"] == "参考要点覆盖" for i in r["分项"]), r
    assert "参考要点" in r["来源"]
    # 跑题答案不能拿到高分
    bad = rc.score_politics("我不会写。" * 10, "如何理解调查", ref, 10, 150)
    assert bad["分数"] < r["分数"], (bad, r)


if __name__ == "__main__":
    check_refs()
    check_scoring()
    print("政治分析题参考要点 + 免费评分测试通过")
