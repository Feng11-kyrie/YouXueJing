#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
预跑(路演兜底) —— ⚠️ **已弃用，2026-10-14 由用户决定删除该功能**。

弃用原因（用户原话）：
    "把这个回放快照删去，然后在运行多智能体链路的时候过程不要显示，
     用户又不会看这个"

因此界面上「回放快照（路演兜底）」以及配套的 data/prewarm/ 快照文件都已删除。
**不要再用本脚本生成快照** —— 除非先想清楚：

    删除兜底意味着路演现场失去容错：断网 / API 挂 / 额度用尽 / 模型卡住时，
    多智能体演示会直接失败。用户明确选择接受这个风险。

本文件仍然保留的原因只有一个：`seed_user()` 被 .workbuddy/reseed_demo.py
复用（按固定画像重建演示用户），删掉会连带弄坏那个工具。

原始设计说明（留档）：
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

from yj import store, graph, llm, data, snap    # noqa: E402

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
    # 必须过 snap.to_jsonable: 链路状态里的 marks 是 set, json.dump 会直接抛
    # TypeError(而且在跑完 6 个 Agent 之后才崩)。见 yj/snap.py 的说明。
    os.makedirs(SNAP_DIR, exist_ok=True)
    snap_obj = {
        "名称": args.name,
        "生成时间": datetime.datetime.now().isoformat(timespec="seconds"),
        "用户": args.user,
        "画像设定": args.profile,
        "选中路径": args.path,
        "LLM已配置": ok,
        "内容来源": srcs,
        "结果": r,
    }
    # 先序列化到内存再写盘: 万一还有未知类型, 报错不会留下**半个损坏的快照文件**
    # (之前就是这么坏了一份 roadshow.json, 界面回放时才炸)。
    payload = json.dumps(snap.to_jsonable(snap_obj), ensure_ascii=False, indent=2)
    dst = os.path.join(SNAP_DIR, f"{args.name}.json")
    with open(dst, "w", encoding="utf-8") as f:
        f.write(payload)
    # 写完立刻读回校验一遍: 兜底机制必须自己先被验证
    with open(dst, encoding="utf-8") as f:
        back = json.load(f)
    assert back["结果"]["resources"] == json.loads(
        json.dumps(snap.to_jsonable(r), ensure_ascii=False))["resources"], \
        "快照读回与源数据不一致"
    size = os.path.getsize(dst)
    print(f"\n快照已保存并读回校验通过: {dst}  ({size:,} 字节)")
    print("现场如遇 API 不可用, 在界面「⑤ 讲义生成」选择该快照回放即可。")


if __name__ == "__main__":
    main()
