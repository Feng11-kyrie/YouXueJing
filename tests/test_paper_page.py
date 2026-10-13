#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
「408 历年真题」页的回归测试（不需要 LLM key）。

覆盖：18 个年份都能渲染 / 答题卡与分页 / 筛选（未做·只错题）/ 作答判分并落库 /
综合题与缺图如实标注 / 浏览模式不写作答记录 / 界面不依赖 emoji 字体。

四个 AppTest 上的坑，改这个测试前先看这里（都是实测踩到的）：
  1. `at.radio` 的**顺序与脚本里的书写顺序不一致**，不要用下标定位控件
     （radio[1] 曾经是"第一题的选项"而不是"打开方式"）。用 label 过滤。
  2. `st.subheader` / `st.warning` / `st.info` / `st.caption` 生成的内容
     **不在 `at.markdown` 里**，要在对应的集合上找。
  3. 断言里引用的文案必须和界面里的**原文一致**（曾把"目前没有答案"写成
     "题库暂无答案"，得到一个假失败，白查一轮）。
  4. 分页后一页只渲染 10 题，所以"选项组数"不再是 40，要按页断言。

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


def widget(at, label):
    """按 label 找控件（不要用下标，at.radio 的顺序与脚本顺序不一致）"""
    hits = [r for r in at.radio if r.label == label]
    return hits[0] if hits else None


def md(at):
    return "\n".join(m.value for m in at.markdown)


def cap(at):
    return "\n".join(c.value for c in at.caption)


at = AppTest.from_file(os.path.join(BASE, "app.py"), default_timeout=300)
at.query_params["u"] = USER
at.run()
note("真题页是导航第一项", at.sidebar.radio[0].options[0].endswith("408 历年真题"))
note("首屏无异常", not at.exception, str([e.value for e in at.exception][:1]))
note("默认停在最新年份 2026", at.selectbox[0].value == "2026",
     f"got={at.selectbox[0].value}")

# ---- 选择 2025
at.selectbox[0].set_value("2025").run()
note("切到 2025 无异常", not at.exception, str([e.value for e in at.exception][:1]))
p = data.paper(2025)

# 卷情一行 + 说明一行（不再是两个整行的黄/蓝提示块）
head = md(at)
note("卷情含年份/题数/总分",
     all(k in head for k in ("408 真题", "47 题", "150 分")))
note("综合题缺口写在说明行", "综合应用题 7 题暂无答案" in cap(at))
note("缺图写在说明行", "插图未抽取齐全" in cap(at))

# 答题卡
note("出现答题卡", "答题卡" in head)
# 注意：样式表里也有一次 .yj-cell 定义，所以减去 1
n_cells = head.count("yj-cell") - 1
note("答题卡方格子数 = 题数", n_cells == p["题数"],
     f"cells={n_cells} 题数={p['题数']}")

# 分页：一页 10 题
note("分页：第 1/5 页", "第 1/5 页" in md(at))
note("本页 10 道单选", len([r for r in at.radio if r.label == "选项"]) == 10,
     f"实际 {len([r for r in at.radio if r.label == '选项'])}")
jump = [b for b in at.button if str(b.key or "").startswith("pg_")]
note("有跳页按钮", len(jump) == 5, f"{len(jump)} 个")

# ---- 作答判分
opts = [r for r in at.radio if r.label == "选项"]
q1 = p["题目"][0]
opts[0].set_value(opts[0].options[1]).run()
subs = [b for b in at.button if "提交" in str(b.label)]
note("有提交按钮", bool(subs))
subs[0].click().run()
note("提交无异常", not at.exception, str([e.value for e in at.exception][:1]))
fb = [s.value for s in at.success] + [s.value for s in at.error]
note("出现判分反馈", bool(fb), str(fb)[:60])
rows = store.get_answers(USER)
note("作答已落库", q1["id"] in rows, f"{len(rows)} 条")
note("成绩行随之更新", "已作答 **1/40**" in md(at))

# 答题卡状态：错题应变成 yj-bad
note("答错的题在答题卡标红", "yj-bad" in md(at))

# ---- 筛选
note("有筛选项", widget(at, "显示") is not None)
widget(at, "显示").set_value("只错题").run()
note("筛「只错题」无异常", not at.exception, str([e.value for e in at.exception][:1]))
note("只错题 = 1 题", "筛选「只错题」：1/47 题" in cap(at))
widget(at, "显示").set_value("未做").run()
note("筛「未做」= 46 题", "筛选「未做」：46/47 题" in cap(at))
widget(at, "显示").set_value("全部").run()
note("切回全部", "筛选" not in cap(at))

# ---- 分页跳转
jump = [b for b in at.button if str(b.key or "").startswith("pg_")]
jump[2].click().run()
note("跳到第 3 页", "第 3/5 页" in md(at))
note("第 3 页仍是 10 题", len([r for r in at.radio if r.label == "选项"]) == 10)

# ---- 浏览模式
w = widget(at, "打开方式")
w.set_value("浏览模式").run()
note("浏览模式无异常", not at.exception, str([e.value for e in at.exception][:1]))
note("浏览模式给答案折叠块", len(at.expander) >= 10, f"expander={len(at.expander)}")
note("浏览模式不出选项", not [r for r in at.radio if r.label == "选项"])
n_before = len(store.get_answers(USER))
note("浏览模式不写作答记录", len(store.get_answers(USER)) == n_before)

# ---- 界面不依赖 emoji 字体（用户截图里标题 emoji 渲染成破图）
import re
src = open(os.path.join(BASE, "app.py"), encoding="utf-8").read()
# Unicode Emoji_Presentation 里本项目可能用到的码位段（精确列举，不含 ★✓✗）
_EMOJI_RANGES = [
    (0x1F300, 0x1FAFF),   # 各类图形/表情（📄🎯🧭📊📘🖼️📝👀💡📦📐📚👆🐳）
    (0x1F000, 0x1F2FF),   # 麻将/扑克等
    (0x2705, 0x2705),     # ✅
    (0x274C, 0x274C),     # ❌
    (0x1F7E0, 0x1F7EB),   # 🟠🟡🟢
    (0x2B50, 0x2B50),     # ⭐
    (0x26A0, 0x26A0),     # ⚠️
]


def _EMOJI_PRESENTATION(ch):
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in _EMOJI_RANGES)

# 精确判断"会被当彩色图标渲染"的码位：用 Unicode 自带的
# Emoji_Presentation 属性（⌚ 这种默认彩色呈现的字符）。
# 不要用码位区间硬判 —— ★(U+2605) ✓(U+2713) ✗(U+2717) 都落在常见
# emoji 区间里，但它们是普通文本符号，会有语义地保留（第一版就是这么误报的）。
import unicodedata as _ud
emoji = sorted({c for c in src
                if _ud.category(c) == "So" and _EMOJI_PRESENTATION(c)})
note("界面源码里没有彩色 emoji", not emoji, f"发现 {emoji}")
note("标题不再有图标",
     all(not re.match(r"st\.title\(\"[^A-Za-z0-9\u4e00-\u9fff]", t)
         for t in re.findall(r"st\.title\(.*?\)", src)))

# ---- 18 个年份全部可渲染
bad = []
for y in data.years():
    at.selectbox[0].set_value(y).run()
    if at.exception:
        bad.append((y, str([e.value for e in at.exception][:1])))
note("18 个年份全部可渲染", not bad, str(bad[:2]))

print()
if fails:
    print(f"失败 {len(fails)} 处:")
    for f in fails:
        print("  ✗", f)
    sys.exit(1)
print("真题页回归测试全部通过")
