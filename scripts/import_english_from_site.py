#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从懒笔记的 **paper 页**导入英语真题（完形 1–20 + 阅读 21–40）。

为什么换这个源
--------------
原来用 GitHub 仓库的 PDF，实测有两个问题：
  ① **文字层噪声多**：题号里夹空格（`3 7.`、`3 .`）、行首多标点（`. 21.`）、
     两位数被拆开 —— 每漏一种噪声就整年进不来（我修了三轮才到 29/34）
  ② **2021/2022 的完形选项乱序且乱码**（`[C] peaks[ D] fades 1.[A] pauses[B] returs`，
     连拼写都错：returs / altermatively）—— 这段文字层不可救

换成懒笔记的 `/kaoyan/paper/<年>-english-<one|two>/` 页后：
  · 页面把题目渲染成**极规整的结构**（题号单行 + `[ A ]` 选项各占一行）
  · **34/34 套全部拿到 完形 20 + 阅读 20**
  · 拼写正确（pauses / returns / alternatively …）

**教训**：PDF 文字层是"排版抽取"的产物，噪声难免；而**网页正文是结构化的**。
同一个内容如果既有 PDF 又有网页版，优先用网页版 —— 这一条在政治那边也一样
（当时从 PDF 换成 eol 的网页正文，一次补齐了 5 年）。

用法
----
    .venv/bin/python scripts/import_english_from_site.py --scan
    .venv/bin/python scripts/import_english_from_site.py --write
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

SITE = "https://english-exam.lazynote.cn/kaoyan/paper"
SLUG = {"EN1": "english-one", "EN2": "english-two"}


