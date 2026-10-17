#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
清理英语解析文件里的**过期/错位键**。

为什么需要：解析文件与试题文件**分开存放**（这是为了重导试题不冲掉答案），
代价是 —— 试题的题号一旦变过，解析文件里会留下**旧题号的残留**。

实测踩到的具体事故：
  英语二早期版本把写作题号误识别成 46/47/48（翻译 46 也被标成写作），
  那时存的 `参考范文` 落在了键 `46` 上。后来题号修正为 47/48，
  但解析文件里 `解答["46"]` 仍是那份**写作范文** ——
  于是第 46 题（翻译）读到的"参考译文"其实是作文范文。

清理规则（对着当前试题文件校准）：
  · 键不在当前题号里 → 删（孤儿键）
  · `参考范文` 只应出现在 WRITE 题上
  · `_参考译文` 只应在存在 TRANS 题的卷里
  · `答案`/`解析` 只在客观题上

用法：
    .venv/bin/python scripts/clean_english_expl.py --dry
    .venv/bin/python scripts/clean_english_expl.py --write
"""
import argparse
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from yj import english as en                                    # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    total_removed = 0
    for tier in ("EN1", "EN2"):
        for year in en.years(tier):
            rec = en.paper(tier, year) or {}
            qmap = {}          # 题号(str) → 部分代码
            for ps in rec.get("篇目", []):
                for q in ps.get("小题") or []:
                    qmap[str(q["题号"])] = ps.get("部分")
            p = en.expl_path_of(tier, year)
            if not os.path.exists(p):
                continue
            try:
                d = json.load(open(p, encoding="utf-8"))
            except Exception:                               # noqa: BLE001
                continue
            ans = d.get("解答") or {}
            removed = []
            for k in list(ans.keys()):
                if k == "_参考译文":
                    if "TRANS" not in qmap.values():
                        removed.append(k)
                    continue
                if k not in qmap:
                    removed.append(k)                       # 孤儿键
                    continue
                part = qmap[k]
                v = ans[k]
                if isinstance(v, dict) and v.get("参考范文") and part != "WRITE":
                    removed.append(k)                       # 范文落错题
                if isinstance(v, dict) and v.get("答案") and part in ("TRANS", "WRITE"):
                    removed.append(k)                       # 客观答案落在主观题上
            if removed:
                total_removed += len(removed)
                print(f"  {en.TIERS[tier]['简称']} {year}: 清理 {len(removed)} 个 "
                      f"→ {removed[:6]}")
                if args.write:
                    for k in removed:
                        ans.pop(k, None)
                    d["解答"] = ans
                    tmp = p + ".tmp"
                    with open(tmp, "w", encoding="utf-8") as f:
                        json.dump(d, f, ensure_ascii=False, indent=1)
                    os.replace(tmp, p)
    print(f"\n共清理 {total_removed} 个过期键" + ("（已写盘）" if args.write else "（试运行）"))


if __name__ == "__main__":
    main()
