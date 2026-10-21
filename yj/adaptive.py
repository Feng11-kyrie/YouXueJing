#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自适应诊断组卷：**下一套诊断优先考上次错的、没掌握的，同时保证覆盖**。

用户要求："用户知识变多后，要给更符合他的诊断题库，之前的错题权重要更多"。

做法（四科统一）：
  1. 以"诊断单元"为抽样单位（数学=考点，政治=部分，英语=篇目，408=章）；
  2. 单元权重 = 1 + 4×错题数 + 2×没做过 + 2×正确率<60%；
  3. 先强制放入有错题的单元，再按权重抽满；
  4. 单元内优先选**上次做错的题**，其次没做过的，再随机；
  5. 生成完整 payload 存库（diag_plans），刷新不会变题。

注意：这是"诊断"不是"考试"，不追求固定卷面；每次重新诊断都会换题。
"""
import random
from collections import Counter, defaultdict


def _weighted(items, weights, k, rng):
    """Efraimidis-Spirakis 加权无放回抽样。"""
    keyed = []
    for x, w in zip(items, weights):
        keyed.append(((rng.random() ** (1.0 / max(float(w), 0.01))), x))
    keyed.sort(key=lambda t: t[0], reverse=True)
    return [x for _, x in keyed[:k]]


def _rec(answers, qid):
    r = answers.get(qid) or {}
    return None if r.get("source") == "selfscore" else r


def _qid_math(tier, q):
    return f"MATH-{tier}-{q['_year']}-{q['题号']}"


# ------------------------------------------------------------------ 数学
def math_plan(tier, answers, n=12, seed=None):
    from . import math as m
    ps = m.points(tier)
    if not ps:
        return []
    rng = random.Random(seed)
    units, weights, wrong_units = [], [], []
    for kp, qs in ps.items():
        wrong = [q for q in qs
                 if (_rec(answers, _qid_math(tier, q)) or {}).get("is_correct") is False]
        done = [q for q in qs
                if _rec(answers, _qid_math(tier, q)) is not None]
        ok = sum(1 for q in done
                 if _rec(answers, _qid_math(tier, q)).get("is_correct"))
        rate = (ok / len(done)) if done else None
        w = 1 + 4 * min(len(wrong), 3)
        if not done:
            w += 2
        if rate is not None and rate < 0.6:
            w += 2
        units.append(kp)
        weights.append(w)
        if wrong:
            wrong_units.append(kp)

    chosen = []
    for kp in wrong_units:
        if len(chosen) < n and kp not in chosen:
            chosen.append(kp)
    rest = [(u, w) for u, w in zip(units, weights) if u not in chosen]
    if rest and len(chosen) < n:
        chosen += _weighted([u for u, _ in rest], [w for _, w in rest],
                            n - len(chosen), rng)

    out = []
    for kp in chosen:
        qs = ps[kp]
        wrong = [q for q in qs
                 if (_rec(answers, _qid_math(tier, q)) or {}).get("is_correct") is False]
        unseen = [q for q in qs if _rec(answers, _qid_math(tier, q)) is None]
        pool = wrong or unseen or qs
        out.append({"考点": kp, "题目": rng.choice(pool)})
    return out


# ------------------------------------------------------------------ 政治
def zz_plan(answers, n_per_part=3, seed=None):
    from . import zhengzhi as zz
    rng = random.Random(seed)
    parts = zz.part_mastery(answers)
    weak = {p["部分"]: (p["正确率"] is not None and p["正确率"] < 0.6)
            for p in parts}
    out = []
    for part in zz.PARTS:
        cand = []
        for y in zz.years():
            for q in zz.paper(y)["题目"]:
                p, _ = zz.part_of(q["题号"], q["题型"])
                if p != part or "分析题" in str(q["题型"]):
                    continue
                qid = f"ZZ-{y}-{q['题号']}"
                r = _rec(answers, qid)
                cand.append((y, q, qid, r))
        if not cand:
            continue

        def w_of(row):
            _, _, _, r = row
            w = 1 + (5 if r and r["is_correct"] is False else 0)
            if r is None:
                w += 2
            if weak.get(part):
                w += 2
            return w

        picked = []
        for kind, need in (("单项选择题", 2),
                           ("多项选择题", 1)):
            pool = [r for r in cand if r[1]["题型"] == kind and r not in picked]
            if not pool:
                continue
            picked += _weighted(pool, [w_of(r) for r in pool],
                                min(need, n_per_part - len(picked)), rng)
        picked = picked[:n_per_part]
        for y, q, qid, _ in picked:
            q = dict(q)
            q["id"] = qid
            out.append({"year": y, "题目": q})
    return out


# ------------------------------------------------------------------ 英语
def eng_plan(tier, answers, seed=None):
    from . import english as en
    rng = random.Random(seed)
    mastery = {p["部分"]: p for p in en.part_mastery(tier, answers)}
    picked = []
    for code in ("CLOZE", "READ", "NEW"):
        units = []
        for y in en.years(tier):
            rec = en.paper(tier, y) or {}
            for ps in rec.get("篇目", []):
                if ps.get("部分") != code:
                    continue
                wrong = sum(1 for q in ps.get("小题") or []
                            if (_rec(answers, q.get("id")) or {}).get("is_correct")
                            is False)
                w = 1 + 5 * wrong
                st = mastery.get(code) or {}
                if st.get("正确率") is not None and st["正确率"] < 0.6:
                    w += 2
                units.append((y, ps, w))
        if not units:
            continue
        y, ps, _ = _weighted(units, [u[2] for u in units], 1, rng)[0]
        picked.append({**ps, "year": y})
    if not picked:
        return None
    return {"tier": tier, "year": picked[0].get("year"),
            "篇目": picked,
            "题数": sum(len(p.get("小题") or []) for p in picked)}


# ------------------------------------------------------------------ 408
def data_plan(answers, n=32, seed=None):
    from . import data, diagnose
    rng = random.Random(seed)
    qs = data.questions()
    by_ch = defaultdict(list)
    for q in qs.values():
        ch = data.chapter_of(q.get("主考点"))
        if ch:
            by_ch[ch].append(q)
    mastery = diagnose.mastery_by_chapter(answers)
    chapters = list(by_ch)
    weights = []
    for ch in chapters:
        wrong = sum(1 for q in by_ch[ch]
                    if (_rec(answers, q["id"]) or {}).get("is_correct") is False)
        st = mastery.get(ch) or {}
        w = 1 + 3 * min(wrong, 3)
        if st.get("正确率", st.get("掌握度", 1)) < 0.6:
            w += 2
        weights.append(w)

    # 每章先 1 题（24 章），剩余名额按权重给薄弱章加题
    chosen_ch = _weighted(chapters, weights, min(len(chapters), n), rng)
    items = []

    def q_for(ch):
        pool = by_ch[ch]
        wrong = [q for q in pool
                 if (_rec(answers, q["id"]) or {}).get("is_correct") is False]
        unseen = [q for q in pool if _rec(answers, q["id"]) is None]
        return rng.choice(wrong or unseen or pool)

    used = set()
    for ch in chosen_ch:
        q = q_for(ch)
        used.add(q["id"])
        items.append({"order": len(items) + 1, "id": q["id"],
                      "学科": q.get("学科", ""),
                      "诊断章节名": data.node_name(ch),
                      "难度": q.get("难度", 2)})
    # 剩余名额：给薄弱章再加题（同章可多题），避免与已选重复
    if len(items) < n:
        extra = _weighted(chapters, weights, n, rng)
        for ch in extra:
            if len(items) >= n:
                break
            pool = [q for q in by_ch[ch] if q["id"] not in used]
            if not pool:
                continue
            wrong = [q for q in pool
                     if (_rec(answers, q["id"]) or {}).get("is_correct") is False]
            unseen = [q for q in pool if _rec(answers, q["id"]) is None]
            q = rng.choice(wrong or unseen or pool)
            used.add(q["id"])
            items.append({"order": len(items) + 1, "id": q["id"],
                          "学科": q.get("学科", ""),
                          "诊断章节名": data.node_name(ch),
                          "难度": q.get("难度", 2)})
    return items[:n]
