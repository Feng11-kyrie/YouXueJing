#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
学习资源生成：讲义 / 习题 / 知识点总结。

两种模式, 且**界面会明确标注来源**:
  llm      —— 调 LLM 生成讲解正文
  template —— 用真实数据(考纲结构 + 真题统计 + 你的掌握度)填充模板

模板模式不是"假 AI 输出": 它给的都是真数据(考频、真题清单、前置掌握度),
只是没有 LLM 写的讲解文字。这一点在界面上必须说清 —— 对外表述要真实。

另外做了一层**程序化的考纲校验**(verify): 检查生成内容里提到的考点名
是否都在考纲叶子集合内, 防止 LLM 编造考纲外的知识点。这不需要 LLM, 可重复验证。
"""
import re

from . import data, llm

TASK_LESSON = "lesson"
TASK_SUMMARY = "summary"


# ---------------------------------------------------------------- 讲义
def lesson(leaf, answers=None, use_llm=True, marks=None):
    """生成某个考点的讲义。返回 {markdown, source, 校验}"""
    n = data.nodes().get(leaf, {})
    f = data.freq().get(leaf, {})
    ch = data.chapter_of(leaf)
    subj = data.subject_of(leaf)

    # ---- 真实数据部分(两种模式都有)
    pres = data.prereqs().get(leaf, [])
    from .diagnose import mastery_by_leaf
    ml = mastery_by_leaf(answers or {})
    mine = ml.get(leaf)

    rel = sorted([q for q in data.questions().values() if q["主考点"] == leaf],
                 key=lambda q: -q["year"])

    ctx = {
        "考点": n.get("name", leaf),
        "考纲位置": f"{data.CODE2NAME.get(subj, '')} › {data.node_name(ch)}",
        "考查总次数": f.get("考查总次数", 0),
        "主考点次数": f.get("主考点次数", 0),
        "次考点次数": f.get("次考点次数", 0),
        "覆盖年份数": f.get("覆盖年份数", 0),
        # 逐年从 dict 预格式化成文本: 早期版本直接把 dict 插进 f-string,
        # 界面上会露出 {'2024': 1} 这种 Python 字面量(用户可见的观感缺陷)。
        "逐年": "　".join(f"{y}:{c}" for y, c in sorted(f.get("逐年", {}).items()))
                or "无",
        "逐年年数": len(f.get("逐年", {})),
        "占本学科": f.get("占本学科题量比"),
        "我的掌握度": (f"{mine['掌握度']:.0%}（{mine['答对']}/{mine['题数']}）"
                       if mine else ("未测（你标记为薄弱）"
                                     if leaf in (marks or set()) else "未测")),
        "前置考点": [{"名称": data.node_name(p),
                      "我的掌握度": (f"{ml[p]['掌握度']:.0%}" if p in ml else "未测")}
                     for p in pres],
        "后续考点": [data.node_name(s) for s in data.successors().get(leaf, [])][:6],
        "相关真题": [{"年份": q["year"], "题号": q["题号"], "难度": q.get("难度"),
                      "题型": q["题型"]} for q in rel[:12]],
        "真题总数": len(rel),
    }

    body, source = None, "template"
    if use_llm:
        prompt = f"""请为 408 考研学生写一份「{ctx['考点']}」的复习讲义。

严格要求：
1. **只能讲这个考点范围内的内容**，不要扩展到考纲外的知识点。
2. 下面给出的真实数据（考频、真题分布、前置考点）是事实，请据此安排篇幅与重点，
   不要编造没有依据的统计数字。
3. 结构：核心概念 → 考查重点 → 常见易错点 → 复习建议。
4. 用中文 Markdown，控制在 600 字以内，不要写客套话。

