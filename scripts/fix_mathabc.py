#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用 mathabc.xyz 的题面/解析，修数学题库里 **OCR 坏掉、渲染失败** 的题。

判定标准：`yj.mathrender.to_html()` 对该题的题干/解析返回 `<code>`（说明
latex2mathml 连修完括号都转不了）。只修这些题，不动正常内容。

用法：
    .venv/bin/python scripts/fix_mathabc.py --scan          # 只列出坏题
    .venv/bin/python scripts/fix_mathabc.py --fix           # 抓 mathabc 并替换
    .venv/bin/python scripts/fix_mathabc.py --fix --tier 一
"""
import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from yj import math as m                                        # noqa: E402
from yj import mathrender as mr                                 # noqa: E402

UA = {"User-Agent": "Mozilla/5.0"}
BASE_URL = "https://mathabc.xyz"


def _get(url):
    return urllib.request.urlopen(
        urllib.request.Request(url, headers=UA), timeout=30
    ).read().decode("utf-8", "ignore")


def _norm(h):
    h = re.sub(r"<script.*?</script>", "", h, flags=re.S)
    h = re.sub(r"<style.*?</style>", "", h, flags=re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", h)).strip()


def _links(tier, year):
    h = _get(f"{BASE_URL}/kaoyan/public/paper/"
             + urllib.parse.quote(f"数学{tier}") + f"/{year}/")
    parts = re.split(r"第(\d{1,2})题", h)
    out = {}
    for i in range(1, len(parts), 2):
        mm = re.search(r'href="(/kaoyan/problem/\d+/?)"', parts[i + 1])
        if mm:
            out[int(parts[i])] = mm.group(1)
    return out


def _detail(path):
    t = _norm(_get(BASE_URL + path))
    a = t.find("📝 题目")
    b = t.find("💡 答案解析")
    stem = t[a + 4:b].strip() if a >= 0 and b > a else ""
    tail = t[b:] if b >= 0 else t
    ans = ""
    ma = re.search(r"\*\*答案\*\*:\s*(.*?)\s*---", tail, re.S)
    if ma:
        ans = ma.group(1).strip()
    me = re.search(r"\*\*解析\*\*:\s*(.*?)(?:\s*📋|\s*方法点评|$)", tail, re.S)
    expl = me.group(1).strip() if me else ""
    if not expl:
        # 有些页面没有 **解析:** 标记，直接是正文 —— 取最后一个"答案解析"
        # 之后、到「详细解题步骤 / 方法点评」之前的内容
        body = tail.split("💡 答案解析")[-1]
        body = re.split(r"📋|方法点评", body)[0].strip()
        expl = body
    return stem, ans, expl


def _bad_fields(tiers):
    bad = []
    for t in tiers:
        for y in m.years(t):
            for q in m.questions(t, y):
                for field in ("题干", "解析"):
                    s = q.get(field) or ""
                    if s and "<code>" in mr.to_html(s):
                        bad.append((t, y, q["题号"], field))
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan", action="store_true")
    ap.add_argument("--fix", action="store_true")
    ap.add_argument("--tier", action="append", choices=["一", "二", "三"])
    a = ap.parse_args()
    tiers = a.tier or ["一", "二", "三"]
    bad = _bad_fields(tiers)
    print("渲染失败的字段：", len(bad))
    for x in bad:
        print("  ", x)
    if not a.fix:
        return

    # 按 (tier, year, n) 聚合，避免同一题抓两次
    targets = sorted({(t, y, n) for t, y, n, _ in bad})
    cache = {}
    fixed = 0
    for t, y, n in targets:
        key = (t, y)
        try:
            if key not in cache:
                cache[key] = _links(t, y)
            link = cache[key].get(int(n))
            if not link:
                print(f"{t} {y} 第{n}题：mathabc 没找到链接")
                continue
            stem, ans, expl = _detail(link)
        except Exception as e:                                  # noqa: BLE001
            print(f"{t} {y} 第{n}题：抓取失败 {type(e).__name__}: {e}")
            continue
        p = os.path.join(BASE, "data", "math", t, f"{y}.json")
        d = json.load(open(p, encoding="utf-8"))
        for q in d["题目"]:
            if int(q["题号"]) != int(n):
                continue
            if len(stem) > 20 and "<code>" in mr.to_html(q.get("题干") or ""):
                q["题干"] = stem
            if ans and ans != "见解析":
                # mathabc 偶尔给「（D）」这种带括号的答案，统一成字母
                mm = re.fullmatch(r"[（(]?\s*([A-D])\s*[)）]?", ans.strip())
                q["答案"] = mm.group(1) if mm else ans
            if len(expl) > 40 and "<code>" in mr.to_html(q.get("解析") or ""):
                q["解析"] = expl
        json.dump(d, open(p, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        fixed += 1
        print(f"{t} {y} 第{n}题：已替换（题干 {len(stem)} / 解析 {len(expl)}）")
    print("处理", fixed, "题")


if __name__ == "__main__":
    main()
