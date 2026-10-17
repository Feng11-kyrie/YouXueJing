#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
导入**考研数学一**真题（2010–2025）→ data/math/<年>.json。

为什么不从官方 PDF 抽题
------------------------
考研网的数学卷 PDF，**公式是图片**，文字层只剩汉字。实测 2022 数一：
    "设 ，则 / A. B. C. D."
题干与选项全是空的。所以数学不能像政治那样直接抽 PDF。

改用开源 LaTeX 题库（Markdown）：
    https://github.com/TsekaLuk/Kaoyan-Math1-Papers
    papers/<年>年考研数学(一)真题.md      —— 题干 + 选项（LaTeX）
    solutions/<年>年解析/<年>年解析.md    —— 【答案】+ 详细解析

这套源的质量**逐年不同**（2022 的题目文件是 OCR 乱码、2021 缺填空题标题、
2020 个别选项丢了 (D) 标记）。所以本脚本的核心不是"抽得多"，而是
**抽完逐题校验**：题量、选项数、答案是否齐全，不合格的年份直接标出来，
不往库里写半成品。

用法：
    .venv/bin/python scripts/import_math.py --all
    .venv/bin/python scripts/import_math.py --year 2015 --write
    .venv/bin/python scripts/import_math.py --report
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

REPO = "TsekaLuk/Kaoyan-Math1-Papers"
BRANCH = "main"
CACHE = os.path.join(BASE, ".cache", "math", "md")
IMG = os.path.join(BASE, ".cache", "math", "img")
OUT = os.path.join(BASE, "data", "math")
UA = "Mozilla/5.0"

# 旧大纲（2010–2020）：8 选择 / 6 填空 / 9 解答；新大纲（2021 起）：10 / 6 / 6
NEW = set(range(2021, 2030))


def _get(url, timeout=40):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


TREE_CACHE = os.path.join(BASE, ".cache", "math", "tree.json")


def fetch_tree(force=False):
    """仓库文件清单。缓存到本地 —— GitHub 未鉴权 API 每小时只有 60 次，
    逐年份调用会直接 403（实测踩到）。"""
    os.makedirs(os.path.dirname(TREE_CACHE), exist_ok=True)
    if not force and os.path.exists(TREE_CACHE):
        try:
            return json.load(open(TREE_CACHE, encoding="utf-8"))["tree"]
        except Exception:                                   # noqa: BLE001
            pass
    url = f"https://api.github.com/repos/{REPO}/git/trees/{BRANCH}?recursive=1"
    data = json.loads(_get(url).decode())
    json.dump(data, open(TREE_CACHE, "w", encoding="utf-8"))
    return data["tree"]


def sync(year):
    """把某一年的题目/解析 Markdown 拉到 .cache/math/md/（只下一次）。"""
    os.makedirs(CACHE, exist_ok=True)
    tree = fetch_tree()
    papers = [x["path"] for x in tree
              if x["path"].startswith("papers/") and x["path"].endswith(".md")]
    sols = [x["path"] for x in tree
            if re.search(rf"solutions/{year}年解析/.*\.md$", x["path"])]
    # 题面优先用标准命名；没有就退而求其次（2024 有多种命名、2025 是"2025年数学一真题"）
    cand = [p for p in papers if f"{year}年考研数学(一)真题" in p]
    if not cand:
        cand = [p for p in papers if str(year) in p and "数学" in p]
    if not cand:
        return None, None

    # 同一年可能有多份题面（2024 有 4 份、命名各异），按内容挑：
    # 必须同时含三个大题标题，取篇幅最大的（小的往往是残缺版）。
    best_path, best_text = None, ""
    for p in cand:
        try:
            url = (f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/"
                   + urllib.parse.quote(p))
            txt = _get(url).decode("utf-8", "ignore")
        except Exception:                                   # noqa: BLE001
            continue
        if not all(k in txt for k in ("选择题", "填空题", "解答题")):
            continue
        if len(txt) > len(best_text):
            best_path, best_text = p, txt
    if best_path is None:
        paper_path = sorted(cand, key=len)[0]
    else:
        paper_path = best_path
    sol_path = sols[0] if sols else None

    def dl(path, name):
        p = os.path.join(CACHE, name)
        if os.path.exists(p) and os.path.getsize(p) > 200:
            return p
        url = (f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/"
               + urllib.parse.quote(path))
        open(p, "wb").write(_get(url))
        return p

    paper = dl(paper_path, f"{year}-paper.md")
    sol = dl(sol_path, f"{year}-sol.md") if sol_path else None
    return paper, sol


