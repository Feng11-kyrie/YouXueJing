#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
抓取 408 综合应用题的**评分标准**（分档给分），输出结构化 rubric。

为什么要有这个东西
------------------
现有的免费评分（`yj/rubric_checker.py::score_generic`）只看篇幅 / 分点 / 考点词，
给的是"表述完整度"。但 408 综合题的真实阅卷是**分档给分**：

    （1）算法基本思想（4 分）
    ①清晰、准确描述 O(n) 的算法        → 4 分
    ②不太清晰但方向正确                → 2-3 分
    ③完全错误                          → 0 分

判分应该是"学生答到哪一档"，而不是"写够 150 字给 70%"。

数据从哪来（这一轮查证过的，别再重复试）
--------------------------------------
**可用**：考研网（kaoyan.cn）的「真题」文档库，`/file/question/*.pdf` 是文字型
PDF，可以直接 `norm_lines()` 取行。目录接口（2026-10 实测）：

    https://api.kaoyan.cn/pc/question/questionList?page=1&pageSize=10&keyword=408
    https://static.kaoyan.cn/json/question/<question_id>.json   → file_url

涵盖 2011–2026，但**能读出【评分标准】的只有 2025 一份**（其余年份是：
纯扫描件 2011–2014、只有题目没有答案 2019/2021/2023/2024/2026、
答案里只有"解答"没有分档 2015/2016/2018/2020/2022）。
所以本脚本的定位是：**有就抓、没有就跳过并记进覆盖率报告**，判分侧再退回
`score_generic()`。这条链路任何时候发现新文档都能直接补上。

不做什么
--------
· 不猜 URL：文档 hash 无法枚举，一律走接口发现。
· 不做 OCR：扫描件（2011–2014）直接跳过，本地 `.cache/408/*-answer.pdf`
  的 OCR 结果带水印，不能用来比对（见 docs/handover_408_rubrics.md）。
· 不写"看起来像官方"的假 rubric：分档文本原样保留，解析不了就跳过。

用法
----
    .venv/bin/python scripts/fetch_408_rubrics.py --all          # 抓 + 解析 + 写
    .venv/bin/python scripts/fetch_408_rubrics.py --year 2025    # 单年
    .venv/bin/python scripts/fetch_408_rubrics.py --report       # 只看覆盖率
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from scripts.parse_english import norm_lines                     # noqa: E402

API_LIST = "https://api.kaoyan.cn/pc/question/questionList"
API_META = "https://static.kaoyan.cn/json/question/{qid}.json"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")

CACHE = os.path.join(BASE, ".cache", "408_ky")
OUT = os.path.join(BASE, "data", "408", "rubrics")
LOCAL_Q = os.path.join(BASE, "data", "408")

# 题号 → 满分：以本地题库（官方试卷）为准做二次校验
_QFULL = {}


# ---------------------------------------------------------------------------
# 网络
# ---------------------------------------------------------------------------
def _get(url, timeout=30):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Referer": "https://www.kaoyan.cn/",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _get_json(url, timeout=30):
    return json.loads(_get(url, timeout).decode("utf-8", "ignore"))


def discover():
    """
    列出考研网上所有 408 真题文档 → {年份: {question_id, 标题, file_url, 大小}}。

    坑（实测）：**不要用 keyword=408 搜索**。2024/2023 各有 170+ 条"自命题"
    重复项，全部指向同一份试卷 PDF，会把搜索结果淹掉 —— 翻到第 30 页都还没
    见到 2015 年。改用 `first_type=4`（统考类综合）分页浏览，一共 260 条、
    26 页，2011–2026 每年一份，干净。
    """
    found = {}
    total = None
    page = 1
    while page <= 60:
        url = f"{API_LIST}?page={page}&pageSize=10&first_type=4"
        try:
            j = _get_json(url)
        except Exception as e:                              # noqa: BLE001
            print(f"· 目录接口第 {page} 页失败：{type(e).__name__}: {e}")
            break
        data = (j.get("data") or {})
        items = data.get("data") or []
        if total is None:
            total = data.get("total")
        for it in items:
            title = it.get("title") or ""
            m = re.match(r"(\d{4})\s*年\s*408", title)
            if not m or it.get("first_type_name") != "统考类综合":
                continue
            yr = int(m.group(1))
            rec = {
                "question_id": it.get("question_id"),
                "标题": title,
                "日期": it.get("created_at"),
            }
            # 同一年有多份时取最新上传的（新上传的解析更全）
            if yr not in found or str(rec["日期"]) > str(found[yr]["日期"]):
                found[yr] = rec
        if len(items) < 10:
            break
        if total and page * 10 >= total:
            break
        page += 1

    for yr, rec in found.items():
        try:
            meta = _get_json(API_META.format(qid=rec["question_id"])).get("data") or {}
        except Exception:                                   # noqa: BLE001
            meta = {}
        rec["file_url"] = meta.get("file_url")
        rec["大小KB"] = meta.get("doc_size")
        rec["上传者"] = meta.get("uploaded_by")
    return dict(sorted(found.items()))