def fetch_paper(tier, year, pg=None, own_browser=True):
    """
    取一套卷的 paper 页正文。**必须先访问 /kaoyan/ 建会话**，
    否则会被限流（表现为整页内容拿不到）。
    """
    t = None
    if pg is not None:
        pg.goto(f"{SITE}/{year}-{SLUG[tier]}/", wait_until="domcontentloaded",
                timeout=45000)
        pg.wait_for_timeout(2200)
        t = pg.inner_text("body")
        return t
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        page = b.new_context(viewport={"width": 1400, "height": 1200}).new_page()
        page.goto("https://english-exam.lazynote.cn/kaoyan/",
                  wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(1500)
        page.goto(f"{SITE}/{year}-{SLUG[tier]}/", wait_until="domcontentloaded",
                  timeout=45000)
        page.wait_for_timeout(2200)
        t = page.inner_text("body")
        b.close()
    return t


def parse_choice_questions(t, lo, hi):
    """
    解析页面上的选择题。形态极规整：

        1.
        [ A ]
        pauses
        [ B ]
        returns
        [ C ]
        peaks
        [ D ]
        fades

    所以按"题号独立成行 → 紧跟四组（[字母], 文本）"来切。
    """
    lines = [l.strip() for l in t.split("\n")]
    out = {}
    i = 0
    while i < len(lines):
        m = re.fullmatch(r'(\d{1,2})\s*[.、]?', lines[i])
        if m and lo <= int(m.group(1)) <= hi:
            n = int(m.group(1))
            opts, j = {}, i + 1
            while j + 1 < len(lines) and len(opts) < 4:
                lm = re.fullmatch(r'\[\s*([A-D])\s*\]', lines[j])
                if lm:
                    opts[lm.group(1)] = lines[j + 1]
                    j += 2
                else:
                    j += 1
            if len(opts) == 4 and n not in out:
                out[n] = opts
            i = j
        else:
            i += 1
    return out


def _subjective_from_pdf(tier, year):
    """
    从 PDF 取**主观题**（翻译 / 写作）。

    **不能按 Section/Part 名称硬匹配** —— 实测两卷的编号与分节都不同：

        英语一 2024：翻译 46–50（`(46)` 标记待译句）、写作 51/52
        英语二 2021：写作是 **47/48**（不是 51/52），
                      且分节标记里出现过两个 `Part B`

    所以改用**通用的 `Directions` 锚点**：PDF 里每道主观题都以
    `NN. Directions:` 或 `NN. Directions :` 开头（NN 是题号），
    取到下一个 Directions 或段末为止，就是要写的内容。

    翻译单独处理：它的待译句以 `(46)` … `(50)` 标在篇章里。
    """
    import glob
    sub = "英语一" if tier == "EN1" else "英语二"
    srcdir = os.environ.get("KYZHENTI", "/tmp/kyzhenti/公共课/英语真题")
    cands = [c for c in glob.glob(f'{srcdir}/{sub}/*{year}*真题.pdf')
             if '带书签' not in c and '无解析' not in c]
    if not cands:
        return []
    from scripts.parse_english import norm_lines
    try:
        lines = norm_lines(cands[0])
    except Exception:                                       # noqa: BLE001
        return []

    out = []
    # ---- 翻译：篇章里的 (46)…(50)（英语二只有 (46)）----
    joined = " ".join(lines)
    lo, hi = (46, 50) if tier == "EN1" else (46, 46)
    hits = [m for m in re.finditer(r'\((4[6-9]|50)\)', joined)
            if lo <= int(m.group(1)) <= hi]
    if not hits and tier == "EN2":
        # 英语二的翻译**不用 (46) 标记**，而是给一整段要求译成中文。
        # 从 `NN. Directions:` 锚点取正文即可（实测 2021：`46. Directions:
        # Translate the following text into Chinese...` + 后面整段英文）。
        for i, l in enumerate(lines):
            m = re.match(r'^\s*(\d{1,2})\s*[.、]\s*Directions?\s*[:：]?', l)
            if not m:
                continue
            seg = " ".join(lines[i + 1:i + 4]).lower()
            if "translate the following" in seg:
                body = " ".join(lines[i + 1:])
                body = re.sub(r'^.*?points\)\s*', '', " ".join(body.split()),
                              count=1)
                body = re.sub(r'\s*Section\s+[A-Z].*$', '', body)
                out.append({"题号": int(m.group(1)), "题干": "翻译下面这段文字",
                            "材料": body[:1600], "题型": "翻译", "分值": 15})
                break
    if hits:
        # 篇章正文 = 第一个标记之前的一段（去掉 Directions）
        head = joined[:hits[0].start()]
        head = re.sub(r'.*?Directions\s*:?', '', head, count=1, flags=re.S)
        head = " ".join(head.split())[-1400:]
        for i, m in enumerate(hits):
            n = int(m.group(1))
            end = hits[i + 1].start() if i + 1 < len(hits) else len(joined)
            sent = " ".join(joined[m.end():end].split())
            # 截到句子结束（PDF 断行会把下一句粘上来）
            sent = re.split(r'(?<=[.?!])\s+(?=[A-Z“"(])', sent)[0].strip()
            if len(sent) < 25:
                sent = " ".join(joined[m.start():m.start() + 340].split())
            out.append({"题号": n, "题干": sent, "材料": head,
                        "题型": "翻译", "分值": 10 if tier == "EN1" else 15})

    # ---- 写作：所有 "NN. Directions" 锚点 ----
    anchors = []
    for i, l in enumerate(lines):
        m = re.match(r'^\s*(\d{1,2})\s*[.、]\s*Directions?\s*[:：]?', l)
        if m:
            anchors.append((i, int(m.group(1))))
    for k, (i, n) in enumerate(anchors):
        end = anchors[k + 1][0] if k + 1 < len(anchors) else len(lines)
        body = " ".join(lines[i + 1:end])
        body = " ".join(body.split())
        # 去掉下一题的开头（如 "Section III"）
        body = re.sub(r'\s*Section\s*[IVX]+.*$', '', body)
        if len(body) < 25:
            continue
        # **必须按关键词区分翻译与写作** —— 实测英语二的翻译篇也以
        # `46. Directions:` 开头，只看锚点会把它误判成写作（出现过 46/47/48
        # 全被标成"写作"）。翻译的指令里一定有 translate/译，
        # 写作的一定有 write/essay/letter。
        low = body.lower()
        # 判据要精确：英语二的翻译指令是
        #   `Translate the following text into Chinese. **Write** your
        #    translation on the ANSWER SHEET.`
        # —— 里面就有 "write"，所以不能用 "write" 判写作（我第一版这么写，
        # 结果英语二的翻译被判成了写作，46/47/48 全标错）。
        is_trans = "translate the following" in low
        is_write = bool(re.search(r'write\s+(an?\s+)?(essay|letter|email|note)',
                                  low))
        if is_trans and not is_write:
            continue          # 已在翻译分支处理
        if not is_write:
            continue          # 既不是翻译也不是写作，跳过
        out.append({"题号": n, "题干": "写作要求",
                    "材料": body[:1800], "题型": "写作",
                    "分值": 10 if "essay based on the chart" in body.lower()
                            or "write an essay" in body.lower() else 10})

    # 按题号排序并去重
    seen, dedup = set(), []
    for it in sorted(out, key=lambda x: x["题号"]):
        if it["题号"] in seen:
            continue
        seen.add(it["题号"])
        dedup.append(it)
    return dedup


def _stem_for(lines, num):
    """
    取某题的**题干**：题号独立成行，下一行就是题干
    （实测 `21.` / `The Romans buried the nails probably for the sake of______.`）。
    """
    for i, l in enumerate(lines):
        if re.fullmatch(rf'{num}\s*[.、]?', l):
            for j in range(i + 1, min(i + 3, len(lines))):
                nx = lines[j]
                if nx and not re.fullmatch(r'\[\s*[A-D]\s*\]', nx):
                    return nx
            return ""
    return ""


def _article_for(lines, marker, first_q):
    """
    取某篇阅读的**文章**：`Text N` 标题之后、该篇第一道题之前。

    **已知局限**：站点页的行同 PDF 一样是**按排版断行**的，右端被截断
    （实测 `they left behind a ` 后面缺内容）。所以文章能读、但不完整。
    要拿完整文章需要从 PDF 重新拼行 —— 那是另一件事，这里先如实保留。
    """
    start = None
    for i, l in enumerate(lines):
        if l.strip() == marker:
            start = i + 1
            break
    if start is None:
        return ""
    end = len(lines)
    for j in range(start, len(lines)):
        if re.fullmatch(rf'{first_q}\s*[.、]?', lines[j]):
            end = j
            break
    return " ".join(x for x in lines[start:end] if x)


def _cloze_body_from_pdf(tier, year):
    """
    从 GitHub 那份 PDF 里取完形文章（含空的位置）。

    为什么要跨来源：站点页的正文里，**空的位置只剩数字**且与选项表隔得很远，
    按"第一个题号之前"切会拿到导航条；PDF 那份文章完整、空以数字标出。
    两者互补：**题目与选项用站点的（干净），文章用 PDF 的（有空位置）**。

    取法：找到 `Section I` 之后、第一个选项行之前的内容，去掉 Directions。
    """
    import glob
    sub = "英语一" if tier == "EN1" else "英语二"
    srcdir = os.environ.get("KYZHENTI", "/tmp/kyzhenti/公共课/英语真题")
    cands = [c for c in glob.glob(f'{srcdir}/{sub}/*{year}*真题.pdf')
             if '带书签' not in c and '无解析' not in c]
    if not cands:
        return ""
    from scripts.parse_english import norm_lines
    try:
        lines = norm_lines(cands[0])
    except Exception:                                       # noqa: BLE001
        return ""
    # 起始：Section I 那行；结束：第一个完形选项行（"1. [A]" / "1. A." / "1. [A] x [B]..."）
    start = None
    for i, l in enumerate(lines):
        if re.match(r'^Section\s*I\s', l):
            start = i + 1
            break
    if start is None:
        return ""
    body = []
    for l in lines[start:]:
        # 去掉 Directions 说明（它不是文章）。
        # 注意 Directions 是**多行**的，续行形如
        #   `C or D on the ANSWER SHEET. (10 points)`，所以还要按关键词过滤。
        if re.match(r'^(Directions|Read\s+the\s+following\s+text)\b', l):
            continue
        if re.search(r'ANSWER\s*SHEET|directions?\s*[:：]|points\)\s*$', l):
            continue
        # 选项区起点
        if re.match(r'^\s*1\s*[.、]\s*\[?[A-D]', l):
            break
        if re.match(r'^\s*Text\s*1\b', l):
            break
        body.append(l)
    return "\n".join(body).strip()


def parse_paper(t, tier, year=None):
    """整套卷 → rec（与 yj.english 的模型一致）。"""
    cz = parse_choice_questions(t, 1, 20)
    rd = parse_choice_questions(t, 21, 40)
    if len(cz) != 20 or len(rd) != 20:
        return None, f"完形 {len(cz)}/20 阅读 {len(rd)}/20"  # 只校验客观题
    rec = {"tier": tier, "篇目": []}
    # 完形：一篇文章 + 20 空。
    # 【文章从 PDF 取，不从本页取】实测本页的正文里**空的位置只剩数字**、
    # 且与题号表分开得很远（第 52–55 行是正文，第 56 行起才是选项表），
    # 直接按"第一个题号行之前"切会拿到导航文字（`懒笔记 首页 真题卷 目录…`）。
    # 而 GitHub 那份 PDF 的完形文章是完整的（空以数字标出），正好互补。
    body = _cloze_body_from_pdf(tier, year)
    rec["篇目"].append({
        "部分": "CLOZE", "材料": body,
        "小题": [{"题号": n, "题干": "", "选项": cz[n]} for n in sorted(cz)]})
    # 阅读：页面上是 21–40 连排，按每 5 题分 4 篇。
    # **文章从本页取**：页面上 `Text N` 标题之后、该篇第一道题之前就是文章
    # （实测 2024 英语一：Text 1 在第 242 行、第 21 题在第 250 行）。
    lines = [l.strip() for l in t.split("\n")]
    order = sorted(rd)
    for k in range(0, 20, 5):
        chunk = order[k:k + 5]
        if len(chunk) < 5:
            break
        first = chunk[0]
        rec["篇目"].append({
            "部分": "READ",
            "材料": _article_for(lines, f"Text {k // 5 + 1}", first),
            "小题": [{"题号": n, "题干": _stem_for(lines, n),
                      "选项": rd[n]} for n in chunk]})
    # 主观题（翻译/写作）：从 PDF 取篇章与要求
    subs_list = _subjective_from_pdf(tier, year)
    for it in subs_list:
        rec["篇目"].append({
            "部分": "TRANS" if it["题型"] == "翻译" else "WRITE",
            "材料": it["材料"], "小题": [it]})
    rec["题目数"] = sum(len(p["小题"]) for p in rec["篇目"])
    extra = f' + 主观 {len(subs_list)} 题' if subs_list else ''
    return rec, f"完整 {rec['题目数']} 题{extra}"


def _clean(obj):
    """去掉孤立代理字符（写盘会抛 surrogates not allowed）"""
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean(v) for v in obj]
    if isinstance(obj, str):
        return obj.encode("utf-8", "ignore").decode("utf-8", "ignore")
    return obj


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan", action="store_true")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright
    os.makedirs(en.ENG_DIR, exist_ok=True)
    ok = bad = 0
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        pg = b.new_context(viewport={"width": 1400, "height": 1200}).new_page()
        pg.goto("https://english-exam.lazynote.cn/kaoyan/",
                wait_until="domcontentloaded", timeout=45000)
        pg.wait_for_timeout(1500)
        for tier in ("EN1", "EN2"):
            for y in range(2010, 2027):
                try:
                    t = fetch_paper(tier, y, pg=pg)
                except Exception as e:                      # noqa: BLE001
                    print(f"  {en.TIERS[tier]['简称']} {y}: ❌ {type(e).__name__}")
                    bad += 1
                    time.sleep(1.0)
                    continue
                rec, msg = parse_paper(t, tier, year=y)
                tag = f"{en.TIERS[tier]['简称']} {y}"
                if rec is None:
                    bad += 1
                    print(f"  {tag}: ⚠️ {msg}")
                else:
                    ok += 1
                    print(f"  {tag}: ✅ {msg}")
                    if args.write and not args.scan:
                        rec = _clean(rec)
                        rec["年份"] = str(y)
                        rec["来源"] = "懒笔记 paper 页（结构化正文）"
                        p = en.path_of(tier, y)
                        tmp = p + ".tmp"
                        with open(tmp, "w", encoding="utf-8") as f:
                            json.dump(rec, f, ensure_ascii=False, indent=1)
                        os.replace(tmp, p)
                time.sleep(1.2)          # 停顿：否则被限流
        b.close()
    print(f"\n完整 {ok} 套 / 失败 {bad} 套")
    for t in ("EN1", "EN2"):
        print(f"  {en.TIERS[t]['简称']}: {en.years(t)}")


if __name__ == "__main__":
    main()
