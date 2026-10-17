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
import json
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


# ---------------------------------------------------------------------------
# 通用主观题评分（政治分析题 / 408 综合题）
# ---------------------------------------------------------------------------
# 与英语的差别（必须如实承认）：
#   · 英语有**干净的参考译文/范文**（34 套逐句译文 + 68 篇范文）→ 可算语义相似度
#   · 政治分析题 **没有任何参考答案**（85 道，解析为空）→ 只能做结构体检
#   · 408 综合题的参考答案是**带水印的 OCR**（"微信：x1xj985211"）
#     → 语义相似度会被水印词污染，也只做结构体检
# 所以这里的"免费评分"是**结构体检**：字数、分点、是否回应题干关键词，
# 给的是"表述完整度"而非"知识正确性"。界面必须说清楚。
_CJK = re.compile(r'[\u4e00-\u9fff]')


def score_generic(answer, prompt="", reference="", full=10.0,
                  need_words=120, terms=None):
    """
    政治/408 主观题的**结构体检**（免费、离线、即时）。

    评三件事（都不需要"知道正确答案"）：
      ① 篇幅：中文字数是否达到该题应有的量（论述题通常 120–300 字）
      ② 分点：是否分层作答（"第一/①/首先"或换行编号）——
         考研政治分析题、408 综合题都按采分点给分，不分点必丢分
      ③ 回应题干：题干里的关键词（≥2 字的实词）在作答里出现了多少

    返回结构与其他评分一致：{分数, 满分, 分项, 问题, 来源}
    """
    ans = (answer or "").strip()
    if len(ans) < 10:
        return {"分数": 0.0, "满分": full, "分项": [],
                "问题": ["没有作答（或字数过少）"], "来源": SOURCE}

    n_zh = len(_CJK.findall(ans))

    # ① 篇幅（40%）
    if n_zh >= need_words:
        s_len = 1.0
    elif n_zh >= need_words * 0.6:
        s_len = 0.7
    else:
        s_len = max(0.0, n_zh / max(1, need_words) * 0.7)

    # ② 分点（35%）：认序号词与换行编号
    lines = [l for l in ans.split("\n") if l.strip()]
    # 坑：原来只认"行首的 1."和 ①②③，**不认全角的（1）（2）** ——
    # 而 408 综合题的标准写法恰恰就是"（1）…（2）…"，于是分点永远被判 0。
    marks = len(re.findall(r'(?:^|\n)\s*(?:\d+[.、)]|第[一二三四五六七八九十]+)', ans))
    marks += len(re.findall(r'[（(]\s*[1-9]\s*[)）]', ans))     # （1）（2）—— 可出现在行中
    marks += len(re.findall(r'[①②③④⑤⑥⑦⑧⑨⑩]', ans))
    marks += len(re.findall(r'(?:首先|其次|再次|最后|一方面|另一方面)', ans))
    if marks >= 3:
        s_pts = 1.0
    elif marks >= 2:
        s_pts = 0.75
    elif marks == 1:
        s_pts = 0.45
    else:
        s_pts = 0.15 if len(lines) >= 3 else 0.0

    # ③ 回应题干（25%）：题干关键词覆盖率
    kws = [w for w in re.findall(r'[\u4e00-\u9fff]{2,6}', prompt or "")
           if len(w) >= 2][:12]
    hit = [w for w in kws if w in ans]
    cov = (len(hit) / len(kws)) if kws else 0.0
    s_cov = min(1.0, cov / 0.5)          # 覆盖一半关键词即算满分

    # ④ 术语命中（可选，权重 30%）——**这是最有价值的信号**
    # 408 每道题都带官方的「主考点名/次考点名」；政治的分析题可传材料关键词。
    # 学生作答里出现该题考点的术语，是"答到点上"的强证据，
    # 比"字数够不够"有意义得多。
    term_hit, term_all = [], list(terms or [])
    ans_low = ans
    for w in term_all:
        w = str(w).strip()
        if len(w) < 2:
            continue
        # 考点名往往是长短语（"散列表的构造与冲突处理"），学生只会写到其中几个词。
        # 所以按 **3 字子串** 判命中（"散列表"能对上，"的构造"这种通用片段也能对上，
        # 但要求至少一个 3 字片段，比对整串宽松、又比 2 字精确）。
        if w in ans_low:
            term_hit.append(w)
            continue
        grams = [w[i:i + 3] for i in range(max(0, len(w) - 2))]
        if any(g in ans_low for g in grams):
            term_hit.append(w)
    s_term = (len(term_hit) / len(term_all)) if term_all else 0.0
    s_term = min(1.0, s_term / 0.6)        # 命中六成考点术语即算满分

    if term_all:
        rate = 0.30 * s_len + 0.30 * s_pts + 0.15 * s_cov + 0.25 * s_term
    else:
        rate = 0.40 * s_len + 0.35 * s_pts + 0.25 * s_cov
    score = round(rate * full, 1)

    problems = []
    if n_zh < need_words:
        problems.append(f"篇幅偏少：{n_zh} 字（这类题通常需要"
                        f"{need_words} 字以上）")
    if marks < 2:
        problems.append("没有明显分点 —— 论述题按采分点给分，"
                        "建议用「第一/第二」或 ①②③ 分层")
    if term_all and s_term < 0.4:
        problems.append("考点术语出现得少：本题考点是「"
                        + "、".join(term_all[:3]) + "」，作答里应明确点到这些概念")
    if kws and cov < 0.3:
        problems.append("作答与题干的呼应偏少 —— 有几个题干关键词没出现，"
                        "可能没答到点上")
    if not problems:
        problems.append("篇幅与结构达到基本要求（注意：这不代表内容正确）")

    return {
        "分数": score, "满分": full,
        "分项": [
            {"项": "篇幅", "得分": round(s_len * full * (0.30 if term_all else 0.40), 1),
             "满分": round(full * (0.30 if term_all else 0.40), 1), "说明": f"{n_zh} 字"},
            {"项": "分点", "得分": round(s_pts * full * (0.30 if term_all else 0.35), 1),
             "满分": round(full * (0.30 if term_all else 0.35), 1),
             "说明": f"识别到 {marks} 处分层标记"},
            {"项": "呼应题干", "得分": round(s_cov * full * (0.15 if term_all else 0.25), 1),
             "满分": round(full * (0.15 if term_all else 0.25), 1),
             "说明": (f"题干关键词命中 {len(hit)}/{len(kws)}" if kws else "无关键词")},
        ] + ([{"项": "考点术语", "得分": round(s_term * full * 0.25, 1),
               "满分": round(full * 0.25, 1),
               "说明": f"命中 {len(term_hit)}/{len(term_all)}："
                       + ("、".join(term_hit[:3]) or "无")}] if term_all else []),
        "问题": problems,
        "来源": "结构体检（本地计算，不含知识正确性判断）",
    }


