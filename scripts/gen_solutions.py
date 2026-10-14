#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用 LLM 生成**缺失的综合题参考答案**（路 A）。

背景：为什么需要它
------------------
本地答案册能提供的解析已全部抽出（112 道）。剩余缺口的原因都很硬：

    2021 全年        整份扫描件是歪的，OCR 全部失败（试过 300dpi / 切条 /
                     方向分类 / UVDoc 去弯曲，逐页 0 行）
    2019 缺 41/42    扫描页识别不出（重跑多次结果一致）
    2020 缺 41/46
    2024 缺 41
    2025 缺 43/44

**这些解析在本地文件里物理上不存在。** 但题干我们全都有（846 题，含各步骤
的分值），所以可以用 LLM 按步骤写出一份**参考答案**。

诚实要求（红线）
----------------
生成的内容**必须标注来源**：界面上写成
    「参考答案（AI 生成，未经官方核验）」
绝不能和答案册抽取的那批混为一谈 —— 那批标「答案册（OCR 抽取）」。
两批在 data/solutions/*.json 里用 `生成` 字段区分。

用法：
    .venv/bin/python scripts/gen_solutions.py --dry-run     # 先看要生成哪些
    .venv/bin/python scripts/gen_solutions.py --write       # 真正生成并写入
    .venv/bin/python scripts/gen_solutions.py --year 2021 --write
"""
import argparse
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from yj import data, llm                              # noqa: E402

OUT = os.path.join(BASE, "data", "solutions")
YEARS = [str(y) for y in data.years()]
NUMS = [str(n) for n in range(41, 48)]


def load(year):
    p = os.path.join(OUT, f"{year}.json")
    if os.path.exists(p):
        return json.load(open(p, encoding="utf-8"))
    return {"年份": year, "来源": "", "题数": 0, "解答": {}, "生成": []}


def prompt_for(q, year):
    """给 LLM 的提示：要求按题干括号里的步骤分值结构作答。"""
    stems = re.findall(r'[（(]\s*\d+\s*分\s*[）)]', q["题干"])
    return f"""你是一位 408 考研（计算机学科专业基础综合）阅卷老师。
请为下面这道**综合应用题**写一份参考答案。

严格要求：
1. **按步骤作答**：题干的每一小问都要单独作答，并在每问开头标出该问分值
   （题干的括号里已经给了分值，照抄即可，如「(1)（4 分）」）。
2. 最后一小问若要求"用 C/C++ 描述算法"，必须给出**完整可读的代码**并加注释。
3. 只讲这道题涉及的考点，不要扩展到考纲外内容。
4. 用中文，条理清晰，不要客套话。公式与数字要准确。
5. 输出 Markdown，直接给答案，不要重复题干。

【题目信息】
年份：{year} 年 408 真题　题号：{q['题号']}　总分：{q.get('分值')} 分
题型：{q['题型']}　学科：{q.get('学科')}　主考点：{data.node_name(q['主考点'])}
题干里出现的小问分值为：{'、'.join(stems) if stems else '（题干未标注，按小问均分处理）'}

【题干】
{q['题干']}
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", default=None, help="只处理某一年")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    ok, msg = llm.status()
    print(f"LLM: {msg}")
    if not ok:
        print("未配置 key，无法生成。请先配 .streamlit/secrets.toml", file=sys.stderr)
        sys.exit(1)

    years = [args.year] if args.year else YEARS
    todo = []
    for y in years:
        rec = load(y)
        for n in NUMS:
            if n not in (rec.get("解答") or {}):
                todo.append((y, n))
    print(f"待生成：{len(todo)} 道")
    for y, n in todo:
        print(f"  {y} 年第 {n} 题")
    if args.dry_run or not todo:
        return

    made = 0
    for y, n in todo:
        paper = data.paper(y)
        q = next((x for x in paper["题目"] if str(x["题号"]) == n), None)
        if not q:
            print(f"  {y}-{n}: 题库里找不到该题，跳过")
            continue
        r = llm.complete("solution", prompt_for(q, y),
                         payload={"y": y, "n": n, "v": 1})
        if not r.get("text"):
            print(f"  {y}-{n}: 生成失败（{r.get('source')}）")
            continue
        rec = load(y)
        rec.setdefault("解答", {})[n] = r["text"].strip()
        gen = list(rec.get("生成") or [])
        if n not in gen:
            gen.append(n)
        rec["生成"] = sorted(gen, key=int)
        rec["题数"] = len(rec["解答"])
        rec["来源"] = ("答案册 PDF（OCR：PaddleOCR / 文字层）"
                       + (" + AI 生成（缺失部分）" if gen else ""))
        if args.write:
            json.dump(rec, open(os.path.join(OUT, f"{y}.json"), "w",
                                encoding="utf-8"),
                      ensure_ascii=False, indent=1)
        made += 1
        flag = "AI" if n in (rec.get("生成") or []) else "?"
        print(f"  {y}-{n}: 已生成 {len(r['text'])} 字 [{flag}]")

    print(f"\n完成 {made} 道" + ("（已写入）" if args.write else "（未写入）"))


if __name__ == "__main__":
    main()
