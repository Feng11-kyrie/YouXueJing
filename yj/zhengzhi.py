# -*- coding: utf-8 -*-
"""
考研政治：数据结构与考纲部分划分。

为什么按**题号**划分而不是关键词分类
------------------------------------
教育部考试中心的命题规则里，各科目对应的题号是**固定**的（研招网公布的
《考研政治出题规则：各知识点对应题号》）：

    题型          题号      分值
    单项选择题    1–16      每题 1 分
    多项选择题    17–33     每题 2 分
    材料分析题    34–38     每题 10 分

    科目（分数占比）              单选      多选        分析题
    马克思主义基本原理概论(24%)   1–4       17–21       34
    毛泽东思想和中国特色…(30%)    5–8       22–26       35
    中国近现代史纲要(14%)         9–12      27–29(+30)  36
    思想道德修养与法律基础(16%)   13–14(+12) 30/31      37
    形势与政策与当代世界经济(16%) 15–16     32–33       38
        （15 国内时政 / 16 国际时政；32 国内时政 / 33 国际时政）

规则里也说明了特例：纲要与思修的题号在个别年份会互相挪动（"或"那两行），
所以**不能只靠题号一刀切** —— 本模块对边界题做了标记（`边界`字段），
让上层能提示"这部分归属以实际命题为准"。

与 408 的关键差异（影响产品机制）
--------------------------------
  · 408：考纲是 266 个叶子考点 + 依赖关系图 → 能"补根因"
  · 政治：五个**部分**之下才是考点；而且**时政没有前置关系**（纯记忆），
    马原/史纲才有可追溯的逻辑链。所以「补根因」在政治上只能用一部分。
"""
import json
import os
import re

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ZZ_DIR = os.path.join(BASE, "data", "zhengzhi")

# 科目代号 → 名称（与 408 的 CODE2NAME 并列，供将来统一注册表使用）
PARTS = {
    "MY": "马克思主义基本原理",
    "MZT": "毛泽东思想和中国特色社会主义理论体系概论",
    "SG": "中国近现代史纲要",
    "SX": "思想道德修养与法律基础",
    "SZ": "形势与政策以及当代世界经济与政治",
}
PART_SHORT = {"MY": "马原", "MZT": "毛中特", "SG": "史纲",
              "SX": "思修法基", "SZ": "时政与当代"}

# 各部分的**实际考查分值**（注意：不是大纲占比）
#
# 研招网公布的规则里明确写了这个差额：
#     "毛中特大纲规定考察 30 分，但是实际考察 24 分；纲要大纲规定考察 14 分，
#      实际考察 20 分。因为纲要与毛中特的毛泽东思想部分联系非常紧密，
#      二者经常结合起来进行考察。"
# 实测 2015 年也印证了：马原 24、毛中特 24、史纲 22、思修 14、时政 16。
# 所以这里存**实际值** —— 拿大纲占比去算"这部分占多少分"会算错。
PART_SCORE = {"MY": 24, "MZT": 24, "SG": 20, "SX": 16, "SZ": 16}
PART_SCORE_NOTE = ("实际考查分值（与大纲占比不同：大纲写毛中特 30 / 纲要 14，"
                   "实际是毛中特 24 / 纲要 20）")


def part_of(num, qtype):
    """
    按题号判断这道题属于哪个部分。

    返回 (部分代号, 是否边界题)。边界题指官方规则里存在"或"的情况 ——
    例如第 12 题可能是史纲（单选 9–12）也可能是思修（单选 11–14），
    第 30 题可能是史纲也可能是思修。这类题**标注出来**而不是猜：
    猜错会让"这部分你答对几题"的统计失真。
    """
    n = int(num)
    if qtype == "单项选择题":
        if 1 <= n <= 4:
            return "MY", False
        if 5 <= n <= 8:
            return "MZT", False
        if n == 9 or n == 10:
            return "SG", False
        if n in (11, 12):
            return "SG", True          # 也可能是思修（11–14）
        if n in (13, 14):
            return "SX", True          # 也可能是史纲（9–12 与 11–14 重叠）
        if n == 15:
            return "SZ", False         # 国内时政
        if n == 16:
            return "SZ", False         # 国际时政
    elif qtype == "多项选择题":
        if 17 <= n <= 21:
            return "MY", False
        if 22 <= n <= 26:
            return "MZT", False
        if n in (27, 28, 29):
            return "SG", False
        if n == 30:
            return "SG", True          # 也可能是思修
        if n == 31:
            return "SX", False
        if n == 32:
            return "SZ", False         # 国内时政
        if n == 33:
            return "SZ", False         # 国际时政
    elif qtype in ("分析题", "材料分析题"):
        # 题型名实测有两种：2015 那份叫"分析题"，2023–2025 那几份叫"材料分析题"。
        # 原来只判"分析题"，导致那三年的 34–38 题部分归属为 None
        # （界面统计会直接 KeyError 崩掉 —— 实测踩到）。
        return {34: ("MY", False), 35: ("MZT", False), 36: ("SG", True),
                37: ("SX", True), 38: ("SZ", False)}.get(n, (None, False))
    return None, False