# ---------------------------------------------------------------------------
# 按官方评分标准分档给分（408 综合应用题）
# ---------------------------------------------------------------------------
# 与 score_generic 的**本质区别**：
#   结构体检只看"写够没有、分没分点"；这里看的是**这道题真实的评分标准**：
#       （1）算法基本思想（4 分）
#       ①清晰准确、能达到 O(n)        → 4 分
#       ②方向对但表述不清            → 2-3 分
#       ③完全错误                    → 0 分
#   判分变成"学生落在哪一档"，而且能直接告诉学生漏了哪一步、值几分。
#
# 数据从哪来（见 scripts/fetch_408_rubrics.py）：
#   data/408/rubrics/<年>.json 存【评分标准】原文的解析结果。
#   **没有 rubric 的年份/题目一律退回 score_generic()** —— 这是交接文档定的规则，
#   不能因为"想看起来准"就编一份标准出来。
#
# 判不准的地方必须承认：
#   机器读不懂代码，也判断不了"算法思想对不对"。能用的证据只有：
#   有没有分步写、有没有代码/注释/复杂度、复杂度是否与题目要求一致、
#   与参考答案的字面重合度。所以这是**证据推断**，不是阅卷分数 —— 界面必须写明。
_RUBRIC_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "408", "rubrics")

