#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用 PaddleOCR 从**纯扫描**的答案册里提取综合题（41–47）参考答案。

背景
----
13 个年份的答案册有文字层，已由 scripts/extract_solutions.py 提取（89 道）。
但 2019/2021/2024/2025/2026 五年是纯扫描图片，文字层只有 6–17 个字符，
需 OCR。macOS 内置 Vision 框架试过，**中文识别为 0**（把「【解析】」认成
"[**¥,4]"），数字能认。所以改用 PaddleOCR。

定位策略（关键）
----------------
OCR 结果里「解析」两字常被认错，**不能靠它定位**。改用题号数字定位：
    44. / 44． / 44、   —— 数字是 OCR 最可靠的部分（Vision 也能认对）
再加两条约束，减少误切：
    · 只在「综合应用题」之后找（该标题也做模糊匹配，容忍错字）
    · 题号必须按 41→47 递增出现，跳号则丢弃该段

校准
----
对已有文字层的年份（如 2022）也跑一遍 OCR，与抽取结果比较，
用于判断 OCR 质量是否可用 —— 先校准、再上目标年份。

用法：
    .venv/bin/python scripts/ocr_solutions.py --calibrate 2022   # 先校准
    .venv/bin/python scripts/ocr_solutions.py --years 2026 2025  # 再跑目标年
    .venv/bin/python scripts/ocr_solutions.py --years 2019 2021 2024 2025 2026 --write

实测校准结论（不要随意改参数）：
    dpi=300 是分水岭（150dpi 检测器整页返回 0 行）
    模型 PP-OCRv6 对这批卷面**跨次运行不稳定**，同一页可能 0 行或 70 行；
    但目标年份（2024/2025/2026）实测能稳定切出 7 道【答案要点】
