#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
**免费版评分**：不调任何大模型 API，完全本地计算。

为什么要做这个
------------
用户要求："用户如果不接入自己的 API Key 就默认用免费版评分系统"。
AI 评阅每次约 ¥0.006（输入 ~1100 + 输出 ~450 tokens），
对"随便练两道题"的场景没必要花钱；而免费版还能保证**断网、离线、路演现场**都能用。

两类题的评分逻辑**完全不同**（这是实测出来的结论，不是猜的）
--------------------------------------------------------
**翻译**：任务是"准确传达这句英文的意思"，所以**语义相似度就是评分依据**。
用本地嵌入模型（fastembed + BAAI/bge-small-zh-v1.5，50MB，ONNX，无需 torch）
把学生译文与参考译文的**每一句**比对，取最高相似度。

实测区分度（2024 英语一第 46 题）：

    很好（贴合参考）        1.000
    中等（正确意译）        0.806
    较差（只译出一部分）    0.710
    抄英文原文              0.504   ← 抄原文会被压低
    跑题（讲环境保护）      0.456

**不需要按句对齐**：最初想"第 46 题对参考第 1 句"，但实测 34 套里
**20 套切句数与题数不一致**（英语一多/少一句、英语二整篇只有 1 题）。
改用"取与所有参考句的最高相似度"，绕开对齐问题，且实测更稳。

**作文**：所有考生的作文**主题相同**，语义相似度测的是"话题"不是"水平"——
实测三篇质量差距很大的作文，与参考范文的相似度是 0.902 / 0.931 / 0.923，
**完全分不开**。所以作文改用**语言质量指标**（词数/句式/词汇/衔接），
并以 63 篇机构参考范文的指标分布作为**校准锚点**。

校准锚点（63 篇范文实测）
------------------------
    词数中位 117（94–199）· 平均句长 13.5（7.7–23.6）
    长句率 0.45（0.08–1.0）· 词汇丰富度 0.74（0.65–0.83）· 连接词 2（0–5）

能做什么、不能做什么（必须如实告知用户）
--------------------------------------
    ✅ 排序可靠（差的确实低于好的）、分项可解释、翻译按"是否传达意思"给分
    ❌ 判断不了"内容是否切题"（除非常识关键词）、判断不了"逻辑是否连贯"
    ❌ 绝对值是**公式估算**，没有人工评分样本做回归校准 → 不等于阅卷分数