def download(year, url):
    """下载到 .cache/408_ky/<年>.pdf（有缓存就不再下）。"""
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, f"{year}.pdf")
    if os.path.exists(path) and os.path.getsize(path) > 20000:
        return path
    if not url:
        return None
    data = _get(url, timeout=90)
    with open(path, "wb") as f:
        f.write(data)
    return path


# ---------------------------------------------------------------------------
# 解析
# ---------------------------------------------------------------------------
# 综合题题头："41.(13 分)" / "41．（本题 13 分）"
_Q_HEAD = re.compile(r"^(\d{1,2})\s*[.．、]\s*[（(]\s*(?:本题\s*)?(\d+)\s*分")
# 分档小标题："（1）算法基本思想（4 分）"
_STEP = re.compile(r"^（\s*(\d+)\s*）\s*(.+?)\s*[（(]\s*(\d+)\s*分\s*[)）]\s*$")
# 档次条目："①……"
_ITEM = re.compile(r"^([①②③④⑤⑥⑦⑧⑨⑩])\s*(.+)$")
_MARK = re.compile(r"^【([^】]+)】")


def _num_score(txt):
    """
    从一条档次的文字里取分值 → (下限, 上限, 类型)。

    实测到的写法（2025 年 41 题）：
        可得 4 分 / 可给 7 分 / 得 0 分 / 可再给 1 分   → 固定分
        可酌情给 2 - 3 分                              → 区间
        则最高可给 5 分                                → 上限（下界视为 0）
        可参照上述……酌情给分（没有数字）               → 无固定分，中档
    """
    m = re.search(r"(\d+)\s*[-–—~至]\s*(\d+)\s*分", txt)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        return min(a, b), max(a, b), "区间"
    if re.search(r"最高可给\s*(\d+)\s*分", txt):
        return 0, int(re.search(r"最高可给\s*(\d+)\s*分", txt).group(1)), "上限"
    m = re.search(r"(?:可得|可给|得|再给)\s*(\d+)\s*分", txt)
    if m:
        v = int(m.group(1))
        return v, v, "固定"
    return None, None, "无分值"


def _join_wrapped(lines):
    """PDF 取行是按版面断的，句子会断在中间 → 把续行接回上一行。"""
    out = []
    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        starts_new = (bool(_STEP.match(s)) or bool(_ITEM.match(s))
                      or bool(_MARK.match(s)) or bool(_Q_HEAD.match(s)))
        if out and not starts_new:
            out[-1] = out[-1] + s
        else:
            out.append(s)
    return out


def _find_blocks(lines):
    """
    找出所有【评分标准】块 → [(起始行, 结束行, 题号, 题满分)]。

    题号/满分取**该块之前最近的一道题头**（评分标准紧跟在它评的那道题后面）。
    """
    heads = []
    for i, l in enumerate(lines):
        m = _Q_HEAD.match(l)
        if m and 41 <= int(m.group(1)) <= 47:
            heads.append((i, int(m.group(1)), int(m.group(2))))

    def owner(i):
        prev = [(h, q, f) for h, q, f in heads if h < i]
        return (prev[-1][1], prev[-1][2]) if prev else (None, None)

    out = []
    for i, l in enumerate(lines):
        if "【评分标准】" not in l:
            continue
        end = len(lines)
        for j in range(i + 1, len(lines)):
            if _MARK.match(lines[j]) or _Q_HEAD.match(lines[j]):
                end = j
                break
        qno, full = owner(i)
        out.append((i, end, qno, full))
    return out