_rubric_cache = {}


def rubric_for(year, qno):
    """
    取某年第 N 题的评分标准；没有返回 None。

    调用方据此二选一：有 rubric → score_by_rubric()，没有 → score_generic()。
    """
    try:
        year, qno = int(year), int(qno)
    except (TypeError, ValueError):
        return None
    key = (year, qno)
    if key in _rubric_cache:
        return _rubric_cache[key]
    rub = None
    p = os.path.join(_RUBRIC_DIR, f"{year}.json")
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                doc = json.load(f)
            rub = (doc.get("题目") or {}).get(str(qno))
            if rub:
                rub = dict(rub)
                rub["_年"] = year
                rub["_题号"] = qno
                rub["_来源"] = doc.get("来源") or ""
        except Exception:                                   # noqa: BLE001
            rub = None
    _rubric_cache[key] = rub
    return rub


def available_rubrics():
    """[(年, 题号)] —— 自检/覆盖率用。"""
    out = []
    if not os.path.isdir(_RUBRIC_DIR):
        return out
    for fn in sorted(os.listdir(_RUBRIC_DIR)):
        m = re.match(r"(\d{4})\.json$", fn)
        if not m:
            continue
        try:
            doc = json.load(open(os.path.join(_RUBRIC_DIR, fn), encoding="utf-8"))
        except Exception:                                   # noqa: BLE001
            continue
        for qno in doc.get("题目") or {}:
            out.append((int(m.group(1)), int(qno)))
    return out


# ---- 小工具 ---------------------------------------------------------------
# 注：_CJK（中文字符）在上面的 score_generic 段已定义，这里直接复用。
_TECH_RE = re.compile(r"O\s*[（(]\s*[^）)]{1,12}[)）]"
                      r"|[A-Za-z][A-Za-z0-9+#./]{1,12}")
_CJK_RUN = re.compile(r"[\u4e00-\u9fff]+")
_STOP = set("的 了 和 与 及 或 是 在 对 从 到 为 以 使 让 则 若 可 会 能 要 有 无 被 把 中 上 下 "
            "问题 题目 考生 答案 分值 得分 给分 评分 应该 可以 需要 本题 如下 下列".split())


def _cjk_bigrams(text):
    """中文 2-gram 集合（算"与参考答案的字面重合"，比整句比对宽容，能容忍改写）。"""
    grams = set()
    for run in _CJK_RUN.findall(text or ""):
        for i in range(len(run) - 1):
            g = run[i:i + 2]
            if g not in _STOP:
                grams.add(g)
    return grams


def _recall(ref, ans):
    """参考答案的 2-gram 有多大比例出现在作答里。"""
    r = _cjk_bigrams(ref)
    if not r:
        return None
    return len(r & _cjk_bigrams(ans)) / len(r)


def _split_sections(text):
    """
    按 (1)/(2)/(3) 把作答切开 → {序号: 文本}。

    学生照题目结构分步写（阅卷就是这么看的），每步只跟对应那段比；
    没有分步就整段一起看（会略微低估）。
    """
    text = (text or "").strip()
    if not text:
        return {}
    marks = list(re.finditer(
        r"(?:^|\n)\s*(?:[（(]\s*([1-9])\s*[)）]|([1-9])\s*[.、)])", text))
    if len(marks) < 2:
        return {}
    out = {}
    for i, m in enumerate(marks):
        no = int(m.group(1) or m.group(2))
        start = m.end()
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        seg = text[start:end].strip()
        if seg and no not in out:
            out[no] = seg
    return out


