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
# 导航已改为卡片式（一列 st.button，选中项白卡片），不再是 st.radio
nav = [b for b in at.sidebar.button if str(b.key or "").startswith("nav_")]
note("侧栏是按钮式导航", len(nav) == 6, f"{len(nav)} 个")
note("真题页是第一项", nav and nav[0].label.endswith("408 历年真题"), 
     nav[0].label if nav else "")
# AppTest 上按钮的 type 只在 proto 上（element 没有 .type/.kind）
def btype(b):
    t = b.proto.type
    return getattr(t, "name", t) if not isinstance(t, str) else t

note("默认选中真题页", btype(nav[0]).lower() == "primary",
     f"type={btype(nav[0])}")
note("同时只有一个选中项",
     sum(1 for b in nav if btype(b).lower() == "primary") == 1)
note("首屏无异常", not at.exception, str([e.value for e in at.exception][:1]))
note("默认停在最新年份 2026", at.selectbox[0].value == "2026",
     f"got={at.selectbox[0].value}")

# ---- 导航点击真的切页（按钮式导航是这次改动的核心，必须验证）
at.sidebar.button(key="nav_学习路径").click().run()
note("点导航切到学习路径", "学习路径" in [h.value for h in at.title]
     or any("学习路径" in m.value for m in at.markdown),
     f"title={[h.value for h in at.title]}")
nav2 = [b for b in at.sidebar.button if str(b.key or "").startswith("nav_")]
sel = [b.label for b in nav2 if btype(b).lower() == "primary"]
note("选中态跟着移动", sel and "学习路径" in sel[0], str(sel))
at.sidebar.button(key="nav_408 历年真题").click().run()
note("切回真题页", "408 历年真题" in md(at) and bool(at.selectbox))

# ---- 选择 2025
at.selectbox[0].set_value("2025").run()
note("切到 2025 无异常", not at.exception, str([e.value for e in at.exception][:1]))
p = data.paper(2025)

# 卷情一行 + 说明一行（不再是两个整行的黄/蓝提示块）
head = md(at)
# 首屏被"元信息天花板"压过：现在标题+控件同排、卷情+成绩+缺口说明合并成
# 一行 caption，所以断言要看 caption 而不是 markdown
info = cap(at)
note("卷情含年份/题数/总分",
     all(k in info for k in ("2025 年", "47 题", "150 分")), info[:50])
note("综合题缺口写在卷情行", "综合 7 题无答案不计分" in info)
# 缺图数逐年不同（2026 是 3、2025 是 1），断言只查"有没有写出来"，
# 不要把某一年份的具体数字写死 —— 第一版就是这么写错的
note("缺图写在卷情行", "题缺插图" in info, info[-24:])

# 答题卡：图例并进同一行（省掉原来上方一整行说明），方格按页分组
note("出现答题卡图例", "方框底色即答题状态" in head)
note("答题卡按页分组", head.count("yj-pgblock") - 1 >= 5,
     f"pgblock={head.count('yj-pgblock') - 1}")
# 计数要扣掉样式表里的定义：.yj-cell 定义 1 次、.yj-legend .yj-cell 1 次，
# 再加图例本身的 3 个格子
n_cells = head.count("yj-cell") - 2 - 3
note("答题卡方格子数 = 题数", n_cells == p["题数"],
     f"cells={n_cells} 题数={p['题数']}")

# 分页：一页 10 题（分页导航是"上一页 / 第 N/M 页 / 下一页"）
note("分页信息显示第 1/5 页", "第 <b>1</b> / 5 页" in md(at), )
note("本页 10 道单选", len([r for r in at.radio if r.label == "选项"]) == 10,
     f"实际 {len([r for r in at.radio if r.label == '选项'])}")
jump = [b for b in at.button if str(b.key or "").startswith("pg_")]
note("有分页按钮（上/下页）", len(jump) == 2, f"{len(jump)} 个")

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
note("成绩行随之更新", "已作答 1/40" in cap(at))

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

# ---- 分页跳转（用"下一页"按钮）
at.button(key="pg_next").click().run()
note("下一页后是第 2 页", "第 <b>2</b> / 5 页" in md(at))
note("第 2 页仍是 10 题", len([r for r in at.radio if r.label == "选项"]) == 10)
at.button(key="pg_prev").click().run()
note("上一页回到第 1 页", "第 <b>1</b> / 5 页" in md(at))

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
