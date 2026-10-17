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


def _mathml(tex, display=False):
    # latex2mathml 不认 \textcircled{1}，先换成 ①（数学一 2024 第 7 题会用到）
    tex = re.sub(r"\\textcircled\s*\{\s*(\d)\s*\}",
                 lambda m: _CIRCLED.get(m.group(1), m.group(0)), tex)
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