def _has_code(text):
    """代码特征：语言关键字 + 结构符号。宁可漏判，也不要把大白话当代码。"""
    kw = len(re.findall(r"\b(?:int|void|char|float|double|return|for|while|if|else|"
                        r"struct|sizeof|malloc|free|typedef|bool|NULL|true|false)\b",
                        text or ""))
    braces = ("{" in (text or "")) and ("}" in (text or ""))
    semis = (text or "").count(";") >= 2
    return kw >= 3 and (braces or semis)


def _complexities(text):
    """作答里出现的复杂度写法（归一化：去空格、中文括号）。"""
    out = set()
    for m in _TECH_RE.finditer(text or ""):
        s = re.sub(r"\s+", "", m.group(0)).replace("（", "(").replace("）", ")")
        if s.lower().startswith("o("):
            out.add(s)
    return out


def _code_loops(text):
    """代码里 for/while 的嵌套层数（估计实现本身的复杂度量级）。"""
    depth = best = 0
    for m in re.finditer(r"\b(for|while)\b|(\{)|(\})", text or ""):
        tok = m.group(0)
        if tok in ("for", "while"):
            depth += 1
            best = max(best, depth)
        elif tok == "}":
            depth = max(0, depth - 1)
    return best


def _clean_reference(text):
    """
    去掉答案册 OCR 里的水印（"公众号：计算机考研数据"）。

    水印被打散插在句子中间，逐字删不现实 —— 只删已知整串，整行是水印的丢掉。
    残留碎片只会让字面重合度略低，不影响分档。
    """
    if not text:
        return ""
    wm = ["公众号【研池大叔】，免费分享考研干货！", "公众号：计算机考研数据",
          "公众号·计算机考研数据", "公众号：计算机考研", "公众号·计算机考研",
          "计算机考研数据", "考研数据", "公众号"]
    out = []
    for ln in str(text).split("\n"):
        if any(w in ln for w in ("公众号", "微信")) and len(ln.strip()) <= 24:
            continue
        for w in wm:
            ln = ln.replace(w, "")
        out.append(ln)
    return "\n".join(out)


# ---- 每步该看到什么 -------------------------------------------------------
def _cond_targets(cond_text):
    """档次条件里写的复杂度目标，如 O(n)。"""
    return sorted({re.sub(r"\s+", "", x).replace("（", "(").replace("）", ")")
                   for x in re.findall(r"O\s*[（(]\s*[^）)]{1,12}[)）]", cond_text)})


def _step_checks(step, targets):
    """
    根据评分标准的措辞决定这一步"该看到什么"。

    实测 408 第 41 题（算法设计）的三步固定是：思想 → 代码 → 复杂度。
    按措辞取检查项，比按题号写死可靠 —— 换年份的 rubric 也能用。
    """
    name = step.get("步骤") or ""
    want_idea = any(k in name for k in ("思想", "设计", "思路", "原理"))
    want_code = any(k in name for k in ("实现", "代码", "C", "注释"))
    want_cx = "复杂度" in name

    checks = []
    if want_idea:
        checks.append({"名": "思路描述", "权重": 0.6})
    if want_code:
        checks.append({"名": "代码", "权重": 0.5})
        checks.append({"名": "注释", "权重": 0.2})
    if want_cx or targets:
        checks.append({"名": "时间复杂度", "权重": 0.5 if not want_code else 0.3})
        if want_cx:
            checks.append({"名": "空间复杂度", "权重": 0.5})
    if not checks:
        checks.append({"名": "篇幅", "权重": 1.0})
    return checks