"""
import os
import re

import numpy as np

# 嵌入模型：首次使用会下载约 50MB，之后本地推理（几十毫秒）
_MODEL_NAME = "BAAI/bge-small-zh-v1.5"
_model = None

SOURCE = "免费版评分（本地客观指标估算，非阅卷分数）"

# 连接词/结构词（作文的衔接分项）
_CONN = (
    "first", "second", "third", "finally", "however", "moreover", "furthermore",
    "besides", "therefore", "thus", "although", "while", "in addition",
    "for example", "for instance", "as a result", "in conclusion", "in short",
    "on the one hand", "on the other hand", "to sum up", "what is more",
)


def _get_model():
    """懒加载嵌入模型（首次约 20 秒下载 + 初始化）。"""
    global _model
    if _model is None:
        from fastembed import TextEmbedding
        _model = TextEmbedding(_MODEL_NAME)
    return _model


def available():
    """免费评分是否可用（嵌入库是否装上）。"""
    try:
        import fastembed  # noqa: F401
        return True
    except Exception:                                       # noqa: BLE001
        return False


def _embed(texts):
    m = _get_model()
    vs = [np.array(v, dtype="float32") for v in m.embed(list(texts))]
    out = []
    for v in vs:
        n = np.linalg.norm(v)
        out.append(v / n if n else v)
    return out


def _split_zh_sentences(text):
    parts = re.split(r'(?<=[。！？；])', text or "")
    return [p.strip() for p in parts if len(p.strip()) >= 8]


# ---------------------------------------------------------------------------
# 翻译
# ---------------------------------------------------------------------------
# 相似度 → 得分率的映射区间。下限取 0.55（低于此基本是"没译对/跑题"），
# 上限 0.95（再高就接近参考译文本身）。
_SIM_LO, _SIM_HI = 0.55, 0.95


def score_translation(student, reference, full=2.0):
    """
    翻译评分：**语义相似度**为主 + 长度合理性校验。

    student   : 学生译文
    reference : 该篇参考译文（整段，内部会切句取最高相似度）
    full      : 该题满分（英语一 2 分 / 英语二 15 分）

    返回 {分数, 满分, 相似度, 分项:[{项,得分,满分,说明}], 问题:[...], 来源}
    """
    problems = []
    ans = (student or "").strip()
    issues = []

    if len(ans) < 3:
        return {"分数": 0.0, "满分": full, "相似度": 0.0,
                "分项": [{"项": "译文", "得分": 0, "满分": full,
                          "说明": "没有作答"}],
                "问题": ["没有作答"], "来源": SOURCE}

    ref_sents = _split_zh_sentences(reference) or ([reference] if reference else [])
    if not ref_sents:
        return {"分数": None, "满分": full, "相似度": None,
                "分项": [], "问题": ["这道题没有参考译文，无法免费评分"],
                "来源": SOURCE}

    # ① 语义相似度（取与所有参考句的最高值）
    try:
        vecs = _embed([ans] + ref_sents)
        a = vecs[0]
        sim = float(max(float(a @ r) for r in vecs[1:]))
    except Exception:                                       # noqa: BLE001
        return {"分数": None, "满分": full, "相似度": None,
                "分项": [], "问题": ["本地评分模型不可用（未安装 fastembed）"],
                "来源": SOURCE}

    rate = (sim - _SIM_LO) / (_SIM_HI - _SIM_LO)
    rate = max(0.0, min(1.0, rate))

    # ② 长度合理性：中文译文长度应与参考句相当（0.5–2.2 倍）
    ref_len = max(len(s) for s in ref_sents)
    ratio = len(ans) / max(1, ref_len)
    len_ok = 0.45 <= ratio <= 2.4
    if not len_ok:
        rate *= 0.85
        issues.append(f"译文长度与参考差距较大（{len(ans)} 字 vs 参考约 {ref_len} 字）")

    # ③ 抄英文原文检测
    ascii_ratio = sum(1 for c in ans if ord(c) < 128) / max(1, len(ans))
    if ascii_ratio > 0.6:
        rate = min(rate, 0.15)
        issues.append("译文里绝大部分是英文 —— 要求是译成中文")

    score = round(rate * full, 1)

    if sim < 0.55:
        issues.append("与参考译文的意思差距较大，可能是漏译或理解偏差")
    elif sim < 0.72:
        issues.append("部分信息没译出，或表达与原文有出入")
    elif sim < 0.88:
        issues.append("基本传达了原意，个别词句可以更准确")
    else:
        issues.append("与参考译文高度一致")

    return {
        "分数": score, "满分": full, "相似度": round(sim, 3),
        "分项": [
            {"项": "意思传达", "得分": round(rate * full, 1), "满分": full,
             "说明": f"与参考译文语义相似度 {sim:.2f}"},
            {"项": "长度", "得分": "—", "满分": "—",
             "说明": f"{len(ans)} 字 / 参考约 {ref_len} 字"},
        ],
        "问题": issues, "来源": SOURCE,
    }


# ---------------------------------------------------------------------------
# 作文
# ---------------------------------------------------------------------------
def score_writing(student, need_words=100, full=10.0):
    """
    作文评分：**语言质量指标**（不用语义相似度，理由见模块说明）。

    分项与权重（参考 63 篇机构范文的实测分布设定）：
        词数达标   35%   要求词数的 0.9–1.6 倍算达标
        句式       25%   平均句长 13.5 为范文水平；长句（≥15 词）率 0.45 为范文水平
        词汇       20%   词汇丰富度 0.74 为范文水平（按长度校正，避免短文本偏高）
        衔接       20%   连接词 2 个为范文中位

    返回 {分数, 满分, 分项, 问题, 来源}
    """
    text = (student or "").strip()
    words = re.findall(r"[A-Za-z']+", text)
    n = len(words)
    if n < 5:
        return {"分数": 0.0, "满分": full,
                "分项": [], "问题": ["没有作答（或字数过少）"], "来源": SOURCE}

    sents = [s for s in re.split(r'[.!?]+', text) if s.strip()]
    lens = [len(re.findall(r"[A-Za-z']+", s)) for s in sents] or [0]
    avg = n / max(1, len(lens))
    long_ratio = sum(1 for x in lens if x >= 15) / max(1, len(lens))
    ttr = len({w.lower() for w in words}) / max(1, n)
    low = text.lower()
    conn = sum(low.count(c) for c in _CONN)

    # ① 词数（35%）
    ratio = n / max(1, need_words)
    if 0.9 <= ratio <= 1.6:
        s_word = 1.0
    elif ratio >= 0.7:
        s_word = 0.75
    elif ratio >= 0.4:
        s_word = 0.4
    else:
        s_word = max(0.0, ratio)

    # ② 句式（25%）：平均句长与长句率各半
    s_avg = min(1.0, avg / 13.5)
    s_long = min(1.0, long_ratio / 0.45)
    s_sent = 0.5 * s_avg + 0.5 * s_long

    # ③ 词汇（20%）：TTR 按长度校正（短文本 TTR 天然偏高）
    ttr_adj = ttr * min(1.0, n / 100)
    s_vocab = min(1.0, ttr_adj / 0.74)

    # ④ 衔接（20%）：连接词 2 个算满（范文里也有 0 个的，所以不苛求）
    s_conn = min(1.0, conn / 2.0)

    rate = 0.35 * s_word + 0.25 * s_sent + 0.20 * s_vocab + 0.20 * s_conn
    score = round(rate * full, 1)

    problems = []
    if ratio < 0.9:
        problems.append(f"字数不足：{n} 词，要求约 {need_words} 词")
    if s_avg < 0.6:
        problems.append(f"句子偏短：平均 {avg:.1f} 词/句（范文约 13.5）")
    if long_ratio < 0.25:
        problems.append(f"长句偏少：≥15 词的句子占 {long_ratio:.0%}（范文约 45%）")
    if ttr_adj < 0.55:
        problems.append(f"用词较单一：词汇丰富度 {ttr:.2f}（范文约 0.74）")
    if conn == 0:
        problems.append("没有使用连接词（first / however / therefore 等）")
    if not problems:
        problems.append("各项指标均达到范文水平")

    return {
        "分数": score, "满分": full,
        "分项": [
            {"项": "字数", "得分": round(s_word * full * 0.35, 1),
             "满分": round(full * 0.35, 1), "说明": f"{n} 词（要求约 {need_words}）"},
            {"项": "句式", "得分": round(s_sent * full * 0.25, 1),
             "满分": round(full * 0.25, 1),
             "说明": f"平均 {avg:.1f} 词/句，长句 {long_ratio:.0%}"},
            {"项": "词汇", "得分": round(s_vocab * full * 0.20, 1),
             "满分": round(full * 0.20, 1), "说明": f"丰富度 {ttr:.2f}"},
            {"项": "衔接", "得分": round(s_conn * full * 0.20, 1),
             "满分": round(full * 0.20, 1), "说明": f"连接词 {conn} 个"},
        ],
        "问题": problems, "来源": SOURCE,
    }
