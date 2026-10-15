#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量下载并**验证**考研政治真题 PDF。

为什么需要"验证"这一步
----------------------
实测：搜到 PDF ≠ 能用。踩过的坑：
  · 清华社《基础练习》55 页  → 是知识讲义，选项抽不出来（0 行）
  · 中公马原十年真题        → 有内容但格式混乱，答案选项揉在题干里
  · 新东方 2015 页面        → 导流页，正文 JS 加载，抓不到

所以每个候选 PDF 都要过三关：
  ① 是不是真 PDF（看文件头 %PDF）
  ② 有没有三题型标题（单项选择题/多项选择题/材料分析题）
  ③ **选项行数够不够**（每题 4 个选项 × 33 题 ≈ 132 行）—— 这一关最关键，
     它能把"讲义"和"题库"区分开（讲义也有"单项选择题"标题，但没有选项行）

用法：
    .venv/bin/python scripts/fetch_zz_pdfs.py --urls urls.txt
    .venv/bin/python scripts/fetch_zz_pdfs.py --url "https://..." --year 2016
候选 URL 也可直接作为位置参数（每行一个 / 每个参数一个）。
"""
import argparse
import os
import re
import subprocess
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEST = os.path.join(BASE, ".cache", "zhengzhi")
OPT_LINE = re.compile(r'(?m)^\s*[A-D]\s*[.．、]')


def fetch(url, out):
    """下载（伪装 UA —— 有些高校站点拦默认 curl UA）"""
    try:
        subprocess.run(["curl", "-sL", "--max-time", "90", "-A",
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
                        "-o", out, url], check=True)
    except subprocess.CalledProcessError:
        return 0
    return os.path.getsize(out) if os.path.exists(out) else 0


def validate(path):
    """返回 (是否可用, 说明, 年份)"""
    if not os.path.exists(path) or os.path.getsize(path) < 20000:
        return False, f"文件太小（{os.path.getsize(path) if os.path.exists(path) else 0} 字节）", None
    with open(path, "rb") as f:
        if f.read(4) != b"%PDF":
            return False, "不是 PDF（可能是 HTML 页面）", None
    try:
        from pypdf import PdfReader
        r = PdfReader(path)
        txt = "\n".join((p.extract_text() or "") for p in r.pages)
    except Exception as e:                              # noqa: BLE001
        return False, f"PDF 解析失败 {type(e).__name__}", None

    # 【关键判据：用解析器本身验证】不能只看"有多少选项行" ——
    # 实测清华社那份知识讲义有 830 行选项样式，但**一道题都抽不出来**
    # （选项散在知识点讲解里，没有题号锚点）。所以真正的判据是：
    # 解析后能不能得到 16 单选 + 17 多选 + 5 分析 的标准结构。
    sys.path.insert(0, BASE)
    from scripts.parse_zhengzhi import parse
    try:
        items = parse(path, None)
    except SystemExit:
        return False, "解析器找不到题型标题（不是真题排版）", None
    except Exception as e:                              # noqa: BLE001
        return False, f"解析失败 {type(e).__name__}", None

    cnt = {}
    for it in items:
        cnt[it["题型"]] = cnt.get(it["题型"], 0) + 1
    s_ = cnt.get("单项选择题", 0)
    m_ = cnt.get("多项选择题", 0)
    a_ = cnt.get("材料分析题", cnt.get("分析题", 0))
    year = None
    ym = re.search(r'(20\d{2})\s*年', txt[:1200])
    if ym:
        year = ym.group(1)

    # 官方结构：16 单选 / 17 多选 / 5 分析。允许分析题少（有些题源只放客观题）
    if s_ >= 14 and m_ >= 15 and a_ >= 3:
        return True, f"单选 {s_} / 多选 {m_} / 分析 {a_}（{len(r.pages)} 页）", year
    return (False,
            f"解析出的题量不符（单选 {s_} / 多选 {m_} / 分析 {a_}）"
            f"—— 不是真题题库", None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", action="append", default=[])
    ap.add_argument("--urls", help="每行一个 URL 的文件")
    ap.add_argument("urls_pos", nargs="*", help="候选 URL（位置参数）")
    args = ap.parse_args()

    urls = list(args.url) + list(args.urls_pos)
    if args.urls and os.path.exists(args.urls):
        urls += [l.strip() for l in open(args.urls, encoding="utf-8")
                 if l.strip() and not l.startswith("#")]
    if not urls:
        print("没有候选 URL", file=sys.stderr)
        sys.exit(1)

    os.makedirs(DEST, exist_ok=True)
    ok_n = 0
    for i, u in enumerate(urls, 1):
        tmp = os.path.join("/tmp", f"zzcand{i}.pdf")
        size = fetch(u, tmp)
        good, why, year = validate(tmp)
        print(f"[{i}/{len(urls)}] {'✅' if good else '❌'} {why}")
        print(f"         {u[:100]}")
        if good:
            ok_n += 1
            dst = os.path.join(DEST, f"{year or 'unknown'}.pdf")
            if os.path.exists(dst):
                print(f"         ⚠️ {os.path.basename(dst)} 已存在，跳过覆盖")
            else:
                os.replace(tmp, dst)
                print(f"         → 已存为 {os.path.relpath(dst, BASE)}"
                      f"（用 parse_zhengzhi.py 解析）")
    print(f"\n可用 {ok_n} / {len(urls)}")


if __name__ == "__main__":
    main()
