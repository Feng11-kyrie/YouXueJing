#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
抓取考研英语真题的**答案与解析**（来源：懒笔记 english-exam.lazynote.cn）。

为什么答案要单独抓、单独存
--------------------------
试题来自 GitHub（干净、无答案），答案来自懒笔记 —— **两个来源、两种格式、
各自会独立变动**。所以答案存成 `<tier>-<年>-解析.json`，与试题文件分开。
政治那边把答案混在题目文件里，被重新解析覆盖过三次，教训已经吃过。

各部分的答案格式**不一样**（实测）
--------------------------------
    阅读（21–40）  ： `21.` … `【答案】\nD\n（细节题）`  —— 带题号
    完形（1–20）   ： `【答案】\n[ D ] Without`           —— **不带题号**，按出现顺序
    新题型（41–45） ： 与阅读同（带题号）
    翻译（46–50）  ： 没有"答案"，只有参考译文 → 存 `参考译文` 字段
    写作（51–52）  ： `section3` 是下载页，没有答案 → 交给 AI 评阅

抓取注意点（踩过）
----------------
  · **必须先访问一次 `/kaoyan/` 建会话，且请求之间停顿约 1 秒**，
    否则出现"整年 0/8 可用"的**假失败**（我第一次探测 2020/2026 就得到 0）。

用法
----
    .venv/bin/python scripts/fetch_english_answers.py --tier EN1 --year 2024 --write
    .venv/bin/python scripts/fetch_english_answers.py --all --write
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
TIER_SLUG = {"EN1": "english-one", "EN2": "english-two"}

# 要抓的节：节名 → (题号区间, 解析函数名)
SECTIONS = [
    ("section1",          (1, 20)),
    ("section2-part-a-1", (21, 25)),
    ("section2-part-a-2", (26, 30)),
    ("section2-part-a-3", (31, 35)),
    ("section2-part-a-4", (36, 40)),
    ("section2-part-b",   (41, 45)),
    ("section2-part-c",   (46, 50)),
]


def _letter(s):
    """全角字母 → 半角大写"""
    out = []
    for c in s:
        o = ord(c)
        if 0xFF21 <= o <= 0xFF3A:
            c = chr(o - 0xFF21 + ord("A"))
        out.append(c.upper())
    return "".join(out)


def parse_blocks_with_exp(t, lo, hi):
    """
    解析分节页，返回 {题号: {"答案": 字母, "解析": 文本}}。

    页面结构（正文区）：
        26.                       ← 题号独立成行
        According to ...          ← 题干
        [ A ] / 选项文本 / ...
        【答案】
        D                          ← 答案字母
        （细节题）                 ← 题型
        【判型】...【定位】...【选项】...   ← 解析主体
        27.                       ← 下一题

    完形的答案行是 `[ D ] Without`（带方括号和首个词），也要兼容。
    """
    lines = [l.strip() for l in t.split("\n")]
    # 找所有"题号独立成行"的位置
    starts = []
    for i, l in enumerate(lines):
        m = re.fullmatch(r'(\d{1,2})\s*[.、]', l)
        if m:
            n = int(m.group(1))
            if lo <= n <= hi:
                starts.append((i, n))
    # 去掉目录里的重复题号：取每个题号**最后一次**出现（正文在目录之后）
    last = {}
    for i, n in starts:
        last[n] = i
    pos = sorted(last.items(), key=lambda kv: kv[1])

    out = {}
    for k, (n, i0) in enumerate(pos):
        i1 = pos[k + 1][1] if k + 1 < len(pos) else len(lines)
        blk = lines[i0:i1]
        # 找答案
        ans = None
        ai = None
        for j, l in enumerate(blk):
            if '【答案】' in l:
                ai = j
                # 同一行就有字母：`【答案】D`
                m = re.search(r'【答案】\s*\[?\s*([A-G])\s*\]?', l)
                if m:
                    ans = m.group(1)
                    break
                # 下一行：`D` 或 `[ D ]` 或 `[ D ] Without`
                if j + 1 < len(blk):
                    m2 = re.match(r'\[?\s*([A-G])\s*\]?', blk[j + 1])
                    if m2:
                        ans = m2.group(1)
                    break
        if ans is None:
            continue
        # 解析 = 答案之后到块尾，去掉表格化的选项重复段（保留正文）
        body = []
        for l in blk[ai + 1:]:
            if not l:
                continue
            body.append(l)
        # 去掉开头的答案行残留（`[ D ] Without` 里的 Without 保留会有用）
        if body:
            body[0] = re.sub(r'^\[?\s*[A-G]\s*\]?\s*', '', body[0]).strip()
            if not body[0]:
                body.pop(0)
        out[n] = {"答案": ans, "解析": "\n".join(body)[:4000]}
    return out


