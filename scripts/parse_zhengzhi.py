#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把考研政治真题 PDF 解析成结构化题库（客观题 + 分析题）。

为什么单独写一个解析器
----------------------
政治的排版与 408 不同，实测（2015 年那份 PDF）踩到四个坑：
  ① **答案在题干末尾的括号里**："…这表明（答案：B）" —— 408 的答案在单独的文件里
  ② **答案标记可能跨行断开**："…（答\\n案：D）" —— 直接按行处理会漏
  ③ **选项符号全角半角混用**：多数是 "A．"，但实测有 "D." —— 只匹配一个会漏选项
  ④ **题干有多余换行**："书本知\\n识非常重要" —— 必须把换行合并，否则题干读起来是断的

题型分值（2010 年改革后固定，16 年一致）：
    一、单项选择题 1～16    每题 1 分，共 16 分
    二、多项选择题 17～33   每题 2 分，共 34 分
    三、材料分析题 34～38   每题 10 分，共 50 分
**只有前两类可机判（50 分）**；分析题是主观题，界面走"参考答案 + 自评给分"。

用法：
    .venv/bin/python scripts/parse_zhengzhi.py --pdf .cache/zhengzhi/2015.pdf --year 2015
    .venv/bin/python scripts/parse_zhengzhi.py --pdf ... --year 2015 --write