"""
import argparse
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(BASE, ".cache", "408")
OUT = os.path.join(BASE, "data", "solutions")

# 题号 + 标记。标记可能是「解析」/「解答」/「答案要点」——
# 2026 年答案册用的是「41.【答案要点】」（实测 OCR 结果），
# 早期年份用「41. 解答：」。所以标记部分做成可选，主要靠题号数字定位
# （数字是 OCR 最可靠的部分）。允许 OCR 常见的标点误认（. ． 。 、 ,）
NUM = re.compile(r'(?<!\d)(4[1-7])\s*[.．。、,，:：]\s*'
                 r'(?:【\s*(?:解\s*析|解\s*答|答\s*案\s*要\s*点|答\s*案)\s*】'
                 r'|解\s*析|解\s*答)?')
# 「综合应用题」的模糊匹配：允许中间任意字符缺失/误认
SECTION_FUZZ = re.compile(r'综.{0,2}合.{0,2}应.{0,2}用.{0,2}题')


def ocr_pdf(pdf_path, dpi=200):
    """逐页 OCR，返回 [(页号, 文本)]。"""
    from paddleocr import PaddleOCR
    import Quartz
    from Foundation import NSURL

    doc = Quartz.CGPDFDocumentCreateWithURL(NSURL.fileURLWithPath_(pdf_path))
    n = Quartz.CGPDFDocumentGetNumberOfPages(doc)
    # PaddleOCR 3.x 的 API：不再有 use_angle_cls / show_log / cls=，
    # 改为构造时传 use_* 开关，预测时用 predict()。首次运行会下载模型。
    # 关掉文档方向分类与去弯曲：卷面是正的，省时间也少一个出错点。
    # 参数是实测校准出来的，不要随意改：
    #   · dpi=300 是分水岭 —— 150dpi 时检测器整页返回 0 行，300dpi 出 71–78 行
    #   · text_det_thresh 0.3→0.2、box_thresh 0.6→0.4：卷面字密，默认阈值漏检
    #   · limit_side_len=8000：默认 4000 会把大页缩小（曾把 8850px 的页缩掉）
    ocr = PaddleOCR(lang="ch",
                    use_doc_orientation_classify=False,
                    use_doc_unwarping=False,
                    use_textline_orientation=False,
                    text_det_thresh=0.2,
                    text_det_box_thresh=0.4,
                    text_det_limit_side_len=8000,
                    text_det_limit_type="max")

    def render(page_no):
        page = Quartz.CGPDFDocumentGetPage(doc, page_no)
        rect = Quartz.CGPDFPageGetBoxRect(page, Quartz.kCGPDFMediaBox)
        s = dpi / 72.0
        w, h = int(rect.size.width * s), int(rect.size.height * s)
        ctx = Quartz.CGBitmapContextCreate(
            None, w, h, 8, 0, Quartz.CGColorSpaceCreateDeviceRGB(),
            Quartz.kCGImageAlphaPremultipliedLast)
        Quartz.CGContextSetRGBFillColor(ctx, 1, 1, 1, 1)
        Quartz.CGContextFillRect(ctx, Quartz.CGRectMake(0, 0, w, h))
        Quartz.CGContextScaleCTM(ctx, s, s)
        Quartz.CGContextDrawPDFPage(ctx, page)
        img = Quartz.CGBitmapContextCreateImage(ctx)
        # 存临时 PNG 交给 PaddleOCR（它吃路径或 ndarray）
        import tempfile
        from PIL import Image
        prov = Quartz.CGImageGetDataProvider(img)
        data = Quartz.CGDataProviderCopyData(prov)
        buf = bytes(data)
        im = Image.frombuffer("RGBA", (w, h), buf, "raw", "RGBA", 0, 1).convert("RGB")
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        im.save(tmp.name)
        return tmp.name

    out = []
    for p in range(1, n + 1):
        path = render(p)
        try:
            res = ocr.predict(path)
        except Exception as e:                      # noqa: BLE001
            print(f"    第 {p} 页 OCR 失败: {type(e).__name__}: {e}")
            res = None
        finally:
            os.unlink(path)
        # 3.x 的 predict 返回列表，每项是 dict，文本在 'rec_texts' 里
        lines = []
        for page_res in (res or []):
            try:
                lines.extend(page_res.get("rec_texts") or [])
            except AttributeError:
                continue
        out.append((p, "\n".join(lines)))
        print(f"    第 {p}/{n} 页: {len(lines)} 行")
    return out


# OCR 会把页眉页脚混进正文，实测抓到：
#   "86/2027年全国硕士研究生招生考试计算机学科专业基础考试大纲"
# 这类文本夹在句子中间会破坏可读性，统一删掉。
HEADER_NOISE = re.compile(
    r'\d{0,3}\s*/?\s*20\d{2}\s*年全国硕士研究生招生考试.{0,24}大纲')


def clean_ocr(text):
    text = HEADER_NOISE.sub(' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def split_solutions(pages):
    """从 OCR 文本里切出 41–47 的解答。按题号递增定位。"""
    full = "\n".join(t for _p, t in pages)
    m = SECTION_FUZZ.search(full)
    scope = full[m.end():] if m else full
    hits = list(NUM.finditer(scope))
    kept, last = [], 40
    for h in hits:
        num = int(h.group(1))
        if num <= last:                      # 必须递增，否则视为噪声
            continue
        last = num
        kept.append((num, h.start(), h.end()))
    out = {}
    for i, (num, _s, e) in enumerate(kept):
        end = kept[i + 1][1] if i + 1 < len(kept) else len(scope)
        body = re.sub(r'\s+', ' ', scope[e:end]).strip()
        if len(body) > 60:
            out[str(num)] = body
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", nargs="*", default=[])
    ap.add_argument("--calibrate", default=None,
                    help="对有文字层的年份跑 OCR，与已知答案对比质量")
    ap.add_argument("--dpi", type=int, default=300,
                    help="实测 300 是分水岭：150 全为 0 行，300 正常")
    ap.add_argument("--write", action="store_true", help="写入 data/solutions/")
    args = ap.parse_args()

    targets = [args.calibrate] if args.calibrate else args.years
    if not targets:
        print("请指定 --years 或 --calibrate", file=sys.stderr)
        sys.exit(1)

    for y in targets:
        pdf = os.path.join(CACHE, f"{y}-answer.pdf")
        if not os.path.exists(pdf):
            print(f"{y}: 找不到 {pdf}")
            continue
        print(f"=== {y} 年答案册 OCR（dpi={args.dpi}）===")
        pages = ocr_pdf(pdf, dpi=args.dpi)
        sols = split_solutions(pages)
        print(f"  → 切出 {len(sols)} 道：{sorted(sols, key=int)}")
        if args.calibrate:
            # 与已抽取的文字层版本对比
            ref_path = os.path.join(OUT, f"{y}.json")
            if os.path.exists(ref_path):
                ref = json.load(open(ref_path, encoding="utf-8"))["解答"]
                print(f"  已知（文字层）有 {len(ref)} 道：{sorted(ref, key=int)}")
                for k in sorted(set(ref) & set(sols), key=int):
                    a, b = ref[k], sols[k]
                    common = set(a) & set(b)
                    cov = len(common) / max(len(set(a)), 1)
                    print(f"    第 {k} 题：已知 {len(a)} 字 / OCR {len(b)} 字，"
                          f"字符重合率 {cov:.0%}")
        if args.write and sols:
            dst = os.path.join(OUT, f"{y}.json")
            # 【合并而不是覆盖】OCR 模型对这批卷面跨次运行不稳定（同一页可能
            # 0 行或 70 行），单次结果可能缺题。重跑时应当**补齐缺的题号**，
            # 而不是把已有（可能更完整、或来自文字层更准）的结果覆盖掉。
            # 踩过的坑：OCR 把年份文件整体覆盖，2024 少切出一道就永久丢了。
            prev = {}
            if os.path.exists(dst):
                try:
                    prev = json.load(open(dst, encoding="utf-8")).get("解答", {})
                except Exception:                   # noqa: BLE001
                    prev = {}
            added = [k for k in sols if k not in prev]
            merged = {**prev, **{k: sols[k] for k in added}}
            json.dump({"年份": y, "来源": "答案册 PDF（OCR：PaddleOCR / 文字层）",
                       "题数": len(merged), "解答": merged},
                      open(dst, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            print(f"  已写入 {dst}（新增 {sorted(added, key=int)}，"
                  f"原有 {sorted(prev, key=int)} → 合计 {len(merged)} 道）")


if __name__ == "__main__":
    main()