def parse_ordering_blocks_with_exp(t, lo=41, hi=45):
    """
    **段落排序题**的逐题解析（与填空/小标题题不同，它没有 `【答案】`）。

    页面结构（实测 2010 英语一）：
        正确顺序 / 41 / B / → / 42 / F / …          ← 整体正确顺序链
        通读验证…                                     ← 整篇总结
        41.                                           ← 逐题解析开始
        正确段
        B                                             ← 该位正确段
        【引出后一段】
        段 F …
        【辨错段】
        段 C …

    所以：块起点是 `NN.`，答案取 `正确段` 的下一行，
    解析取该块其余内容。
    """
    lines = [l.strip() for l in t.split("\n")]
    starts = [(i, int(m.group(1))) for i, l in enumerate(lines)
              if (m := re.fullmatch(r'(\d{1,2})\s*[.、]', l))
              and lo <= int(m.group(1)) <= hi]
    # 取每个题号的**最后一次**出现（逐题解析在最后，正文前面还有卷面）
    last = {}
    for i, n in starts:
        last[n] = i
    pos = sorted(last.items(), key=lambda kv: kv[1])
    out = {}
    for k, (n, i0) in enumerate(pos):
        i1 = pos[k + 1][1] if k + 1 < len(pos) else len(lines)
        blk = lines[i0:i1]
        ans = None
        ai = None
        for j, l in enumerate(blk):
            if l in ("正确段", "正确答案", "正确项"):
                ai = j
                for k2 in range(j + 1, min(j + 3, len(blk))):
                    m = re.fullmatch(r'[A-G]', blk[k2])
                    if m:
                        ans = blk[k2]
                        ai = k2
                        break
                break
        if ans is None:
            continue
        body = [x for x in blk[ai + 1:] if x]
        out[n] = {"答案": ans, "解析": "\n".join(body)[:4000]}
    return out


def parse_cloze_answers(t, lo=1, hi=20):
    """
    完形：`【答案】\\n[ D ] Without` —— **不带题号**，按出现顺序对应 1..20。

    为什么敢按顺序：实测该页每空的解析块以"空序号"顺序排列，
    且 `【答案】` 标记每空恰好出现一次（数量与 20 相符时才采纳）。
    """
    got = re.findall(r'【答案】\s*\n?\s*\[\s*([A-Da-dＡ-Ｄ])\s*\]', t)
    if len(got) != hi - lo + 1:
        return {}
    return {lo + i: _letter(a) for i, a in enumerate(got)}


def parse_numbered_answers(t, lo, hi):
    """阅读/新题型：`21.` … `【答案】\\nD`（带题号）"""
    out = {}
    for m in re.finditer(r'(?m)^\s*(\d{1,2})\s*[.、]', t):
        n = int(m.group(1))
        if not (lo <= n <= hi) or n in out:
            continue
        seg = t[m.start():m.start() + 2500]
        am = re.search(r'【答案】\s*\n?\s*\[?\s*([A-Da-dＡ-Ｄ])\s*\]?', seg)
        if am:
            out[n] = _letter(am.group(1))
    return out


def parse_partb_answers(t, lo=41, hi=45):
    """
    新题型 Part B 的答案。

    实测形态：页面上按题号顺序排出 5 段，每段是
        41.
        (41)____
        【答案】
        [ E ]
        （题型判定…）
    答案标记 `【答案】\n[ X ]` **不带题号**，所以按出现顺序对应 41–45。
    数量必须恰好等于 5 才采纳（与完形同一策略：宁可不要，不要错配）。
    """
    got = re.findall(r'【答案】\s*\n?\s*\[\s*([A-Ga-g])\s*\]', t)
    if len(got) != hi - lo + 1:
        return {}
    return {lo + i: _letter(a) for i, a in enumerate(got)}


def parse_en1_partb_ordering(t):
    """
    **英语一 Part B：段落排序**的答案。

    英语一的 Part B 与英语二不同 —— 它是"把 7 段打乱重排"，
    答案不是逐题的 `【答案】\n[ E ]`，而是**一整条正确顺序链**。
    实测两种呈现形态，都要支持：

      ① 干净的"正确顺序"块（逐行交替）：
             正确顺序
             41
             B
             →
             42
             F
             ...
      ② FAQ 里的一句话：`41=B → 42=F → 43=D → 44=G → 预给E`

    **注意"预给"**：排序题有一段是卷面已给的（如 2010 的 E 在 45 位），
    那一位不需要作答、链上写成 `预给E`。若漏掉它，只拿到 4 个答案。
    """
    lines = [l.strip() for l in t.split("\n")]
    out = {}
    for i, l in enumerate(lines):
        if l == "正确顺序":
            j = i + 1
            while j < len(lines):
                m = re.fullmatch(r'(4[1-5])', lines[j])
                if m and j + 1 < len(lines) and re.fullmatch(r'[A-G]', lines[j + 1]):
                    out[int(m.group(1))] = lines[j + 1]
                    j += 2
                    if j < len(lines) and lines[j] == "→":
                        j += 1
                elif re.match(r'^预给\s*[A-G]', lines[j]) or l == "预给":
                    break
                else:
                    break
            if len(out) >= 4:
                break
    if len(out) >= 4:
        return _fill_pregiven(t, out)
    # 形态二：41=B → 42=F → … → 预给E
    for m in re.finditer(r'(4[1-5])\s*=\s*([A-G])', t):
        out.setdefault(int(m.group(1)), m.group(2))
    if out:
        return _fill_pregiven(t, out)
    return out