"""
import argparse
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

OUT_DIR = os.path.join(BASE, "data", "zhengzhi")

# 三个大题的标题（允许"一、"与"单项选择题"之间有空格）
SEC = re.compile(r'[一二三]\s*[、,.]\s*(单项选择题|多项选择题|材料分析题|分析题)')
# 题号：行首的 "12." 或 "12．"
# 题号符号实测有 "1." "1．" "1、" 三种（2023 那份用"、"）
#
# 【不要在这里加"后面不能跟数字"的约束】我试过：正文里 "增长5.9%" 的 "9."
# 本不该算题号，但加上 `(?!\d)` 后**反而把 12 个年份弄坏了**（38 道掉到 30 道左右）
# —— 因为 `\s*` 会先吃掉空白，负向断言检查的位置和我预期的不一样。
# 结论：这个正则动不得。2024 第23题/2017 第30题的"选项 0 个"是**已知的个别问题**，
# 不值得为它破坏 16 个年份的整体正确性（那是 608/608 的结构完整性）。
QNUM = re.compile(r'(?m)^\s*(\d{1,2})\s*[.．、]\s*')
# 分析题专用题号正则 —— 与单选/多选的 QNUM 不同，它必须容忍三种位置：
#   ① 行首：          "\n34. 结合材料回答问题："
#   ② 粘在上一题末尾：  "…（5分）36.结合材料回答问题："
#      （实测 2012 第 36 题就是这样，题号前是"分）"，漏了它整题就丢了）
#   ③ **前面是全角空格**： "\u3000\u300038、结合材料回答问题："（实测 2014/2016 第 38 题）
# 所以前缀用"行首 或 )）分 或 全角空格 之后"。
# **不能无条件放宽**（写成 `(?<![\d])(3[4-8])`）—— 我试过，那样会匹配到正文里的
# 数字，2013/2014 会多识别出题号导致误切（38 道掉到 34 道）。
# 另注意：别把 \n 放进字符类 —— `(?:\n|[)）分])` 里 \n 会匹配真实换行，
# 而换行紧跟着"（"，正则就从"（"开始匹配而失败（这个坑我踩过）。
QNUM_LOOSE = re.compile(r'(?m)(?:^|(?<=[)）分\u3000\s]))\s*(3[4-8])\s*[.．、]?\s*'
                        r'(?=[^\d\s])')
# 答案标记 —— 实测有**两种排版**，必须都支持：
#   ① 括号格式，且答案在**题干中间**（2015 那份）：
#         "…水稻来。”这表明（答案：B） "
#   ② 裸写格式，答案自成一行（2016 那份 eol 文字版）：
#         "D.在事物的发展过程中要时时注意事物的自我否定\n答案：B\n【解析】…"
#
# 原来的正则只支持 ①，导致 2016 的 31 个答案全部读不到
# （表现为"2016 缺 2 道答案"——其实更多，只是那两道题源里另有括号格式的答案）。
# 另外**字母可能是全角**（"答案：ＢＣＤ"），也要归一化。
#
# 注意锚定方式：① 不能锚行首（答案在句中）；② 必须锚行首（否则会匹配到
# 【解析】里的"答案"字样）。所以用两条交替分支，各自带合适的锚定。
# 冒号后的空白/换行都要容忍 —— 实测有 "（答案：\nBCD）" 这种跨行写法。
ANS = re.compile(
    r'(?:[（(]\s*答\s*案\s*[:：]?\s*([A-Da-dＡ-Ｄａ-ｄ]{1,4})\s*[)）]'
    r'|(?m:^)\s*答\s*案\s*[:：]\s*([A-Da-dＡ-Ｄａ-ｄ]{1,4})(?=\s|$))')


def ans_letter(m):
    """
    从 ANS 的匹配里取答案字母，并**归一化全角 → 半角、统一大写**。

    为什么需要：实测题源里既有半角 "B" 也有全角 "Ｂ"（2016 那份是
    "答案：ＢＣＤ"）。不归一化的话，答案字符串会和选项键 "BCD" 对不上，
    判分时就找不到选项（审计会报"答案越界"）。
    """
    s = m.group(1) or m.group(2) or ""
    out = []
    for c in s:
        o = ord(c)
        if 0xFF21 <= o <= 0xFF3A:          # 全角 Ａ-Ｚ
            c = chr(o - 0xFF21 + ord("A"))
        elif 0xFF41 <= o <= 0xFF5A:        # 全角 ａ-ｚ
            c = chr(o - 0xFF41 + ord("a"))
        out.append(c.upper())
    return "".join(out)
# 选项：允许全角/半角点号
# 选项符号实测有四种：".", "．", "、", 以及**全角逗号 "，"**
# （最后一种是子 agent 在 2016 年那份 docx 里发现的，原来的正则匹配不到）
# 选项匹配 —— **先按行首切，不够再按字母序列切**（两段式，踩坑后的做法）
#
# 实测排版极其不统一，同一份文件里都可能混着来：
#   ① 每行一个选项、带分隔符：   A．实践是认识的基础
#   ② 全挤在一行、带分隔符：     A. 《德意志意识形态》B.《神圣家族》C.《哲学的贫困》
#   ③ 每行一个选项、**没有分隔符**：A《共产党宣言》 / B.家庭、私有制和国家的起源
#   ④ 混着来（2020 那份）：      A《共产党宣言》
#                                B.家庭、私有制和国家的起源C.《反杜林论》
#
# 教训：不要试图用"一个大正则"覆盖全部 —— 我先试过放宽成"不要求行首"，
# 结果正文里孤立的 A 被当成选项起点，2010–2014 直接解析出 0 道。
# 所以：**先严格（行首锚定），不够 4 个再按字母序列切**（字母 A→B→C→D
# 连续出现本身就是最强的分隔信号，正文里不会四个字母连着出现）。
OPT = re.compile(r'(?m)^\s*([A-D])\s*[.．、,，]?\s*(.+?)'
                 r'(?=\n\s*[A-D]\s*[.．、,，]?\s|\Z)', re.S)

# 字母序列切分：找出 A、B、C、D 四个标记（要求按顺序连续出现）
OPT_SEQ = re.compile(r'(?<![A-Za-z0-9])([A-D])\s*[.．、,，]?\s*(?=[^\s])')

def _norm_letters(s):
    """全角字母 → 半角大写"""
    out = []
    for c in s:
        o = ord(c)
        if 0xFF21 <= o <= 0xFF3A:
            c = chr(o - 0xFF21 + ord("A"))
        elif 0xFF41 <= o <= 0xFF5A:
            c = chr(o - 0xFF41 + ord("a"))
        out.append(c.upper())
    return "".join(out)


def clean_option(s):
    """
    清掉选项尾巴上粘的答案/解析。

    **实测 100 处**（2014/2016/2021 各 33 个 D 选项、2015 一个）：
    题源里答案和最后一个选项**排在同一行**，没有换行分隔：
        "D.在事物的发展过程中要时时注意事物的自我否定答案：B【解析】本题考查的是…"
    结果整个答案和解析都被吞进 D 选项的文本里 —— 用户在选项里直接看到答案。

    判据：出现 `答案：` / `【答案】` / `【解析】` 就从那里截断。
    这类标记在**正常选项正文里不会出现**，所以截断是安全的
    （已用"道德为法律提供价值基础"等正常选项验证过不被误切）。
    """
    m = re.search(r'【\s*答案\s*】|[（(]?\s*答\s*案\s*[:：]|【\s*解析\s*】', str(s))
    if m:
        s = str(s)[:m.start()]
    return s.strip().rstrip('。．.')


def split_options(block):
    """
    从一段文本里取出选项。返回 (选项dict, 选项起始偏移)。

    两段式：
      1) 行首模式 —— 每行一个选项（PDF/docx/多数网页）
      2) 字母序列模式 —— 按 A→B→C→D 连续标记切（选项挤在一行、或没有分隔符时）
    返回偏移是为了让调用方知道题干到哪里结束。
    """
    m = list(OPT.finditer(block))
    opts = {}
    for x in m:
        opts.setdefault(x.group(1), x.group(2))
    if len(opts) >= 4:
        return opts, m[0].start()

    # 兜底：找形如 A…B…C…D… 的连续字母标记
    marks = []
    expect = "ABCD"
    ei = 0
    for x in OPT_SEQ.finditer(block):
        if x.group(1) == expect[ei]:
            marks.append(x)
            ei += 1
            if ei == 4:
                break
    if ei == 4:
        o2 = {}
        for i, x in enumerate(marks):
            end = marks[i + 1].start() if i + 1 < len(marks) else len(block)
            o2[x.group(1)] = block[x.end():end]
        return o2, marks[0].start()

    return (opts, m[0].start()) if opts else ({}, None)

def clean(s: str) -> str:
    """合并题干里的多余换行与空格（PDF 抽出的中文常被硬换行切碎）"""
    s = re.sub(r'[ \t\u3000]+', ' ', s)
    s = re.sub(r'\s*\n\s*', '', s)       # 中文不需要空格补位
    return s.strip()


def detect_year(txt):
    """从正文开头识别年份（两份题源都在开头写明"20XX 年…真题"）"""
    m = re.search(r'(20\d{2})\s*年', txt[:1200])
    return m.group(1) if m else None


def read_text(path):
    """
    读取题源文本。支持 PDF 与 docx —— 实测两者都有可用来源：
        PDF  ：高校官网/教学平台挂的真题（2015、2022–2025）
        docx ：另一种常见形式（2016 年那份是黄淮学院数学系网站上的 docx），
               而且 **docx 的排版往往比 PDF 干净**（没有硬换行把中文切碎）
    """
    low = path.lower()
    if low.endswith((".txt", ".html", ".htm")):
        # 【纯文本 / HTML】有些年份的真题只在网页正文里（高校的 article 页、
        # eol.cn 的页面）。fetch_zz_pdfs.py 会把 HTML 剥成 .txt 再交过来，
        # 这里必须能读 —— 原来只认 .docx，其余一律当 PDF，
        # 结果 .txt 被 PdfReader 打开报 "Stream has ended unexpectedly"（实测踩到）。
        raw = open(path, encoding="utf-8", errors="ignore").read()
        if low.endswith((".html", ".htm")):
            raw = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", raw,
                         flags=re.S | re.I)
            raw = re.sub(r"<[^>]+>", "\n", raw)
            raw = (raw.replace("&nbsp;", " ").replace("&amp;", "&")
                      .replace("&lt;", "<").replace("&gt;", ">"))
            raw = re.sub(r"[ \t\u3000]+", " ", raw)
            raw = re.sub(r"\n{2,}", "\n", raw)
        return raw
    if low.endswith(".docx"):
        import zipfile
        with zipfile.ZipFile(path) as z:
            xml = z.read("word/document.xml").decode("utf-8", "ignore")
        # 按段落取文本：选项在 docx 里是独立段落，必须保留段边界，
        # 否则所有选项会被粘成一行，正则匹配不到
        out = []
        for para in re.findall(r'<w:p[ >].*?</w:p>', xml, re.S):
            t = "".join(re.findall(r'<w:t[^>]*>(.*?)</w:t>', para, re.S))
            t = re.sub(r'<[^>]+>', '', t).strip()
            if t:
                out.append(t)
        return "\n".join(out)
    from pypdf import PdfReader
    return "\n".join((p.extract_text() or "") for p in PdfReader(path).pages)


def parse(pdf_path, year=None):
    raw = read_text(pdf_path)
    # 先把"跨行断开的答案标记"接上，否则会漏题
    raw = re.sub(r'[（(]\s*答\s*\n\s*案', '（答案', raw)
    if not year:
        year = detect_year(raw)
        print(f"（未指定年份，从正文识别为 {year}）")

    # 按三个大题切段
    secs = list(SEC.finditer(raw))
    if not secs:
        raise SystemExit("没找到题型标题 —— PDF 可能不是真题排版")
    spans = []
    for i, m in enumerate(secs):
        end = secs[i + 1].start() if i + 1 < len(secs) else len(raw)
        spans.append((m.group(1), raw[m.end():end]))

    # 【按官方题号范围裁剪】实测 2023 那份 PDF 在分析题后面**接着排了答案与解析**，
    # 解析的编号同样是 "39." "40." 这种形式，会被当成题号 →
    # 结果分析题解析出 11 道（34–43），而官方只有 34–38；
    # 而且答案正文被并进了上一题的题干（第 35 题里混进了第 34 题的答案）。
    # 官方题号范围是固定的（见文件头），超出范围的一律不是题目。
    RANGE = {"单项选择题": (1, 16), "多项选择题": (17, 33),
             "材料分析题": (34, 38), "分析题": (34, 38)}

    # 【去重】实测 2016 那份 docx 把**整份试卷重复排了两遍**（两个"一、单项选择题"
    # 分别在位置 11 和 10779），结果解析出 32 道单选（应为 16）。
    # 这类文件直接入库会让同一道题出现两次。按"题型+题号"去重，
    # 保留第一次出现的（第一份通常是试题原文，第二份可能是带答案的版本）。
    seen = set()

    items = []
    for name, body in spans:
        is_choice = name in ("单项选择题", "多项选择题")
        n = {"单项选择题": 1, "多项选择题": 2, "材料分析题": 10,
             "分析题": 10}[name]
        # 分析题用宽松正则（题号可能粘在上一题末尾），单选/多选必须用行首正则
        # —— 正文里数字密度高，放宽会给单选/多选切错边界。
        base = list(QNUM.finditer(body)) if is_choice else []
        nums = base
        if is_choice:
            # 【已知的个别问题，不在核心正则上修】
            # 实测 2024 多选正文里 "…投资增长11.4%。" 的 "4." 会被 QNUM 当成题号，
            # 于是第 23 题的 chunk 在那里被切断、选项丢失；2017 第 30 题同理。
            # 我试过两种修法（正则里加 `(?!\d)`、在匹配结果上过滤小数），
            # **两次都把 12 个年份弄坏**（38 道掉到 27–31 道）。
            # 权衡：608/608 的**结构完整**比修好这 2 道题的选项重要得多 ——
            # 破坏 16 个年份的整体正确性去救 2 道题是亏的。
            # 留待将来用一个"只在缺失处局部重扫"的方案，而不是改全局正则。
            # 【补漏：题号后没有 `.．、` 分隔符】实测 2017 第 30 题源里写成
            #     `30“天下之事，不难于立法…`
            # 数字后直接是中文引号，QNUM 匹配不到 → 整道多选被丢。
            # 这里**只对"缺的题号"补**，且要求该数字独占行首、后面不是数字 ——
            # 比无条件放宽安全得多（我试过无条件放宽：正文里的数字被当题号，
            # 2010–2021 从 38 道掉到 34 道）。
            lo_c, hi_c = RANGE.get(name, (1, 38))
            have = {int(m.group(1)) for m in nums}
            for want in range(lo_c, hi_c + 1):
                if want in have:
                    continue
                for m in re.finditer(r'(?m)^\s*' + str(want) + r'(?![\d.．、,，])',
                                     body):
                    mm = re.match(r'\s*(\d{1,2})', body[m.start():])
                    if mm:
                        nums.append(mm)
                        break
            nums.sort(key=lambda z: z.start())
        if not is_choice:
            lo_a, hi_a = RANGE.get(name, (34, 38))
            seen_num, last = set(), lo_a - 1
            for m in QNUM_LOOSE.finditer(body):
                v = int(m.group(1))
                if lo_a <= v <= hi_a and v > last and v not in seen_num:
                    seen_num.add(v)
                    last = v
                    nums.append(m)
            nums.sort(key=lambda z: z.start())
        for i, m in enumerate(nums):
            end = nums[i + 1].start() if i + 1 < len(nums) else len(body)
            chunk = body[m.end():end]
            num = int(m.group(1))
            lo, hi = RANGE.get(name, (1, 38))
            if not (lo <= num <= hi):
                continue                 # 超出官方题号范围 → 是答案解析，不是题目
            # 遇到重复题号就跳过（保留第一份）。
            # 副作用：若第一份某题选项残缺，第二份更全的那份也会被跳过 ——
            # 2016 那份 docx 因此少入几道题。这是**有意接受的取舍**：
            # 合并策略实测会破坏好数据（见文件末尾说明）。
            if (name, num) in seen:
                continue
            seen.add((name, num))

            if not is_choice:
                # 分析题：整块当题干（含材料），没有选项与答案
                stem = clean(chunk)
                if len(stem) > 20:
                    items.append({"题号": str(num), "题型": name, "分值": n,
                                  "题干": stem, "选项": {}, "答案": None})
                continue

            # 【关键】题干与选项的切分**以第一个选项行为界**，不以答案标记为界。
            # 原因：实测两种题源 —— 2015 那份答案内嵌在题干括号里，
            # 2023 那份**完全没有答案**（答案要另找或靠投票）。
            # 原来用"答案标记"当切分点，遇到无答案的题源会把选项吞进题干。
            opts_found, opt_start = split_options(chunk)
            first_opt = bool(opts_found)
            head = chunk[:opt_start] if opt_start is not None else chunk
            # 答案可能出现在**两个位置**（实测两种题源各占一种）：
            #   ① 题干里（2015 那份）：  "…这表明（答案：B）"
            #   ② **选项之后**（2016 那份 eol 文字版）：
            #         "…D.在事物的发展过程中要时时注意事物的自我否定\n答案：B\n【解析】…"
            # 原来只在 head（题干部分）里找，2016 的答案全在选项之后 → 一个都读不到。
            # 所以先在 head 里找，找不到再在整个 chunk 里找。
            # am_in_head 决定"题干切到哪里"：答案在题干里才需要从 am 处切断，
            # 否则 head 本身就是完整题干（答案在后面，不该影响题干）。
            am = ANS.search(head)
            am_in_head = am is not None
            if not am:
                am = ANS.search(chunk)
            # 【不做"从解析正文推答案"】
            # 我试过两版启发式（从解析结论里取字母 / 用选项原文反查），
            # **两版都在本来没有答案的年份制造误报**：
            # 2010/2011/2012/2014/2019/2020 凭空多出 1–4 个答案。
            # 那是编造 —— 比"没有答案"更糟（用户红线：不能编造数据）。
            # 所以彻底放弃这条路：答案要么来自题源的明确标记，要么来自投票，
            # 要么进 scripts/zz_manual_answers.py 人工核对过的表。
            # （2016 第 22 题的答案藏在解析结论里，已放进人工表。）

            if not am:
                # 【不丢题】原来这里直接 continue，会丢掉"答案标记格式异常"的题。
                # 现在改成：整块当题干、答案留空，交给 vote_zz_answers.py 投票定答案。
                # 理由：政治题源本身错漏不少（实测多选约 30% 答案有误），
                # 答案本来就不可信，不值得为它丢掉一道题。
                stem_only = clean(head)
                om2 = None
                if om2:
                    stem_only = clean(stem_only[:om2.start()])
                opts_only = {k: clean_option(clean(v)) for k, v in opts_found.items()}
                # 【阈值必须是 8 不是 15】实测 2012 第 14 题的题干
                # 「社会主义道德建设的核心」只有 11 字 —— 真题本来就短，
                # 用 15 会把它丢掉（表现为"2012 单选只有 15 道"）。
                # 真正的质量闸门是"选项必须齐 4 个"。
                if len(stem_only) >= 8:
                    items.append({"题号": str(num), "题型": name, "分值": n,
                                  "题干": stem_only, "选项": opts_only,
                                  "答案": None, "待投票": True})
                continue
            stem = clean(head[:am.start()] if am_in_head else head)
            opts = {k: clean_option(clean(v)) for k, v in opts_found.items()}
            if len(opts) < 4:
                continue     # 选项不全的丢弃：判分依赖选项，缺一个就会算错
            items.append({"题号": str(num), "题型": name, "分值": n,
                          "题干": stem, "选项": opts,
                          "答案": ans_letter(am)})
    # 【为什么不做"同题号合并"】我试过：把重复出现的同一题号合并、保留选项更全的
    # 那份。结果**把好数据也弄坏了** —— 2015 那份的 16 道单选被合并成 6 道，
    # 2024 也少了一道。原因是这些文件的重复不是"两道完整相同的题"，而是
    # 被切成了碎片，同题号的多份各自残缺，无法靠合并还原。
    # 所以回到简单可靠的行为：**遇到重复题号就跳过**（保留第一份），
    # 并在循环内就做完整性过滤。2016 那份 docx 因此只入 32 道 —— 见 README/提交说明，
    # 它需要单独的解析策略，不值得为一年不可靠的数据牺牲已入库的五年。
    return items


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", required=True,
                    help="题源文件路径（PDF 或 docx 都支持）")
    ap.add_argument("--year", default=None,
                    help="不传则从正文自动识别")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    items = parse(args.pdf, args.year)
    by_type = {}
    for it in items:
        by_type.setdefault(it["题型"], []).append(it)
    print(f"{args.year} 年解析结果：共 {len(items)} 道")
    for k, v in by_type.items():
        have_ans = sum(1 for x in v if x.get("答案"))
        print(f"  {k}: {len(v)} 道" + (f"（{have_ans} 道有答案）"
                                       if k != "材料分析题" else "（主观题）"))

    pending = [x for x in items if x.get("待投票")]
    if pending:
        print(f"  ⚠️ {len(pending)} 道因答案标记异常需投票定答案："
              f"{[x['题号'] for x in pending]}")
    if by_type.get("单项选择题"):
        s = by_type["单项选择题"][0]
        print(f"\n抽查单选第 {s['题号']} 题：")
        print("  题干:", s["题干"][:70])
        for k in sorted(s["选项"]):
            print(f"    {k}. {s['选项'][k][:50]}")
        print("  答案:", s["答案"])

    if args.write:
        os.makedirs(OUT_DIR, exist_ok=True)
        dst = os.path.join(OUT_DIR, f"{args.year}.json")
        json.dump({"年份": args.year, "题数": len(items), "题目": items},
                  open(dst, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"\n已写入 {dst}")


if __name__ == "__main__":
    main()
