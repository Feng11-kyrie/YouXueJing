#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
「📄 408 历年真题」页的回归测试（不需要 LLM key）。

覆盖：18 个年份都能渲染整套卷 / 单选题作答判分并落库 / 综合题与缺图如实标注 /
浏览模式与作答模式的区别（浏览模式不写作答记录、不出选项）。

三个 AppTest 上的坑，改这个测试前先看这里（都是实测踩到的）：
  1. `at.radio` 的**顺序与脚本里的书写顺序不一致** —— 侧栏导航不是第一个，
     "打开方式"也不在 radio[1]（radio[1] 其实是第一题的选项）。
     要按控件定位就得用 `label` 过滤，不要用下标。
  2. `st.subheader` / `st.warning` / `st.info` 生成的内容**不在 `at.markdown` 里**，
     分别要在 `at.subheader` / `at.warning` / `at.info` 上找。
  3. 断言里引用的文案必须和界面里的**原文一致**（我曾把"目前没有答案"写成
     "题库暂无答案"，得到一个假失败，白查一轮）。

用法:  .venv/bin/python tests/test_paper_page.py
"""
import os
import sys
import tempfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from yj import data, store                        # noqa: E402

# 关键：测试绝不写生产库（与 test_llm_stub.py 同样的理由）。
# 这条不是形式主义 —— 写这个测试时第一版没隔离，真的把 2 条作答写进了
# 演示画像 demo，只能按原参数重新播种修回来。
store.DB = os.path.join(tempfile.gettempdir(), "yj_test_paper.db")
if os.path.exists(store.DB):
    os.remove(store.DB)

from streamlit.testing.v1 import AppTest          # noqa: E402

USER = "paper_smoke"
fails = []


def note(name, ok, detail=""):
    print(f"  {'✓' if ok else '✗'} {name}" + (f"  {detail}" if detail else ""))
    if not ok:
        fails.append((name, detail))


at = AppTest.from_file(os.path.join(BASE, "app.py"), default_timeout=300)
at.query_params["u"] = USER
at.run()
note("真题页是导航第一项", at.sidebar.radio[0].options[0] == "📄 408 历年真题")
note("无异常", not at.exception, str([e.value for e in at.exception][:1]))
note("默认停在最新年份 2026", at.selectbox[0].value == "2026",
     f"got={at.selectbox[0].value}")

# ---- 选 2025
at.selectbox[0].set_value("2025").run()
note("切到 2025 无异常", not at.exception, str([e.value for e in at.exception][:1]))
p = data.paper(2025)
labels = [m.label for m in at.metric]
note("四个概览指标齐", len(labels) >= 4, str(labels[:4]))
heads = [str(m.value) for m in at.markdown]
allmd = "\n".join(m.value for m in at.markdown)
# 注意元素类型: subheader / warning / info 不在 at.markdown 里
note("标题含 2025", "2025 年 408 真题" in [x.value for x in at.subheader])
note("综合题如实标注",
     any("综合应用题" in w.value and "没有答案" in w.value
         for w in at.warning))
note("缺图如实标注",
     any("插图尚未抽取齐全" in i.value for i in at.info))
note("单选选项组数 = 40", len(at.radio) == 40 + 2, f"radio={len(at.radio)}")

# ---- 作答判分（radio[2] 是第一道题的选项）
r = at.radio[2]
q1 = p["题目"][0]
r.set_value(r.options[1]).run()
note("选择题无异常", not at.exception, str([e.value for e in at.exception][:1]))
subs = [b for b in at.button if "提交" in str(b.label)]
note("有提交按钮", bool(subs), f"{len(subs)} 个")
if subs:
    subs[0].click().run()
    note("提交无异常", not at.exception, str([e.value for e in at.exception][:1]))
    fb = [s.value for s in at.success] + [s.value for s in at.error]
    note("出现判分反馈", bool(fb), str(fb)[:90])
    rows = store.get_answers(USER)
    note("作答已落库", bool(rows), f"{len(rows)} 条")
    note("写入的是本题", q1["id"] in rows, q1["id"])
    note("出现本卷成绩汇总",
         any("这套卷子你已作答" in m.value for m in at.markdown))

# ---- 浏览模式：按 label 找控件（at.radio 的顺序与脚本顺序不一致，
#      radio[1] 其实是第一题的选项，不能按下标取"打开方式"）
mode_w = [r for r in at.radio if r.label == "打开方式"][0]
mode_w.set_value("👀 浏览模式（只看不记）").run()
note("浏览模式无异常", not at.exception, str([e.value for e in at.exception][:1]))
note("浏览模式给答案折叠块", len(at.expander) >= 40, f"expander={len(at.expander)}")
note("浏览模式不再出现选项", len(at.radio) == 2, f"radio={len(at.radio)}")

# ---- 最老一年 + 全部年份都能渲染
for y in data.years():
    at.selectbox[0].set_value(y).run()
    if at.exception:
        note(f"{y} 年渲染", False, str([e.value for e in at.exception][:1]))
note("18 个年份全部可渲染", not any(f[0].endswith("年渲染") for f in fails))

# ---- 直接访问最老一年
at.selectbox[0].set_value("2009").run()
note("2009 卷正常", not at.exception, str([e.value for e in at.exception][:1]))

print()
if fails:
    print(f"失败 {len(fails)} 处:")
    for f in fails:
        print("  ✗", f)
    sys.exit(1)
print("真题页冒烟全部通过")