def years():
    """
    已有数据的年份（升序）。

    **必须用正则严格匹配 `<4位数字>.json`** —— 不能只做后缀过滤：
    这个目录里还有 `<年份>-解析.json`、`<年份>-待确认.json` 等派生文件，
    用 `f[:4]` 会把同一年算两次（实测 2016 出现过重复，导致题量统计虚高）。
    """
    if not os.path.isdir(ZZ_DIR):
        return []
    return sorted(f[:4] for f in os.listdir(ZZ_DIR)
                  if re.fullmatch(r'\d{4}\.json', f))


def paper(year):
    """读某年政治真题；不存在返回 None"""
    p = os.path.join(ZZ_DIR, f"{year}.json")
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        rec = json.load(f)
    for it in rec["题目"]:
        code, edge = part_of(it["题号"], it["题型"])
        it["部分"] = code
        it["部分名"] = PART_SHORT.get(code, "")
        it["边界题"] = edge
    return rec


def explanation(year, num):
    """
    取某年某题的解析；没有则返回 None。

    结构：{"文本": ..., "来源": "题源抽取" | "AI 生成（未经官方核验）",
           "时政存疑": True?}

    **来源必须如实透出到界面** —— 用户红线：AI 生成的内容要标注，
    不能让人以为是官方解析。时政题还要额外提示"对时政细节可能有误"
    （2026 卷考的"十五五"规划建议在模型训练截止之后）。

    存放在 <年份>-解析.json，**与题目文件分开** ——
    题目文件会被 parse_zhengzhi.py --write 整个重写，解析混进去就会丢
    （我为此丢过两次答案）。
    """
    p = os.path.join(ZZ_DIR, f"{year}-解析.json")
    if not os.path.exists(p):
        return None
    try:
        rec = json.load(open(p, encoding="utf-8"))
    except Exception:                                       # noqa: BLE001
        return None
    e = (rec.get("解答") or {}).get(str(num))
    if not e or not e.get("文本"):
        return None
    return e


def questions():
    """全部政治题目，键为 "ZZ-<年>-<题号>"，与 408 的 id 风格一致"""
    out = {}
    for y in years():
        rec = paper(y)
        for it in rec["题目"]:
            out[f"ZZ-{y}-{it['题号']}"] = {**it, "year": y, "id":
                                           f"ZZ-{y}-{it['题号']}"}
    return out


def part_stats(year):
    """某年各部分的题数与分值汇总（用于界面上显示覆盖情况）"""
    rec = paper(year)
    if not rec:
        return {}
    out = {}
    for it in rec["题目"]:
        # 容错：万一将来出现没归类的题型名，统计不该崩
        # （实测踩到过：未归属的题会让界面 KeyError）
        p = it.get("部分") or "未归类"
        d = out.setdefault(p, {"题数": 0, "单选": 0, "多选": 0, "分析": 0,
                               "分值": 0, "边界": 0})
        d["题数"] += 1
        d["分值"] += it["分值"]
        if it["题型"] == "单项选择题":
            d["单选"] += 1
        elif it["题型"] == "多项选择题":
            d["多选"] += 1
        else:
            d["分析"] += 1
        if it["边界题"]:
            d["边界"] += 1
    return out


