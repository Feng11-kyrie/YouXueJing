#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
重算全部题目的「需插图」标记。

原标记有两类错误(实测):
  漏报 2 题: 「如下无向图」「如下有向图」未被旧正则匹配
  误报 22 题: 「位图中」「有向图中」「该图拓扑序列」等 —— 这里的"图"指图论/位图,
              不是插图。旧正则的 `图中`/`该图`/`如下所示` 过宽。
另有 3 道单选题的**选项本身就是图片**(如 2009-04 的四棵二叉树), 也计入需插图。
"""
import os, re, json, glob, shutil

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(BASE, "data", "408")
BAK = os.path.join(BASE, ".cache", "backup_flag")
import sys
sys.path.insert(0, os.path.join(BASE, "scripts"))
from parse_408 import FIG_RE


def main():
    os.makedirs(BAK, exist_ok=True)
    added, removed = [], []
    for f in sorted(glob.glob(os.path.join(SRC, "20[0-9][0-9].json"))):
        y = os.path.basename(f)[:4]
        d = json.load(open(f, encoding="utf-8"))
        touch = False
        for r in d["题目"]:
            t = r["题干"] + "".join((r.get("选项") or {}).values())
            new = bool(FIG_RE.search(t))
            if r["题型"] == "单项选择题" and len(r.get("选项") or {}) < 4:
                new = True                      # 选项为图片
            if new != r.get("需插图"):
                (added if new else removed).append((y, r["题号"]))
                r["需插图"] = new
                touch = True
        if touch:
            shutil.copy(f, os.path.join(BAK, f"{y}.json"))
            json.dump(d, open(f, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    tot = sum(len(json.load(open(f, encoding="utf-8"))["题目"])
              for f in glob.glob(os.path.join(SRC, "20[0-9][0-9].json")))
    need = sum(1 for f in glob.glob(os.path.join(SRC, "20[0-9][0-9].json"))
               for r in json.load(open(f, encoding="utf-8"))["题目"] if r.get("需插图"))
    print(f"新增标记 {len(added)} 题: {added}")
    print(f"移除标记 {len(removed)} 题: {removed[:30]}{' …' if len(removed)>30 else ''}")
    print(f"\n需插图合计: {need} / {tot} 题")


if __name__ == "__main__":
    main()
