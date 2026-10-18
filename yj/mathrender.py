#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数学题干/解析的渲染：把 Markdown 里的 LaTeX 公式转成 **MathML**。

为什么用 MathML 而不是 KaTeX
---------------------------
NiceGUI 的 markdown 不渲染 LaTeX；引 KaTeX 要额外加载 JS/CSS 并在每次内容
更新后手动 re-render。MathML 是浏览器原生支持的（Chrome 109+ / Safari），
服务端用 latex2mathml 转好直接塞进 HTML 即可 —— 无 JS、无 CDN、离线可用。

代价：排版不如 KaTeX 精致；latex2mathml 对极少数宏不支持，遇到就退回原样文本
（不能让一个公式把整道题渲染挂掉）。
"""
import html
import re

import latex2mathml.converter as _l2m

# 行内 $...$ 与行间 $$...$$
_MATH = re.compile(r"\$\$(.+?)\$\$|\$(.+?)\$", re.S)


_CIRCLED = {str(i): chr(0x2460 + i - 1) for i in range(1, 10)}


def _repair_arrays(tex):
    """
    修 OCR 丢掉的 \\end{array}：源数据里出现过
    `\\left| \\begin{array}{ccc} ... \\right|`（没有 end），
    latex2mathml 会直接报错、整块退回原始 LaTeX。

    做法：每个 \\begin{array} 找它后面最近的 \\end{array} 与 \\right；
    如果 \\right 先到，就在 \\right 前补一个 \\end{array}。
    只补"确实缺 end"的数组，不动合法的嵌套。
    """
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
    """补齐 OCR 丢掉的 \\right)：只处理"\\left 多于 \\right"的情况。"""
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
            if tex.startswith("\\}", j):
                j += 2
            else:
                j += 1
            if stack:
                stack.pop()
            i = j
            continue
        i += 1
    for d in reversed(stack):
        tex += "\\right" + pairs.get(d, ")")
    return tex


def _split_top(s):
    """按顶层 \\\\ 切分 aligned 行；array/matrix 内部的 \\\\ 不算。"""
    out, buf, depth, i = [], [], 0, 0
    while i < len(s):
        if s.startswith("\\begin{", i):
            depth += 1
        elif s.startswith("\\end{", i):
            depth = max(0, depth - 1)
        if depth == 0 and s.startswith("\\\\", i):
            out.append("".join(buf))
            buf = []
            i += 2
            continue
        buf.append(s[i])
        i += 1
    out.append("".join(buf))
    return out


def _aligned_lines(tex):
    """把 aligned 拆成逐行公式 —— latex2mathml 对 & 对齐支持不好。"""
    tex = _repair_arrays(tex)
    m = re.search(r"\\begin\{aligned\}(.*?)\\end\{aligned\}", tex, re.S)
    if not m:
        return None
    body = re.sub(r"\\xlongequal\s*\{[^{}]*\}", "=", m.group(1))
    lines = []
    for line in _split_top(body):
        line = _repair_delims(line.replace("&", "").strip())
        if line:
            lines.append(line)
    return lines or None


def _mathml(tex, display=False):
    # latex2mathml 不认 \textcircled{1}，先换成 ①（数学一 2024 第 7 题会用到）
    tex = re.sub(r"\\textcircled\s*\{\s*(\d)\s*\}",
                 lambda m: _CIRCLED.get(m.group(1), m.group(0)), tex)
    lines = _aligned_lines(tex)
    if lines:
        return "<br>".join(_mathml_single(l, display=True) for l in lines)
    return _mathml_single(tex, display)


def _mathml_single(tex, display=False):
    # \xlongequal{...} 是"恒等变形"标注，MathML 不认识；降级成 =
    tex = re.sub(r"\\xlongequal\s*\{[^{}]*\}", "=", tex)
    try:
        out = _l2m.convert(tex.strip())
    except Exception:                                       # noqa: BLE001
        return "<code>" + html.escape("$" + tex.strip() + "$") + "</code>"
    if display and "<math" in out:
        out = out.replace('<math xmlns="http://www.w3.org/1998/Math/MathML"',
                          '<math display="block" xmlns="http://www.w3.org/1998/Math/MathML"')
    return out


def to_html(text, display=False):
    """
    把一段含 LaTeX 的文本转成可放进 ui.html 的 HTML。

    安全：先做 html.escape，再把公式占位替换成 MathML —— 公式以外的内容
    不会被当成标签执行。
    """
    text = str(text or "")
    if not text:
        return ""
    parts = []
    pos = 0
    for m in _MATH.finditer(text):
        parts.append(html.escape(text[pos:m.start()]))
        if m.group(1) is not None:
            parts.append(_mathml(m.group(1), display=True))
        else:
            parts.append(_mathml(m.group(2), display=display))
        pos = m.end()
    parts.append(html.escape(text[pos:]))
    out = "".join(parts)

    # 公式外的 Markdown 转义（\_ 表示下划线）与换行
    out = out.replace("\\_", "_").replace("\\\\", "\\")
    out = out.replace("\r\n", "\n")
    out = re.sub(r"\n{2,}", "</p><p>", out)
    out = out.replace("\n", "<br>")
    return f'<div class="mathbody"><p>{out}</p></div>'


def _inline(line):
    h = to_html(line)
    return re.sub(r'^<div class="mathbody"><p>|</p></div>$', "", h)


def note_html(text):
    """速记的轻量 Markdown：只认 ## 标题、- 列表，其余按段落 + 公式渲染。"""
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
