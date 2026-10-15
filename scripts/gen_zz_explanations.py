#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成**考研政治客观题（单选 + 多选）的解析**。

用户要求
--------
"把政治真题的解析也全部生成，到时候如果用户提交答案给出答案以及解析"

所以产出要能让界面在用户提交答案后同时显示：① 正确答案 ② 解析。

两种来源，**逐条标注**（不能混为一谈）
-------------------------------------
  ① 题源自带的解析 —— 部分年份的题源里就有【解析】，这是最可靠的，直接抽取。
     实测 2016 那份 eol 文字版有 20 处，格式为：
         "答案：B\n【解析】本题考查的是…故本题的正确答案为B。"
  ② AI 生成 —— 其余年份没有解析，用 LLM 写。**必须标注"AI 生成（未经官方核验）"**。

  **绝不把 ② 说成官方解析** —— 这是用户的红线。

关于时政题的特别处理
--------------------
政治有 16 分的「时政与当代」，考的是**当年**发生的事情。
对 2026 卷尤其严重：它考"十五五"规划建议（2025 年 10 月二十届四中全会），
**这在模型训练截止之后**。对这类题：

  · 仍然生成（考点分析、干扰项辨析大多不依赖具体时政细节，有参考价值）
  · 但**额外标注** `需自行核对时政`，提示学生"这条解析对时政细节可能有误"
  · **不编造**当年的具体提法、数字、文件名 —— prompt 里明确要求"不确定就不要写细节"

存储
----
    data/zhengzhi/<年份>-解析.json
        {"年份": "2016", "题数": 33,
         "解答": {"1": {"文本": "...", "来源": "题源抽取"},
                  "2": {"文本": "...", "来源": "AI 生成（未经官方核验）",
                        "时政存疑": true}}}

  **单独放一个文件，不混进 <年份>.json** —— 那个文件会被
  parse_zhengzhi.py --write 整个重写，混进去就会丢（我为此丢过两次答案）。

用法
----
    .venv/bin/python scripts/gen_zz_explanations.py --dry-run
    .venv/bin/python scripts/gen_zz_explanations.py --limit 10 --write   # 试质量
    .venv/bin/python scripts/gen_zz_explanations.py --write              # 全量
    .venv/bin/python scripts/gen_zz_explanations.py --extract-only --write  # 只抽题源自带的
"""
import argparse
import glob
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from yj import llm, zhengzhi as zz                          # noqa: E402
from scripts.parse_zhengzhi import read_text                 # noqa: E402

DEST = os.path.join(BASE, "data", "zhengzhi")
CACHE = os.path.join(BASE, ".cache", "zhengzhi")

# 时政题的题号范围（官方结构：单选 15-16、多选 32-33 是时政；分析题 38 也偏时政）
SHIZHENG = {15, 16, 32, 33}


def path_of(year):
    return os.path.join(DEST, f"{year}-解析.json")


def load(year):
    p = path_of(year)
    if os.path.exists(p):
        try:
            return json.load(open(p, encoding="utf-8"))
        except Exception:                                   # noqa: BLE001
            pass
    return {"年份": str(year), "解答": {}}


def save(year, rec):
    rec["题数"] = len(rec["解答"])
    tmp = path_of(year) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path_of(year))            # 原子写，中断不留半个文件


def source_file(year):
    fs = (glob.glob(os.path.join(CACHE, f"{year}*.txt"))
          + glob.glob(os.path.join(CACHE, f"{year}*.pdf"))
          + glob.glob(os.path.join(CACHE, f"{year}*.docx"))
          + glob.glob(os.path.join(CACHE, f"{year}*.html")))
    return fs[0] if fs else None


def extract_builtin(year):
    """
    从题源里抽取**自带的解析**：{"题号": "解析文本"}。

    只认一种可靠形态 —— "答案：X" 紧跟 "【解析】…"，因为这样能确定
    解析属于哪一道题。抽不到就返回空（交给 AI 生成）。

    边界判定：解析文本到"下一个题号"或结尾为止。题源里的解析通常以
    "故本题的正确答案为B。" 这类句子收尾，上面这种切法足够稳。
    """
    f = source_file(year)
    if not f:
        return {}
    raw = read_text(f)
    out = {}
    # 定位每个 "答案：X\n【解析】" 的位置
    marks = list(re.finditer(
        r'答案\s*[:：]?\s*[A-Da-dＡ-Ｄ]{1,4}\s*\n\s*【解析】\s*[:：]?', raw))
    if not marks:
        return out
    # 用"题号"把这些解析归属到题：向前找最近的题号
    qnums = [(m.start(), int(m.group(1)))
             for m in re.finditer(r'(?m)^\s*(\d{1,2})\s*[.．、]', raw)]
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(raw)
        # 解析别一路吃到下一题（那样会把题干吞进来）
        nxt = [s for s, _ in qnums if s > m.start()]
        if nxt:
            end = min(end, nxt[0])
        text = raw[m.end():end].strip()
        text = re.sub(r'\s+', '', text)
        # 归属：向前找最近的题号
        owner = None
        for s, n in qnums:
            if s < m.start():
                owner = n
            else:
                break
        if owner and 12 <= len(text) <= 800:
            out.setdefault(str(owner), text)
    return out


def prompt_for(q, year):
    opts = q.get("选项") or {}
    opts_txt = "\n".join(f'{k}. {v}' for k, v in sorted(opts.items()))
    n = int(q["题号"])
    shizheng = n in SHIZHENG or q.get("部分") == "SZ"
    extra = ""
    if shizheng:
        extra = """