def parse_block(lines):
    """把一个【评分标准】块解析成步骤 / 档次。"""
    merged = _join_wrapped(lines)
    steps = []
    for s in merged:
        m = _STEP.match(s)
        if m:
            steps.append({"步骤": m.group(2).strip(), "分值": int(m.group(3)),
                          "档": []})
            continue
        m = _ITEM.match(s)
        if m and steps:
            txt = m.group(2).strip()
            lo, hi, kind = _num_score(txt)
            steps[-1]["档"].append({
                "序号": m.group(1),
                "条件": txt,
                "得分": (lo if lo == hi else f"{lo}-{hi}") if lo is not None else None,
                "得分下界": lo, "得分上界": hi, "分值类型": kind,
            })

    # 档型判断：正向分能加起来等于步骤分值 → 采分点（并列得分）；
    # 否则是互斥分档（只有一档成立）。
    for st in steps:
        full = st["分值"]
        pos = [x["得分上界"] for x in st["档"] if x["得分上界"]]
        if not st["档"]:
            st["模式"] = "无档次"
        elif max(pos or [0]) >= full:
            st["模式"] = "分档"
        elif pos and sum(pos) == full:
            st["模式"] = "采分点"
        else:
            st["模式"] = "分档"
    return steps


def validate(qno, full, steps, year):
    """
    校验：各步骤分值之和 == 该题满分，且每步的档能给出等于分值的最高分。

    **这是交接文档点名要做的校验**：PDF 解析出来对不上，宁可跳过也不能
    写进库里 —— 错的 rubric 比没有 rubric 更伤人。
    """
    errs = []
    if not steps:
        return ["没有解析出步骤"]
    total = sum(s["分值"] for s in steps)
    if full is None:
        errs.append("题头没有满分")
    elif total != full:
        errs.append(f"步骤分值合计 {total} ≠ 题头满分 {full}")

    local = _QFULL.get((year, qno))
    if local is not None and full is not None and local != full:
        errs.append(f"题头满分 {full} ≠ 本地题库分值 {local}")
    if local is not None and total != local:
        errs.append(f"步骤分值合计 {total} ≠ 本地题库分值 {local}")

    for s in steps:
        ups = [x["得分上界"] for x in s["档"] if x["得分上界"] is not None]
        if not ups:
            errs.append(f"「{s['步骤']}」没有任何带分值的档")
        elif s["模式"] == "分档" and max(ups) != s["分值"]:
            errs.append(f"「{s['步骤']}」最高档 {max(ups)} 分 ≠ 步骤分值 {s['分值']}")
        elif s["模式"] == "采分点" and sum(x for x in ups if x > 0) != s["分值"]:
            errs.append(f"「{s['步骤']}」采分点合计 ≠ 步骤分值 {s['分值']}")
    return errs


def parse_pdf(path, year):
    """PDF → {题目: {满分, 来源行, 步骤, 校验}}，外加统计信息。"""
    try:
        lines = norm_lines(path)
    except Exception as e:                                  # noqa: BLE001
        return {"错": f"取行失败：{type(e).__name__}: {e}", "行数": 0}

    info = {"行数": len(lines), "评分标准块": 0, "题目": {}}
    if not lines:
        info["错"] = "没有文字层（扫描件）"
        return info

    for i0, i1, qno, full in _find_blocks(lines):
        info["评分标准块"] += 1
        if not qno:
            info.setdefault("跳过", []).append(f"第{i0}行：找不到所属题号")
            continue
        steps = parse_block(lines[i0:i1])
        errs = validate(qno, full, steps, year)
        if errs:
            info.setdefault("跳过", []).append(
                f"{qno} 题：" + "；".join(errs))
            continue
        info["题目"][str(qno)] = {
            "满分": full,
            "模式说明": ("按官方评分标准分档给分（【评分标准】原文）"),
            "原文行": i0 + 1,
            "步骤": steps,
        }
    if not info["题目"]:
        info.setdefault("说明", "全文没有可解析的【评分标准】")
    return info


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def _load_local_full(year):
    p = os.path.join(LOCAL_Q, f"{year}.json")
    if not os.path.exists(p):
        return
    try:
        doc = json.load(open(p, encoding="utf-8"))
    except Exception:                                       # noqa: BLE001
        return
    for q in doc.get("题目") or []:
        if q.get("题型") == "综合应用题":
            _QFULL[(year, int(q["题号"]))] = float(q.get("分值") or 0)


