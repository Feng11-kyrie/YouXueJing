#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
抓取英语**主观题**的参考材料（翻译参考译文 / 写作参考范文）。

为什么单独一个脚本
------------------
客观题的答案是"一个字母"，在分节页上以 `【答案】` 标出；
主观题没有 ABCD，参考材料在**另外两个页面族**上：

    翻译（46–50）：分节页 `section2-part-c` → `【参考译文】`
    写作（51–52 / 英语二 47–48）：独立页 `section3-part-a` / `section3-part-b`
                                  → `【参考范文 · N 词】` … `【参考译文】`

用户要求"所有真题卷上题目都有答案和解析" —— 主观题虽无"答案"，
但必须有**参考译文/范文**，否则学生提交后没有对照。

用法
----
    .venv/bin/python scripts/fetch_english_subjective.py --all --write
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

# 【两卷的章节编号完全不同，必须按卷种探测】
#   英语一：翻译 = section2-part-c（Section II Part C）
#           写作 = section3-part-a / section3-part-b（Section III）
#   英语二：翻译 = section3（Section III 英译汉）
#           写作 = section-iv-part-a / section-iv-part-b（Section IV）
# 硬编码任一单一路径都会漏掉另一卷（实测英语二的写作/翻译全抓不到）。
TRANS_PATHS = {"EN1": ["section2-part-c", "section3"],
               "EN2": ["section3", "section2-part-c"]}
WRITE_PATHS = {"EN1": ["section3-part-a", "section-iv-part-a"],
               "EN2": ["section-iv-part-a", "section3-part-a"]}
WRITE_PATHS2 = {"EN1": ["section3-part-b", "section-iv-part-b"],
                "EN2": ["section-iv-part-b", "section3-part-b"]}


def _pick(ctx, year, slug, candidates):
    """按候选顺序探测，返回第一个 200 的路径名。"""
    for sec in candidates:
        try:
            r = ctx.request.get(f"{SITE}/{year}-{slug}/{sec}/", timeout=20000)
            if r.status == 200:
                return sec
        except Exception:                                   # noqa: BLE001
            pass
    return None


def parse_translation_ref(t):
    """
    取翻译的**参考译文**。

    两种页面形态（实测）：
      · 有整段标记 `【参考译文】`（多数年份）
      · 逐句标记 `【译文】`（英语二 2010/2011），每句后面跟一段英文原文

    所以不能只取第一个标记：逐句形态下第一个 `【译文】` 只是**第 1 句**，
    而且紧跟着英文原文，直接截到下一个 `【` 会把英文混进来。
    做法：收集**所有**译文块，只保留中文占比高的那些，再拼接。
    """
    import re as _re
    CJK = _re.compile(r'[\u4e00-\u9fff]')

    def blocks(marker):
        out = []
        for m in _re.finditer(marker, t):
            seg = t[m.end():]
            nxt = _re.search(r'【[^】]{2,12}】', seg)
            if nxt:
                seg = seg[:nxt.start()]
            seg = " ".join(seg.split())
            if len(seg) >= 8:
                out.append(seg)
        return out

    # 解析文字的特征词 —— 出现就说明"译文"已经结束，后面是讲解
    _STOP = ("本句", "考点", "词汇", "句式", "翻译题", "常考", "意群", "调序",
             "词义", "语法", "结构", "得分点", "本题", "提示", "注意")

    def chinese_only(seg):
        """
        只保留开头的连续中文句：遇到英文原文、或遇到**解析文字**就停。

        实测英语一 2015、英语二 2014/2015/2019/2020 的参考译文块后面
        直接跟着讲解（"…都是阅读理解与翻译题的常考句式；掌握本句的分析方法…"），
        这些也是中文，光按"中文占比"过滤挡不住。
        """
        sents = _re.split(r'(?<=[。！？；])', seg)
        keep = []
        for sn in sents:
            sn = sn.strip()
            if not sn:
                continue
            cjk = len(CJK.findall(sn))
            if cjk < 2 or cjk / max(1, len(sn)) < 0.25:
                break
            if any(k in sn for k in _STOP):
                break
            keep.append(sn)
            if sum(len(x) for x in keep) > 1400:      # 译文本身不会太长
                break
        return "".join(keep)

    # 优先整段标记
    whole = blocks(r'【参考译文】')
    if whole:
        joined = " ".join(whole)
        # 【整段路径也要过滤】实测英语一 2015、英语二 2014/2015/2019/2020 的
        # `【参考译文】` 块里也夹着英文原文，中文占比只有 43–50%。
        if len(CJK.findall(joined)) / max(1, len(joined)) < 0.6:
            joined = chinese_only(joined)
        if len(joined) > 20:
            return joined[:3000]

    # 逐句形态：合并所有中文块
    parts = []
    for seg in blocks(r'【译文】'):
        zh = chinese_only(seg)
        if len(CJK.findall(zh)) >= 3:
            parts.append(zh)
    if parts:
        return " ".join(parts)[:3000]

    # 兜底：裸标记
    i = t.find("参考译文")
    if i >= 0:
        return " ".join(t[i + 4:i + 1200].split())[:3000]
    return ""


