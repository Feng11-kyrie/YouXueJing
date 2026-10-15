#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量导入考研英语真题（**只导入"完整解析成功"的卷**）。

设计原则：**宁可少导，不要导半套**
--------------------------------
英语卷的文字层排版在 2010–2026 之间变过好几次（实测至少 3 种完形排版），
所以本脚本对每套卷做**完整性校验**：

    客观题（完形 20 + 阅读 20）必须**全部**解析出题干与四个选项

不满足就**跳过并报告原因**，而不是把残缺的数据写进库 ——
残缺数据在界面上看起来"能用"，但学生做题时会遇到空选项，
比"这一年暂时没有"更糟（这是本项目反复踩过的坑：宁可如实说没有）。

已知的排版差异（实测）
--------------------
  完形 1–20：
    · 新格式（2023+）：`1. A. Through` 竖排 A 栏 + 后接 B/C/D 三栏
    · 旧格式（2010–2022）：`1. [A] when` 竖排 + **B/C/D 挤在同一行**
                            `[B] why [C] how [D] what`
      而且 A 栏与 B/C/D 之间可能隔着 `Part A` / `Directions:` 几行 ——
      所以不能按固定偏移取，要向下搜索。
  阅读 21–40：格式稳定（题干 + A–D 各一行），个别年份少 1–2 题
      （题干跨行被合并所致），所以也纳入完整性校验。

用法
----
    .venv/bin/python scripts/import_english.py --scan           # 只体检，不写
    .venv/bin/python scripts/import_english.py --write          # 导入完整的卷
    .venv/bin/python scripts/import_english.py --write --years 2023-2026
