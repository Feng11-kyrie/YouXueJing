#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""严格验证考研政治真题 PDF：下载到唯一临时文件，报页数/字数/题量/真实年份。"""
import os
import re
import subprocess
import sys

BASE = "/Users/fengshuo/P03-优学鲸"
sys.path.insert(0, BASE)


def fetch(url, out):
    # 必须先删旧文件：curl 失败时残留的旧 PDF 会被误判为"下载成功"
    if os.path.exists(out):
        os.remove(out)
    if not url.startswith(("http://", "https://")):
        return 0
    subprocess.run(["curl", "-sL", "--max-time", "90", "-A",
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
                    "-o", out, url])
    return os.path.getsize(out) if os.path.exists(out) else 0


def verify(url, idx):
    tmp = f"/tmp/zzv_{idx}.pdf"
    size = fetch(url, tmp)
    if size < 20000:
        return url, False, f"下载失败/过小 {size}B", None, 0, 0, "", 0
    with open(tmp, "rb") as f:
        if f.read(4) != b"%PDF":
            return url, False, "非 PDF（HTML 页面）", None, 0, 0, "", 0
    try:
        from pypdf import PdfReader
        r = PdfReader(tmp)
        pages = [(p.extract_text() or "") for p in r.pages]
        txt = "\n".join(pages)
    except Exception as e:                                   # noqa: BLE001
        return url, False, f"解析失败 {type(e).__name__}", None, 0, 0, "", 0

    head = txt[:600].replace("\n", " ")
    # 年份：优先标题里的 "20XX 年全国硕士研究生招生考试思想政治理论试题"
    ye = re.findall(r'(19|20)(\d{2})\s*年', txt[:2500])
    cands = [f"{a}{b}" for a, b in ye if 2005 <= int(f"{a}{b}") <= 2027]
    year = None
    tm = re.search(r'(20\d{2})\s*年全国硕士研究生(招生)?考试', txt[:2500])
    if tm:
        year = tm.group(1)
    elif cands:
        year = cands[0]

    sys.path.insert(0, os.path.join(BASE, "scripts"))
    try:
        from scripts.parse_zhengzhi import parse
        items = parse(tmp, None)
    except SystemExit:
        return url, False, "无题型标题（非真题排版）", year, len(pages), len(txt), head, 0
    except Exception as e:                                   # noqa: BLE001
        return url, False, f"解析异常 {type(e).__name__}", year, len(pages), len(txt), head, 0
    c = {}
    for it in items:
        c[it["题型"]] = c.get(it["题型"], 0) + 1
    s_, m_ = c.get("单项选择题", 0), c.get("多项选择题", 0)
    a_ = c.get("材料分析题", c.get("分析题", 0))
    ok = s_ >= 14 and m_ >= 15 and a_ >= 3
    why = f"单选{s_}/多选{m_}/分析{a_}"
    return url, ok, why, year, len(pages), len(txt), head, s_ + m_ + a_


if __name__ == "__main__":
    urls = [u for u in sys.argv[1:] if u.strip()]
    n_ok = 0
    for i, u in enumerate(urls, 1):
        res = verify(u, i)
        url, ok, why, year, np_, nc, head, tot = res
        flag = "OK " if ok else "NG "
        print(f"{flag}[{i}] year={year} pages={np_} chars={nc} {why}")
        print(f"      {url}")
        if ok:
            n_ok += 1
        print(f"      HEAD: {head[:180]}")
    print(f"\n=== ok {n_ok}/{len(urls)} ===")
