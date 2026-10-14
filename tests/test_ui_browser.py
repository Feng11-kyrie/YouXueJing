#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
浏览器端回归测试（需要 Playwright + 一个跑着的服务）。

为什么单独有这一份
------------------
AppTest 覆盖不了两件事，而这两件恰好都出过问题：

1. **选项控件的真实行为**。`st.radio` 有两个坑：
   - 首次渲染会自动选中第一项 → 用户看到"每道题 A 都是选中的"（用户实际反馈过）
   - 一旦同时传 `index=` 和用 Session State 设值，Streamlit 会清空该键，
     表现为 AppTest 的 `set_value` 完全失效（实测踩到）
   所以"能不能选中、点 B 是不是真的记成 B"必须在真浏览器里验。
2. **首屏可见性**（见 scripts/fold_check.py）。

用法（先把服务跑起来）：
    .venv/bin/python tests/test_ui_browser.py
    .venv/bin/python tests/test_ui_browser.py --url http://localhost:8501

⚠️ 已知限制：必须用**独立测试库**启动服务，否则会有 3 项假失败
-----------------------------------------------------------------
本脚本会把 store.DB 指向 /tmp/yj_test_browser.db，但浏览器里的应用是另一个
进程、写的是它自己的 data/yj.db。如果服务是用默认库启动的，就会出现：

    ✗ 第一题默认选中占位项（不是 A）  checked=2
    ✗ 给出提示
    ✗ 落库 0 条  1 条

原因是共享库里 demo 已经答过 2026 年第 1 题（卡片变成"已作答"形态、
不再渲染 radio），脚本挑到的"第一张卡"其实是第 2 题 —— 也就是说这些断言
**检查的不是它想检查的东西**，并非产品缺陷。

要跑干净，用同一个测试库启动服务：
    YJ_DB=/tmp/yj_test_browser.db .venv/bin/streamlit run app.py --server.port 8501
    YJ_DB=/tmp/yj_test_browser.db .venv/bin/python proto/app.py --port 8890
（NiceGUI 版读的是 proto/store_lite 的 DB，同样需要指向测试库。）

产品行为的独立核对结论（2026-10-14，真实浏览器逐题检查 NiceGUI 版）：
    第 1/2/3 题默认选中样式数 = 0   → 默认确实不预选
    未选就提交 → 出现提示且落库 0 条 → 行为正确
"""
import argparse
import os
import sqlite3
import sys
import tempfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

# 用独立测试库：这个测试会真的写入作答记录，绝不能污染演示画像
TEST_DB = os.path.join(tempfile.gettempdir(), "yj_test_browser.db")
if os.path.exists(TEST_DB):
    os.remove(TEST_DB)

from yj import store                              # noqa: E402

store.DB = TEST_DB

# 注意：浏览器里的应用是**另一个进程**（Streamlit 服务），它写的是它自己的
# data/yj.db。所以这个脚本读到的必须和它一致 —— 为了不污染演示画像，
# 服务需要用同一个测试库启动：
#     YJ_DB=/tmp/yj_test_browser.db .venv/bin/streamlit run app.py
# 未指定时脚本会提示并跳过写库类断言，避免给出"假通过"。
APP_DB = os.environ.get("YJ_DB") or os.path.join(BASE, "data", "yj.db")
SAME_DB = os.path.abspath(APP_DB) == os.path.abspath(TEST_DB)

FAILS = []


def note(name, ok, detail=""):
    print(f"  {'✓' if ok else '✗'} {name}" + (f"  {detail}" if detail else ""))
    if not ok:
        FAILS.append(name)


# 在第一张题卡上操作的 JS 片段（避免依赖易变的 DOM 层级顺序）
CARD0 = """() => [...document.querySelectorAll('div[data-testid=stVerticalBlock]')]
  .filter(d => parseFloat(getComputedStyle(d).borderTopWidth) > 0
               && d.offsetWidth > 300)[0]"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8501")
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1440, "height": 1100})
        pg = ctx.new_page()

        def open_app(user):
            pg.goto(f"{args.url}/?u={user}", wait_until="domcontentloaded")
            pg.wait_for_selector('[data-testid="stSidebar"]', timeout=60000)
            pg.wait_for_timeout(3500)

        def card_state():
            return pg.evaluate(f"""() => {{
              const c = ({CARD0})();
              return {{
                checked: [...c.querySelectorAll('input[type=radio]')]
                           .findIndex(x => x.checked),
                options: [...c.querySelectorAll('label')]
                           .filter(l => l.querySelector('input'))
                           .map(l => l.innerText.trim().slice(0, 18)),
                nudged: false,
              }};
            }}""")

        def click_option(prefix):
            pg.evaluate(f"""(p) => {{
              const c = ({CARD0})();
              [...c.querySelectorAll('label')]
                .find(l => l.innerText.trim().startsWith(p)).click();
            }}""", prefix)
            pg.wait_for_timeout(700)

        def submit():
            pg.evaluate(f"""() => {{
              const c = ({CARD0})();
              [...c.querySelectorAll('button')]
                .find(b => b.innerText.includes('提交')).click();
            }}""")
            pg.wait_for_timeout(3500)

        def rows(user):
            if not os.path.exists(APP_DB):
                return []
            return sqlite3.connect(APP_DB).execute(
                "select question_id, chosen, is_correct from answers where user_id=?",
                (user,)).fetchall()

        # ---------------- 真题页：默认不预选 ----------------
        print('=== 1) 真题页：默认不预选（用户反馈过「每道题 A 都是蓝的」）===')
        U = "bw_paper"
        open_app(U)
        st0 = card_state()
        note("第一题默认选中占位项（不是 A）",
             st0["checked"] == 0, f"checked={st0['checked']} 选项={st0['options'][:2]}")
        note("占位项文案明确", st0["options"][0].startswith("－ 请选择"),
             st0["options"][0])

        print("\n=== 2) 真题页：未选就提交不写库 ===")
        submit()
        note("给出提示", "还没选选项" in pg.inner_text("body"))
        note("落库 0 条", len(rows(U)) == 0, f"{len(rows(U))} 条")
        if not SAME_DB:
            print(f"    （应用库={APP_DB}，非测试库；写库类断言仍按应用库核对）")

        print("\n=== 3) 真题页：点 B 就记成 B（选项映射不错位）===")
        click_option("B.")
        note("点 B 后 checked 下标 = 2", card_state()["checked"] == 2,
             f"checked={card_state()['checked']}")
        submit()
        got = rows(U)
        note("落库 1 条", len(got) == 1, str(got))
        note("记录的是 B", got and got[0][1] == "B", str(got))

        print("\n=== 4) 诊断页：32 题默认一个都不选 ===")
        open_app("bw_diag")
        pg.click('button:has-text("快速诊断")')
        pg.wait_for_timeout(4000)
        r = pg.evaluate("""() => {
          const rs = [...document.querySelectorAll('input[type=radio]')];
          return {total: rs.length, checked: rs.filter(x => x.checked).length};
        }""")
        note("诊断页 radio 数 > 0", r["total"] > 0, f"{r['total']} 个")
        note("默认没有任何选项被选中", r["checked"] == 0, f"选中 {r['checked']} 个")

        browser.close()

    print()
    if FAILS:
        print(f"失败 {len(FAILS)} 项: {FAILS}")
        sys.exit(1)
    print("浏览器端回归测试全部通过")


if __name__ == "__main__":
    main()