"""
import argparse
import glob
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from yj import english as en                                    # noqa: E402
from scripts.parse_english import (norm_lines, split_parts_by_content,  # noqa: E402
                                   parse_choice_block)

SRC = os.environ.get("KYZHENTI", "/tmp/kyzhenti/公共课/英语真题")

# 题号内/点号前都可能夹空格（实测 `3 . [A] careless`、`3 7. It can...`）
# 行首可能有个孤立标点（实测 `. 21. Quinn...`）
NUM = r'[.、,，]?\s*(\d(?:\s?\d)?)\s*[.、]\s*'
NEW_A = re.compile(r'^' + NUM + r'([A-D])\.\s*(.*)$')
OLD_A = re.compile(r'^' + NUM + r'\[([A-D])\]\s*(.*)$')
BRACKET_ROW = re.compile(r'\[([A-D])\]\s*([^\[]*)')


def parse_cloze(lines, lo=1, hi=20):
    """
    完形解析 —— **兼容两种实测排版**（见模块开头）。

    返回 (题目列表, 文章正文, 格式名)。文章用 A 栏起点之前的行拼成。
    """
    new = [(i, int(m.group(1)), m.group(3).strip()) for i, l in enumerate(lines)
           for m in [NEW_A.match(l)] if m and lo <= int(re.sub(r'\s+','',m.group(1))) <= hi]
    old = [(i, int(m.group(1)), m.group(3).strip()) for i, l in enumerate(lines)
           for m in [OLD_A.match(l)] if m and lo <= int(re.sub(r'\s+','',m.group(1))) <= hi]
    if new and not old:
        fmt, rows = "new", new
    elif old and not new:
        fmt, rows = "old", old
    elif new and old:
        fmt, rows = ("new", new) if len(new) >= len(old) else ("old", old)
    else:
        return [], "", "none"

    nums = [n for _, n, _ in rows]
    col = {"A": {n: t for _, n, t in rows}}
    a0 = rows[0][0]

    if fmt == "new":
        width = len(rows)
        for k, L in enumerate("BCD"):
            base = a0 + width * (k + 1)
            for idx, n in enumerate(nums):
                j = base + idx
                if j >= len(lines):
                    continue
                m = re.match(r'^([A-D])\.\s*(.*)$', lines[j])
                if m:
                    col.setdefault(L, {})[n] = m.group(2).strip()
    else:
        # 旧格式：B/C/D 挤在同一行；A 栏结束后**向下搜索**（中间可能隔着
        # "Part A"/"Directions:" 等行，实测少取 3 行会让 20 题只齐 16 题）
        got = 0
        for j in range(a0 + len(nums), len(lines)):
            if got >= len(nums):
                break
            l = lines[j]
            if not (re.search(r'\[B\]', l) and re.search(r'\[D\]', l)):
                continue
            d = {L: t.strip() for L, t in BRACKET_ROW.findall(l)}
            if set(d) >= {"B", "C", "D"}:
                n = nums[got]
                for L in "BCD":
                    col.setdefault(L, {})[n] = d[L]
                got += 1

    qs = [{"题号": n, "题干": "",
           "选项": {L: col.get(L, {}).get(n, "") for L in "ABCD"}}
          for n in nums]
    return qs, "\n".join(lines[:a0]), fmt



# ---------------------------------------------------------------------------
# 另外两种实测到的排版（与上面的"竖排A栏 + 后接B/C/D栏"并列）
# ---------------------------------------------------------------------------
# 形态②「四选项同行」：一整行里把 A–D 全排出来
#     1. [A] that [B] when [C] why [D] where
# 实测：英语一 2014/2016/2017/2018/2019、英语二 2012/2014/2016/2017/2019/2020
# 形态③「B/C/D 同行但无 A 标记」：
#     A 竖排 '1. [A] xxx'，B/C/D 在后续行 'B. resolve C. discuss D. ignore'
# 实测：英语二 2018
_TOK = re.compile(r'\[([A-D])\]|(?<![A-Za-z])([A-D])[.、)]')


def _tokens(s):
    return [m.group(1) or m.group(2) for m in _TOK.finditer(s)]


def _strip_tokens(s):
    return [t.strip() for t in _TOK.split(s) if t and t.strip()]


def parse_cloze_rowwise(lines, lo=1, hi=20):
    """形态②：一行里 A–D 齐全。"""
    out = {}
    for l in lines:
        m = re.match(r'^' + NUM + r'(.+)$', l)
        if not m:
            continue
        n = int(re.sub(r'\s+', '', m.group(1)))
        if not (lo <= n <= hi):
            continue
        if _tokens(m.group(2))[:4] != ['A', 'B', 'C', 'D']:
            continue
        vals = _strip_tokens(m.group(2))
        if len(vals) >= 4:
            out[n] = {L: v for L, v in zip('ABCD', vals[:4])}
    return out


def parse_cloze_bcd_line(lines, lo=1, hi=20):
    """形态③：A 竖排，B/C/D 同行（无 A 标记）。"""
    arows = []
    for i, l in enumerate(lines):
        m = re.match(r'^' + NUM + r'([A-D])[.、)]?\s*(.+)$', l)
        if m and m.group(2) == 'A' and lo <= int(re.sub(r'\s+', '', m.group(1))) <= hi:
            arows.append((i, int(re.sub(r'\s+', '', m.group(1))),
                          m.group(3).strip()))
    if len(arows) < hi - lo + 1:
        return {}
    out = {n: {'A': t} for _, n, t in arows}
    got = 0
    for j in range(arows[0][0] + len(arows), len(lines)):
        if got >= len(arows):
            break
        l = lines[j]
        if not re.match(r'^\s*B[.、)]', l):
            continue
        if _tokens(l)[:3] == ['B', 'C', 'D']:
            vals = _strip_tokens(l)
            if len(vals) >= 3:
                n = arows[got][1]
                for L, v in zip('BCD', vals[:3]):
                    out[n][L] = v
                got += 1
    return {n: v for n, v in out.items() if len(v) == 4}


def parse_cloze_best(lines, lo=1, hi=20):
    """
    依次尝试四种实测排版，**取能凑齐最多题的那个**。

    为什么不在解析前先"判定格式"：我试过按行特征分类，结果各形态的计数
    互相混杂（同一年既像 A 又像 B），判定不可靠。**直接看哪种能产出
    "20 题 × 4 选项"更实在** —— 产出是唯一的硬标准。

    返回 (题目列表, 文章正文, 形态名, 完整题数)
    """
    cands = []
    for name, fn in (("newcols", lambda: parse_cloze(lines, lo, hi)),
                     ("rowwise", lambda: parse_cloze_rowwise(lines, lo, hi)),
                     ("bcdline", lambda: parse_cloze_bcd_line(lines, lo, hi))):
        try:
            r = fn()
        except Exception:                                   # noqa: BLE001
            r = ({}, "", name) if name != "rowwise" else {}
        if name == "newcols":
            qs, body, fmt = r
            d = {q["题号"]: q["选项"] for q in qs}
        else:
            d, body, fmt = r, "", name
        full = sum(1 for v in d.values() if len(v) == 4)
        cands.append((full, name, d, body))
    full, name, d, body = max(cands, key=lambda x: x[0])
    qs = [{"题号": n, "题干": "",
           "选项": {L: (d.get(n) or {}).get(L, "") for L in "ABCD"}}
          for n in sorted(d)]
    if not body:
        # 文章正文 = 第一个选项行之前
        first = None
        for i, l in enumerate(lines):
            if re.match(r'^\s*1\s*[.、]', l):
                first = i
                break
        body = "\n".join(lines[:first or 0])
    return qs, body, name, full


def read_body(seg, start_marker):
    """
    从某段里取出**文章正文**：跳过 Directions 说明，取到第一道题号之前。

    英语的文章正文里也会出现数字（年份、百分比），所以不能靠"遇到数字就停"，
    而是靠**题号出现的固定形态**（`NN. xxx` 且后面跟着选项）。
    """
    out = []
    for l in seg:
        if re.match(r'^(Directions|Section|Part)\b', l):
            continue
        if re.match(r'^\d{1,2}\.\s', l):
            break
        out.append(l)
    return "\n".join(out)


def _clean_text(s):
    """
    去掉**孤立代理字符**（surrogate）。

    实测：PDF 文字层里会出现未配对的代理码位（如 U+D8xx），
    json.dump 写盘时抛 `UnicodeEncodeError: surrogates not allowed`。
    这类字符本来就是解码残留、不是真实内容，直接剔除。
    """
    if not isinstance(s, str):
        return s
    return s.encode("utf-8", "ignore").decode("utf-8", "ignore")


def _clean_rec(obj):
    """递归清洗整条记录里的字符串。"""
    if isinstance(obj, dict):
        return {k: _clean_rec(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean_rec(v) for v in obj]
    return _clean_text(obj)


def parse_paper(lines, tier):
    """
    解析一整套卷。返回 (rec, 报告)。rec 为 None 表示**不完整，应跳过**。
    """
    marks = split_parts_by_content(lines)
    bounds = [i for i, _, _ in marks] + [len(lines)]
    seg = {n: lines[i:bounds[k + 1]] for k, (i, kd, n) in enumerate(marks)}
    rep = {}

    rec = {"tier": tier, "篇目": []}

    # ---- 完形 ----
    # 【必须在**全文件范围**内解析，不能只用 Section I 那一段】
    # 踩过的坑：旧格式（2010–2022）的 B/C/D 选项行落在 `Part A` 标题**之后**，
    # 按分节切会给切到别的段里 → B/C/D 全空（表现为"完形 0/20"）。
    # 我在独立测试里传的是整个文件、能找到，换成分节后就全 0 —— 就是这个原因。
    # 完形的题号 1–20 与其它部分（21+）不冲突，所以全文件扫是安全的。
    cqs, cbody, fmt, cz_ok = parse_cloze_best(lines, 1, 20)
    rep["完形"] = f"{cz_ok}/20（{fmt}）"
    if cz_ok == 20:
        rec["篇目"].append({"部分": "CLOZE", "材料": cbody, "小题": cqs})

    # ---- 阅读 4 篇 ----
    rd_total = 0
    for t in ("Text 1", "Text 2", "Text 3", "Text 4"):
        blk = parse_choice_block(seg.get(t, []), 21, 40)
        good = [q for q in blk.values() if all((q["选项"] or {}).values())]
        rd_total += len(good)
        if good:
            rec["篇目"].append({"部分": "READ", "材料": read_body(seg.get(t, []), t),
                                "小题": good})
    rep["阅读"] = f"{rd_total}/20"

    # 经验证：完形 20 且阅读 20 才认为这套卷可用
    if cz_ok != 20 or rd_total != 20:
        rep["结论"] = "跳过（不完整）"
        return None, rep
    rec["题目数"] = sum(len(p["小题"]) for p in rec["篇目"])
    rep["结论"] = f"完整 {rec['题目数']} 题"
    return rec, rep


def find_pdf(tier, year):
    sub = "英语一" if tier == "EN1" else "英语二"
    cands = [c for c in glob.glob(f'{SRC}/{sub}/*{year}*真题.pdf')
             if '带书签' not in c and '无解析' not in c]
    return cands[0] if cands else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan", action="store_true", help="只体检，不写盘")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--years", help="如 2023-2026，默认全部")
    args = ap.parse_args()

    if args.years:
        a, _, b = args.years.partition("-")
        ys = range(int(a), int(b or a) + 1)
    else:
        ys = range(2010, 2027)

    os.makedirs(en.ENG_DIR, exist_ok=True)
    ok = skip = 0
    for tier in ("EN1", "EN2"):
        for y in ys:
            pdf = find_pdf(tier, y)
            if not pdf:
                print(f"  {en.TIERS[tier]['简称']} {y}: 无逐年文件")
                continue
            try:
                rec, rep = parse_paper(norm_lines(pdf), tier)
            except Exception as e:                              # noqa: BLE001
                print(f"  {en.TIERS[tier]['简称']} {y}: ❌ {type(e).__name__} "
                      f"{str(e)[:40]}")
                skip += 1
                continue
            tag = f"{en.TIERS[tier]['简称']} {y}"
            detail = f"完形 {rep.get('完形','-')} 阅读 {rep.get('阅读','-')}"
            if rec is None:
                skip += 1
                print(f"  {tag}: ⚠️ {detail} → {rep['结论']}")
                continue
            ok += 1
            print(f"  {tag}: ✅ {detail} → {rep['结论']}")
            if args.write and not args.scan:
                rec = _clean_rec(rec)
                rec["年份"] = str(y)
                p = en.path_of(tier, y)
                tmp = p + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(rec, f, ensure_ascii=False, indent=1)
                os.replace(tmp, p)
    print(f"\n完整 {ok} 套 / 跳过 {skip} 套")
    if args.write and not args.scan:
        for t in ("EN1", "EN2"):
            print(f"  {en.TIERS[t]['简称']} 已入库: {en.years(t)}")


if __name__ == "__main__":
    main()