def parse_writing_ref(t):
    """
    写作页上的参考范文。

    形态：`【参考范文 · 101 词】` / `写作无唯一标准答案，以下为达标示范`
    / 正文 / `【参考译文】`（范文的中译，不要）
    所以取"参考范文"标记之后、`【参考译文】` 之前的正文。
    """
    m = re.search(r'【参考范文[^】]*】', t)
    if not m:
        return "", ""
    word = ""
    wm = re.search(r'(\d+)\s*词', m.group(0))
    if wm:
        word = wm.group(1)
    body = t[m.end():]
    # 去掉"写作无唯一标准答案…"那一行说明
    body = re.sub(r'^\s*\n?[^\n]*无唯一标准答案[^\n]*\n', '', body)
    em = re.search(r'【参考译文】', body)
    if em:
        body = body[:em.start()]
    body = "\n".join(l.strip() for l in body.split("\n") if l.strip())
    return body[:2500], word


def _save(tier, year, key, payload):
    """把参考材料合并进已有的解析文件（不覆盖已有答案）。"""
    p = en.expl_path_of(tier, year)
    rec = {"tier": tier, "年份": str(year), "解答": {},
           "来源": "懒笔记 english-exam.lazynote.cn"}
    if os.path.exists(p):
        try:
            rec = json.load(open(p, encoding="utf-8"))
        except Exception:                                   # noqa: BLE001
            pass
    rec.setdefault("解答", {})[key] = payload
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
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright
    jobs = []
    if args.all:
        for t in ("EN1", "EN2"):
            for y in en.years(t):
                jobs.append((t, y))
    else:
        jobs = [(args.tier, args.year)]

    with sync_playwright() as pw:
        b = pw.chromium.launch()
        ctx = b.new_context(viewport={"width": 1400, "height": 1100})
        pg = ctx.new_page()
        pg.goto("https://english-exam.lazynote.cn/kaoyan/",
                wait_until="domcontentloaded", timeout=45000)
        pg.wait_for_timeout(1500)

        for tier, year in jobs:
            slug = SLUG[tier]
            tag = f"{en.TIERS[tier]['简称']} {year}"
            # 该卷的写作题号（英语二 47/48，英语一 51/52）
            wr = [int(q["题号"]) for ps in (en.paper(tier, year) or {}).get("篇目", [])
                  if ps["部分"] == "WRITE" for q in ps["小题"]]
            tr = [int(q["题号"]) for ps in (en.paper(tier, year) or {}).get("篇目", [])
                  if ps["部分"] == "TRANS" for q in ps["小题"]]
            got = []

            # ---- 翻译参考译文 ----
            ref = ""
            tsec = _pick(ctx, year, slug, TRANS_PATHS[tier])
            if tsec:
                try:
                    pg.goto(f"{SITE}/{year}-{slug}/{tsec}/",
                            wait_until="domcontentloaded", timeout=30000)
                    pg.wait_for_timeout(2200)
                    ref = parse_translation_ref(pg.inner_text("body"))
                except Exception:                           # noqa: BLE001
                    ref = ""
            if ref:
                if args.write:
                    _save(tier, year, "_参考译文", ref)
                got.append("译文✓")

            # ---- 写作参考范文 ----
            for k, num in enumerate(wr):
                cands = WRITE_PATHS[tier] if k == 0 else WRITE_PATHS2[tier]
                sec = _pick(ctx, year, slug, cands)
                if not sec:
                    continue
                try:
                    pg.goto(f"{SITE}/{year}-{slug}/{sec}/",
                            wait_until="domcontentloaded", timeout=30000)
                    pg.wait_for_timeout(2200)
                    essay, word = parse_writing_ref(pg.inner_text("body"))
                except Exception:                           # noqa: BLE001
                    essay, word = "", ""
                if essay:
                    if args.write:
                        _save(tier, year, str(num),
                              {"参考范文": essay, "词数": word,
                               "来源": "懒笔记（机构整理，仅供参考）"})
                    got.append(f"范文{num}✓")
                time.sleep(0.8)

            print(f"  {tag}: {got or '（无）'}")
            time.sleep(0.8)
        b.close()
    print("完成")


if __name__ == "__main__":
    main()