# ---------------------------------------------------------------- 解析
def split_sections(text):
    # 标题有的带 #、有的不带（2021 的「二、填空题」就是裸文本），都要认
    pat = re.compile(r"(?m)^#{0,3}\s*[一二三]\s*[、.]\s*(选择题|填空题|解答题)[^\n]*$")
    ms = list(pat.finditer(text))
    return {m.group(1): text[m.end():(ms[i + 1].start() if i + 1 < len(ms) else len(text))]
            for i, m in enumerate(ms)}


def expected_counts(section_head, kind, year):
    m = re.search(r"(\d{1,2})\s*[-~～至]\s*(\d{1,2})", section_head[:200])
    if m and 1 <= int(m.group(1)) <= int(m.group(2)) <= 23:
        return list(range(int(m.group(1)), int(m.group(2)) + 1))
    if kind == "选择题":
        return list(range(1, 11)) if year >= 2022 else list(range(1, 9))
    if kind == "填空题":
        return list(range(11, 17)) if year >= 2022 else list(range(9, 15))
    return list(range(17, 23)) if year >= 2022 else list(range(15, 24))


def split_questions(sec_text, kind, year):
    nums = expected_counts(sec_text, kind, year)
    starts, pos = [], 0
    for n in nums:
        m = re.search(rf"(?m)^\s*[（(]?\s*{n}\s*[）).．、]\s*", sec_text[pos:])
        if m:
            starts.append((n, pos + m.start(), pos + m.end()))
            pos += m.end()
    out = []
    for i, (n, s, body) in enumerate(starts):
        end = starts[i + 1][1] if i + 1 < len(starts) else len(sec_text)
        out.append((n, sec_text[body:end].strip()))
    return out, nums


OPT_PAREN = re.compile(r"[（(]\s*([A-D])\s*[)）]")
OPT_LINE = re.compile(r"(?m)^\s*([A-D])\s*[.．、]\s*")


def _norm_opt_markers(block):
    r"""把 $\mathrm{B}$、$\mathbf{C}$ 这类公式里的选项字母还原成 (B)、(C)。"""
    return re.sub(r"\\(?:mathrm|mathbf|pmb|boldsymbol)\s*\{\s*([A-D])\s*\}",
                  r"(\1)", block)


def split_options(block):
    b = _norm_opt_markers(block)
    pos = {}
    cur = 0
    for L in "ABCD":
        pats = [rf"[（(]\s*{L}\s*[)）]", rf"(?m)^\s*{L}\s*[.．、]"]
        best = None
        for p in pats:
            m = re.search(p, b[cur:])
            if m and (best is None or cur + m.start() < best[0]):
                best = (cur + m.start(), cur + m.end())
        if best:
            pos[L] = best
            cur = best[1]
    if len(pos) == 3:
        # 少一个标记（OCR 常见：最后一个选项没印 (D)）。
        # 把「最后一个标记之后的文字」按空行切成两段，后一段就是缺的那个选项 ——
        # 不能直接把缺的字母钉在最后标记的末尾，否则上一个选项会被切空。
        miss = [L for L in "ABCD" if L not in pos][0]
        last = max(pos.items(), key=lambda kv: kv[1][0])
        trailing = b[last[1][1]:]
        m = re.search(r"\n\s*\n(?=\S)", trailing)
        if m:
            pos[miss] = (last[1][1] + m.end(), last[1][1] + m.end())
        elif "\n" in trailing:
            k = trailing.rfind("\n")
            pos[miss] = (last[1][1] + k + 1, last[1][1] + k + 1)
    if len(pos) < 4:
        return block.strip(), {}
    starts = sorted(pos.items(), key=lambda kv: kv[1][0])
    stem = b[:starts[0][1][0]].strip()
    opts = {}
    for i, (L, (s, e)) in enumerate(starts):
        end = starts[i + 1][1][0] if i + 1 < len(starts) else len(b)
        opts[L] = b[e:end].strip()
    if any(not v for v in opts.values()):
        return block.strip(), {}
    return stem, opts


def parse_paper(text, year):
    secs = split_sections(text)
    qs, meta = [], {}
    for kind in ("选择题", "填空题", "解答题"):
        if kind not in secs:
            meta[kind] = "缺节标题"
            continue
        got, nums = split_questions(secs[kind], kind, year)
        meta[kind] = f"{len(got)}/{len(nums)}"
        for n, block in got:
            if kind == "选择题":
                stem, opts = split_options(block)
                qs.append({"题号": n, "题型": "单项选择题", "题干": stem, "选项": opts})
            elif kind == "填空题":
                qs.append({"题号": n, "题型": "填空题", "题干": block})
            else:
                qs.append({"题号": n, "题型": "解答题", "题干": block})
    # 2021 那份缺「二、填空题」标题：11–16 题混在选择题段里
    if "填空题" not in secs and "选择题" in secs:
        got, nums = split_questions(secs["选择题"], "填空题", year)
        got = [(n, b) for n, b in got if n >= 11]
        if got:
            meta["填空题"] = f"{len(got)}/{len(nums)}（无节标题，从选择题段兜底）"
            for n, block in got:
                qs.append({"题号": n, "题型": "填空题", "题干": block})
    qs.sort(key=lambda q: q["题号"])
    return qs, meta