def part_pool(year=None, part=None, only_answerable=True):
    """
    按**部分**取客观题，供「挑考点练习」使用。

    用户要求把"分块"从真题页挪到练习页：
        "政治真题部分你要按照题目顺序来啊，在这部分内容不要分块，
         分块部分应该在挑考点练习那里"

    所以真题页按题号平铺（连续作答的体验），而"按部分针对性练"
    放在练习页 —— 这里就是它的题库来源。

    year=None 表示**跨所有年份**取（练习要的是题量，不是某一年的整卷）。
    only_answerable=True 只取有答案且有解析的题 —— 练习必须能判分、
    能看解析，否则练了也不知道对错。
    """
    out = []
    for y in years():
        if year and str(y) != str(year):
            continue
        for it in paper(y)["题目"]:
            if it["题型"] not in ("单项选择题", "多项选择题"):
                continue
            if part and it.get("部分") != part:
                continue
            if only_answerable and (not it.get("答案")
                                    or not explanation(y, it["题号"])):
                continue
            out.append({**it, "year": y, "id": f"ZZ-{y}-{it['题号']}"})
    return out


def part_summary():
    """
    各部分的总览（跨所有年份）：题量、可练题数、已覆盖年份数。
    供练习页的卡片显示真实规模 —— 不能写死"若干题"。
    """
    out = {}
    for code in PARTS:
        pool = part_pool(part=code)
        ys = sorted({q["year"] for q in pool})
        n_single = sum(1 for q in pool if q["题型"] == "单项选择题")
        n_multi = sum(1 for q in pool if q["题型"] == "多项选择题")
        out[code] = {
            "名称": PARTS.get(code, code),
            "简称": PART_SHORT.get(code, code),
            "分值": PART_SCORE.get(code, 0),
            "可练": len(pool),
            "单选": n_single,
            "多选": n_multi,
            "年份数": len(ys),
        }
    return out


# ---------------------------------------------------------------- 部分诊断
def part_list():
    """五个部分：客观题数 + 分析题数（全部年份累计）。"""
    from collections import Counter
    obj, ana = Counter(), Counter()
    for y in years():
        for q in paper(y)["题目"]:
            part, _ = part_of(q["题号"], q["题型"])
            if not part:
                continue
            if "分析题" in str(q["题型"]):
                ana[part] += 1
            else:
                obj[part] += 1
    return [{"部分": p, "简称": PART_SHORT[p], "客观题": obj.get(p, 0),
             "分析题": ana.get(p, 0)} for p in PARTS]


def diagnostic(n_per_part=3):
    """
    政治诊断：**每个部分抽 2 道单选 + 1 道多选**（尽量），约 15 题、10 分钟。

    为什么按部分而不是随机：政治的选择题 1–16 单选、17–33 多选，题号本身就
    映射到五个部分；随机抽很可能整卷偏马原。按部分各抽几道，结果才能回答
    "哪一部分弱"。
    """
    out = []
    ys = list(reversed(years()))
    for p in PARTS:
        picked = []
        for y in ys:
            for q in paper(y)["题目"]:
                part, _ = part_of(q["题号"], q["题型"])
                if part != p or "分析题" in str(q["题型"]):
                    continue
                kind = q["题型"]
                if sum(1 for x in picked
                       if x["题目"]["题型"] == kind) >= (
                        2 if kind == "单项选择题" else 1):
                    continue
                if any(x["题目"]["题号"] == q["题号"] and x["year"] == y
                       for x in picked):
                    continue
                q = dict(q)
                q["id"] = f"ZZ-{y}-{q['题号']}"
                picked.append({"year": y, "题目": q})
                if len(picked) >= n_per_part:
                    break
            if len(picked) >= n_per_part:
                break
        out.extend(picked)
    return out


def part_mastery(answers):
    """
    按部分统计**客观题**正确率；分析题单独计"已练"数（不算正确率）。

    分析题没有客观对错，硬算正确率是假的 —— 页面上分开显示。
    """
    out = []
    for p in PARTS:
        done = ok = ana = 0
        for y in years():
            for q in paper(y)["题目"]:
                part, _ = part_of(q["题号"], q["题型"])
                if part != p:
                    continue
                qid = f"ZZ-{y}-{q['题号']}"
                r = answers.get(qid)
                if "分析题" in str(q["题型"]):
                    if r:
                        ana += 1
                    continue
                if not r or r.get("source") == "selfscore":
                    continue
                done += 1
                ok += 1 if r.get("is_correct") else 0
        out.append({"部分": p, "简称": PART_SHORT[p], "作答": done,
                    "答对": ok, "正确率": (ok / done) if done else None,
                    "分析题已练": ana})
    out.sort(key=lambda r: (r["正确率"] is None, r["正确率"] or 0, -r["作答"]))
    return out