【真实数据】
{ctx}
"""
        r = llm.complete(TASK_LESSON, prompt, payload={"leaf": leaf, "v": 1})
        if r["text"]:
            body, source = r["text"], r["source"]

    md = _render_lesson(ctx, body, source)
    return {"markdown": md, "source": source, "校验": verify(md), "数据": ctx}


def _freq_chart(逐年_str):
    """
    逐年分布 → 单行字符图。考频分布是"这个考点该怎么投入时间"的直接依据,
    一行图比一串数字更快读懂(路演时也更好讲)。
    """
    pairs = [p for p in (逐年_str or "").split("　") if ":" in p]
    if not pairs:
        return ""
    items = [(p.split(":", 1)[0], int(p.split(":", 1)[1])) for p in pairs]
    top = max(c for _y, c in items) or 1
    return " ".join("▁▂▃▄▅▆▇█"[min(7, int(c / top * 7))] for _y, c in items)


def _render_lesson(ctx, body, source):
    L = [f"## {ctx['考点']}", ""]
    L.append(f"**考纲位置**：{ctx['考纲位置']}　|　"
             f"**18 年考频**：{ctx['考查总次数']} 次"
             f"（主考点 {ctx['主考点次数']} 次，覆盖 {ctx['覆盖年份数']}/18 年）　|　"
             f"**我的掌握度**：{ctx['我的掌握度']}")
    L.append("")
    if ctx["前置考点"]:
        L.append("**前置考点**：" + "、".join(
            f"{p['名称']}（{p['我的掌握度']}）" for p in ctx["前置考点"]))
        L.append("")
    if body:
        tag = {"llm": "LLM 生成", "cache": "LLM 生成（预跑缓存）"}
        L.append(f"> 以下讲解由 {tag.get(source, source)}")
        L.append("")
        L.append(body)
    else:
        # 模板模式: 不出"讲解正文"(没有 LLM 就没有), 但把**真实数据**组织成
        # 可执行的学习依据。早先这里只写了一句"请对照考纲自查" —— 那等于没给东西。
        L.append("> 以下为**模板模式**：未配置 LLM API，"
                 "不生成讲解正文，只把该考点的真实考查数据整理出来。")
        L.append("")
        L.append("### 这个考点怎么考")
        L.append(f"- **18 年共出现 {ctx['考查总次数']} 次**："
                 f"作为主考点 {ctx['主考点次数']} 次，作为次考点 {ctx['次考点次数']} 次")
        L.append(f"- **覆盖 {ctx['覆盖年份数']}/18 年**"
                 + (f"，占本学科题量 {ctx['占本学科']:.1%}" if ctx["占本学科"] else "")
                 + f"　→　{'常年必考，优先投入' if ctx['覆盖年份数'] >= 12 else ('反复出现，稳定考点' if ctx['覆盖年份数'] >= 6 else '偶考，按时间取舍')}")
        L.append(f"- **逐年分布**：{ctx['逐年']}")
        if _freq_chart(ctx["逐年"]):
            L.append(f"- **分布图**：`{_freq_chart(ctx['逐年'])}`"
                     f"（左起 2009 → 右至 2026）")
        L.append("")
        L.append("### 学完它之后要用到它的地方")
        if ctx["后续考点"]:
            L.append("　".join(f"`{s}`" for s in ctx["后续考点"])
                     + "　——　这些考点把它当前置，先补它比硬练它们更省时间。")
        else:
            L.append("依赖图里没有以它为前置的考点，它更偏独立考点。")
        L.append("")
        L.append("**建议做法**：")
        L.append("1. 先确认上面列出的前置考点是否牢固"
                 + (f"（当前：{'、'.join(p['名称'] + ' ' + p['我的掌握度'] for p in ctx['前置考点'])}）"
                    if ctx["前置考点"] else "（该考点无前置）"))
        L.append(f"2. 用下面 {ctx['真题总数']} 道真题自测，把错题按这个考点归档；")
        L.append(f"3. 对着「分布图」判断投入：它出现在 {ctx['逐年年数']} 个年份里。")
    L.append("")
    L.append("### 相关真题")
    if ctx["相关真题"]:
        for q in ctx["相关真题"]:
            L.append(f"- {q['年份']} 年 第 {q['题号']} 题　{q['题型']}　难度 {q['难度']}")
    else:
        L.append("- 题库中暂无该考点的选择题。")
    return "\n".join(L)


# ---------------------------------------------------------------- 考纲校验
def verify(markdown):
    """
    程序化校验: 检查文本中出现的「考点名」是否都在考纲叶子集合内。

    做法: 在文本里找所有与叶子考点名相同或高度相似的片段。
    这是**不需要 LLM 的可重复校验**, 用来防 LLM 编造考纲外知识点。
    """
    leaf_names = {}
    for lid in data.leaf_ids():
        leaf_names[data.node_name(lid)] = lid
    # 只检查"看起来像考点名"的片段: 出现在 ### 标题或 **加粗** 里的
    cands = set(re.findall(r"\*\*([^*\n]{2,30})\*\*", markdown))
    cands |= set(re.findall(r"^###\s+(.+)$", markdown, re.M))
    unknown = []
    for c in cands:
        c = c.strip()
        if len(c) < 2:
            continue
        if not re.search(r"[\u4e00-\u9fff]", c):
            continue
        if any(c == nm or c in nm or nm in c for nm in leaf_names):
            continue
        # 常见的非考点词白名单
        # ⚠️ 这里必须包含**本模块自己输出的固定小标题** —— 否则模板模式会被
        # 自己的标题误判为"越纲"(修 generate 的排版时踩过: 新增小节标题后
        # 复核结果立刻变成"发现 6 个越纲项")。校验要拦的是 LLM 编造的考点,
        # 不是我们自己的排版词。
        if any(k in c for k in ("建议", "做法", "易错", "重点", "复习", "概念",
                                "结构", "相关真题", "需要掌握", "考纲位置",
                                "模板模式", "前置", "考频", "掌握度",
                                "这个考点怎么考", "学完它之后", "分布图",
                                "逐年分布", "覆盖", "用到它的地方", "年共出现")):
            continue
        unknown.append(c)
    return {
        "通过": not unknown,
        "疑似考纲外": unknown[:8],
        "说明": "检查生成文本里的小标题/加粗词是否都能在考纲 266 个叶子考点中找到。",
    }


# ---------------------------------------------------------------- 习题
def exercises(leaf, n=5, exclude=None):
    """从题库取该考点的真题作练习(带答案, 可直接判分)"""
    exclude = set(exclude or ())
    pool = [q for q in data.questions().values()
            if q["主考点"] == leaf and q["题型"] == "单项选择题"
            and q.get("答案") and q["id"] not in exclude]
    pool.sort(key=lambda q: (q.get("难度") or 3, -q["year"]))
    # 键名统一用中文, 与题库/图谱其余部分保持一致(曾用英文 year 导致界面取不到值)
    return [{"id": q["id"], "年份": q["year"], "题号": q["题号"],
             "题干": q["题干"], "选项": q.get("选项") or {},
             "答案": q["答案"], "难度": q.get("难度"),
             "需插图": q.get("需插图"), "图片": q.get("图片")}
            for q in pool[:n]]


# ---------------------------------------------------------------- 知识点总结
def summary(leaf):
    """一页纸的知识点速记(纯数据, 不依赖 LLM)"""
    n = data.nodes().get(leaf, {})
    f = data.freq().get(leaf, {})
    ch = data.chapter_of(leaf)
    subs = []      # 该考点下的子考点(如果它本身是节)
    for i, x in data.nodes().items():
        if x.get("parent") == leaf:
            subs.append(x["name"])
    L = [f"# {n.get('name', leaf)} · 知识点速记", "",
         f"- **学科**：{data.CODE2NAME.get(data.subject_of(leaf), '')}",
         f"- **所属章**：{data.node_name(ch)}",
         f"- **18 年考查**：{f.get('考查总次数', 0)} 次"
         f"（主考点 {f.get('主考点次数', 0)}，次考点 {f.get('次考点次数', 0)}）",
         f"- **覆盖年份**：{f.get('覆盖年份数', 0)}/18"]
    if f.get("逐年"):
        # 与讲义同样处理: 不把 dict 字面量印到界面/文本里
        L.append("- **逐年分布**："
                 + "　".join(f"{y}:{c}" for y, c in sorted(f["逐年"].items())))
    if subs:
        L += ["", "## 包含的子考点"]
        L += [f"- {s}" for s in subs]
    pres = data.prereqs().get(leaf, [])
    if pres:
        L += ["", "## 前置知识（先确认这些牢固）"]
        L += [f"- {data.node_name(p)}" for p in pres]
    rel = [q for q in data.questions().values()
           if q["主考点"] == leaf]
    if rel:
        L += ["", "## 真题分布"]
        from collections import Counter
        c = Counter(q["year"] for q in rel)
        L.append("　".join(f"{y}:{c[y]}" for y in sorted(c)))
    return "\n".join(L)
