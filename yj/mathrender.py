#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数学题干/解析的渲染：**保留 LaTeX，交给前端 KaTeX**。

为什么换掉 MathML
-----------------
之前用 latex2mathml 在服务端转 MathML。它对 aligned / 矩阵 / 行列式的排版很差：
`\\begin{array}` 的行列对不齐、`&` 会当普通字符、缺 `\\end{array}` 直接报错退回
原始 LaTeX（2025 数一第 5 题实测）。数学题里 these 恰恰是最常见的结构。
现在改成：服务端只做**坏 LaTeX 修补 + HTML 转义**，保留 $...$ / $$...$$，
浏览器加载本地 KaTeX（static/katex，离线可用）统一渲染。

KaTeX 不支持的少数写法在这里修：
  · OCR 丢掉的 \\end{array} / \\right  —— 自动补齐
  · \\xlongequal{...}                  —— 改成 \\overset{...}{=}
"""
import html
import re

_CIRCLED = {str(i): chr(0x2460 + i - 1) for i in range(1, 10)}


def _repair_arrays(tex):
    """补 OCR 丢掉的 \\end{array}（\\right 先到就补在它前面）。"""
    for _ in range(20):
        i = tex.find("\\begin{array}")
        fixed = False
        while i >= 0:
            end = tex.find("\\end{array}", i)
            right = tex.find("\\right", i)
            if right >= 0 and (end < 0 or right < end):
                tex = tex[:right] + "\\end{array}" + tex[right:]
                fixed = True
                break
            i = tex.find("\\begin{array}", i + 1)
        if not fixed:
            break
    return tex


def _repair_delims(tex):
    """补齐 OCR 丢掉的 \\right（仅处理 left 多于 right 的情况）。"""
    stack, i = [], 0
    pairs = {"(": ")", "[": "]", "\\{": "\\}", "|": "|", ".": "."}
    while i < len(tex):
        if tex.startswith("\\left", i):
            j = i + 5
            while j < len(tex) and tex[j] == " ":
                j += 1
            if tex.startswith("\\{", j):
                d, j = "\\{", j + 2
            else:
                d, j = (tex[j] if j < len(tex) else ""), j + 1
            if d in pairs:
                stack.append(d)
            i = j
            continue
        if tex.startswith("\\right", i):
            j = i + 6
            while j < len(tex) and tex[j] == " ":
                j += 1
            j += 2 if tex.startswith("\\}", j) else 1
            if stack:
                stack.pop()
            i = j
            continue
        i += 1
    for d in reversed(stack):
        tex += "\\right" + pairs.get(d, ")")
    return tex


def _strip_xlongequal(tex):
    """把 \\xlongequal{...}（参数里带嵌套花括号）整体换成 =。"""
    out, i = [], 0
    while i < len(tex):
        if tex.startswith("\\xlongequal", i):
            j = i + len("\\xlongequal")
            while j < len(tex) and tex[j].isspace():
                j += 1
            if j < len(tex) and tex[j] == "{":
                depth = 0
                while j < len(tex):
                    if tex[j] == "{":
                        depth += 1
                    elif tex[j] == "}":
                        depth -= 1
                        if depth == 0:
                            j += 1
                            break
                    j += 1
            out.append("=")
            i = j
            continue
        out.append(tex[i])
        i += 1
    return "".join(out)


def _clean(tex):
    tex = re.sub(r"\\textcircled\s*\{\s*(\d)\s*\}",
                 lambda m: _CIRCLED.get(m.group(1), m.group(0)), tex)
    tex = _strip_xlongequal(tex)
    tex = _repair_arrays(tex)
    tex = _repair_delims(tex)
    return tex


def _balance_dollars(text):
    """奇数个 $ 时把最后一个转义掉，避免它把后面的正文吞进公式。"""
    if text.count("$") % 2:
        i = text.rfind("$")
        text = text[:i] + "\\$" + text[i + 1:]
    return text


def _wrap(text):
    out = html.escape(_balance_dollars(_clean(str(text or ""))))
    out = out.replace("\\_", "_")
    # 数学块内的换行压成空格，避免 KaTeX 把换行当公式内容
    out = re.sub(r"\$\$.+?\$\$|\$.+?\$",
                 lambda m: m.group(0).replace("\n", " "), out, flags=re.S)
    out = re.sub(r"\n{2,}", "</p><p>", out).replace("\n", "<br>")
    return f'<div class="mathbody"><p>{out}</p></div>'


def to_html(text, display=False):
    """保留 $...$ / $$...$$ 的 HTML；公式由前端 KaTeX 渲染。"""
    return _wrap(text)


def _inline(line):
    h = _wrap(line)
    return re.sub(r'^<div class="mathbody"><p>|</p></div>$', "", h)


def note_html(text):
    """速记的轻量 Markdown：只认 ## 标题、- 列表，其余按段落。"""
    out = []
    for raw in str(text or "").splitlines():
        s = raw.strip()
        if not s:
            continue
        if s.startswith("## "):
            out.append(f"<h4 class='t-body font-semibold' style='margin:6px 0 2px'>"
                       f"{html.escape(s[3:])}</h4>")
        elif s.startswith(("- ", "* ")):
            out.append(f"<div>• {_inline(s[2:])}</div>")
        else:
            out.append(f"<p>{_inline(s)}</p>")
    return '<div class="mathbody">' + "".join(out) + "</div>"