ANS_IN_BLOCK = re.compile(
    r"【答案】\s*(?:[（(]\s*([A-Da-d]{1,4})\s*[)）]|([^\n。]{1,80}))")


def parse_solution(text):
    heads, pos = [], 0
    for n in range(1, 24):
        m = re.search(rf"(?m)^\s*[（(]?\s*{n}\s*[）).．、]\s*", text[pos:])
        if m:
            heads.append((n, pos + m.start(), pos + m.end()))
            pos += m.end()
    out = {}
    for i, (n, s, e) in enumerate(heads):
        end = heads[i + 1][1] if i + 1 < len(heads) else len(text)
        block = text[e:end]
        am = ANS_IN_BLOCK.search(block)
        ans = ""
        if am:
            ans = (am.group(1) or am.group(2) or "").strip()
            ans = re.sub(r"\s*[.。]\s*$", "", ans)      # 去掉答案末尾的句号
            block = block[am.end():]
        block = re.sub(r"^[.。；;、\s]+", "", block.strip())
        out[n] = {"答案": ans, "解析": block}
    return out


def merge(paper, sol):
    for q in paper:
        s = sol.get(q["题号"]) or {}
        if q["题型"] == "单项选择题":
            m = re.search(r"[A-D]", s.get("答案") or "")
            q["答案"] = m.group(0) if m else None
        elif q["题型"] == "填空题":
            q["答案"] = (s.get("答案") or "").strip() or None
        q["解析"] = s.get("解析") or ""
    return paper


# ---------------------------------------------------------------- 校验
def validate(qs, year):
    errs = []
    by = {k: [q for q in qs if q["题型"] == k]
          for k in ("单项选择题", "填空题", "解答题")}
    want = (10, 6, 6) if year >= 2022 else (8, 6, 9)
    for kind, w in zip(("单项选择题", "填空题", "解答题"), want):
        if len(by[kind]) != w:
            errs.append(f"{kind} {len(by[kind])}/{w}")
    for q in by["单项选择题"]:
        if len(q.get("选项") or {}) != 4:
            errs.append(f"第{q['题号']}题选项 {len(q.get('选项') or {})}/4")
        if not q.get("答案"):
            errs.append(f"第{q['题号']}题缺答案")
    for q in by["填空题"]:
        if not q.get("答案"):
            errs.append(f"第{q['题号']}题缺答案")
    for q in qs:
        if len(re.findall(r"[\u4e00-\u9fff]", q["题干"])) < 3 and \
                len(q["题干"]) < 20:
            errs.append(f"第{q['题号']}题题干疑似为空")
    garbled = sum(q["题干"].count("\ufffd") for q in qs)
    if garbled:
        errs.append(f"题干含 {garbled} 个乱码字符")
    return errs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, action="append")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--report", action="store_true")
    a = ap.parse_args()

    if a.report:
        p = os.path.join(OUT, "_coverage.md")
        print(open(p, encoding="utf-8").read() if os.path.exists(p) else "还没跑过")
        return

    years = list(range(2010, 2026)) if a.all else (a.year or [2025])
    rows = []
    os.makedirs(OUT, exist_ok=True)
    for y in years:
        paper, sol = sync(y)
        if not paper:
            rows.append((y, "缺题源", "", ""))
            print(f"{y}: 缺题源")
            continue
        text = open(paper, encoding="utf-8", errors="ignore").read()
        qs, meta = parse_paper(text, y)
        s = parse_solution(open(sol, encoding="utf-8", errors="ignore").read()) if sol else {}
        qs = merge(qs, s)
        errs = validate(qs, y)
        status = "ok" if not errs else "需修"
        rows.append((y, status, f"{len(qs)}题", "；".join(errs[:6])))
        print(f"{y}: {status} {len(qs)} 题 · {meta} · {('；'.join(errs[:4]) or '通过')}")
        if a.write and not errs:
            doc = {"年份": y, "卷种": "一", "题数": len(qs),
                   "来源": (f"https://github.com/{REPO}（Markdown/LaTeX 题库）"),
                   "题目": qs}
            json.dump(doc, open(os.path.join(OUT, f"{y}.json"), "w", encoding="utf-8"),
                      ensure_ascii=False, indent=1)

    lines = ["# 考研数学一 数据导入覆盖率", "",
             "| 年 | 状态 | 题量 | 问题 |", "|---|---|---|---|"]
    for y, st, n, e in rows:
        lines.append(f"| {y} | {st} | {n} | {e} |")
    open(os.path.join(OUT, "_coverage.md"), "w", encoding="utf-8").write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
