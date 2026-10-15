#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
**投票得到的答案** —— 独立存档、可重复应用，避免被重解析冲掉。

为什么要有这个文件
------------------
答案有两个来源，原来都存在"会被重解析冲掉"的问题：
  · 投票结果原来只写回 `<年份>.json`（题目文件）
  · 而 `parse_zhengzhi.py --write` 会**整个重写**题目文件

我因此**丢了三次答案**（2026 的人工答案 1 次、投票结果 2 次）。
根治办法：把答案从题目文件里**分离出来**，做成可重复应用的派生数据。
本文件是"投票来源"，`zz_manual_answers.py` 是"人工核对来源"。

数据形态
--------
    第  1 题 [单项] 题源 None → 投票 C（3/3）**已修正**
    ...
    修正 33 道｜存疑 0 道 （无）
    已写回 /path/data/zhengzhi/2010.json      ← 年份标记在段落**末尾**

**这是踩过的坑**：写回标记在段末而不是段首。原来的解析器"遇到标记就把它
当成后续条目的年份"，结果**每一段的答案都被归给了下一年**，
最后一段（2025）没有下一年、整年丢失。

用法
----
    .venv/bin/python scripts/zz_voted_answers.py                 # 应用固化数据
    .venv/bin/python scripts/zz_voted_answers.py --check         # 只看差异
    .venv/bin/python scripts/zz_voted_answers.py --from-log F    # 从日志重新解析