def _fill_pregiven(t, got):
    """
    排序题有一段是**卷面已给**的（2010 的 E 落在第 45 位），
    答案链上写成 `预给E`。这一位学生不需要作答，但它确实在正确顺序里，
    所以**要补上**——否则 UI 里会显示"暂无答案"，看起来像我们漏了。

    补法：把 `预给X` 赋给链上缺失的那个位置号（缺失位置通常是最后一位）。
    """
    m = re.search(r'预给\s*([A-G])', t)
    if not m:
        return got
    letter = m.group(1)
    if letter in got.values():
        return got
    miss = [n for n in range(41, 46) if n not in got]
    if len(miss) == 1:
        got = dict(got)
        got[miss[0]] = letter
    return got


def parse_reference(t):
    """
    翻译：没有"答案"，只有**参考译文**。抽出来存 `参考译文` 字段，
    供 AI 评阅时作对照（yj/ai_grade.py 的 reference 参数）。
    """
    m = re.search(r'【参考译文】\s*\n?(.{20,3000}?)(?=\n【|\Z)', t, re.S)
    if m:
        return " ".join(m.group(1).split())[:2000]
    # 没有显式标记时，取"译文"段落做兜底
    m = re.search(r'【译文】\s*\n?(.{20,3000}?)(?=\n【|\Z)', t, re.S)
    return " ".join(m.group(1).split())[:2000] if m else ""


