#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
408 真题 PDF -> 结构化 JSON 题库

数据源: neville-studio/408-exam-paper (MIT, 2009-2026)
  papers-rebuild/{year}.pdf       试卷(文字版)
  answers/{year}-answer.pdf       答案解析(需空密码解密)

用法:
  python parse_408.py 2023                # 解析单年
  python parse_408.py 2023 --debug        # 打印未解析成功的题目原文

输出: data/408/{year}.json
"""
import os
import re
import json
import sys
import argparse

from pypdf import PdfReader

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(BASE, ".cache", "408")
OUT = os.path.join(BASE, "data", "408")

# ---------------------------------------------------------------- 学科关键词
SUBJECT_KW = {
    "数据结构": [
        "链表", "顺序表", "二叉树", "哈夫曼", "排序", "查找", "散列", "哈希", "B树", "B+树",
        "邻接", "顶点", "边", "栈", "队列", "时间复杂度", "稀疏矩阵", "折半", "图", "结点",
        "中序", "前序", "后序", "层次遍历", "平衡二叉树", "堆", "归并", "快速排序", "拓扑",
        "关键路径", "连通", "度", "森林", "树",
    ],
    "计算机组成原理": [
        "主频", "指令", "流水线", "Cache", "cache", "存储器", "总线", "浮点", "IEEE", "机器数",
        "补码", "寄存器", "数据通路", "中断", "I/O", "编址", "CPI", "异常", "CPU", "DRAM",
        "SRAM", "ROM", "磁盘", "寻址", "汇编", "字节", "字长", "溢出", "溢出", "主存",
    ],
    "操作系统": [
        "进程", "线程", "页表", "页框", "虚拟内存", "调度", "死锁", "信号量", "互斥", "同步",
        "文件系统", "索引节点", "内核", "系统调用", "设备分配", "就绪队列", "段页", "分页",
        "页面置换", "缺页", "临界区", "银行家", "时间片", "管程", "目录", "磁盘调度", "用户态",
        "内核态", "位图", "逻辑设备", "物理设备",
    ],
    "计算机网络": [
        "TCP", "UDP", "IP", "子网", "路由", "以太网", "帧", "CRC", "NAT", "信道", "带宽",
        "调制", "协议", "分组交换", "域名", "DNS", "HTTP", "FTP", "拥塞", "滑动窗口", "往返",
        "报文", "首部", "交换机", "网桥", "VLAN", "DHCP", "ICMP", "IPv4", "IPv6", "QAM",
        "停止-等待", "GBN", "SR协议", "链路", "传输速率", "OSI", "三次握手",
    ],
}

# 需插图判定。
# 注意: 「图」在数据结构里常指"图论"(如图的基本概念), 所以不能见到「图」就判需插图。
# 判断原则: **宁可宽松** —— 误报无害(没抽到图就不显示), 漏报有害(用户看不到图)。
# 据此已实测修掉两类错误:
#   漏报: 「如下无向图」「题 33～41 图」(范围写法)
#   误报: 「位图中」「有向图中」「该图拓扑序列」—— 这里的"图"指图论/位图, 非插图
FIG_RE = re.compile(
    r"如下[^。，；、\n]{0,10}图"                 # 如下图 / 如下无向图 / 如下图所示
    r"|下\s*图"                                # 下图
    r"|如\s*图"                                # 如图
    r"|题\s*\d+\s*(?:[～~\-—]\s*\d+\s*)?图"      # 题 47 图 / 题 33～41 图
    r"|图\s*所示"                              # 图所示
    r"|图\s*\d+"                               # 图1
    r"|(?:参考|见|参见|根据|依据)\s*图"           # 参考图中
    r"|如下所示"                                # 如下所示(可能指内联表格, 也可能是插图)
    # 如下的二叉树 / 下面带权图 / 下列图 G / 下列两棵表达式树
    # 负向断言排除「下列关于图的叙述」「下列选项中」这类图论/选项语境
    r"|(?:如下|下面|下列|见下|见前)(?![关于选说])(?:[^。，；、\n]{0,12})(?:图|树|网)"
)

# 选项标记: A. / A． / A、
OPT_RE = re.compile(r"(?<![A-Za-z0-9])([A-D])\s*[.．、]\s*")

# 题干起始: "12." / "12．" / "12、"
Q_RE = re.compile(r"(?m)^[ \t]*(\d{1,2})\s*[.．、]\s*")


def pdf_text(path, decrypt=False):
    """提取 PDF 全文。answers 需空密码解密。"""
    r = PdfReader(path)
    if r.is_encrypted:
        r.decrypt("")
    pages = []
    for p in r.pages:
        pages.append(p.extract_text() or "")
    return pages


def clean(s):
    s = s.replace("\u3000", " ")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{2,}", "\n", s)
    return s.strip()


def find_questions(text):
    """
    按 N. 切出题目块。返回 [(num, body)]

    用「按期望序号顺序查找」而非「单调递增去重」: 试卷中偶发游离的假匹配
    (例如图表标签/页码里的 "20") 会让递增去重误判并跳掉中间若干题
    (2024 年就因此丢了 15-19 题),顺序查找可免疫。
    """
    hits = []
    pos = 0
    for expected in range(1, 48):
        m = re.compile(rf"(?m)^[ \t]*{expected}\s*[.．、]\s*").search(text, pos)
        if not m:
            continue
        hits.append((expected, m.start(), m.end()))
        pos = m.end()
    blocks = []
    for i, (num, _s, e) in enumerate(hits):
        nxt = hits[i + 1][1] if i + 1 < len(hits) else len(text)
        blocks.append((num, text[e:nxt]))
    return blocks


def split_options(body):
    """把题干与 ABCD 选项分开。返回 (stem, {A:..,B:..,C:..,D:..})"""
    ms = list(OPT_RE.finditer(body))
    if len(ms) < 4:
        return clean(body), {}
    # 取前四个依次出现的 A B C D
    picked = []
    want = ["A", "B", "C", "D"]
    for m in ms:
        if not picked:
            if m.group(1) == "A":
                picked.append(m)
        elif m.group(1) == want[len(picked)]:
            picked.append(m)
        if len(picked) == 4:
            break
    if len(picked) < 4:
        return clean(body), {}
    stem = body[: picked[0].start()]
    opts = {}
    for i, m in enumerate(picked):
        s = m.end()
        e = picked[i + 1].start() if i + 1 < len(picked) else len(body)
        opts[m.group(1)] = clean(body[s:e])
    return clean(stem), opts


# 408 考纲固定结构(自 2009 年统考以来稳定):
#   数据结构 45分 = 单选11题(1-11)  + 综合2题(41-42)
#   组成原理 45分 = 单选11题(12-22) + 综合2题(43-44)
#   操作系统 35分 = 单选10题(23-32) + 综合2题(45-46)
#   计算机网络 25分 = 单选8题(33-40) + 综合1题(47)
# 合计 150 分, 单选 40 题 80 分 + 综合 7 题 70 分
SUBJECT_RANGES = [
    ("数据结构", 1, 11, 41, 42),
    ("计算机组成原理", 12, 22, 43, 44),
    ("操作系统", 23, 32, 45, 46),
    ("计算机网络", 33, 40, 47, 47),
]


def subject_by_range(num):
    """按考纲固定结构定位学科(权威)。"""
    for subj, c_lo, c_hi, a_lo, a_hi in SUBJECT_RANGES:
        if c_lo <= num <= c_hi or a_lo <= num <= a_hi:
            return subj
    return None


def classify(text):
    """关键词打分(仅作为学科校验的辅助信号)"""
    scores = {}
    for subj, kws in SUBJECT_KW.items():
        scores[subj] = sum(text.count(k) for k in kws)
    best = max(scores, key=scores.get)
    return best, scores


def pdf_layout_text(path):
    """按视觉布局提取文本(layout 模式), 用于还原答案表格。"""
    r = PdfReader(path)
    if r.is_encrypted:
        r.decrypt("")
    out = []
    for p in r.pages:
        try:
            out.append(p.extract_text(extraction_mode="layout") or "")
        except Exception:
            out.append("")
    return "\n".join(out)


def _parse_layout_table(layout_text):
    """
    用 layout 模式还原 '8行 x 5列' 答案表(共 40 个字母)。

    题号映射: 第 j 列第 i 行 -> 题号 (j-1)*8 + i
    (第1列自上而下是 1-8 题, 第2列是 9-16 题, ... 第5列是 33-40 题)

    实测两种排版朝向:
      模式A(2010/2011/2018): 行号 1..8 各带 5 个字母
          "1. DBDBC  2. CDBAC ... 8. BACBA"
      模式B(2009/2013/2015/2017): 第1行的 5 个答案散落在左侧, 标号为 1/9/17/25/33;
          第2..8行仍是 5 个字母一组
          "1. D    2. CACAA   3. DCBCD ... 8. DAABA
           9. C   17. D   25. C   33. B"
    """
    i = layout_text.find("单项选择题")
    region = layout_text[i:] if i >= 0 else layout_text
    j = region.find("解析")
    if j > 0:
        region = region[:j]

    # 5 字母块(模式A的每一行; 模式B的第2..8行)
    runs = re.findall(r"(?<![A-D])[A-D]{5}(?![A-D])", region)
    # 带标号的单字母: 1/9/17/25/33 -> 模式B 的第1行
    singles = {}
    for m in re.finditer(r"(?<!\d)(1|9|17|25|33)\s*[.．、n]?\s*([A-D])(?![\w])", region):
        singles.setdefault(int(m.group(1)), m.group(2))

    grid = {}  # (row 1..8, col 0..4) -> letter
    if len(runs) >= 8:
        # 模式A: 前 8 个 5 字母块依次是第 1..8 行
        for r, letters in enumerate(runs[:8], start=1):
            for c, ch in enumerate(letters):
                grid[(r, c)] = ch
    elif len(runs) >= 7 and len(singles) >= 4:
        # 模式B: 7 个 5 字母块是第 2..8 行; 单字母按标号定位到第 1 行的各列
        for idx, letters in enumerate(runs[:7]):
            r = idx + 2
            for c, ch in enumerate(letters):
                grid[(r, c)] = ch
        for label, ch in singles.items():
            c = (label - 1) // 8
            if 0 <= c < 5:
                grid[(1, c)] = ch

    out = {}
    for (r, c), ch in grid.items():
        q = c * 8 + r
        if 1 <= q <= 40:
            out.setdefault(q, ch)
    return out


def parse_answers(pages, layout_text=""):
    """
    从答案 PDF 抽取 {题号: 答案字母}

    实测 18 年答案 PDF 共有三类版式, 本函数按可靠性依次尝试:
      A. 段落式   "31.【参考答案】B"                      -> 2023
      B. 成对式   "1. B 2. A 3. A ..."                    -> 2012 / 2020 / 2022
      C. 表格网格 数字块与字母块分离(如 "1. 9. 17... \\n DBDBC") -> 2009-2011/2013-2015/2017/2018
    另有 5 年答案 PDF 无文字层(纯扫描图, 提取不到字符):
      2019 / 2021 / 2024 / 2025 / 2026 -> 需 OCR 或人工录入
    """
    text = "\n".join(pages)
    ans = {}

    # --- 0. 布局表(最可靠): layout 模式可将 8行x5列 答案表原样还原
    #     结构: 行号 1..8, 每行 5 个字母; 题号 = (列-1)*8 + 行
    lay = _parse_layout_table(layout_text)
    if len(lay) == 40:
        return lay, "布局表"

    # --- A. 段落式
    for m in re.finditer(r"(\d{1,2})\s*[.．、]?\s*【参考答案】\s*([A-D])", text):
        n = int(m.group(1))
        if 1 <= n <= 40 and n not in ans:
            ans[n] = m.group(2)
    if len(ans) >= 35:
        return ans, "段落式"

    # --- B. 成对式: "N. X" 后不接字母/数字(避免匹配 "1. 解析" 之类)
    pairs = {}
    for m in re.finditer(r"(?<!\d)(\d{1,2})\s*[.．、]\s*([A-D])(?![\w])", text):
        n = int(m.group(1))
        if 1 <= n <= 40 and n not in pairs:
            pairs[n] = m.group(2)
    if len(pairs) >= 35:
        return pairs, "成对式"

    # --- C. 表格网格: 数字块(每块5个) 与 5字母块 按行 zip
    grid = _parse_grid(text, pairs)
    if grid and len(grid) >= 35:
        return grid, "表格网格"

    if ans:
        return ans, "部分(段落式)"
    if pairs:
        return pairs, "部分(成对式)"
    return {}, "无文字层/未识别"


def _parse_grid(text, pairs):
    """
    重建 '数字块 + 5字母块' 版式的答案表。

    关键点: 部分年份(2009/2013/2015/2017)第 1 行的字母是以成对式
    "1. B  9. A  17. A ..." 出现的, 因此字母块只有 7 组而数字有 8 行。
    必须按「前 N 行已被成对式覆盖」做偏移对齐, 否则整表错位一行。
    """
    i = text.find("参考答案")
    region = text[i:] if i >= 0 else text
    nums = [int(m.group(1)) for m in re.finditer(r"(?<!\d)(\d{1,2})\s*[.．、]", region)]
    nums = [n for n in nums if 1 <= n <= 40]
    groups = re.findall(r"(?<![A-D])[A-D]{5}(?![A-D])", region)
    if not groups:
        return {}

    seen, rows, cur = set(), [], []
    for n in nums:
        if n in seen:
            continue
        seen.add(n)
        cur.append(n)
        if len(cur) == 5:
            rows.append(cur)
            cur = []
    if cur:
        rows.append(cur)

    # 前几行已由成对式给出?
    offset = 0
    for row in rows:
        if len(row) == 5 and all(n in pairs for n in row):
            offset += 1
        else:
            break

    out = {n: c for n, c in pairs.items() if 1 <= n <= 40}
    for row, letters in zip(rows[offset:], groups):
        if len(row) != len(letters):
            continue
        for n, ch in zip(row, letters):
            out.setdefault(n, ch)
    return out


def verify_against_explanations(pages, answers):
    """
    自洽校验: 解析正文里通常写着 "故选 B"/"答案为 D"。
    用它与答案表交叉验证, 返回 (一致数, 不一致清单)。
    """
    text = "\n".join(pages)
    blocks = {}
    marks = list(re.finditer(r"(?m)^[ \t]*(\d{1,2})\s*[.．、]\s*解析", text))
    for i, m in enumerate(marks):
        n = int(m.group(1))
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        blocks.setdefault(n, text[m.end():end])
    agree, disagree = 0, []
    for n, blk in blocks.items():
        if n not in answers:
            continue
        found = re.findall(r"(?:故选|答案为|正确答案为|正确答案是|应选|选)\s*([A-D])", blk)
        if not found:
            continue
        if found[-1] == answers[n]:
            agree += 1
        else:
            disagree.append((n, answers[n], found[-1]))
    return agree, disagree


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("year", type=int)
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    y = args.year
    paper = os.path.join(CACHE, f"{y}.pdf")
    answer = os.path.join(CACHE, f"{y}-answer.pdf")
    for p in (paper, answer):
        if not os.path.exists(p):
            sys.exit(f"缺少文件: {p}\n请先下载到 {CACHE}/")

    ppages = pdf_text(paper)
    apages = pdf_text(answer, decrypt=True)
    ptext = "\n".join(ppages)

    blocks = find_questions(ptext)

    # 答案优先取「校订答案库」(由 build_answer_key.py 生成):
    # 11 年人工读图录入 + 7 年自动提取且交叉校验干净。
    # 实测自动提取在版式复杂的年份会出错(2009 错 16 题), 故校订库优先。
    vkey = os.path.join(OUT, "answers_verified.json")
    vans = {}
    if os.path.exists(vkey):
        d = json.load(open(vkey, encoding="utf-8"))
        vans = {int(k): c for k, c in d.get("答案", {}).get(str(y), {}).items()}

    if vans:
        answers, ans_mode, conf = vans, "校订答案库", "高"
        agree, disagree = verify_against_explanations(apages, answers)
    else:
        answers, ans_mode = parse_answers(apages, pdf_layout_text(answer))
        agree, disagree = verify_against_explanations(apages, answers)
        # 版式确定性: 布局表/段落式/成对式为高; 网格重建实测会错位 -> 低, 不入库
        if ans_mode in ("布局表", "段落式", "成对式"):
            conf = "高"
        elif ans_mode == "表格网格":
            conf = "低(网格重建, 需校验)"
        else:
            conf = "无(答案PDF无文字层)"

    items = []
    unresolved = []
    for num, body in blocks:
        is_choice = num <= 40
        fig = bool(FIG_RE.search(body))
        rec = {
            "id": f"408-{y}-{num:02d}",
            "year": y,
            "题号": num,
            "题型": "单项选择题" if is_choice else "综合应用题",
        }
        if is_choice:
            stem, opts = split_options(body)
            rec["题干"] = stem
            rec["选项"] = opts
            rec["答案"] = answers.get(num) if conf == "高" else None
            if conf != "高" and num in answers:
                rec["_答案待校验"] = answers[num]   # 低置信, 仅留待人工/LLM复核
            rec["分值"] = 2
            # 选项抽不全 => 选项本身是图片(如 2009#4 的四个树形图),同样属于需插图
            if len(opts) < 4:
                fig = True
                rec["选项为图片"] = True
        else:
            rec["题干"] = clean(body)
            rec["选项"] = {}
            rec["答案"] = None           # 综合题为主观题,无客观选项答案
            rec["分值"] = None           # 分值见综合题题干内的"(N 分)"
        # 学科: 以考纲固定结构为准, 关键词打分仅作校验
        subject = subject_by_range(num)
        kw, scores = classify(rec["题干"] + "".join(rec["选项"].values()))
        rec["学科"] = subject
        rec["_学科校验"] = kw if kw != subject else "一致"
        rec["_学科得分"] = scores
        rec["需插图"] = fig
        rec["_来源"] = f"neville-studio/408-exam-paper (MIT) papers-rebuild/{y}.pdf"
        if is_choice and (len(rec["选项"]) != 4 or not rec["题干"]):
            unresolved.append((num, body))
        items.append(rec)

    os.makedirs(OUT, exist_ok=True)
    dst = os.path.join(OUT, f"{y}.json")
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(
            {
                "year": y,
                "来源": "neville-studio/408-exam-paper (MIT) — 文字重排版",
                "年份说明": "2009-2026 共 18 套",
                "题目数": len(items),
                "题目": items,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    # ---- 质量报告
    ch = [r for r in items if r["题型"] == "单项选择题"]
    print(f"=== {y} 年解析报告 ===")
    print(f"总题数        : {len(items)}  (单选 {len(ch)} / 综合 {len(items)-len(ch)})")
    print(f"选项切分成功  : {sum(1 for r in ch if len(r['选项'])==4)}/{len(ch)}")
    print(f"答案(高置信)  : {sum(1 for r in ch if r['答案'])}/{len(ch)}   [版式: {ans_mode}]")
    print(f"解析交叉校验  : 一致 {agree} / 不一致 {len(disagree)} {disagree[:3]}")
    print(f"需插图题      : {sum(1 for r in items if r['需插图'])}/{len(items)}"
          f"  (单选 {sum(1 for r in ch if r['需插图'])}/{len(ch)})")
    from collections import Counter
    print("学科分布(考纲) :", dict(Counter(r["学科"] for r in items)))
    dis = [(r["题号"], r["学科"], r["_学科校验"]) for r in items if r["_学科校验"] != "一致"]
    print(f"关键词校验不一致: {len(dis)} 题 (仅供参考, 学科以考纲区间为准)")
    if dis:
        print("   ", dis[:15])
    figs = [r["题号"] for r in items if r["需插图"]]
    imgopt = [r["题号"] for r in items if r.get("选项为图片")]
    print(f"需插图题号      : {figs}")
    print(f"  其中选项为图片: {imgopt}")
    print(f"纯文字单选题    : {len(ch)-len([r for r in ch if r['需插图']])}/{len(ch)}"
          f"  <- 可直接自动判题的比例")
    if unresolved:
        print(f"未完全解析    : {len(unresolved)} 题 -> {[n for n,_ in unresolved]}")
    print(f"输出          : {dst}")

    if args.debug and unresolved:
        for n, body in unresolved:
            print(f"\n----- 未解析 #{n} -----\n{body[:400]}")


if __name__ == "__main__":
    main()
