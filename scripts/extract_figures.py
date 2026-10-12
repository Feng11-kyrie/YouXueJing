#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
抽取 408 真题的插图, 并映射到题目。

背景
----
120 道题标注了需插图(如「如题 38 图所示」), 但图不在结构化数据里,
用户看到题干却看不到图。实测插图是 PDF 里的**嵌入位图**(非矢量), 共 126 张。

四个必须处理的坑(全部实测得到)
------------------------------
1. **页面级变换**: 内容流开头有 `0.75 0 0 -0.75 0 841.92 cm`, 图片与文字坐标
   都在它之前, 必须先套用才能得到真实 PDF 坐标。
2. **`page.images` 的顺序不是视觉顺序**, 必须用内容流里的坐标。
3. **题注位置不固定**: 「题 N 图」可能在图的**上方**也可能在**下方**。
4. **两种题注风格**:
   - 显式 `题 N 图`  —— 直接给出题号(较新年份)
   - 模糊 `如下图 / 下图所示 / 如图所示` —— 需回落到"该页引入插图的题目"
   另有**一条图被切成多张横条**的情况(2018 第8页 11 张), 需纵向拼接。

用法:
  python extract_figures.py --probe 2025    # 只检查映射, 不落盘
  python extract_figures.py                 # 全部年份抽取
