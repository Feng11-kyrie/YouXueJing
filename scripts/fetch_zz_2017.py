#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
重建 **2017 年考研政治真题**（真实 2017 卷，2016 年 12 月那场）。

为什么要单独一个脚本
--------------------
原来 `data/zhengzhi/2017.json` 里存的其实是 **2018 年卷**（与 `2018.json` 题干
相似度 0.94；第 16 题还写着"2017 年 12 月 1 日中国共产党与世界政党高层对话会"，
那是 2018 卷时事）。也就是说：2017 年卷之前是**缺的**，而且同一个年度的答题
记录会被混在 2018 卷上。

来源（考研网 kaoyan.cn，文字型 PDF，含"参考答案及解析"）：
    https://static.kaoyan.cn/file/question/2024/12/02/75cb4091a5f55d9b2a09fb7f37f58224.pdf

这份 PDF 的排版与 `parse_zhengzhi` 的默认假设不同：
  · 没有"一、单项选择题"这类大标题，只有一句"下列各题的备选答案中，只有一项..."
  · 题干、选项会被页眉页脚（"2017年…试题"、"第 N 页 共 15 页"）打断
  · 文末"参考答案及解析"里每题是 `N.【答案】X` + `完整解析：…`
所以流程是：先清洗、补上三个大题标题 → 交给现有解析器 → 再从答案区取答案与解析。

用法：
    .venv/bin/python scripts/fetch_zz_2017.py            # 用缓存 PDF
    .venv/bin/python scripts/fetch_zz_2017.py --download # 重新下载
"""
import argparse
import json
import os
import re
import sys

import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "scripts"))

from scripts.parse_english import norm_lines                     # noqa: E402
import parse_zhengzhi as pz                                      # noqa: E402

URL = ("https://static.kaoyan.cn/file/question/2024/12/02/"
       "75cb4091a5f55d9b2a09fb7f37f58224.pdf")
CACHE = os.path.join(BASE, ".cache", "zhengzhi", "2017-real.pdf")
DEST = os.path.join(BASE, "data", "zhengzhi")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def fetch(force=False):
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    if force or not os.path.exists(CACHE) or os.path.getsize(CACHE) < 20000:
        req = urllib.request.Request(URL, headers={"User-Agent": UA,
                                                   "Referer": "https://www.kaoyan.cn/"})
        with urllib.request.urlopen(req, timeout=90) as r, open(CACHE, "wb") as f:
            f.write(r.read())
    return CACHE


def clean_lines(path):
    out = []
    for ln in norm_lines(path):
        if re.fullmatch(r"第\s*\d+\s*页\s*共\s*15\s*页", ln):
            continue
        if ln.strip().startswith("2017年全国硕士研究生招生考试试题"):
            continue
        out.append(ln)
    return out


def build_paper_text(lines):
    """补上三个大题标题（解析器靠标题切段），并在答案区前截断。"""
    ans_start = next(i for i, l in enumerate(lines) if "参考答案及解析" in l)
    ana_start = next(i for i, l in enumerate(lines)
                     if l.strip() == "根据材料，回答对应的问题。")
    q1 = next(i for i, l in enumerate(lines) if re.match(r"^\s*1\s*[.．、]", l))
    q17 = next(i for i, l in enumerate(lines) if re.match(r"^\s*17\s*[.．、]", l))
    out = []
    for i, l in enumerate(lines[:ans_start]):
        if i == q1:
            out.append("一、单项选择题")
        if i == q17:
            out.append("二、多项选择题")
        if i == ana_start:
            out.append("三、材料分析题")
        out.append(l)
    return "\n".join(out)


def extract_answers(lines):
    """
    从"参考答案及解析"区取 → ({题号: 答案}, {题号: 解析文本})。

    格式：`N.【答案】X`，下一行起是 `完整解析：…`，直到下一个答案行。
    """
    start = next(i for i, l in enumerate(lines) if "参考答案及解析" in l)
    seg = lines[start:]
    marks = []
    for i, l in enumerate(seg):
        m = re.match(r"^(\d{1,2})\s*[.．、]\s*【答案】\s*([A-D]{1,4})", l)
        if m and 1 <= int(m.group(1)) <= 33:
            marks.append((i, int(m.group(1)), m.group(2)))
    answers, expl = {}, {}
    for k, (i, n, a) in enumerate(marks):
        answers[n] = a
        end = marks[k + 1][0] if k + 1 < len(marks) else len(seg)
        body = "\n".join(seg[i + 1:end]).strip()
        body = re.sub(r"^完整解析[：:]\s*", "", body).strip()
        expl[n] = body
    return answers, expl


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--download", action="store_true", help="强制重新下载")
    a = ap.parse_args()

    path = fetch(a.download)
    lines = clean_lines(path)
    print(f"· 取行 {len(lines)} 行")
    text_path = os.path.join(os.path.dirname(CACHE), "2017-real-paper.txt")
    open(text_path, "w", encoding="utf-8").write(build_paper_text(lines))

    items = pz.parse(text_path, "2017")
    answers, expl = extract_answers(lines)
    print(f"· 解析出 {len(items)} 道题；答案 {len(answers)} 条；解析 {len(expl)} 条")
    if len(items) != 38 or len(answers) != 33:
        print("  ⚠️ 数量不对，先别写库（应为 38 题 / 33 个客观题答案）")
        return 1

    for it in items:
        n = int(it["题号"])
        if it["题型"] != "材料分析题":
            it["答案"] = answers.get(n)
            it["答案来源"] = "考研网（kaoyan.cn）2017 真题文档【答案】原文"
            it["待投票"] = not it["答案"]
    json.dump({"年份": "2017", "题数": len(items), "题目": items},
              open(os.path.join(DEST, "2017.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    sol = {str(n): {"文本": t, "来源": "题源抽取（考研网）"}
           for n, t in expl.items()}
    json.dump({"年份": "2017", "题数": 38, "解答": sol},
              open(os.path.join(DEST, "2017-解析.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"· 已写入 {os.path.relpath(DEST, BASE)}/2017.json 与 2017-解析.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