def _check_one(name, section, targets, full, whole=""):
    """跑一个检查项 → (0..1, 说明)。whole 是整份作答（复杂度常写在最后一步）。"""
    s = section or ""
    n_zh = len(_CJK.findall(s))
    if name == "思路描述":
        # 60 字以上才可能是"清晰、准确的描述"；短句给低分但不为零
        return (min(1.0, n_zh / 60.0),
                f"思路描述 {n_zh} 字" if n_zh >= 40 else f"思路描述偏短（{n_zh} 字）")
    if name == "代码":
        if _has_code(s):
            return 1.0, "有代码"
        if re.search(r"伪代码|算法描述|步骤如下", s):
            return 0.5, "只有文字步骤，没有代码"
        return 0.0, "没有代码"
    if name == "注释":
        ok = ("//" in s or "/*" in s or "#" in s or "注释" in s or "说明" in s)
        return (1.0 if ok else 0.0), ("有注释" if ok else "没有注释")
    if name == "时间复杂度":
        # 复杂度常写在最后一步（"(3) 时间复杂度 O(n)"），所以本步没写就看整份作答
        cx = _complexities(s) or _complexities(whole)
        if not cx:
            return 0.0, "没有写复杂度"
        if not targets:
            return 1.0, "写了复杂度"
        hit = [x for x in cx if x in targets]
        if hit:
            return 1.0, "复杂度与题目要求一致（" + "、".join(sorted(hit)) + "）"
        # 没达到目标复杂度但与自己写的代码相符 → 部分分（官方也说"超过 O(n) 最高 5 分"）
        loops = _code_loops(s) or _code_loops(whole)
        return 0.6, ("复杂度高于题目要求的最优解（写了 "
                     + "、".join(sorted(cx)[:2]) + "）" if loops >= 1
                     else "复杂度与题目要求不一致")
    if name == "空间复杂度":
        ok = ("空间" in (s or whole)) and bool(_complexities(s) or _complexities(whole))
        return (1.0 if ok else 0.0), ("提到空间复杂度" if ok else "漏了空间复杂度")
    return min(1.0, n_zh / max(20.0, full * 12)), f"{n_zh} 字"


def _quality(section, checks, targets, ref, terms, full, whole=""):
    """跑完所有检查项 → (质量 0..1, 命中说明, 未达成说明)"""
    hits, misses, score, wsum = [], [], 0.0, 0.0
    for c in checks:
        ok, why = _check_one(c["名"], section, targets, full, whole)
        score += c["权重"] * ok
        wsum += c["权重"]
        if ok >= 0.6:
            hits.append(why)
        else:
            misses.append(why)
    q = score / (wsum or 1.0)

    rec = _recall(ref, section) if ref else None
    if rec is not None:
        # 与参考答案重合度只用来区分"答到点子"和"泛泛而谈"，权重压低
        q = 0.75 * q + 0.25 * min(1.0, rec / 0.30)
        # 与参考答案几乎不沾边、篇幅又短 → 视为没答到点上
        # 只看"纯文字、又短、又和参考答案不沾边"的作答；代码段天然少中文，不适用
        if (rec < 0.05 and not _has_code(section)
                and len(_CJK.findall(section)) < 80):
            q = min(q, 0.2)

    if terms:
        hit_n = sum(1 for t in terms if str(t) and str(t)[:4] in (section or ""))
        q = 0.9 * q + 0.1 * min(1.0, 2.0 * hit_n / max(1, len(terms)))
    return max(0.0, min(1.0, q)), hits, misses


def _pick_band(bands, q):
    """按质量选档：档次按分值从高到低排，阈值按档数取。"""
    bands = [b for b in bands if b.get("得分上界") is not None]
    if not bands:
        return None
    bands = sorted(bands, key=lambda b: -float(b["得分上界"]))
    k = len(bands)
    if k == 1:
        return bands[0]
    ths = {2: [0.5], 3: [0.6, 0.32]}.get(k, [0.72, 0.5, 0.28])
    for i, th in enumerate(ths):
        if q >= th:
            return bands[i]
    return bands[-1]


def _point_hit(cond, section, targets):
    """
    采分点模式：一条一条判"做到没有"。

    例（2025 第 41 题第 3 步）：
        ① 时间复杂度与实现一致 → 看有没有写复杂度
        ③ 正确分析空间复杂度   → 看有没有写空间复杂度
    """
    s = section or ""
    cx = _complexities(s)
    if "空间" in cond:
        return ("空间" in s) and bool(cx)
    if "时间" in cond:
        # 官方这一条只要求"估计的复杂度与实现一致"，不要求等于最优解 ——
        # 写了复杂度就算达成（写错的那条是 0 分档，不会加分）
        return bool(cx)
    if "代码" in cond or "实现" in cond:
        return _has_code(s)
    if "注释" in cond:
        return ("//" in s or "注释" in s or "说明" in s)
    return len(_CJK.findall(s)) >= 20


