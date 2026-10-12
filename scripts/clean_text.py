#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
清洗 408 题干的文本污染。

实测出 4 类问题(按严重程度):

1) 页眉页脚混入题干/选项 —— **最严重, 21.6% 的题被污染**
   每翻一页, PDF 文字层就把当页页眉页脚塞进当前题目的文本里:
     "...寻址方式 \n2009 年全国硕士研究生入学统一考试计算机科学与技术学科联考
      计算机学科专业基础综合试题 第2页，共10页\n"
   污染会出现在**选项里**, 用户会直接看到。

2) 章节标题混入
   "...第4页，共10页 \n \n二、综合应用题（第41～47 题，共70 分）\n"

3) 上标被拆成独立行 —— 56 处
   "2\n7\n×\n29/32" 实际是 2^7 × 29/32 ;  "O(n\n2\n)" 是 O(n²)

4) 孤立运算符独占一行
   "2\n7\n×\n29/32" 里的 ×

清洗后上标统一写成 ASCII 的 `^` 记法(如 `2^7`), 便于检索; 由前端渲染成真正的上标。
不使用 Unicode 上标(如 ⁷) —— 会破坏下游检索与匹配。

用法:
  python clean_text.py --dry-run    # 只报告, 不改文件
  python clean_text.py              # 应用(先自动备份到 .cache/backup/)
"""
import os
import re
import json
import glob
import shutil
import argparse

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(BASE, "data", "408")
BAK = os.path.join(BASE, ".cache", "backup")

# ---------------------------------------------------------------- 清洗规则
# 顺序有讲究: 上标还原要看到 "基数\n指数\n" 的结构, 所以必须排在
# 「孤立运算符」之前 —— 否则运算符先被并入行内, 上标规则就匹配不到了。
OPS = "×*·÷=＋+\\-－–—"
# (规则名, 正则, 替换串)
RULES = [
    # 1) 页眉: 必须**贪婪吃到行尾** —— 页脚常与页眉同处一行, 非贪婪会漏掉后半截
    #    "2009 年全国硕士研究生入学统一考试…专业基础综合试题 第2页，共10页"
    ("页眉页脚", re.compile(r"\d{4}\s*年全国硕士研究生(?:入学)?统一考试[^\n]*"), ""),
    # 2) 独立出现的页脚: "第 2 页（共 10 页）"
    ("页脚", re.compile(r"第\s*\d+\s*页\s*[（(]?\s*共\s*\d+\s*页[）)]?"), ""),
    # 3) 章节标题: "二、综合应用题（第41～47 题，共70 分）"
    ("章节标题", re.compile(r"[一二三四五六七八九十]\s*、\s*[^\n]*?(?:单项选择题|综合应用题)[^\n]*"), ""),
    # 4) 上标还原: 基数 + 换行 + 独占一行的数字 -> ^数字
    #    指数后面可能是换行、运算符、或(在选项里)字符串结尾, 三种都要允许
    ("上标还原", re.compile(
        rf"([A-Za-z0-9)\]）])\n[ \t]*(\d{{1,3}})[ \t]*(?=\n|[{OPS}]|$)"), r"\1^\2"),
    # 5) 孤立运算符独占一行: "…\n×\n…" -> " × "
    ("孤立运算符", re.compile(r"\n[ \t]*([×*·÷])[ \t]*\n"), r" \1 "),
    # 6) 换行紧贴数学运算符 -> 化为空格(仅收紧排版, 不改语义)
    ("运算符换行", re.compile(rf"\n[ \t]*(?=[{OPS}])|(?<=[{OPS}])[ \t]*\n[ \t]*"), " "),
]


def clean(s):
    """返回 (清洗后文本, {规则名: 命中次数})"""
    hits = {}
    for name, pat, rep in RULES:
        s, n = pat.subn(rep, s)
        if n:
            hits[name] = hits.get(name, 0) + n
    # 收尾: 合并多余空行/行首行尾空白
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    s = re.sub(r"[ \t]{2,}", " ", s)
    return s.strip(), hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    total_hits = {}
    changed_q = 0
    changed_field = 0
    samples = []
    files = sorted(glob.glob(os.path.join(SRC, "20[0-9][0-9].json")))

    if not args.dry_run:
        os.makedirs(BAK, exist_ok=True)

    for f in files:
        y = os.path.basename(f)[:4]
        d = json.load(open(f, encoding="utf-8"))
        touched = False
        for r in d["题目"]:
            qhit = {}
            new, h = clean(r["题干"])
            if new != r["题干"]:
                qhit.update(h)
                if not args.dry_run:
                    r["题干"] = new
                touched = True
            for k, v in list((r.get("选项") or {}).items()):
                nv, h2 = clean(v)
                if nv != v:
                    for kk, vv in h2.items():
                        qhit[kk] = qhit.get(kk, 0) + vv
                    if not args.dry_run:
                        r["选项"][k] = nv
                    touched = True
            if qhit:
                changed_q += 1
                changed_field += sum(qhit.values())
                for kk, vv in qhit.items():
                    total_hits[kk] = total_hits.get(kk, 0) + vv
                if len(samples) < 4:
                    samples.append((r["id"], qhit,
                                    (r["题干"][:110] if not args.dry_run else "") or ""))
        if touched and not args.dry_run:
            shutil.copy(f, os.path.join(BAK, f"{y}.json"))
            json.dump(d, open(f, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    mode = "干跑(未改文件)" if args.dry_run else "已应用(原文件备份至 .cache/backup/)"
    print(f"=== 文本清洗 {mode} ===")
    print(f"  受影响题目: {changed_q} / {len(files)*47}  ({changed_q/(len(files)*47)*100:.1f}%)")
    print(f"  修复处数  : {changed_field}")
    print("\n  按规则:")
    for k, v in sorted(total_hits.items(), key=lambda x: -x[1]):
        print(f"    {v:>5} 处   {k}")


if __name__ == "__main__":
    main()
