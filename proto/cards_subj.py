#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
政治 / 408 主观题的**评分面板**（英语那套的做法推广到两科）。

两条路径与英语一致：
  · 「免费评分」—— 本地结构体检（篇幅 / 分点 / 呼应题干），零成本即时
  · 「AI 精评」—— 用**用户自己的 API Key**（BYOK），账单在用户厂商账号

与英语的**真实差别**（必须让用户看到）：
  英语有干净的参考译文/范文，能算"意思对不对"；
  政治分析题没有参考答案、408 的参考答案是带水印的 OCR ——
  所以这两科的免费评分只能评**表述完整度**，评不了知识正确性。
"""
import os
import re

from nicegui import ui

from yj import ai_grade as aig
from yj import rubric_checker as rc
from proto import llm_key
from proto import store_lite as store


def _rubric_for(subject, full):
    """给 AI 精评用的评分档次（按分值粗分三档，避免假装精确）。"""
    if subject == "ZZ":
        return {"名称": f"政治分析题（{full:g} 分）",
                "档次": [("优秀", f"{full*0.8:g}–{full:g}", "观点正确、结合材料、层次清晰、术语准确"),
                         ("合格", f"{full*0.5:g}–{full*0.8:g}", "观点基本正确，结合材料不够充分"),
                         ("不足", f"0–{full*0.5:g}", "观点有偏差或未结合材料")]}
    return {"名称": f"408 综合应用题（{full:g} 分）",
            "档次": [("优秀", f"{full*0.8:g}–{full:g}", "思路完整、关键步骤与结论正确"),
                     ("合格", f"{full*0.5:g}–{full*0.8:g}", "主要步骤正确，细节或结论有误"),
                     ("不足", f"0–{full*0.5:g}", "思路不完整或关键结论错误")]}


def _terms_of(q, subject):
    """抽取"该题该点到的术语"——408 用官方考点名，政治用题干里的实词。"""
    out = []
    if subject == "408":
        for k in ("主考点名", "次考点名"):
            v = q.get(k)
            if isinstance(v, (list, tuple)):
                out.extend([x for x in v if x])
            elif v:
                out.append(v)
    return out


def _free_score(q, subject, text, prompt_text, material, full, need_words,
                reference):
    """
    免费评分走哪条路（顺序不能反）：

      ① **有官方评分标准**（data/408/rubrics/<年>.json）→ 按分档给分
      ② 没有 → 结构体检（篇幅 / 分点 / 考点词）

    为什么不能"一律按评分标准"：408 的评分标准在公开资料里只找到
    2025 年 41 题这一份（见 docs/handover_408_rubrics.md 与
    data/408/rubrics/_coverage.md），其余年份只能退回结构体检。
    两条路的结论**必须能区分**，否则学生会把"体检分"当成"阅卷分"。
    """
    if subject == "408":
        rub = rc.rubric_for(q.get("year"), q.get("题号"))
        if rub:
            r = rc.score_by_rubric(text, rub, full,
                                   reference=reference or "",
                                   terms=_terms_of(q, subject))
            r["依据"] = "按评分标准分档"
            return r
    r = rc.score_generic(text, prompt_text, material or "", full,
                         need_words, terms=_terms_of(q, subject))
    r["依据"] = "结构体检"
    return r


def subj_panel(q, subject, prompt_text, material, full, user,
               need_words=120, storage_key=None, reference=""):
    """
    渲染一道主观题的作答 + 评分区。

    subject : "ZZ"（政治）或 "408"
    prompt_text : 题干
    material    : 材料（政治的材料分析题有；408 一般为空）
    full        : 该题满分
    reference   : 参考答案（有则用于校正"是否答到点子"；没有也能判）
    """
    key = storage_key or q.get("id") or f'{subject}-{q.get("题号")}'
    rb = _rubric_for(subject, full)

    ans = ui.textarea("你的作答（可手写后照录要点，用于获取反馈）") \
        .props("outlined autogrow").classes("w-full")
    ans.style("font-size:15px")
    out = ui.column().classes("w-full gap-1")

    def run_free():
        text = (ans.value or "").strip()
        if len(text) < 5:
            ui.notify("先写一点内容再评分。", color="warning")
            return
        r = _free_score(q, subject, text, prompt_text, material, full,
                        need_words, reference)
        _render(out, r, full, free=True)

    def run_ai():
        k = llm_key.get()
        if not k.get("key"):
            ui.notify("还没有接入 API Key —— 请在页面顶部「接入我的 API Key」里填写。",
                      color="warning")
            return
        text = (ans.value or "").strip()
        if len(text) < 5:
            ui.notify("先写一点内容再评阅。", color="warning")
            return
        out.clear()
        with out:
            ui.label("AI 精评中…（约 10–20 秒）").classes("t-sm muted")
        ui.timer(0.05, lambda: _do_ai(text, k), once=True)

    def _do_ai(text, k):
        try:
            r = aig.grade("WRITING" if subject == "408" else "TRANSLATION",
                          "EN1", prompt_text, text, reference=material,
                          api_key=k["key"], base_url=k["base"] or None,
                          model=k["model"] or None)
        except Exception as e:                              # noqa: BLE001
            r = {"error": f"{type(e).__name__}: {str(e)[:70]}"}
        if not r.get("error"):
            try:
                import json as _json
                store.save_ai_grade(user, key, subject, r.get("档次"),
                                    r.get("位置"),
                                    rc._band_to_score(r.get("档次"), full,
                                                      rb) if hasattr(rc, "_band_to_score") else None,
                                    float(full),
                                    _json.dumps(r, ensure_ascii=False), "ai")
            except Exception:                               # noqa: BLE001
                pass
        _render(out, r, full, free=False)

    with ui.row().classes("items-center gap-2 flex-wrap"):
        ui.button("免费评分", on_click=run_free).props("unelevated dense")
        b = ui.button("AI 精评", on_click=run_ai).props(
            "unelevated dense" if llm_key.get().get("key") else "outline dense disabled")
    # 说明必须分科目：408 判不了代码对不对，政治判不了观点对不对 ——
    # 原来两科共用一句"评不了代码"，政治那边看着莫名其妙。
    tip = ("免费评分：有评分标准的题按「分档」给分，其余做结构体检"
           "（篇幅 / 分点 / 考点词）—— 都评不了算法与代码是否真的正确；"
           "要更准的评阅需在顶部接入自己的 API Key。"
           if subject == "408" else
           "免费评分：按「篇幅 / 分点 / 呼应题干 / 考点词」做结构体检 —— "
           "评不了观点是否正确；要更准的评阅需在顶部接入自己的 API Key。")
    ui.label(tip).classes("t-xs").style("color:#9CA3AF")


def _render(box, r, full, free):
    box.clear()
    with box:
        if r.get("error"):
            ui.label(f'评分失败：{r["error"]}').classes("t-sm") \
                .style("color:#8C2C2C")
            return
        if free:
            # 两种来源必须一眼分得开：分档给分 vs 结构体检。
            # 把"体检分"写成"评分标准分"会让学生误以为是阅卷分数。
            is_rubric = r.get("类型") == "rubric"
            # 标题统一带「免费评分」前缀：按钮叫免费评分，结果却叫结构体检，
            # 用户会以为这是两个功能（政治页就这么被误会过）。
            ui.label(f'免费评分 · {r.get("依据", "结构体检")}　'
                     f'{r.get("分数")} / {full:g}') \
                .classes("t-lead font-bold") \
                .style("color:#17418F" if is_rubric else "")
            ui.label(r.get("来源", "")).classes("t-xs").style("color:#6B7280")
            for it in r.get("分项") or []:
                ui.label(f'　{it["项"]}：{it["得分"]} / {it["满分"]} —— {it["说明"]}') \
                    .classes("t-sm").style("line-height:1.7")
        else:
            ui.label("AI 精评（参考，非官方得分）").classes("t-lead font-bold") \
                .style("color:#B45309")
            if r.get("档次"):
                with ui.row().classes("items-center gap-3"):
                    ui.label(f'档次：{r["档次"]}').classes("t-body font-semibold")
                    if r.get("位置"):
                        ui.label(r["位置"]).classes("t-sm muted")
        for i, p in enumerate(r.get("问题") or [], 1):
            ui.label(f'{i}. {p}').classes("t-sm whitespace-pre-wrap") \
                .style("line-height:1.8")
        if r.get("建议"):
            ui.label(f'建议：{r["建议"]}').classes("t-sm mt-1") \
                .style("color:#17418F")
