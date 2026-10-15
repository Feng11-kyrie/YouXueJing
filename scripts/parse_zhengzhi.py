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
QNUM = re.compile(r'(?m)^\s*(\d{1,2})\s*[.．、]\s*')
# 答案标记：允许括号内换行、冒号全半角、可无括号
# 冒号后**允许换行** —— 实测第 27 题是 "（答案：\nBCD）"，原来的正则漏掉了它，
# 表现为"33 道题只解析出 32 道"。
ANS = re.compile(r'[（(]\s*答\s*案\s*[:：]\s*([A-D]{1,4})\s*[)）]', re.S)
# 选项：允许全角/半角点号
# 选项符号实测有四种：".", "．", "、", 以及**全角逗号 "，"**
# （最后一种是子 agent 在 2016 年那份 docx 里发现的，原来的正则匹配不到）
OPT = re.compile(r'(?m)^\s*([A-D])\s*[.．、,，]\s*(.+?)'
                 r'(?=\n\s*[A-D]\s*[.．、,，]|\Z)', re.S)


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
        nums = list(QNUM.finditer(body))
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
            first_opt = OPT.search(chunk)
            head = chunk[:first_opt.start()] if first_opt else chunk
            am = ANS.search(head)          # 答案只在题干部分里找

            if not am:
                # 【不丢题】原来这里直接 continue，会丢掉"答案标记格式异常"的题。
                # 现在改成：整块当题干、答案留空，交给 vote_zz_answers.py 投票定答案。
                # 理由：政治题源本身错漏不少（实测多选约 30% 答案有误），
                # 答案本来就不可信，不值得为它丢掉一道题。
                stem_only = clean(head)
                om2 = None
                if om2:
                    stem_only = clean(stem_only[:om2.start()])
                opts_only = {}
                if first_opt:
                    for om in OPT.finditer(chunk[first_opt.start():]):
                        opts_only[om.group(1)] = clean(om.group(2))
                if len(stem_only) > 15:
                    items.append({"题号": str(num), "题型": name, "分值": n,
                                  "题干": stem_only, "选项": opts_only,
                                  "答案": None, "待投票": True})
                continue
            stem = clean(head[:am.start()])
            opts = {}
            for om in OPT.finditer(chunk[first_opt.start():]):
                opts[om.group(1)] = clean(om.group(2))
            if len(opts) < 4:
                continue     # 选项不全的丢弃：判分依赖选项，缺一个就会算错
            items.append({"题号": str(num), "题型": name, "分值": n,
                          "题干": stem, "选项": opts,
                          "答案": am.group(1)})
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
