#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从「真题墙」文档（lx-ruc/kaoyanshuxue 的 feishu_chunk_*.md 汇总）导入
**数学一/二/三** 真题（2009–2025），题干 + 选项 + 答案 + 解析。

为什么换这个源
--------------
数学一的 LaTeX 题库（TsekaLuk）只覆盖数一，而且 2021–2025 有缺；
这个源一份文档里含三个卷种、每年 22–23 题，且**带答案和详细解析**。
公式用 <equation>...</equation> 包裹，转成 $...$ 交给 yj/mathrender.py。

文档结构（实测）：
    # 数学二
    ## 高等数学 / ### 章节 / #### 考点          ← 按考点组织，题会跨考点重复
    **2014年第16题 | 解答题 | 10分**
    16. (本题满分10分）...题干...
    **答案:** ...
    **解析:** ...
    ---
同一道题在多个考点下重复出现 → 按 (卷种, 年, 题号) 去重，取**题干最长、解析最全**的那份。

用法：
    .venv/bin/python scripts/import_math_lx.py --all
    .venv/bin/python scripts/import_math_lx.py --tier 二 --write
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

CACHE = os.path.join(BASE, ".cache", "math", "lx")
OUT = os.path.join(BASE, "data", "math")
FIG = os.path.join(BASE, "data", "math", "figures")
IMG_REPO = "lx-ruc/kaoyanshuxue"
IMG_BASE = "kaoyan_math_images"
REPO = "lx-ruc/kaoyanshuxue"
BRANCH = "main"
UA = "Mozilla/5.0"


def _get(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def fetch_all(force=False):
    """把仓库里的 feishu_chunk_*.md 拼成一个 lx_all.md（缓存）。"""
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, "lx_all.md")
    if os.path.exists(path) and os.path.getsize(path) > 100000 and not force:
        return path
    # 仓库根目录的 chunk 数量不固定：从 000 开始连续拉，404 就停
    parts = []
    for i in range(400):
        name = f"feishu_chunk_{i:03d}.md"
        url = (f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/"
               + urllib.parse.quote(name))
        try:
            parts.append(_get(url).decode("utf-8", "ignore"))
        except Exception:                                   # noqa: BLE001
            break
    if not parts:
        return None
    open(path, "w", encoding="utf-8").write("\n".join(parts))
    return path




# ---------------------------------------------------------------- 图片兜底
_meta_cache = {}


def answer_meta(tier):
    """数学X 的 answers.json（题目元数据：id / 答案 / 分值 / 考点）。"""
    if tier in _meta_cache:
        return _meta_cache[tier]
    url = (f"https://raw.githubusercontent.com/{IMG_REPO}/main/"
           + urllib.parse.quote(f"{IMG_BASE}/数学{tier}/answers.json"))
    try:
        data = json.loads(_get(url).decode("utf-8"))
    except Exception:                                       # noqa: BLE001
        data = {}
    _meta_cache[tier] = data
    return data


def fetch_question_image(tier, year, n):
    """
    题干/选项在文档里缺失时，用真题墙的**题目图片**兜底。
    返回项目内相对路径（供界面 ui.image 用），失败返回 None。
    """
    key = f"数学{tier}_{year}_Q{n:02d}"
    meta = answer_meta(tier).get(key) or {}
    qid = meta.get("question_id")
    if not qid:
        return None
    os.makedirs(FIG, exist_ok=True)
    fname = f"{tier}-{year}-Q{n:02d}.png"
    dst = os.path.join(FIG, fname)
    if not (os.path.exists(dst) and os.path.getsize(dst) > 1000):
        path = (f"{IMG_BASE}/数学{tier}/{year}/Q{n:02d}_id{qid}.png")
        url = (f"https://raw.githubusercontent.com/{IMG_REPO}/main/"
               + urllib.parse.quote(path))
        try:
            data = _get(url)
        except Exception:                                   # noqa: BLE001
            return None
        open(dst, "wb").write(data)
    return os.path.relpath(dst, os.path.join(BASE, "data"))


ENTRY = re.compile(
    r"^\*\*(\d{4})年第(\d{1,2})题\s*\|\s*(选择题|填空题|解答题)\s*\|\s*([\d.]+)分"
    r"(?:\s*\|\s*答案[:：]\s*([A-D]+))?\*\*", re.M)

KIND = {"选择题": "单项选择题", "填空题": "填空题", "解答题": "解答题"}


def clean_tex(s):
    s = (s or "").replace("<equation>", "$").replace("</equation>", "$")
    s = s.replace("**答案:**", "").replace("**解析:**", "")
    s = s.replace("**答案: **", "").replace("**解析: **", "")
    return s.strip()


def clean_answer(s):
    s = clean_tex(s)
    s = s.replace("**", "").strip()
    s = re.sub(r"^#+\s*", "", s)
    s = re.sub(r"^\(?\d{1,2}\)?\s*[.．、]?\s*(?=\S)", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def parse_entries(text):
    """→ {tier: [(year, n, kind, score, hint, stem, answer, expl)]}"""
    parts = re.split(r"^# 数学([一二三])\s*$", text, flags=re.M)
    out = {}
    for i in range(1, len(parts), 2):
        tier, body = parts[i], parts[i + 1]
        ms = list(ENTRY.finditer(body))
        for j, m in enumerate(ms):
            end = ms[j + 1].start() if j + 1 < len(ms) else len(body)
            chunk = re.split(r"(?m)^---\s*$", body[m.end():end])[0]
            # 先找「解析」再找「答案」：有的条目没有答案行（或格式是
            # "**答案: **"），只按答案切会把整段解析并进题干（数三 2015
            # 第 10/13 题实测如此）。
            em = re.search(r"\*\*解析[:：]?\s*\*\*|解析[:：]", chunk)
            head, expl = (chunk[:em.start()], chunk[em.end():]) if em else (chunk, "")
            am = re.search(r"\*\*答案[:：]?\s*\*\*|答案[:：]", head)
            if am:
                stem, ans = head[:am.start()], head[am.end():]
            else:
                stem, ans = head, ""
            stem = clean_tex(stem)
            stem = re.sub(r"^\s*\d{1,2}\s*[.．、]\s*", "", stem).strip()
            out.setdefault(tier, []).append({
                "year": int(m.group(1)), "n": int(m.group(2)),
                "kind": KIND[m.group(3)], "score": float(m.group(4)),
                "hint": (m.group(5) or "").strip(),
                "stem": stem, "answer": clean_answer(ans),
                "expl": clean_tex(expl).strip(),
            })
    return out


# 选项标记：A. / (A) / A、 / \mathrm{A.} / \mathrm{A}. —— 且**允许顺序乱**
OPT_MARK = re.compile(
    r"(?:\\(?:mathrm|mathbf|pmb|boldsymbol)\s*\{\s*)?"
    r"([A-D])\s*(?:\})?\s*[.．、)）]\s*"
)


def split_options(stem):
    """把选择题题干里的 A/B/C/D 选项拆出来（顺序乱也能认）。"""
    pos = {}
    for m in OPT_MARK.finditer(stem):
        L = m.group(1)
        if L not in pos:
            pos[L] = (m.start(), m.end())
    if len(pos) < 4:
        return stem, {}
    picked = sorted(((L, v[0], v[1]) for L, v in pos.items()), key=lambda x: x[1])
    opts = {}
    for i, (L, s0, e0) in enumerate(picked):
        end = picked[i + 1][1] if i + 1 < len(picked) else len(stem)
        opts[L] = stem[e0:end].strip()
    return stem[:picked[0][1]].strip(), opts


def guess_answer(expl):
    """
    填空/解答题常常没有单独的「答案」行，结果只写在解析末尾。
    取解析里最后一个带等号的公式当"参考结果"（不是精确答案）。
    """
    eqs = re.findall(r"\$[^$]*=[^$]*\$", expl or "")
    return eqs[-1] if eqs else ""


def dedup(entries):
    """同一年同一题号可能重复出现（按考点组织导致）→ 取内容最全的一份。"""
    best = {}
    for e in entries:
        key = (e["year"], e["n"])
        score = (len(e["stem"]) if "无内容" not in e["stem"] else 0,
                 len(e["expl"]), len(e["answer"]))
        cur = best.get(key)
        if cur is None:
            best[key] = (score, e)
        else:
            # 互补：题干取长的、答案取非空的、解析取长的
            s0, c = cur
            merged = dict(c)
            if len(e["stem"]) > len(c["stem"]) and "无内容" not in e["stem"]:
                merged["stem"] = e["stem"]
            if not merged["answer"] and e["answer"]:
                merged["answer"] = e["answer"]
            if len(e["expl"]) > len(merged["expl"]):
                merged["expl"] = e["expl"]
            if not merged["hint"] and e["hint"]:
                merged["hint"] = e["hint"]
            best[key] = (max(s0, score), merged)
    return {k: v[1] for k, v in best.items()}


def build(tier, entries):
    by_year = {}
    for (y, n), e in entries.items():
        if e["kind"] == "单项选择题":
            stem, opts = split_options(e["stem"])
            q = {"题号": n, "题型": e["kind"], "题干": stem, "选项": opts}
            q["答案"] = e["hint"] or (e["answer"][:1] if e["answer"][:1] in "ABCD" else None)
        elif e["kind"] == "填空题":
            ans = e["answer"] or e["hint"] or guess_answer(e["expl"])
            q = {"题号": n, "题型": e["kind"], "题干": e["stem"],
                 "选项": {}, "答案": ans or None}
        else:
            q = {"题号": n, "题型": e["kind"], "题干": e["stem"],
                 "选项": {}, "答案": None}
        q["解析"] = e["expl"]
        q["分值"] = e["score"]
        # 真题墙的元数据：答案 / 分值 / 考点（答案可用来补缺、也可交叉校验）
        meta = answer_meta(tier).get(f"数学{tier}_{y}_Q{n:02d}") or {}
        if meta:
            q["考点"] = meta.get("knowledge_point") or ""
            if not q.get("答案") and meta.get("answer"):
                q["答案"] = str(meta["answer"]).strip()
            if not q.get("答案") and q["题型"] == "填空题":
                q["答案"] = guess_answer(q.get("解析") or "") or None
        by_year.setdefault(y, []).append(q)
    for y in by_year:
        by_year[y].sort(key=lambda q: q["题号"])
        for q in by_year[y]:
            need_img = (not (q.get("题干") or "").strip()
                        or "无内容" in q.get("题干")
                        or (q["题型"] == "单项选择题"
                            and len(q.get("选项") or {}) != 4))
            if need_img:
                rel = fetch_question_image(tier, y, q["题号"])
                if rel:
                    q["图片"] = rel
                    if not (q.get("题干") or "").strip() or "无内容" in q.get("题干"):
                        q["题干"] = "（题干见下方原题图）"
                    if q["题型"] == "单项选择题" and len(q.get("选项") or {}) != 4:
                        q["选项"] = {}          # 选项在原题图里，界面只给 A–D 按钮
    return by_year


def validate(qs, year):
    errs = []
    want = (10, 6, 6) if year >= 2021 else (8, 6, 9)
    from collections import Counter
    c = Counter(q["题型"] for q in qs)
    got = (c.get("单项选择题", 0), c.get("填空题", 0), c.get("解答题", 0))
    for k, g, w in zip(("选择", "填空", "解答"), got, want):
        if g != w:
            errs.append(f"{k} {g}/{w}")
    for q in qs:
        has_img = bool(q.get("图片"))
        if not has_img and (not (q.get("题干") or "").strip()
                            or "无内容" in q["题干"]):
            errs.append(f"第{q['题号']}题缺题干")
        if q["题型"] == "单项选择题":
            if not has_img and len(q.get("选项") or {}) != 4:
                errs.append(f"第{q['题号']}题选项 {len(q.get('选项') or {})}/4")
            if not q.get("答案"):
                errs.append(f"第{q['题号']}题缺答案")
    return errs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", action="append", choices=["一", "二", "三"])
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--year", type=int, action="append")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--force", action="store_true", help="重新下载文档")
    a = ap.parse_args()

    path = fetch_all(a.force)
    if not path:
        print("文档下载失败")
        return 1
    text = open(path, encoding="utf-8").read()
    tiers = parse_entries(text)
    print("文档:", path, "| 卷种:", {k: len(v) for k, v in tiers.items()})

    want = ["一", "二", "三"] if a.all else (a.tier or ["二", "三"])
    rows = []
    for tier in want:
        entries = dedup(tiers.get(tier, []))
        by_year = build(tier, entries)
        for y in sorted(by_year):
            qs = by_year[y]
            errs = validate(qs, y)
            status = "ok" if not errs else "需修"
            rows.append((tier, y, status, len(qs), "；".join(errs[:5])))
            print(f"数学{tier} {y}: {status} {len(qs)} 题 · "
                  f"{('；'.join(errs[:3]) or '通过')}")
            if a.year and y not in a.year:
                continue
            if a.write and not errs:
                d = os.path.join(OUT, tier)
                os.makedirs(d, exist_ok=True)
                json.dump({"年份": y, "卷种": tier, "题数": len(qs),
                           "来源": f"https://github.com/{REPO}（真题墙文档）",
                           "题目": qs},
                          open(os.path.join(d, f"{y}.json"), "w", encoding="utf-8"),
                          ensure_ascii=False, indent=1)

    lines = ["# 数学（真题墙文档）导入覆盖率", "",
             "| 卷种 | 年 | 状态 | 题量 | 问题 |", "|---|---|---|---|---|"]
    for t, y, st, n, e in rows:
        lines.append(f"| {t} | {y} | {st} | {n} | {e} |")
    os.makedirs(OUT, exist_ok=True)
    open(os.path.join(OUT, "_coverage_lx.md"), "w", encoding="utf-8").write(
        "\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
