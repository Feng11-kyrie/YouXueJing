#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把抽到的插图挂到题目上, 并区分「有图」与「缺图」。

字段约定
--------
图片     : 插图文件路径(有则填), 如 "figures/408-2024-07.png"
需插图   : 该题是否需要展示插图 = 正文有插图引用 或 已抽到图
_图片依据: 题注 / 题干引用 / 需插图标记 / 就近回落(置信度递减)
_缺图     : 正文引用了插图但没抽到图 -> 需人工补或显示占位符

区分 需插图 与 图片 的意义: 前者是"要占版面显示图", 后者是"我们真的有这张图"。
两者之差就是已知缺口, 显式记录以便审计。
"""
import os, re, json, glob, shutil, sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(BASE, "data", "408")
BAK = os.path.join(BASE, ".cache", "backup_fig")
sys.path.insert(0, os.path.join(BASE, "scripts"))
from parse_408 import FIG_RE


def main():
    os.makedirs(BAK, exist_ok=True)
    mp = json.load(open(os.path.join(SRC, "figure_map.json"), encoding="utf-8"))["映射"]
    n_fig = n_need = n_miss = 0
    for f in sorted(glob.glob(os.path.join(SRC, "20[0-9][0-9].json"))):
        y = os.path.basename(f)[:4]
        d = json.load(open(f, encoding="utf-8"))
        touch = False
        for r in d["题目"]:
            qid = r["id"]
            txt = r["题干"] + "".join((r.get("选项") or {}).values())
            quoted = bool(FIG_RE.search(txt))
            has = qid in mp
            need = quoted or has
            for k in ("图片", "_图片依据", "_缺图"):
                if k in r:
                    del r[k]; touch = True
            if has:
                r["图片"] = f"figures/{qid}.png"
                r["_图片依据"] = mp[qid].get("依据")
                n_fig += 1
            elif quoted:
                r["_缺图"] = True
                n_miss += 1
            if need:
                n_need += 1
            if r.get("需插图") != need:
                r["需插图"] = need
                touch = True
            elif has or quoted:
                touch = True
        if touch:
            shutil.copy(f, os.path.join(BAK, f"{y}.json"))
            json.dump(d, open(f, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    print(f"挂图 {n_fig} 题  需插图 {n_need} 题  缺图(有引用无图) {n_miss} 题")
    print(f"原文件备份: .cache/backup_fig/")


if __name__ == "__main__":
    main()
