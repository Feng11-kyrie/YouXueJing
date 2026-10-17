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


def subj_panel(q, subject, prompt_text, material, full, user,
               need_words=120, storage_key=None):
    """
    渲染一道主观题的作答 + 评分区。

    subject : "ZZ"（政治）或 "408"
    prompt_text : 题干
    material    : 材料（政治的材料分析题有；408 一般为空）
    full        : 该题满分
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
        r = rc.score_generic(text, prompt_text, material or "", full,
                             need_words, terms=_terms_of(q, subject))
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
    ui.label("免费评分只评「篇幅 / 分点 / 呼应题干」—— 评不了知识正确性；"
             "要更准的评阅需在顶部接入自己的 API Key。") \
        .classes("t-xs").style("color:#9CA3AF")


def _render(box, r, full, free):
    box.clear()
    with box:
        if r.get("error"):
            ui.label(f'评分失败：{r["error"]}').classes("t-sm") \
                .style("color:#8C2C2C")
            return
        if free:
            ui.label(f'结构体检　{r.get("分数")} / {full:g}').classes(
                "t-lead font-bold")
            ui.label(r.get("来源", "")).classes("t-xs").style("color:#6B7280")
            for it in r.get("分项") or []:
                ui.label(f'　{it["项"]}：{it["得分"]} / {it["满分"]} —— {it["说明"]}') \
                    .classes("t-sm")
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