"""
import argparse
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
DEST = os.path.join(BASE, "data", "zhengzhi")

SOURCE = "多轮投票（3 轮独立作答，多数表决）"

ENTRY = re.compile(r'第\s*(\d+)\s*题\s*\[(单项|多项)\][^\n]*?投票\s*'
                   r'([A-Da-dＡ-Ｄ]{1,4})\s*（(\d)/(\d)）')
WRITEBACK = re.compile(r'已写回\s+\S*?(\d{4})\.json')


def _norm(s):
    out = []
    for c in s:
        o = ord(c)
        if 0xFF21 <= o <= 0xFF3A:
            c = chr(o - 0xFF21 + ord("A"))
        elif 0xFF41 <= o <= 0xFF5A:
            c = chr(o - 0xFF41 + ord("a"))
        out.append(c.upper())
    return "".join(out)


def load_logs(paths):
    """
    从多份投票日志合并出 {年份: {题号: 答案}}。

    要点：
      · **回填** —— 写回标记在段末，遇到它才把刚读到的条目归给该年
      · **累加** —— 同一年可能出现在多份日志里（我跑过好几轮），
        后来的值覆盖先前的（更新），但不能因为后一轮没跑到就丢掉前面的
    """
    out = {}
    for path in paths:
        if not os.path.exists(path):
            continue
        buf = []
        for line in open(path, encoding="utf-8"):
            e = ENTRY.search(line)
            if e:
                num, ans, yes, tot = e.group(1), _norm(e.group(3)), \
                    int(e.group(4)), int(e.group(5))
                # 只收全票或过半的（与 vote 脚本的 0.6 阈值一致）
                if tot and yes / tot >= 0.6:
                    buf.append((num, ans))
                continue
            m = WRITEBACK.search(line)
            if m and buf:
                d = out.setdefault(m.group(1), {})
                for k, v in buf:
                    d[k] = v
                buf = []
    return {y: v for y, v in out.items() if v}


# 日志路径（按时间顺序，后者覆盖前者）
LOGS = ["/tmp/vote3.log", "/tmp/vote_final2.log",
        "/tmp/vote_recover.log", "/tmp/vote_last.log"]

# ---- 固化数据：由 --from-log 生成，避免依赖 /tmp（那会被清掉）----
VOTED = {
    "2010": {
        "1": "A", "2": "C", "3": "D", "4": "C", "5": "A", "6": "D",
        "7": "A", "8": "C", "9": "B", "10": "B", "11": "B", "12": "C",
        "13": "B", "14": "A", "15": "D", "16": "D", "17": "ACD",
        "18": "CD", "19": "ACD", "20": "BCD", "21": "ABC", "22": "ABD",
        "23": "ABCD", "24": "BCD", "25": "ACD", "26": "AB", "27": "ABCD",
        "28": "ABD", "29": "ACD", "30": "BCD", "31": "BD", "32": "ABCD",
        "33": "ABC"
    },
    "2011": {
        "1": "C", "2": "D", "3": "D", "4": "B", "5": "A", "6": "C",
        "7": "A", "8": "A", "9": "B", "10": "B", "11": "B", "12": "C",
        "13": "C", "14": "D", "15": "D", "16": "A", "17": "AB",
        "18": "ABC", "19": "AB", "20": "CD", "21": "AC", "22": "ABC",
        "23": "ABCD", "24": "ACD", "25": "ABCD", "26": "BCD", "27": "BD",
        "28": "AC", "29": "BCD", "30": "ACD", "31": "AB", "32": "ABCD",
        "33": "ABCD"
    },
    "2012": {
        "1": "A", "2": "B", "3": "B", "4": "C", "5": "D", "6": "D",
        "7": "A", "8": "B", "9": "D", "10": "C", "11": "B", "12": "D",
        "13": "A", "14": "C", "15": "D", "16": "C", "17": "BCD",
        "18": "ABC", "19": "CD", "20": "ABD", "21": "ABCD", "22": "ABD",
        "23": "BD", "24": "ABD", "25": "ABCD", "26": "BC", "27": "ABC",
        "28": "ABC", "29": "ABCD", "30": "ACD", "31": "ABCD",
        "32": "ABC", "33": "BCD"
    },
    "2013": {
        "1": "A", "2": "C", "3": "A", "4": "B", "5": "D", "6": "A",
        "7": "B", "8": "A", "9": "D", "10": "D", "11": "B", "12": "C",
        "13": "B", "14": "C", "15": "C", "16": "D", "17": "ACD",
        "18": "ABD", "19": "CD", "20": "ABD", "21": "ACD", "22": "BCD",
        "23": "ABD", "24": "ABCD", "25": "ACD", "26": "ABCD",
        "27": "ACD", "28": "ABC", "29": "ACD", "30": "ABD", "31": "BC",
        "32": "BCD", "33": "ACD"
    },
    "2014": {
        "1": "B", "2": "C", "3": "B", "4": "C", "5": "B", "6": "A",
        "7": "B", "8": "A", "9": "D", "10": "A", "11": "C", "12": "D",
        "13": "A", "14": "D", "15": "D", "16": "C", "17": "ABD",
        "18": "AD", "19": "ABC", "20": "AC", "21": "BCD", "22": "AB",
        "23": "ABD", "24": "BCD", "25": "ABD", "26": "ABCD", "27": "BCD",
        "28": "BC", "29": "AB", "30": "AD", "31": "ABCD", "32": "ABCD",
        "33": "ACD"
    },
    "2015": {
        "4": "A", "7": "A", "9": "A", "13": "A", "16": "D", "17": "AD",
        "18": "ACD", "20": "ABC", "22": "ACD", "23": "AC", "24": "ABD",
        "25": "ACD", "26": "ABCD", "28": "ABD", "29": "CD", "30": "ABC",
        "32": "ABCD", "33": "ABD"
    },
    "2016": {
        "1": "B", "2": "D", "3": "A", "4": "C", "5": "C", "6": "B",
        "7": "B", "8": "A", "9": "B", "10": "C", "11": "D", "12": "C",
        "13": "B", "14": "D", "15": "C", "16": "B", "17": "AC",
        "18": "ABD", "19": "ABC", "20": "ABD", "21": "AC", "22": "BCD",
        "23": "CD", "24": "ABC", "25": "ABCD", "26": "ABC", "28": "ABC",
        "29": "ABCD", "31": "ABD", "32": "ABCD", "33": "ABD"
    },
    "2017": {
        "1": "C", "2": "A", "3": "B", "4": "C", "5": "B", "6": "B",
        "7": "C", "8": "A", "9": "D", "10": "B", "11": "A", "12": "A",
        "13": "D", "14": "C", "15": "D", "16": "B", "17": "ACD",
        "18": "ABC", "19": "ABCD", "20": "ABD", "21": "ABD", "22": "ABD",
        "23": "ABCD", "24": "ABC", "25": "BCD", "26": "AC", "27": "ABC",
        "28": "AB", "31": "ABCD", "32": "ACD", "33": "BCD"
    },
    "2018": {
        "1": "C", "2": "A", "3": "B", "4": "C", "5": "B", "6": "B",
        "7": "C", "8": "A", "9": "D", "10": "B", "11": "A", "12": "A",
        "13": "D", "14": "C", "15": "D", "16": "B", "17": "ACD",
        "18": "ABC", "19": "ABCD", "20": "ABD", "21": "ABD", "22": "ABD",
        "23": "ABCD", "24": "ABC", "25": "BCD", "26": "AC", "27": "ABC",
        "28": "AB", "29": "ABCD", "30": "ABC", "31": "ABC", "32": "ACD",
        "33": "BCD"
    },
    "2019": {
        "1": "A", "2": "A", "3": "A", "4": "B", "5": "C", "6": "C",
        "7": "B", "8": "D", "9": "A", "10": "C", "11": "B", "12": "D",
        "13": "B", "14": "D", "15": "C", "16": "D", "17": "BD",
        "18": "ABCD", "19": "ABC", "20": "ABD", "21": "ACD", "22": "ABC",
        "23": "ABC", "24": "ABC", "25": "ABD", "26": "ABCD",
        "27": "ABCD", "28": "ABC", "29": "AC", "30": "ACD", "31": "ACD",
        "32": "ABCD", "33": "ABCD"
    },
    "2020": {
        "1": "C", "2": "D", "3": "D", "4": "A", "5": "C", "6": "A",
        "7": "B", "8": "B", "9": "D", "10": "A", "11": "B", "12": "A",
        "13": "B", "14": "A", "15": "C", "16": "C", "17": "AB",
        "18": "BC", "19": "AD", "20": "ACD", "21": "ABD", "22": "ACD",
        "23": "ABC", "24": "ABCD", "25": "ABCD", "26": "ACD",
        "27": "ABD", "28": "ABC", "29": "BCD", "30": "ABCD", "31": "BCD",
        "32": "ACD", "33": "ABCD"
    },
    "2021": {
        "1": "A", "2": "A", "3": "C", "4": "D", "5": "A", "6": "C",
        "7": "C", "8": "A", "9": "C", "10": "D", "11": "D", "12": "C",
        "13": "B", "14": "C", "15": "B", "16": "D", "17": "AD",
        "18": "CD", "19": "AB", "20": "ACD", "21": "ABCD", "22": "BCD",
        "23": "ABC", "24": "ABD", "25": "ABC", "26": "ABCD", "27": "AC",
        "28": "ABC", "29": "ABCD", "30": "ABCD", "31": "ABC",
        "32": "ABCD", "33": "ABD"
    },
    "2022": {
        "1": "C", "2": "B", "3": "D", "4": "A", "5": "B", "6": "A",
        "7": "D", "8": "D", "9": "A", "10": "D", "11": "C", "12": "C",
        "13": "C", "14": "B", "15": "A", "16": "D", "17": "BD",
        "18": "CD", "19": "ABD", "20": "AB", "21": "AB", "22": "ABD",
        "23": "BCD", "24": "BCD", "25": "ACD", "26": "ABCD", "27": "BCD",
        "28": "ABC", "29": "AC", "30": "ACD", "31": "ABC", "32": "ABCD",
        "33": "ABC"
    },
    "2023": {
        "1": "A", "2": "C", "3": "C", "4": "A", "5": "D", "6": "C",
        "7": "D", "8": "B", "9": "A", "10": "D", "11": "A", "12": "B",
        "13": "C", "14": "A", "15": "B", "16": "D", "17": "ABC",
        "18": "BD", "19": "ABC", "20": "AC", "21": "AB", "22": "AB",
        "23": "ABCD", "24": "BCD", "25": "ACD", "26": "BD", "27": "ACD",
        "28": "CD", "29": "ABCD", "30": "AB", "31": "AC", "32": "ABCD",
        "33": "BCD"
    },
    "2024": {
        "1": "A", "2": "C", "3": "D", "4": "D", "5": "A", "6": "A",
        "7": "B", "8": "C", "9": "B", "10": "B", "11": "A", "12": "C",
        "13": "B", "14": "C", "15": "D", "16": "D", "17": "ABD",
        "18": "AC", "19": "AC", "20": "BC", "21": "ABD", "22": "BCD",
        "24": "ABCD", "25": "ABC", "26": "ABD", "27": "ABD", "28": "ACD",
        "29": "ABD", "30": "ABC", "31": "ABD", "32": "ABCD", "33": "ACD"
    },
    "2025": {
        "1": "C", "2": "B", "3": "D", "4": "C", "5": "B", "6": "C",
        "7": "A", "8": "D", "9": "A", "10": "B", "11": "A", "12": "A",
        "13": "B", "14": "C", "15": "D", "16": "D", "17": "CD",
        "18": "AD", "19": "AC", "20": "ABD", "21": "BCD", "22": "BCD",
        "23": "ABD", "24": "ABCD", "25": "ABC", "26": "ACD", "27": "AD",
        "28": "AC", "29": "ACD", "30": "ACD", "31": "BD", "32": "ABCD",
        "33": "ABC"
    },
}

def apply(voted, check_only=False, force=False):
    """
    force=False（默认）：**只补空缺** —— 题源已有答案就不动（题源是一手来源）。
    force=True         ：投票值覆盖已有值。用于"题干被重新解析过、旧答案已过期"
                          的情形（我改过多次解析规则，题目切分变了，
                          旧答案就对不上题了）。
    """
    total = 0
    for year, answers in sorted(voted.items()):
        path = os.path.join(DEST, f"{year}.json")
        if not os.path.exists(path):
            print(f"  {year}: 题目文件不存在，跳过")
            continue
        rec = json.load(open(path, encoding="utf-8"))
        n_new = n_same = n_conflict = 0
        for q in rec["题目"]:
            k = str(q.get("题号"))
            if k not in answers:
                continue
            want = answers[k]
            old = q.get("答案")
            if old == want:
                n_same += 1
                continue
            if old is not None and not force:
                # 题源自带的答案是一手来源，比投票可靠。冲突留给人复核，
                # 不该让程序默默选一个。
                n_conflict += 1
                continue
            q["答案"] = want
            q["答案来源"] = SOURCE
            n_new += 1
        if not check_only:
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(rec, f, ensure_ascii=False, indent=1)
            os.replace(tmp, path)
        print(f"  {year}: 写入 {n_new} | 已一致 {n_same}"
              f" | 冲突未覆盖 {n_conflict} → 投票数据 {len(answers)} 条")
        total += n_new
    print(f"\n共写入 {total} 个答案"
          + ("（仅检查，未写入）" if check_only else ""))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="投票值覆盖已有答案（用于旧答案已过期时）")
    ap.add_argument("--from-log", default=None,
                    help="从这些日志重新解析（逗号分隔）；默认用文件内固化数据")
    ap.add_argument("--dump", action="store_true",
                    help="把解析结果打印成可粘贴的 VOTED 字面量")
    args = ap.parse_args()

    if args.from_log:
        paths = [p.strip() for p in args.from_log.split(",") if p.strip()]
        voted = load_logs(paths)
        got = sum(len(v) for v in voted.values())
        print(f"从 {len(paths)} 份日志解析出 {len(voted)} 年 / {got} 条\n")
        if args.dump:
            print("VOTED = {")
            for y in sorted(voted):
                items = [f'"{k}": "{voted[y][k]}"'
                         for k in sorted(voted[y], key=int)]
                print(f'    "{y}": {{')
                cur = "        "
                for it in items:
                    if len(cur) + len(it) > 72:
                        print(cur.rstrip()); cur = "        "
                    cur += it + ", "
                print(cur.rstrip().rstrip(","))
                print("    },")
            print("}")
            return 0
        return apply(voted, args.check, args.force)

    if not VOTED:
        print("VOTED 为空 —— 请先用 --from-log 填充（可加 --dump 生成字面量）",
              file=sys.stderr)
        return 1
    return apply(VOTED, args.check, args.force)


if __name__ == "__main__":
    sys.exit(main())
