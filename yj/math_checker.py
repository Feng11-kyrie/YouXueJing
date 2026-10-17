#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数学**解答题**的免费评分（本地、离线、不调模型）。

为什么不能直接用 score_generic
------------------------------
408/政治的"结构体检"看的是篇幅、分点、题干关键词 —— 对数学解答题不够：
  · 数学答案常常很短（"由拉格朗日中值定理得…故最大值为 2"），篇幅没有意义；
  · 真正决定得分的是**关键步骤有没有出现**（求导/驻点/极值/收敛半径…）。
所以这里改成"**与参考答案的关键步骤/术语重合度** + 分步结构 + 长度"三项。
它仍然判断不了推导对不对，界面必须写明"结构体检，不是阅卷分数"。

评分锚点（全部是本地规则，没有人工评分样本校准）：
    关键步骤覆盖 50% ｜ 分步/推导迹象 25% ｜ 长度合理性 25%
"""
import re

_CJK = re.compile(r"[\u4e00-\u9fff]")
_TERM = re.compile(r"[\u4e00-\u9fff]{2,6}")
_MATHTok = re.compile(
    r"(?<![A-Za-z])(lim|sin|cos|tan|cot|ln|log|arcsin|arccos|arctan|"
    r"dx|dy|dz|dt|d\\theta|max|min|sup|inf)(?![A-Za-z])"
    r"|[∫∑∏∞∂∇√]"
)
_STOP = set("的是在了和与则若可会能要对从到为以被把中上下这个那道题因此所以故有"
            "可以应该需要本题如下下列答案解析学生考生得分给分".split())
# 解析里的"套话"：不是解题步骤，命中它们不代表答到点上
_BAD_PREFIX = ("方法", "因为", "所以", "因此", "解得", "由此", "从而", "可知",
               "代入", "整理", "显然", "注意", "本题", "于是", "又", "由题")
# 2 个字但有信息量的数学词（其余 2 字词一律不收，避免"因为/所以"混进来）
_MATH2 = set("导数 偏导 积分 极值 驻点 收敛 矩阵 秩 概率 期望 方差 分布 极限 "
             "连续 可导 微分 方程 通解 特解 面积 体积 曲线 曲面 向量 级数 "
             "拐点 单调 区间 特征 二次 正交 相似 合同 独立 相关 估计 检验".split())
_STEP = re.compile(r"[（(]\s*[1-9]\s*[)）]|[①②③④⑤]|首先|其次|然后|最后|"
                   r"由.{0,20}得|因为|所以|故|因此|综上")


def _terms(ref):
    out = []
    for t in _TERM.findall(ref or ""):
        if t in _STOP or len(t) < 2:
            continue
        if len(t) < 3 and t not in _MATH2:
            continue
        if any(t.startswith(b) for b in _BAD_PREFIX):
            continue
        if t not in out:
            out.append(t)
    for t in _MATHTok.findall(ref or ""):
        t = t or ""
        if t and t not in out:
            out.append(t)
    # 取出现顺序靠前、且不太泛的前 10 个
    return out[:10]


def score_math(answer, reference, prompt="", full=10.0):
    """
    返回与 score_generic 同构的结果：{分数, 满分, 分项, 问题, 来源}
    """
    ans = (answer or "").strip()
    src = "结构体检（按参考答案的关键步骤比对，不含推导正确性）"
    if len(ans) < 8:
        return {"分数": 0.0, "满分": full, "分项": [],
                "问题": ["没有作答（或内容过少）"], "来源": src}

    terms = _terms(reference)
    hit = [t for t in terms if t in ans]
    cov = len(hit) / len(terms) if terms else 0.0

    steps = len(_STEP.findall(ans))
    s_step = min(1.0, steps / 3.0)
    # 数学作答里大量是公式/符号，只数汉字会严重低估 —— 按去空白后的总字符数
    n_chars = len(re.sub(r"\s+", "", ans))
    s_len = min(1.0, n_chars / 80.0)

    score = full * (0.50 * cov + 0.25 * s_step + 0.25 * s_len)
    score = round(score * 2) / 2

    missing = [t for t in terms if t not in ans][:4]
    problems = []
    if missing:
        problems.append("参考答案里的关键步骤/术语没出现：" + "、".join(missing))
    if steps < 2:
        problems.append("看不出分步推导 —— 解答题按步骤给分，建议写清“由…得…”")
    if n_chars < 40:
        problems.append(f"作答偏短（{n_chars} 字符），推导过程可能没写全")
    if not problems:
        problems.append("关键步骤与结构基本齐全（注意：这不代表推导正确）")

    return {
        "分数": score, "满分": float(full),
        "分项": [
            {"项": "关键步骤", "得分": round(full * 0.5 * cov, 1),
             "满分": round(full * 0.5, 1),
             "说明": f"命中 {len(hit)}/{len(terms)}："
                     + ("、".join(hit[:4]) or "无")},
            {"项": "分步推导", "得分": round(full * 0.25 * s_step, 1),
             "满分": round(full * 0.25, 1), "说明": f"识别到 {steps} 处推导/分步"},
            {"项": "篇幅", "得分": round(full * 0.25 * s_len, 1),
             "满分": round(full * 0.25, 1), "说明": f"{n_chars} 字符"},
        ],
        "问题": problems,
        "来源": src,
    }