"""
import os
import re
import io
import json
import glob
import argparse

from pypdf import PdfReader
from PIL import Image

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(BASE, ".cache", "408")
OUT = os.path.join(BASE, "data", "408")
FIGDIR = os.path.join(BASE, "data", "figures")

MAT = re.compile(rb"([-\d.]+) ([-\d.]+) ([-\d.]+) ([-\d.]+) ([-\d.]+) ([-\d.]+) cm")
DO = re.compile(rb"/(\w+)\s+Do\b")
CAPTION = re.compile(r"题\s*(\d{1,2})\s*图")
try:
    from parse_408 import FIG_RE          # 与「需插图」判定共用同一套规则
except Exception:
    FIG_RE = re.compile(r"下\s*图|如\s*图|图\s*所示")
QSTART = re.compile(r"^\s*(\d{1,2})\s*[.．、]")


def mul(m1, m2):
    a1, b1, c1, d1, e1, f1 = m1
    a2, b2, c2, d2, e2, f2 = m2
    return (a1 * a2 + b1 * c2, a1 * b2 + b1 * d2,
            c1 * a2 + d1 * c2, c1 * b2 + d1 * d2,
            a1 * e2 + b1 * f2 + e1, c1 * e2 + d1 * f2 + f1)


def apply(m, x, y):
    a, b, c, d, e, f = m
    return (a * x + c * y + e, b * x + d * y + f)


def page_transform(raw):
    """
    取页面级变换(整体缩放+翻转)。

    必须确认它是**出现在任何 q/BT/Do 之前**的那个 cm: 部分年份(如 2024)没有页面级
    变换, 内容流第一个 cm 其实是某张图的放置矩阵 —— 误当成页面变换会让所有坐标跑飞。
    """
    m = MAT.search(raw)
    if not m:
        return (1, 0, 0, 1, 0, 0)
    if re.search(rb"\b(?:q|BT|Do)\b", raw[:m.start()]):
        return (1, 0, 0, 1, 0, 0)
    return tuple(float(x) for x in m.groups())


def content_bytes(pg):
    """
    取内容流原始字节。
    注意: 不可写 `if pg.get_contents() else ...` —— ContentStream 定义了 __len__
    (基于已解析的算子列表), 首次访问时为空 -> 布尔值 False, 会误判成"无内容流"。
    """
    c = pg.get_contents()
    return c.get_data() if c is not None else b""


def bbox_of(m):
    pts = [apply(m, x, y) for x in (0, 1) for y in (0, 1)]
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def collect_images(raw, ctm, xobjects, out, depth=0):
    """
    递归收集内容流里的位图。

    不能把所有 `/Name Do` 都当图片: 2024 年的插图包在 **Form XObject** 里
    (如 /Meta38 -> 内含 /Image39 Do), Form 也可能只是矢量绘制。
    故按 /Subtype 分流: /Image 记录, /Form 递归(复合其 /Matrix 与 /Resources)。
    """
    if depth > 4 or not xobjects:
        return
    for m in DO.finditer(raw):
        name = m.group(1).decode()
        o = None
        for k, v in xobjects.items():
            if k.lstrip("/") == name:
                o = v.get_object()
                break
        if o is None:
            continue
        cm = None
        for cmm in MAT.finditer(raw, 0, m.start()):
            cm = cmm
        place = tuple(float(x) for x in cm.groups()) if cm else (1, 0, 0, 1, 0, 0)
        full = mul(ctm, place)
        sub = o.get("/Subtype")
        if sub == "/Image":
            out.append({"name": name, "obj": o, "box": bbox_of(full)})
        elif sub == "/Form":
            inner = full
            mtx = o.get("/Matrix")
            if mtx is not None:
                inner = mul(full, tuple(float(x) for x in mtx))
            sub_res = o.get("/Resources") or {}
            try:
                sub_raw = o.get_data()
            except Exception:
                continue
            collect_images(sub_raw, inner, sub_res.get("/XObject") or {}, out, depth + 1)


def group_figures(boxes):
    """把纵向相邻且水平位置一致的图块拼成同一张图(处理'一图被切成横条')。"""
    if not boxes:
        return []
    bs = sorted(boxes, key=lambda b: -b["box"][3])   # 按上边缘从上到下
    groups = [[bs[0]]]
    for b in bs[1:]:
        x0, y0, x1, y1 = b["box"]
        px0, py0, px1, py1 = groups[-1][-1]["box"]
        same_x = abs(x0 - px0) < 6 and abs(x1 - px1) < 6
        adjacent = abs(y1 - py0) < 6 or (y1 <= py0 and py0 - y1 < 6)
        (groups[-1].append(b) if (same_x and adjacent) else groups.append([b]))
    return groups


def page_text_info(pg, pgt):
    """
    返回 (题注列表[(题号,y)], 题目起始[(题号,y)])。

    必须**先按 y 把文字片段聚合成行再匹配**: 部分年份(如 2024)的「题 7 图」会被
    PDF 拆成多个片段, 逐片段匹配一个都找不到。
    """
    frags = []
    def visit(text, cm, tm, font, size):
        if not text.strip():
            return
        x, y = apply(mul(cm, tm), 0, 0)
        frags.append((round(y, 1), x, text))
    pg.extract_text(visitor_text=visit)

    lines = {}
    for y, x, t in frags:
        lines.setdefault(round(y / 3.0), []).append((x, t))    # 3pt 容差归为同一行

    caps, qstarts = [], []
    for key, items in lines.items():
        items.sort()
        line = "".join(t for _x, t in items)
        y = key * 3.0
        for c in CAPTION.finditer(line):
            caps.append((int(c.group(1)), round(y, 1)))
        m2 = QSTART.match(line.strip())
        if m2:
            n = int(m2.group(1))
            if 1 <= n <= 47:
                qstarts.append((n, round(y, 1)))
    return caps, qstarts


def map_page(groups, caps, qstarts, qs, stats, y, pi, verbose):
    """
    给一页里的每个图组确定题号。三级策略(可靠度递减):

      1. 显式题注「题 N 图」 —— 最近者(题注可在图上方或下方)
      2. 该页题干含插图引用的题(用与「需插图」判定共用的 FIG_RE),
         取图片上方最近的一道
      3. 该页被标记为需插图的题, 同样取图片上方最近的一道
         (处理早期年份既无题注、题干也只说「如下图」这类情况)
    """
    out, used, unresolved = [], set(), []
    for g in groups:
        y0 = min(b["box"][1] for b in g)
        y1 = max(b["box"][3] for b in g)

        # --- 1) 显式题注
        cand = []
        for n, cy in caps:
            if (n, cy) in used:
                continue
            d = (y0 - cy) if cy <= y0 else ((cy - y1) if cy >= y1 else 0)
            if d <= 150:
                cand.append((d, n))
        if cand:
            cand.sort()
            n = cand[0][1]
            for c in caps:
                if c[0] == n and c not in used:
                    used.add(c)
                    break
            out.append((n, g, "题注"))
            continue

        # --- 2)/3) 回落到"该页的题": 题干有插图引用者优先, 其次需插图者
        above = [(qy, n) for n, qy in qstarts if n in qs and qy >= y0 - 10]
        above.sort()                       # y 小的优先 = 离图最近的上方题
        pick = None
        tier = None
        for _qy, n in above:
            if n in {nn for nn, _g, _t in out}:
                continue
            if FIG_RE.search(qs[n].get("题干") or ""):
                pick, tier = n, "题干引用"
                break
        if pick is None:
            for _qy, n in above:
                if n in {nn for nn, _g, _t in out}:
                    continue
                if qs[n].get("需插图"):
                    pick, tier = n, "需插图标记"
                    break
        # 刻意不做"盲配最近的一道题": 实测那会把图配给题干毫无插图引用的题
        # (如 2010-09 折半查找配到有向图、2022-06 无向图配到 AOE 网)。
        # 无题注又无引用时宁可留成显式缺口, 交由人工判断。
        if pick is not None:
            out.append((pick, g, tier))
            continue

        unresolved.append(g)
        stats["无题注"] += 1
        if verbose:
            print(f"  ! {y} 第{pi}页 {[b['name'] for b in g]}: 无法定题 "
                  f"(图 y {y0:.0f}-{y1:.0f}, 题注{caps}, 该页题号{[n for n,_ in qstarts]})")
    return out, unresolved


def _load(entry):
    """
    从 XObject 取位图。

    两类编码都要支持:
      - JPEG/PNG 等: 直接交给 PIL
      - **/FlateDecode 原始像素**(2023/2024 部分插图): PIL 认不出, 需按
        /ColorSpace 与 /Width /Height /BitsPerComponent 自行重建
    """
    o = entry["obj"]
    data = o.get_data()
    try:
        img = Image.open(io.BytesIO(data))
        return img.convert("RGB") if img.mode not in ("RGB", "L") else img
    except Exception:
        pass
    w, h = int(o["/Width"]), int(o["/Height"])
    bpc = int(o.get("/BitsPerComponent", 8))
    cs = str(o.get("/ColorSpace", "/DeviceRGB"))
    mode = "RGB" if "RGB" in cs else ("L" if "Gray" in cs else "RGB")
    n = 3 if mode == "RGB" else 1
    need = w * h * n * (bpc // 8)
    if bpc == 8 and len(data) >= need:
        return Image.frombytes(mode, (w, h), data[:need])
    raise ValueError(f"无法重建位图: {cs} {bpc}bpc {w}x{h}")


def _save(group, path):
    """把一个图组落盘; 多块时纵向拼接(处理'一图被切成横条')。"""
    if len(group) == 1:
        _load(group[0]).save(path)
        return
    parts = sorted(group, key=lambda b: -b["box"][3])   # 上 -> 下
    ims = [_load(b) for b in parts]
    w = max(i.width for i in ims)
    h = sum(i.height for i in ims)
    canvas = Image.new("RGB", (w, h), "white")
    oy = 0
    for i in ims:
        canvas.paste(i, (0, oy))
        oy += i.height
    canvas.save(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", help="只检查该年份, 不落盘")
    args = ap.parse_args()

    years = [args.probe] if args.probe else \
        [os.path.basename(p)[:4] for p in sorted(glob.glob(os.path.join(CACHE, "20[0-9][0-9].pdf")))]
    mapping, stats = {}, {"图组": 0, "已映射": 0, "无题注": 0}
    if not args.probe:
        os.makedirs(FIGDIR, exist_ok=True)

    for y in years:
        r = PdfReader(os.path.join(CACHE, f"{y}.pdf"))
        if r.is_encrypted:
            r.decrypt("")
        qs = {q["题号"]: q for q in json.load(open(os.path.join(OUT, f"{y}.json"),
                                                  encoding="utf-8"))["题目"]}
        for pi, pg in enumerate(r.pages, 1):
            raw = content_bytes(pg)
            xobjs = (pg["/Resources"].get("/XObject") or {}) if pg.get("/Resources") else {}
            boxes = []
            collect_images(raw, page_transform(raw), xobjs, boxes)
            if not boxes:
                continue
            groups = group_figures(boxes)
            stats["图组"] += len(groups)
            caps, qstarts = page_text_info(pg, page_transform(raw))
            pairs, _un = map_page(groups, caps, qstarts, qs, stats, y, pi, bool(args.probe))
            for n, g, tier in pairs:
                key = f"408-{y}-{n:02d}"
                if key in mapping:
                    continue
                names = [b["name"] for b in g]
                mapping[key] = {"page": pi, "parts": names, "依据": tier,
                                "y": [round(min(b["box"][1] for b in g)), round(max(b["box"][3] for b in g))]}
                stats["已映射"] += 1
                if args.probe:
                    q = qs[n]
                    print(f"  {key}  {q['学科'][:4]}  第{pi}页  {len(names)}块  "
                          f"题注={'有' if any(c[0]==n for c in caps) else '模糊回落'}")
                else:
                    _save(g, os.path.join(FIGDIR, f"{key}.png"))

    if args.probe:
        print(f"\n统计: {stats}")
        return
    json.dump({"说明": "题目 -> 插图文件映射。文件在 data/figures/{题目id}.png",
               "映射": mapping},
              open(os.path.join(OUT, "figure_map.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"图组 {stats['图组']} 个, 成功映射 {stats['已映射']} 题, 无法定题 {stats['无题注']}")


if __name__ == "__main__":
    main()
