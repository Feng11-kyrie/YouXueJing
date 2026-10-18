#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数学考点速记（「我的薄弱点」用）：按弱考点生成一份速记 + 配套真题。

与 408 的六 Agent 讲义不同，数学这里只做**一个考点一页速记**：
  · 核心公式/方法  · 常见考法  · 易错点
素材用该考点下最近的 3 道真题（题干 + 解析），要求模型只依据这些题提炼，
不编造定理。生成结果落盘到 data/math/notes/，同一考点不重复花钱。
"""
import datetime
import hashlib
import json
import os
import re

from yj import llm
from yj import math as m

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NOTES = os.path.join(BASE, "data", "math", "notes")


def _path(tier, point):
    h = hashlib.md5(point.encode("utf-8")).hexdigest()[:12]
    return os.path.join(NOTES, f"{tier}-{h}.json")


def related(tier, point, n=4):
    """该考点下的真题：选择题优先、近年优先。"""
    qs = [dict(q) for q in (m.points(tier).get(point) or [])]
    qs.sort(key=lambda q: (q.get("题型") != "单项选择题",
                           -int(q["_year"]), int(q["题号"])))
    return qs[:n]


def cached(tier, point):
    p = _path(tier, point)
    if not os.path.exists(p):
        return None
    try:
        rec = json.load(open(p, encoding="utf-8"))
        return rec if rec.get("文本") else None
    except Exception:                                       # noqa: BLE001
        return None


def _clip(s, n=900):
    s = re.sub(r"\s+", " ", s or "").strip()
    return s[:n] + ("…" if len(s) > n else "")


def generate(tier, point, force=False):
    """生成（或读缓存）一个考点的速记。"""
    if not force:
        rec = cached(tier, point)
        if rec:
            rec["来源"] = "cache"
            return rec
    qs = related(tier, point, 3)
    if not qs:
        return {"error": "这个考点下没有真题，无法生成。"}
    material = "\n\n".join(
        f"【{q['_year']} 年第 {q['题号']} 题 · {q['题型']}】\n"
        f"题干：{_clip(q.get('题干'), 700)}\n"
        f"解析：{_clip(q.get('解析'), 900)}" for q in qs)
    prompt = f"""你是考研数学辅导老师。请为考点「{point}」写一份考前速记。

只依据下面 3 道真题提炼，不要编造题目里没有的定理/公式/结论。
用 Markdown 输出，分三节：
## 核心公式与方法
## 常见考法
## 易错点
每节 2–5 条，总共不超过 600 字；公式用 $...$ 包裹。

{material}
"""
    r = llm.complete("math_note", prompt, use_cache=True)
    text = (r.get("text") or "").strip()
    if not text:
        return {"error": "LLM 没有返回内容（检查服务端 Key/额度）。"}
    rec = {"考点": point, "卷种": tier, "文本": text,
           "来源": r.get("source", "llm"),
           "生成时间": datetime.datetime.now().isoformat(timespec="seconds"),
           "题目": [f'{q["_year"]}-{q["题号"]}' for q in qs]}
    os.makedirs(NOTES, exist_ok=True)
    json.dump(rec, open(_path(tier, point), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    return rec