6. **这是一道时政题**。你对当年时政细节的记忆可能不准确 ——
   如果题目涉及具体的会议名称、文件名称、数字、提法，而你不确定，
   **就不要写这些细节**，改为讲"这类题考的是什么、怎么排除干扰项"。
   宁可讲得概括，也不要编造具体表述。
"""
    kind = "单项选择题" if q["题型"] == "单项选择题" else "多项选择题"
    return f"""你是考研政治的辅导老师。下面是一道**{kind}**，正确答案已给出。请写一段解析。

要求：
1. **先说正确答案为什么对** —— 讲清对应的考点原理，不要只说"选 A 因为 A 对"。
2. **再指出主要干扰项错在哪** —— 哪几个最容易误选、错在哪个概念上。
3. **2–4 句话，不超过 150 字**。学生要的是快速看懂，不要长篇大论。
4. 只讲本题考点，不要扩展到考纲外，不要谈命题趋势或复习建议。
5. 直接给解析正文，不要加"解析："前缀，不要重复题干和选项原文。{extra}
【题目】
{year} 年 第 {q['题号']} 题（{kind}）　所属部分：{q.get('部分名', '未知')}
题干：{q['题干']}
{opts_txt}
正确答案：{q['答案']}
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 道（试质量用）")
    ap.add_argument("--year", default=None, help="只跑某一年")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--extract-only", action="store_true",
                    help="只抽题源自带的解析，不调用 LLM")
    args = ap.parse_args()

    years = [args.year] if args.year else zz.years()

    # ---- 第一步：抽取题源自带的解析（免费、最可靠）----
    extracted = {}
    for y in years:
        got = extract_builtin(y)
        if got:
            extracted[y] = got
            print(f"  {y}: 题源自带解析 {len(got)} 条")

    # ---- 第二步：整理待生成清单 ----
    todo = []
    for y in years:
        rec = load(y)
        have = rec["解答"]
        for q in zz.paper(y)["题目"]:
            if q["题型"] not in ("单项选择题", "多项选择题"):
                continue                       # 分析题是主观题，不生成选择题式解析
            num = str(q["题号"])
            if num in have and have[num].get("文本"):
                continue
            # 优先用题源自带的
            if num in extracted.get(y, {}):
                have[num] = {"文本": extracted[y][num], "来源": "题源抽取"}
                continue
            if not q.get("答案"):
                continue                       # 没答案的题不生成解析（先补答案）
            todo.append((y, q))
        if args.write and not args.extract_only:
            save(y, rec)

    n_ready = sum(len(load(y)["解答"]) for y in years)
    print(f"\n已就绪（题源抽取）{n_ready} 条")
    print(f"待 AI 生成 {len(todo)} 道")

    if args.extract_only or args.dry_run or not todo:
        if args.extract_only and args.write:
            for y in years:
                save(y, load(y))
            print("已写盘（仅题源抽取部分）")
        return

    ok, msg = llm.status()
    print(f"LLM: {msg}")
    if not ok:
        print("未配置 key，无法生成", file=sys.stderr)
        sys.exit(1)

    if args.limit:
        todo = todo[:args.limit]
        print(f"（--limit {args.limit}，本次只跑 {len(todo)} 道）")

    done = fail = 0
    fails = []
    pending = {}
    for i, (y, q) in enumerate(todo, 1):
        num = str(q["题号"])
        tag = "时政" if int(num) in SHIZHENG else "  "
        try:
            # llm.complete() 返回 **dict** {"text", "source"}（不是字符串），
            # 且不接受 temperature；payload 用于缓存键（重跑不重复花额度）。
            r = llm.complete("choice", prompt_for(q, y),
                             payload={"exam": "zz", "y": y, "n": num, "v": 1})
            text = ((r or {}).get("text") or "").strip()
            text = re.sub(r'^\s*解析\s*[:：]\s*', '', text)
            if len(text) < 20:
                raise ValueError(f"返回过短（{len(text)} 字）")
            entry = {"文本": text, "来源": "AI 生成（未经官方核验）"}
            if int(num) in SHIZHENG:
                entry["时政存疑"] = True
            pending.setdefault(y, load(y))["解答"][num] = entry
            done += 1
            print(f"  [{i}/{len(todo)}] {y}#{num} [{tag}] {text[:56]}…")
        except Exception as e:                              # noqa: BLE001
            fail += 1
            fails.append(f"{y}#{num}: {type(e).__name__} {e}")
            print(f"  [{i}/{len(todo)}] {y}#{num} ❌ {type(e).__name__}")
        # 按年份增量落盘：跑 40 分钟，中断不能从零重来
        if args.write and pending.get(y) and (
                i % 5 == 0 or i == len(todo)
                or (i < len(todo) and todo[i][0] != y)):
            save(y, pending[y])

    if args.write:
        for y, rec in pending.items():
            save(y, rec)
    print(f"\n完成 {done} 道，失败 {fail} 道")
    for f in fails[:10]:
        print("  ", f)
    print("提示：最后记得跑 scripts/zz_manual_answers.py 应用人工答案")


if __name__ == "__main__":
    main()