def score_by_rubric(answer, rubric, full=None, reference="", terms=None):
    """
    按**官方评分标准**分档给分。

        answer    : 学生作答
        rubric    : rubric_for() 取到的该题 rubric
        full      : 满分（默认取 rubric 里的）
        reference : 参考答案（可选，用于校正"是否答到点子"）
        terms     : 该题考点名（408 用 question_tags.json 的主/次考点名）

    返回 {分数, 满分, 分项, 问题, 来源, 类型:"rubric"}
    """
    ans = (answer or "").strip()
    steps = (rubric or {}).get("步骤") or []
    total_full = float(full or (rubric or {}).get("满分") or 0) or 1.0
    src = "评分标准分档" + (
        f"（{rubric.get('_年')} 年第 {rubric.get('_题号')} 题【评分标准】原文）"
        if rubric.get("_年") else "")

    if not steps:
        return score_generic(ans, "", reference, total_full, terms=terms)

    if len(ans) < 10:
        return {"分数": 0.0, "满分": total_full, "分项": [],
                "问题": ["没有作答（或字数过少）"], "来源": src,
                "类型": "rubric", "档次": []}

    sections = _split_sections(ans)
    ref_all = _clean_reference(reference)
    ref_sections = _split_sections(ref_all)

    items, probs, band_rows = [], [], []
    got = 0.0
    for i, st in enumerate(steps, 1):
        full_i = float(st.get("分值") or 0)
        cond = " ".join(str(b.get("条件") or "") for b in (st.get("档") or []))
        targets = _cond_targets(cond)
        seg = (sections.get(i) if sections else None) or (ans if not sections else "")
        ref_seg = (ref_sections.get(i) if ref_sections else None) or ref_all

        checks = _step_checks(st, targets)
        q, hits, misses = _quality(seg, checks, targets, ref_seg, terms, full_i, ans)

        if len(seg.strip()) < 8:
            band, got_i = None, 0.0
            misses = ["这一步没有作答"]
        elif st.get("模式") == "采分点":
            band, got_i = None, 0.0
            for b in st.get("档") or []:
                up = float(b.get("得分上界") or 0)
                if up <= 0:
                    continue
                if _point_hit(str(b.get("条件") or ""), seg, targets):
                    got_i += up
            got_i = round(min(full_i, got_i) * 2) / 2
        else:
            band = _pick_band(st.get("档") or [], q)
            if band is None:
                got_i = round(q * full_i * 2) / 2
            else:
                lo = float(band.get("得分下界") or 0)
                hi = float(band["得分上界"])
                got_i = round(min(hi, max(lo, q * full_i)) * 2) / 2
                got_i = min(got_i, full_i)

        got += got_i
        if band is not None:
            desc = (f"第 {band.get('序号') or ''} 档："
                    + str(band.get("条件") or "")[:46].rstrip() + "…")
            band_rows.append({"步骤": st.get("步骤"), "档": band.get("序号"),
                              "得分": got_i, "满分": full_i})
        else:
            desc = "；".join(hits) if hits else "未达成"
        # 这一步已经拿到满分就别再列"没做到"—— 会让人以为扣了分
        if misses and seg.strip() and got_i < full_i:
            probs.append(f"「{st.get('步骤')}」：" + "、".join(misses)
                         + f" —— 这一步 {full_i:g} 分")
        items.append({"项": st.get("步骤"), "得分": got_i, "满分": full_i,
                      "说明": desc})

    total = round(min(total_full, got), 1)
    if not probs:
        probs.append("各步骤都按评分标准给分了（机器按证据估算，可能偏高或偏低）")

    return {"分数": total, "满分": total_full, "分项": items, "问题": probs,
            "来源": src, "类型": "rubric", "档次": band_rows}
