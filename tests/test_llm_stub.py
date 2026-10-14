#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用桩(stub)验证 LLM 通路 —— 不需要真实 API key。

为什么需要这个测试
------------------
没有 API key 时, 链路在 llm.complete() 里就短路到模板模式,
于是**缓存、重试、错误降级、来源标注这些分支从未被执行过** ——
"没报错"不等于"能工作"。

本测试把 openai.OpenAI 换成一个假客户端, 从而在不联网、不花钱的前提下验证:
  1. 配置读取(_secrets)
  2. 成功调用 → source="llm"
  3. **结果写进缓存; 二次调用命中缓存 → source="cache"**
  4. API 抛异常 → 重试 → 最终 source="error"(上层据此降级为模板)
  5. 缓存键对相同输入稳定、对不同输入不同
  6. 经 generate.lesson() 后, 讲义正文确实换成了 LLM 文本且来源标注正确
  7. 复核 Agent 对 LLM 文本仍然执行考纲校验

真实剩余风险: 只剩"真实网络调用本身"(鉴权/额度/模型名/响应格式),
这一层需要真 key 才能验证, 本测试不覆盖。

用法:  .venv/bin/python tests/test_llm_stub.py
"""
import os
import sys
import json
import tempfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

FAIL = []


def check(name, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {name}" + (f"   {detail}" if detail else ""))
    if not cond:
        FAIL.append(name)


# ---------------------------------------------------------------- 假客户端
class _Msg:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content):
        self.message = _Msg(content)


class _Resp:
    def __init__(self, content):
        self.choices = [_Choice(content)]


class FakeOpenAI:
    """记录被调用的参数, 可配置成抛异常/返回固定文本。"""
    calls = []
    fail_times = 0
    reply = "## 桩生成的讲义\n\n这是来自假客户端的内容。"

    def __init__(self, **kw):
        self.init_kw = kw
        self.chat = self

    @property
    def completions(self):
        return self

    def create(self, **kw):
        FakeOpenAI.calls.append(kw)
        if FakeOpenAI.fail_times > 0:
            FakeOpenAI.fail_times -= 1
            raise RuntimeError("模拟 API 失败")
        return _Resp(FakeOpenAI.reply)


def main():
    import openai
    from yj import llm, store, generate, data

    # 关键: 测试用**独立的数据库文件**, 绝不写生产缓存。
    # (曾因共用数据库, 把桩内容写进了生产缓存, 真实预跑命中后
    #  两份路演快照里混进了假内容 —— 这类污染排查起来很费劲。)
    store.DB = os.path.join(tempfile.gettempdir(), "yj_test_cache.db")
    if os.path.exists(store.DB):
        os.remove(store.DB)
    store.init_db()
    openai.OpenAI = FakeOpenAI                      # 打桩
    llm.time.sleep = lambda *_a: None               # 去掉重试等待

    print("=== 1) 未配置 key 时降级模板 ===")
    llm._secrets = lambda: {"base_url": "x", "model": "m", "timeout": 5,
                            "retries": 2, "temperature": 0.3}
    r = llm.complete("t_probe", "prompt", payload={"a": 1}, use_cache=False)
    check("无 key → source=template 且不调用 API",
          r["source"] == "template" and not FakeOpenAI.calls)

    print("\n=== 2) 配置 key 后成功调用 ===")
    llm._secrets = lambda: {"api_key": "sk-fake", "base_url": "https://x/v1",
                            "model": "fake-model", "timeout": 5,
                            "retries": 2, "temperature": 0.3}
    payload = {"leaf": "DS-07-07", "v": 1}
    r1 = llm.complete("t_stub", "prompt-A", payload=payload, use_cache=False)
    check("返回 source=llm", r1["source"] == "llm", f"got={r1['source']}")
    check("内容来自客户端", "桩生成的讲义" in (r1["text"] or ""))
    check("调用了 API 且带模型名",
          FakeOpenAI.calls and FakeOpenAI.calls[-1].get("model") == "fake-model")
    check("请求里带了 system+user 两条消息",
          len(FakeOpenAI.calls[-1]["messages"]) == 2)

    print("\n=== 3) 缓存：第二次同输入应命中 ===")
    n_before = len(FakeOpenAI.calls)
    r2 = llm.complete("t_stub", "prompt-A", payload=payload, use_cache=True)
    # 第一次用 use_cache=False 没写缓存 -> 这一轮应真实调用并写缓存
    r3 = llm.complete("t_stub", "prompt-A", payload=payload, use_cache=True)
    check("第三次命中缓存 source=cache", r3["source"] == "cache",
          f"got={r3['source']}")
    check("命中缓存后不再调用 API", len(FakeOpenAI.calls) == n_before + 1,
          f"额外调用 {len(FakeOpenAI.calls) - n_before} 次")
    check("缓存内容与首次一致", r3["text"] == r2["text"])

    print("\n=== 4) 缓存键稳定性 ===")
    k1 = llm._cache_key("t", {"a": 1, "b": 2})
    k2 = llm._cache_key("t", {"b": 2, "a": 1})       # 键序不同
    k3 = llm._cache_key("t", {"a": 1, "b": 3})
    check("同输入(忽略键序) → 同 key", k1 == k2)
    check("不同输入 → 不同 key", k1 != k3)

    print("\n=== 5) API 失败 → 重试 → 降级 error ===")
    FakeOpenAI.fail_times = 99                        # 一直失败
    n0 = len(FakeOpenAI.calls)
    r4 = llm.complete("t_fail", "prompt-fail", payload={"z": 9}, use_cache=False)
    tries = len(FakeOpenAI.calls) - n0
    check("最终 source=error", r4["source"] == "error", f"got={r4['source']}")
    check("按 retries 重试(1+2=3 次)", tries == 3, f"实际 {tries} 次")
    check("错误信息被带回", bool(r4.get("error")))
    FakeOpenAI.fail_times = 0

    print("\n=== 6) 重试后成功也算成功 ===")
    FakeOpenAI.fail_times = 1                         # 第一次失败, 第二次成功
    n0 = len(FakeOpenAI.calls)
    r5 = llm.complete("t_retry_ok", "p", payload={"r": 1}, use_cache=False)
    check("第 2 次成功 → source=llm", r5["source"] == "llm", f"got={r5['source']}")

    print("\n=== 7) 接进 generate.lesson()：正文与来源标注 ===")
    leaf = next(iter(data.leaf_ids()))
    out = generate.lesson(leaf, {}, use_llm=True)
    check("讲义来源为 llm/cache", out["source"] in ("llm", "cache"),
          f"got={out['source']}")
    check("正文出现桩内容", "桩生成的讲义" in out["markdown"])
    check("标注了 LLM 生成", "LLM 生成" in out["markdown"])
    check("附带了考纲校验结果", "通过" in (out.get("校验") or {}))
    check("校验对 LLM 文本确实执行了", isinstance(out["校验"].get("疑似考纲外"), list))

    print("\n=== 8) 复核 Agent 对 LLM 内容仍生效 ===")
    ok = data.freq()
    # 构造一个含考纲外小标题的讲义, 校验应能识别
    bad_md = "## 平衡二叉树\n\n**红黑树的自平衡旋转与颜色约束**\n\n**量子计算加速**\n"
    v = generate.verify(bad_md)
    check("能识别出考纲外内容", not v["通过"], f"疑似={v['疑似考纲外']}")
    check("不误报考纲内考点", "平衡二叉树" not in str(v["疑似考纲外"]))

    print("\n=== 9) 路演兜底：链路状态必须能存成 JSON 快照 ===")
    # 这一节是补一个真实翻过的车: 链路状态里的 marks 是 set, json.dump 直接抛
    # TypeError。它在预跑脚本**跑完 6 个 Agent、打印完复核通过之后**才崩,
    # 所以平时跑界面完全发现不了, 只在"路演现场想用快照兜底"时暴露。
    #
    # ⚠️ 必须给这个用户写入作答记录再过图: 没有作答也没有标记时, 条件边会走
    # "need_diagnosis" 分支直接返回 —— 那样 resources 为空, 断言会**空集通过**,
    # 等于什么都没测到(第一版本就是这么写的, 只序列化了 286 字节)。
    from yj import graph, snap
    gu = "stubtest_user"
    store.reset_user(gu)
    # 必须造出**有对有错**的作答: 全对时掌握度很高, 路径会正确地给出
    # 「暂无需补强」→ 0 个资源, 断言又会空集通过。这里按 3 对 1 错铺，
    # 保证确实有薄弱考点被推荐出来。
    for i, item in enumerate(data.diagnostic()["题目"]):
        q = data.questions()[item["id"]]
        right = (i % 4 != 0)
        if right:
            chosen = item["答案"]
        else:
            # 答错要记一个**真的错误选项**，不能写 None：
            # 数据层现在会丢弃 chosen 为空的作答（"没作答"≠"答错"），
            # 写 None 会让这条作答根本不存在 → 全变成答对 → 没有薄弱考点
            # → 资源 0 个，断言空集通过。（这个测试自己踩过一次）
            opts = [k for k in sorted((q.get("选项") or {}).keys())
                    if k != item["答案"]]
            chosen = opts[0] if opts else item["答案"]
        store.record_answer(gu, item["id"], chosen, right, source="diagnostic")
    st = graph.run(gu, selected_path="root")
    res = st.get("resources") or []
    check("条件边走到生成分支（确实产出了资源）", bool(res),
          f"{len(res)} 个考点")
    check("6 个 Agent 都留下轨迹", len(st.get("traced") or []) >= 6,
          "、".join(t["agent"] for t in st.get("traced") or []))
    try:
        payload = json.dumps(snap.to_jsonable(st), ensure_ascii=False)
        check("graph.run() 输出可 JSON 序列化", True, f"{len(payload):,} 字节")
    except TypeError as e:
        check("graph.run() 输出可 JSON 序列化", False, f"{e}")
    check("marks 已被归一化成列表（不再是 set）",
          not isinstance(snap.to_jsonable(st).get("marks"), set))
    check("序列化后资源数与原始一致",
          len(json.loads(json.dumps(snap.to_jsonable(st)))["resources"]) == len(res))

    print("\n=== 10) 数据层底线：不允许写入「没选答案的作答」 ===")
    # 这个坑来自 st.radio 默认选中第一项：用户直接点提交会写入 chosen=None 的
    # 记录，它会被算进"已作答"、被计为答错，还占掉该题记录导致无法重做。
    # 界面侧已拦一层，这里验证数据层也拦住了。
    bu = "stubtest_blank"
    store.reset_user(bu)
    store.record_answer(bu, "408-2026-01", None, False, source="practice")
    store.record_answer(bu, "408-2026-02", "", False, source="practice")
    store.record_answer(bu, "408-2026-03", "  ", False, source="practice")
    check("空值作答被丢弃", len(store.get_answers(bu)) == 0,
          f"写入 {len(store.get_answers(bu))} 条")
    store.record_answer(bu, "408-2026-04", "B", True, source="practice")
    check("正常作答仍然写入", len(store.get_answers(bu)) == 1)
    # 播种出的画像也不应含空作答（曾经 simulate 把答错记成 None）
    from demo import simulate
    seeded, _ = simulate("DS:0.80,CO:0.65,OS:0.50,CN:0.35")
    check("演示画像播种无空作答",
          all(v["chosen"] for v in seeded.values()),
          f"{sum(1 for v in seeded.values() if not v['chosen'])} 条为空")

    # 【原第 11 项已废弃】原来这里断言"data/prewarm 快照存在，否则路演没兜底"。
    # 2026-10-14 用户明确要求删除回放快照功能（含 data/prewarm/ 与界面按钮），
    # 所以"快照存在"不再是本项目的正确状态 —— 继续断言它反而会误导。
    # 换成验证**现在真正该守的不变量**：解析覆盖率。
    print("\n=== 11) 解析覆盖（真题/讲义都要能看到解析）===")
    import glob as _glob
    from yj import data as _data
    _data.solution_records.cache_clear()
    _data.choice_records.cache_clear()

    choice_files = _glob.glob(os.path.join(BASE, "data", "solutions", "*-choice.json"))
    n_choice = 0
    for f in choice_files:
        with open(f, encoding="utf-8") as fh:
            n_choice += len(json.load(fh).get("解答") or {})
    check("单选题解析已生成", n_choice >= 700,
          f"{n_choice} 道（{len(choice_files)} 个年份文件）")

    lv_files = [f for f in _glob.glob(os.path.join(BASE, "data", "solutions", "*.json"))
                if not f.endswith("-choice.json")]
    n_lv, missing = 0, []
    for f in lv_files:
        with open(f, encoding="utf-8") as fh:
            rec = json.load(fh)
        sol = rec.get("解答") or {}
        n_lv += len(sol)
        for num in range(41, 48):
            if str(num) not in sol:
                missing.append(f"{rec['年份']}-{num}")
    check("综合题解析 18 年全覆盖", not missing,
          f"{n_lv} 道" + (f"，缺 {missing[:6]}" if missing else "，无缺口"))

    # 讲义配套真题必须都能取到解析（否则界面上会显示"暂无解析"）。
    # 注意：不能用 graph.run("demo") —— 本测试为了隔离会把 store.DB 指向临时库，
    # 临时库里没有 demo 的作答，路径会为空（实测返回 0/0 的假失败）。
    # 所以直接对**题库全量**校验解析可取，不依赖任何用户数据。
    from yj import data as _d2
    _qs = [q for q in _d2.questions().values()
           if q.get("题型") == "单项选择题"]
    _cov = sum(1 for q in _qs if _d2.solution(q["year"], q["题号"]))
    check("全部单选题都能取到解析", _qs and _cov == len(_qs),
          f"{_cov}/{len(_qs)}")

    print("\n" + "=" * 60)
    if FAIL:
        print(f"失败 {len(FAIL)} 项: {FAIL}")
        sys.exit(1)
    print("全部通过 —— LLM 通路(除真实网络调用外)已验证")


if __name__ == "__main__":
    main()
