#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用**多次独立求解投票**确定政治客观题的答案（题源不可信时的唯一可靠办法）。

为什么需要投票
--------------
实测（2015 年那份"真题及答案"PDF）：

    单选 1–16   题源 15/16 与独立求解一致 → 题源基本可靠
    多选 17–33  题源**约 5/17 与独立求解不一致** → 题源错误率约 30%

典型错例（我逐题核过原文）：
    第 17 题 题源标 ABC，正确是 AD —— 选项 C「事物发展总是呈现线性上升的态势」
              是形而上学表述，明显错项，题源却把它算进答案
    第 18 题 题源标 ABCD，正确是 ABD —— 同一个"线性"陷阱
    第 16 题 题源标 A，正确是 D

**而单个 LLM 也不可靠**：它在第 16 题答对、在第 20 题可能是它自己错。
所以既不能信题源、也不能信单次求解，只能**多次求解投票**：
一致票数达到阈值才采纳；票数分散的题标为"存疑"，不入库。

用法：
    .venv/bin/python scripts/vote_zz_answers.py --year 2015 --rounds 3
    .venv/bin/python scripts/vote_zz_answers.py --year 2015 --rounds 3 --write
"""
import argparse
import collections
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from yj import llm                                   # noqa: E402

ZZ_DIR = os.path.join(BASE, "data", "zhengzhi")


def ask(it, year, rnd):
    """问一次。rnd 进 payload，避免不同轮次命中同一缓存（那样投票就没意义了）"""
    opts = "\n".join(f'{k}. {v}' for k, v in sorted(it["选项"].items()))
    kind = ("单选（只有一个正确）" if it["题型"] == "单项选择题"
            else "多选（有 2-4 个正确）")
    p = f"""你是考研政治阅卷老师。下面是一道{kind}题，请只根据题干和选项独立作答。

【题干】{it['题干']}
【选项】
{opts}

注意：选项里若有绝对化表述（"总是""必然""完全""唯一"等），通常是错误项。

先写 1-2 句判断依据，最后一行单独输出「我的答案：X」（多选形如「我的答案：ABD」）。"""
    r = llm.complete("zz_vote", p, payload={"y": str(year), "n": it["题号"],
                                           "r": rnd, "v": 1})
    import re
    m = re.search(r'我的答案[:：]\s*([A-D]{1,4})', r.get("text") or "")
    return m.group(1) if m else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", required=True)
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    path = os.path.join(ZZ_DIR, f"{args.year}.json")
    rec = json.load(open(path, encoding="utf-8"))
    need = {"pass": 0.6}                      # 一致票占比阈值
    changed, doubtful = [], []

    for it in rec["题目"]:
        if it["题型"] not in ("单项选择题", "多项选择题"):
            continue
        votes = [v for v in (ask(it, args.year, r) for r in range(args.rounds)) if v]
        if not votes:
            doubtful.append(it["题号"])
            continue
        cnt = collections.Counter(votes)
        win, n = cnt.most_common(1)[0]
        ratio = n / len(votes)
        src = it.get("答案")
        if ratio < need["pass"]:
            # 票数分散 → 存疑，不改答案
            doubtful.append(it["题号"])
            it["答案存疑"] = True
            print(f"  第 {it['题号']:>2} 题 [{it['题型'][:2]}] 票数分散 "
                  f"{dict(cnt)} → 存疑，保留题源 {src}")
            continue
        if win != src:
            changed.append((it["题号"], src, win, ratio))
            print(f"  第 {it['题号']:>2} 题 [{it['题型'][:2]}] 题源 {src} → "
                  f"投票 {win}（{n}/{len(votes)}）**已修正**")
            it["答案"] = win
            it["答案来源"] = f"投票修正（原题源 {src}）"
        else:
            it.setdefault("答案来源", "题源与投票一致")

    print(f"\n修正 {len(changed)} 道｜存疑 {len(doubtful)} 道 "
          f"（{doubtful if doubtful else '无'}）")
    if args.write:
        json.dump(rec, open(path, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print(f"已写回 {path}")


if __name__ == "__main__":
    main()
