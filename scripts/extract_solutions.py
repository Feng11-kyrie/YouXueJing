#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从答案册 PDF 中抽取**综合应用题（41–47）的参考答案**。

为什么需要
----------
单选题有答案（720/720）能自动判分，但 126 道综合应用题一直没有答案 ——
界面上只能写"题库暂无答案，本题不计分"，学生做完大题无从对照。
而 .cache/408/*-answer.pdf 里其实**有完整解答**（实测 2015 年卷第 41 题：
"算法的核心思想是用空间换时间…"），只是格式在不同年份不一样：

    2020 / 2022 / 2023   "41.【解析】…"
    2011–2018            "二、综合应用题" 分节下的 "41. 解答：…"

抽取质量：**这些 PDF 的文字层是 OCR 结果，有噪声**
（如 "IOOBaseT" 实为 100BaseT、"CSMNCD" 实为 CSMA/CD、数字 0/O 与 1/l 常混）。
所以抽取结果标注为"参考答案（OCR 抽取，可能有错字）"，界面必须如实说明，
不能当成逐字准确的官方解析。

输出：data/solutions/<年份>.json  （私有，与答案册同属版权内容，不进公开仓库）

用法：.venv/bin/python scripts/extract_solutions.py
"""
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(BASE, ".cache", "408")
OUT = os.path.join(BASE, "data", "solutions")

# 两种格式：带【解析】的，和"解答："的（后者只在综合应用题分节之内才认）
PAT = re.compile(r'(?<!\d)(4[1-7])\s*[.．、]\s*'
                 r'(?:【\s*(?:解析|解答|答案)\s*】|解\s*析\s*[:：]?|解\s*答\s*[:：])')
SECTION = re.compile(r'二\s*[、,.]\s*综\s*合\s*应\s*用\s*题')


def clean(s: str) -> str:
    """去掉 OCR 噪声与无效字符。

    关键：PDF 抽出的文本里可能有孤立代理项（surrogates）导致 json.dump 抛
    UnicodeEncodeError（实测踩到）。统一走这里做一次清洗。
    """
    s = s.encode("utf-8", "ignore").decode("utf-8", "ignore")
    s = re.sub(r"\S*\.edu\.cn\S*", " ", s)          # 页眉网址
    s = re.sub(r"[\u0000-\u001f]", " ", s)          # 控制字符
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def split_solutions(txt: str) -> dict:
    m = SECTION.search(txt)
    scope = txt[m.end():] if m else txt
    hits = list(PAT.finditer(scope))
    out = {}
    for i, h in enumerate(hits):
        end = hits[i + 1].start() if i + 1 < len(hits) else min(len(scope),
                                                                h.start() + 3500)
        body = clean(scope[h.end():end])
        if len(body) > 80:                # 太短的判为切错
            out[h.group(1)] = body
    return out


def main():
    try:
        from pypdf import PdfReader
    except ImportError:
        print("需要 pypdf：.venv/bin/pip install pypdf", file=sys.stderr)
        sys.exit(1)

    os.makedirs(OUT, exist_ok=True)
    total, years = 0, 0
    scanned = []
    for name in sorted(os.listdir(CACHE)):
        if not name.endswith("-answer.pdf"):
            continue
        year = name[:4]
        try:
            r = PdfReader(os.path.join(CACHE, name))
            txt = "\n".join((p.extract_text() or "") for p in r.pages)
        except Exception as e:                          # noqa: BLE001
            print(f"{year}: 读取失败 {type(e).__name__} —— 跳过")
            continue
        if len(txt) < 2000:
            scanned.append(year)          # 纯扫描件，没有文字层
            continue
        sols = split_solutions(txt)
        if not sols:
            print(f"{year}: 未匹配到综合题解析")
            continue
        with open(os.path.join(OUT, f"{year}.json"), "w", encoding="utf-8") as f:
            json.dump({"年份": year, "来源": "答案册 PDF（OCR 文字层）",
                       "题数": len(sols), "解答": sols},
                      f, ensure_ascii=False, indent=1)
        total += len(sols)
        years += 1
        print(f"{year}: {len(sols)} 道  ->  data/solutions/{year}.json")

    print(f"\n合计 {years} 个年份、{total} 道综合题参考答案")
    if scanned:
        print(f"纯扫描（无文字层，需 OCR 才能取）：{'、'.join(scanned)}")


if __name__ == "__main__":
    main()
