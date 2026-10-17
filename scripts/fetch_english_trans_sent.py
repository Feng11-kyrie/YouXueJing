#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
抓取**逐句**参考译文（英语一 46–50 各一句）。

为什么需要
----------
原先只存了"整篇译文"一份（`解答["_参考译文"]`），挂在每一道题下面 ——
于是第 46 题（**一句话**）下面显示的是**整段 5 句的译文**。
用户指出："这个翻译的参考译文是不是不对啊，为什么一道题问题这么短但译文这么长。"

源站的分节页其实**逐句都有译文**：每个 `(46)`…`(50)` 段里有 `【译文】` 块。
本脚本把它们抓下来，按题号存成 `解答["46"]["_参考译文"]`；
`explanation()` 会优先命中按题号的那份，整篇的那份保留作兜底。

英语二整篇就是一题（46），所以逐句=整篇，不需要区分。

用法
----
    .venv/bin/python scripts/fetch_english_trans_sent.py --all --write
"""
import argparse
import json
import os
import re
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from yj import english as en                                    # noqa: E402

SITE = "https://english-exam.lazynote.cn/kaoyan/sections"
SLUG = {"EN1": "english-one", "EN2": "english-two"}
CJK = re.compile(r'[\u4e00-\u9fff]')


# 页面上"译文之后"会出现的小节标题 —— 遇到即停
_STOP = ("SENTENCE INSIGHTS", "句子精讲", "真题高频词", "考点讲解", "结构树",
         "成分与时态", "点击句子进入", "【")


def parse_per_sentence(t):
    """
    从分节页抽 `(46)`…`(50)` 各自的译文。

    页面结构（实测 2024 英语一）：
        (46) They sometimes travel more than sixty miles…
        【意群】… 【调序】…
        【译文】
        大象有时会跋涉六十多英里去寻找食物或水…

    **两种形态**（实测）：
      · 46–49 有 `【译文】` 标记
      · **50 没有标记**，译文直接跟在英文原文后面（"…preferred food.
        研究人员首先确定了…"）—— 所以还要兜底"取该块里第一段中文"
    """
    out = {}
    hits = list(re.finditer(r'[（(]\s*(4[6-9]|50)\s*[)）]', t))
    # **同一题号在页面上会出现多次**（顶部有"各句解析"汇总区、正文分析区），
    # 实测取第一个会拿到汇总区，里面是**整篇译文**（47 题取到 247 字 = 整篇前半段）。
    # 所以先把每个题号的所有候选块收齐，再**优先选含 `【意群】` 的那个** ——
    # 那才是"这一句的精讲块"，里面的 `【译文】` 就是这一句的译文。
    cand = {}
    for i, m in enumerate(hits):
        n = int(m.group(1))
        end = hits[i + 1].start() if i + 1 < len(hits) else len(t)
        cand.setdefault(n, []).append(t[m.end():end])

    for n, blocks in cand.items():
        # 排序：含【意群】的优先；其次含【译文】的
        blocks = sorted(blocks, key=lambda b: (("【意群】" not in b),
                                               ("【译文】" not in b),
                                               len(b)))
        # 用最好的那个块继续解析（下面的步骤针对单块）
        block = blocks[0]
        # ① 优先找 【译文】 标记
        tm = re.search(r'【译文】\s*\n?(.*?)(?=\n【|\Z)', block, re.S)
        raw = tm.group(1) if tm else ""

        # ② 没有标记：取块里第一段"中文占比高"的连续文本
        if not raw:
            for para in block.split("\n"):
                para = para.strip()
                if len(para) < 12:
                    continue
                cjk = len(CJK.findall(para))
                if cjk >= 8 and cjk / max(1, len(para)) > 0.3:
                    raw = para
                    break
        if not raw:
            continue

        # ③ 截掉译文之后的小节标题（它们在页面上紧跟译文出现）
        for k in _STOP:
            j = raw.find(k)
            if j > 0:
                raw = raw[:j]

        # ④ 只保留开头的连续中文句
        txt = " ".join(raw.split())
        keep = []
        for sn in re.split(r'(?<=[。！？；])', txt):
            sn = sn.strip()
            if not sn:
                continue
            cjk = len(CJK.findall(sn))
            if cjk < 3 or cjk / max(1, len(sn)) < 0.25:
                break
            keep.append(sn)
        # ⑤ **长度上限**：考研翻译的单句译文一般 30–80 字。
        # 实测 (47) 取到了 247 字（把整篇译文的前半段也带进来了），
        # 所以按句累积、超过 110 字就停 —— 宁可少取一句，不要混入别的句子。
        txt, total = "", 0
        for sn in keep:
            if total + len(sn) > 110:
                break
            txt += sn
            total += len(sn)
        if len(txt) >= 8:
            out[n] = txt
    return out


def _save(tier, year, mapping):
    p = en.expl_path_of(tier, year)
    rec = {"tier": tier, "年份": str(year), "解答": {}}
    if os.path.exists(p):
        try:
            rec = json.load(open(p, encoding="utf-8"))
        except Exception:                                   # noqa: BLE001
            pass
    ans = rec.setdefault("解答", {})
    for n, txt in mapping.items():
        cur = ans.get(str(n))
        if isinstance(cur, dict):
            cur["_参考译文"] = txt
        else:
            ans[str(n)] = {"_参考译文": txt}
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--tier", choices=list(en.TIERS))
    ap.add_argument("--year")
    a = ap.parse_args()

    jobs = ([(t, y) for t in ("EN1", "EN2") for y in en.years(t)]
            if a.all else [(a.tier, a.year)])

    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        ctx = b.new_context(viewport={"width": 1300, "height": 1000})
        pg = ctx.new_page()
        pg.goto("https://english-exam.lazynote.cn/kaoyan/",
                wait_until="domcontentloaded", timeout=45000)
        pg.wait_for_timeout(1500)
        for tier, year in jobs:
            slug = SLUG[tier]
            trans_n = [int(q["题号"]) for ps in
                       (en.paper(tier, year) or {}).get("篇目", [])
                       if ps["部分"] == "TRANS" for q in ps["小题"]]
            if not trans_n:
                continue
            sec = "section2-part-c" if tier == "EN1" else "section3"
            try:
                pg.goto(f"{SITE}/{year}-{slug}/{sec}/",
                        wait_until="domcontentloaded", timeout=30000)
                pg.wait_for_timeout(2000)
                m = parse_per_sentence(pg.inner_text("body"))
            except Exception as e:                          # noqa: BLE001
                print(f"  {en.TIERS[tier]['简称']} {year}: ❌ {type(e).__name__}")
                continue
            got = {k: v for k, v in m.items() if k in trans_n}
            ok = len(got) == len(trans_n)
            print(f"  {en.TIERS[tier]['简称']} {year}: {len(got)}/{len(trans_n)} 句"
                  + ("" if ok else f"  ← 缺 {sorted(set(trans_n)-set(got))}"))
            if a.write and got:
                _save(tier, year, got)
            time.sleep(1.2)
        b.close()
    print("完成")


if __name__ == "__main__":
    main()
