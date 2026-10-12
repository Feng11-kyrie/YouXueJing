#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
预跑(路演兜底)。

路演最怕的两件事:
  1. 现场调 LLM API 转圈 → 冷场
  2. 断网 / API 挂 / 额度用尽 → 演示直接失败

做法: 提前把演示用的那条链路完整跑一遍, 落成两种兜底:
  ① LLM 缓存  —— 存进 store.cache, 之后同样的调用直接命中, 秒出
  ② 状态快照  —— 把整条多智能体链路的完整输出存成 JSON,
                 现场即使 API 完全不可用, 也能一键回放同样的结果

用法:
  python scripts/prewarm.py --user demo --profile "DS:0.8,CO:0.65,OS:0.5,CN:0.35"
  python scripts/prewarm.py --name roadshow        # 指定快照名
"""
import os
import sys
import json
import argparse
import datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from yj import store, graph, llm, data          # noqa: E402

SNAP_DIR = os.path.join(BASE, "data", "prewarm")


def seed_user(user_id, profile_str):
    """按给定画像生成一套作答记录(与诊断题单一致)"""
    from demo import simulate
    answers, _detail = simulate(profile_str)
    store.reset_user(user_id)
    for qid, a in answers.items():
        store.record_answer(user_id, qid, a["chosen"], a["is_correct"],
                            source="diagnostic")
    return len(answers)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", default="demo", help="演示用户 id")
    ap.add_argument("--profile", default="DS:0.80,CO:0.65,OS:0.50,CN:0.35",
                    help='模拟画像, 如 "DS:0.8,CN:0.35"')
    ap.add_argument("--name", default="roadshow", help="快照名")
    ap.add_argument("--path", default="root", help="选中哪条路径: root/freq/wrong")
    args = ap.parse_args()

    store.init_db()
    ok, msg = llm.status()
    print(f"LLM 状态: {msg}")

    n = seed_user(args.user, args.profile)
    print(f"已为 {args.user} 写入 {n} 条诊断作答（画像 {args.profile}）")

    print("开始预跑多智能体链路…")
    r = graph.run(args.user, selected_path=args.path)

    print("\n执行轨迹:")
    for t in r.get("traced", []):
        print(f"  {t['agent']:<10} {t['detail']}")

    res = r.get("resources") or []
    srcs = sorted({x["讲义"]["source"] for x in res})
    print(f"\n生成 {len(res)} 个考点的资源, 内容来源: {srcs}")
    if srcs == ["template"]:
        print("  说明: 未配置 LLM API, 快照记录的是**模板模式**输出。")
        print("        配置 key 后重跑本脚本, 快照就会变成 LLM 生成内容。")

    # ---- 落快照
    os.makedirs(SNAP_DIR, exist_ok=True)
    snap = {
        "名称": args.name,
        "生成时间": datetime.datetime.now().isoformat(timespec="seconds"),
        "用户": args.user,
        "画像设定": args.profile,
        "选中路径": args.path,
        "LLM已配置": ok,
        "内容来源": srcs,
        "结果": r,
    }
    dst = os.path.join(SNAP_DIR, f"{args.name}.json")
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False, indent=2)
    size = os.path.getsize(dst)
    print(f"\n快照已保存: {dst}  ({size:,} 字节)")
    print("现场如遇 API 不可用, 在界面「⑤ 资源生成」选择该快照回放即可。")


if __name__ == "__main__":
    main()