def build(years=None):
    os.makedirs(OUT, exist_ok=True)
    print("· 发现文档 …")
    catalog = discover()
    if not catalog:
        print("  （接口没返回，改用已有缓存）")
        catalog = {}
        for f in sorted(os.listdir(CACHE)) if os.path.isdir(CACHE) else []:
            m = re.match(r"(\d{4})\.pdf$", f)
            if m:
                catalog[int(m.group(1))] = {"标题": f"{m.group(1)} 年 408（缓存）",
                                            "file_url": None}

    report = []
    for year, rec in catalog.items():
        if years and year not in years:
            continue
        _load_local_full(year)
        print(f"\n=== {year}  {rec.get('标题')}")
        try:
            path = download(year, rec.get("file_url"))
        except Exception as e:                              # noqa: BLE001
            print(f"  下载失败：{e}")
            report.append({"年": year, "状态": "下载失败", "说明": str(e)[:80]})
            continue
        if not path:
            report.append({"年": year, "状态": "无链接"})
            continue
        got = parse_pdf(path, year)
        print(f"  行数 {got.get('行数', 0)} · 评分标准块 {got.get('评分标准块', 0)}"
              f" · 可用题目 {len(got.get('题目') or {})}")
        for s in got.get("跳过") or []:
            print(f"  跳过：{s}")

        if got.get("题目"):
            doc = {
                "year": year,
                "来源": "考研网（kaoyan.cn）真题文档【评分标准】原文",
                "来源URL": rec.get("file_url"),
                "文档标题": rec.get("标题"),
                "抓取": dt.date.today().isoformat(),
                "题目": got["题目"],
                "未覆盖题号": [str(n) for n in range(41, 48)
                              if str(n) not in got["题目"]],
            }
            p = os.path.join(OUT, f"{year}.json")
            json.dump(doc, open(p, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=1)
            print(f"  写入 {os.path.relpath(p, BASE)}")
            report.append({"年": year, "状态": "有 rubric",
                           "题号": sorted(got["题目"]), "行数": got.get("行数")})
        else:
            report.append({"年": year,
                           "状态": "无可解析 rubric",
                           "行数": got.get("行数", 0),
                           "行数说明": ("扫描件（无文字层）"
                                     if not got.get("行数") else ""),
                           "说明": "；".join(got.get("跳过") or [])
                           or got.get("说明") or got.get("错") or ""})

    _write_coverage(report, catalog)
    return report


def _write_coverage(report, catalog):
    covered = [r for r in report if r["状态"] == "有 rubric"]
    lines = ["# 408 评分标准（rubric）覆盖率", "",
             f"生成时间：{dt.datetime.now().strftime('%Y-%m-%d %H:%M')}", "",
             f"覆盖：**{len(covered)}/{len(report)}** 年有可解析的评分标准。", "",
             "| 年 | 文档 | 行数 | 状态 | 说明 |", "|---|---|---|---|---|"]
    for r in sorted(report, key=lambda x: -x["年"]):
        rec = catalog.get(r["年"]) or {}
        lines.append(
            f"| {r['年']} | {rec.get('标题', '—')} | "
            f"{r.get('行数') or r.get('行数说明') or '—'} | "
            f"{r['状态']} | {('题号 ' + '、'.join(map(str, r.get('题号', []))))
                              if r.get('题号') else r.get('说明', '')} |")
    lines += ["",
              "判分侧规则：`data/408/rubrics/<年>.json` 里查得到该题 → 按评分标准分档；"
              "查不到 → 自动退回 `score_generic()`（结构体检）。"]
    p = os.path.join(OUT, "_coverage.md")
    open(p, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print(f"\n· 覆盖率报告：{os.path.relpath(p, BASE)}"
          f"（{len(covered)}/{len(report)} 年）")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, action="append",
                    help="只处理指定年份（可重复）")
    ap.add_argument("--all", action="store_true", help="处理全部年份")
    ap.add_argument("--report", action="store_true", help="只看已有覆盖率报告")
    a = ap.parse_args()

    if a.report:
        p = os.path.join(OUT, "_coverage.md")
        print(open(p, encoding="utf-8").read() if os.path.exists(p)
              else "还没有跑过，先执行 --all")
        return
    build(a.year)


if __name__ == "__main__":
    main()
