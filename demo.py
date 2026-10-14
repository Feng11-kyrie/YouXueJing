#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
命令行演示: 模拟一个用户做完诊断, 跑通「诊断 → 掌握度 → 画像 → 路径」。

用法:
  python demo.py                # 用内置的模拟画像
  python demo.py --profile "DS:0.9,CO:0.7,OS:0.5,CN:0.35"
"""
import argparse
import random
import json

from yj import data, store, diagnose, profile, path


def simulate(profile_str=None, seed=42):
    """
    模拟作答: 按学科设定"真实水平", 逐题决定对错。
    难度会微调正确率 —— 难题更容易错, 让模拟更接近真实。
    """
    levels = {"DS": 0.80, "CO": 0.65, "OS": 0.50, "CN": 0.35}
    if profile_str:
        for part in profile_str.split(","):
            k, v = part.split(":")
            levels[k.strip().upper()] = float(v)
    rng = random.Random(seed)
    answers, detail = {}, []
    for item in data.diagnostic()["题目"]:
        code = item["学科码"]
        base = levels.get(code, 0.6)
        # 难度 2 -> +0.08, 难度 3 -> 0 ; 难度 4 -> -0.08
        adj = {1: 0.15, 2: 0.08, 3: 0.0, 4: -0.08, 5: -0.15}.get(item["难度"], 0.0)
        p = min(0.97, max(0.03, base + adj))
        correct = rng.random() < p
        # 答错时要记一个**错误选项**，不能记成 None。
        # 曾经这里写的是 `item["答案"] if correct else None`，于是：
        #   ① 播种出来的画像是"10 道题没作答"，而不是"10 道题答错"；
        #   ② 那些 chosen=None 的行被算进"已作答"，还占掉题目记录，
        #      用户在界面上无法重做（要手工清库）。
        # 答错 ≠ 没作答，这两个状态必须分开。
        if correct:
            chosen = item["答案"]
        else:
            opts = sorted((data.questions()[item["id"]].get("选项") or {}).keys())
            wrong = [k for k in opts if k != item["答案"]]
            chosen = rng.choice(wrong) if wrong else item["答案"]
        answers[item["id"]] = {"chosen": chosen,
                               "is_correct": correct, "source": "diagnostic"}
        detail.append((item, correct))
    return answers, detail


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", help='模拟水平, 如 "DS:0.9,CO:0.7,OS:0.5,CN:0.35"')
    ap.add_argument("--verbose", action="store_true", help="逐题打印作答结果")
    args = ap.parse_args()

    print("=" * 78)
    o = data.overview()
    print("优学鲸 · 诊断闭环演示")
    print(f"数据层: {o['题目总数']} 题 / {o['年份范围']} / "
          f"{o['叶子考点']} 考点 / {o['依赖边']} 条依赖边 / 诊断题 {o['诊断题数']} 道")
    print("=" * 78)

    answers, detail = simulate(args.profile)

    if args.verbose:
        print("\n【第 1 步】诊断作答（模拟）")
        for item, ok in detail:
            print(f"  {'✓' if ok else '✗'} {item['order']:>2}. {item['id']}  "
                  f"{item['学科'][:4]}·{item['诊断章节名'][:10]:<12} 难度{item['难度']}")

    n_ok = sum(1 for _i, ok in detail if ok)
    print(f"\n【第 1 步】诊断完成：{n_ok}/{len(detail)} 题正确 "
          f"({n_ok/len(detail):.0%})")

    print("\n【第 2 步】章节掌握度（Laplace 平滑）")
    m = diagnose.summarize(answers)
    for code in ("DS", "CO", "OS", "CN"):
        rows = [c for c in m["章节"].values() if c["学科码"] == code]
        if not rows:
            continue
        print(f"\n  {data.CODE2NAME[code]}")
        for c in sorted(rows, key=lambda x: x["掌握度"]):
            bar = "█" * int(c["掌握度"] * 20)
            print(f"    {c['章节名'][:14]:<16} {c['掌握度']:>5.0%}  {bar:<20} "
                  f"({c['答对']}/{c['题数']})")

    print("\n【第 3 步】用户画像")
    prof = profile.build(answers)
    print(f"  {prof['文字画像']}")
    if prof["薄弱章节"]:
        print("\n  薄弱章节（按 考频 × 未掌握度 排序，即「性价比」）:")
        for c in prof["薄弱章节"][:5]:
            print(f"    {c['章节名'][:14]:<16} 掌握度{c['掌握度']:>5.0%}  "
                  f"考频{c['考频']:>3}  优先级分{c['优先级分']:>5}")

    print("\n【第 4 步】排定该补哪些考点（内部由路径 Agent 完成；"
          "对外不再暴露「学习路径」页面 —— 用户判断该页用处不大）")
    rec = path.recommend(answers)
    for p in rec["路径"]:
        print(f"\n  ── 路径「{p['名称']}」  预计 {p['合计分钟']} 分钟"
              f"  （{p['适用']}）")
        print(f"     {p['说明']}")
        for i, s in enumerate(p["步骤"], 1):
            flag = "" if s["是否已测"] else " [未测]"
            print(f"       {i}. {s['考点名'][:22]:<24} {s['章节'][:10]:<12} "
                  f"当前{s['当前掌握度']:>5.0%}{flag}  {s['预计分钟']:>3}分钟  "
                  f"考频{s['考频']:>2}  可练{s['可练真题']:>2}题")
            print(f"          理由：{s['推荐理由']}")


if __name__ == "__main__":
    main()