def fetch(tier, year, verbose=True, write=False):
    """
    抓一套卷的答案。返回 dict {题号: {答案/参考译文, 来源}}。

    write=True 时**每抓完一节就落盘** —— 全量抓 34 套要几十分钟，
    中途网络抖动不能从零重来（政治那边就是"按年份增量写盘"救回来的）。
    """
    from playwright.sync_api import sync_playwright
    slug = TIER_SLUG[tier]
    out = {}
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        pg = b.new_context(viewport={"width": 1400, "height": 1200}).new_page()
        # 建会话（不做这一步会大面积假失败）
        pg.goto("https://english-exam.lazynote.cn/kaoyan/",
                wait_until="domcontentloaded", timeout=45000)
        pg.wait_for_timeout(1500)

        # 【2026 的分节路径不一样】站点把四篇阅读合并成一页 `section2-part-a`
        # （含 21–40），而 `section2-part-a-1` 是 404。
        #
        # 关键：**必须先用 HTTP 探测状态码，不能靠 goto 失败来发现** ——
        # goto 一个 404 会触发 "Download is starting"，之后**同一个 page
        # 就卡在下载状态**，后续 goto 全部失败（实测：回退分支里再 goto
        # 合并页也报错，而我单独新建 page 访问同一个 URL 是 200）。
        secs = list(SECTIONS)
        try:
            r = pg.context.request.get(f"{SITE}/{year}-{slug}/section2-part-a-1/",
                                       timeout=20000)
            if r.status != 200:
                # 实测 2026：`section2-part-a` 就是 **21–25**（只是省了 `-1` 后缀），
                # a-2=26–30、a-3=31–35、a-4=36–40 —— 所以只替换第一份、范围不变。
                secs = [("section2-part-a", (21, 25))
                        if x[0] == "section2-part-a-1" else x for x in secs]
                if verbose:
                    print(f"      （part-a-1 状态 {r.status} → 改用合并页 part-a）")
        except Exception:                               # noqa: BLE001
            pass

        for sec, (lo, hi) in secs:
            partb_ordering = False
            url = f"{SITE}/{year}-{slug}/{sec}/"
            try:
                pg.goto(url, wait_until="domcontentloaded", timeout=45000)
                pg.wait_for_timeout(1400)
                t = pg.inner_text("body")
            except Exception as e:                          # noqa: BLE001
                if verbose:
                    print(f"      {sec}: 打开失败 {type(e).__name__}")
                time.sleep(1.0)
                continue
            if len(t) < 2000:
                time.sleep(1.0)
                continue
            if sec == "section1":
                got = parse_cloze_answers(t, lo, hi)
            elif sec == "section2-part-b":
                # 【Part B 有三种题型，答案格式也随之不同】
                #   · 句中填空 / 小标题匹配：逐题 `【答案】\n[ C ]`（多数年份）
                #   · 段落排序：一整条正确顺序链（`正确顺序` 块 或 `41=B → …`）
                # 我最初按"英语一一定是排序"写死，结果只有排序那几年成功，
                # 其余年份明明有 `【答案】` 却拿不到 —— 所以**两种都试、取多的**。
                # 【变量名别用 b】这里原本写成 `b = parse_en1_partb_ordering(t)`，
                # 把 fetch() 里的浏览器对象 `b = pw.chromium.launch()` 覆盖了，
                # 导致函数末尾 `b.close()` 抛 AttributeError: 'dict' object has no attribute 'close'。
                g1 = parse_partb_answers(t, lo, hi)
                g2 = parse_en1_partb_ordering(t)
                if len(g2) > len(g1):
                    got = g2
                    partb_ordering = True      # 排序题：解析结构不同
                else:
                    got = g1
            elif sec == "section2-part-c":
                ref = parse_reference(t)
                if ref:
                    got = {"_参考译文": ref}
                else:
                    got = {}
            else:
                got = parse_numbered_answers(t, lo, hi)
            # 【补解析】分节页上每题都有完整解析（【判型】【定位】【选项】…），
            # 原先只存了答案字母、解析全丢 —— 用户要求"题目都有答案和解析"。
            # 注意 got 是 {题号(int): 字母}，解析单独放 exps，
            # 写进 out 时再合并（结构不同，不能就地改 got）。
            exps = {}
            if got and sec != "section2-part-c":
                try:
                    if sec == "section2-part-b" and partb_ordering:
                        exps = parse_ordering_blocks_with_exp(t, lo, hi)
                    else:
                        exps = parse_blocks_with_exp(t, lo, hi)
                except Exception:                       # noqa: BLE001
                    exps = {}
            if got:
                if "_参考译文" in got:
                    out["_参考译文"] = got["_参考译文"]
                else:
                    for n, a in got.items():
                        rec = {"答案": a, "来源": "懒笔记"}
                        e2 = exps.get(int(n)) or {}
                        if e2.get("解析"):
                            rec["解析"] = e2["解析"]
                        out[str(n)] = rec
            if verbose:
                n = 1 if "_参考译文" in got else len(got)
                print(f"      {sec:<18} {n:>2} 条")
            if write:
                _save(tier, year, out)
            time.sleep(1.0)          # 必须停顿：否则触发限流、整页拿不到
        b.close()
    return out


def _save(tier, year, got):
    """
    原子写盘（中断不会留半个文件）。

    **必须与已有文件合并，不能整体覆盖** —— 实测踩到：
    主观题脚本刚写入的 `参考范文` / `_参考译文`，被本脚本下一次
    `--all` 运行时**整个覆盖掉**（参考范文从 17 条变回 0）。
    政治那边也因为"重新解析覆盖"丢过三次答案，同一个教训。

    合并规则：新抓到的答案/解析覆盖同题号的旧值；
    其它键（如 `_参考译文`、`参考范文`、`词数`）原样保留。
    """
    if not got:
        return
    p0 = en.expl_path_of(tier, year)
    old = {}
    if os.path.exists(p0):
        try:
            old = (json.load(open(p0, encoding="utf-8")).get("解答") or {})
        except Exception:                                   # noqa: BLE001
            old = {}
    merged = dict(old)
    for k, v in got.items():
        if isinstance(v, dict) and isinstance(merged.get(k), dict):
            merged[k] = {**merged[k], **v}
        else:
            merged[k] = v
    rec = {"tier": tier, "年份": str(year), "解答": merged,
           "来源": "懒笔记 english-exam.lazynote.cn"}
    p = en.expl_path_of(tier, year)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", choices=list(en.TIERS))
    ap.add_argument("--year")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    os.makedirs(en.ENG_DIR, exist_ok=True)
    jobs = []
    if args.all:
        for t in ("EN1", "EN2"):
            for y in en.years(t):
                jobs.append((t, y))
    else:
        jobs = [(args.tier, args.year)]

    for tier, year in jobs:
        print(f"  {en.TIERS[tier]['简称']} {year}:")
        got = fetch(tier, year, write=args.write)
        n_ans = sum(1 for k, v in got.items() if k != "_参考译文")
        print(f"    → 答案 {n_ans} 条"
              + ("，参考译文 ✓" if "_参考译文" in got else ""))
        if args.write and got:
            print(f"    已写入 {os.path.relpath(en.expl_path_of(tier, year), BASE)}")


if __name__ == "__main__":
    main()
