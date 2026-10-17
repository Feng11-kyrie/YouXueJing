#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NiceGUI 原型用的极简存储层（**只读写 answers 表**）。

为什么不直接 import yj.store：
yj/store.py 用一个模块级全局 DB 路径，而 streamlit 服务进程正持有同一个
sqlite 文件。两个框架进程同时写同一个库，需要打开 WAL 模式才安全
（否则容易 database is locked）。这里独立实现一小段，行为与 yj.store
保持一致 —— 包括那条底线：**chosen 为空直接丢弃**。

另：answers 表结构与 yj/store.py 的 SCHEMA 完全相同，两边数据互通。
"""
import datetime
import os
import sqlite3

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.environ.get("YJ_DB") or os.path.join(BASE, "data", "yj.db")


def conn():
    c = sqlite3.connect(DB, timeout=10)
    c.row_factory = sqlite3.Row
    # WAL：让 streamlit 与 nicegui 两个进程能安全地同时读写同一个库
    c.execute("PRAGMA journal_mode=WAL")
    return c


def ensure_user(user_id):
    with conn() as c:
        c.execute("INSERT OR IGNORE INTO users(user_id, created_at) VALUES(?,?)",
                  (user_id, datetime.datetime.now().isoformat(timespec="seconds")))


def get_answers(user_id, source=None):
    sql = "SELECT * FROM answers WHERE user_id=?"
    args = [user_id]
    if source:
        sql += " AND source=?"
        args.append(source)
    with conn() as c:
        rows = c.execute(sql, args).fetchall()
    # 带上 answered_at：首页要用它画"近 14 天练习记录"（复习节奏）
    return {r["question_id"]: {"chosen": r["chosen"],
                               "is_correct": bool(r["is_correct"]),
                               "source": r["source"],
                               "answered_at": r["answered_at"]} for r in rows}


def record_answer(user_id, question_id, chosen, is_correct,
                   source="practice", at=None):
    """
    at: 可选，指定作答时间（ISO 字符串或 datetime）。
    默认取当前时间。**播种演示数据时必须能指定**：
    否则 32 条作答的时间戳会完全相同（实测踩到），
    首页的学习记录图只有一根柱、"今天 N 题"也是假象。
    """
    """与 yj.store 同一条底线：没选答案就不写库。"""
    if chosen is None or str(chosen).strip() == "":
        return False
    ensure_user(user_id)
    with conn() as c:
        c.execute("""INSERT INTO answers(user_id, question_id, chosen, is_correct,
                                         source, answered_at)
                     VALUES(?,?,?,?,?,?)
                     ON CONFLICT(user_id, question_id) DO UPDATE SET
                       chosen=excluded.chosen, is_correct=excluded.is_correct,
                       source=excluded.source, answered_at=excluded.answered_at""",
                  (user_id, question_id, chosen, 1 if is_correct else 0, source,
                   (at.isoformat(timespec="seconds") if hasattr(at, "isoformat")
                    else at) or datetime.datetime.now().isoformat(timespec="seconds")))
    return True


# ---------------------------------------------------------------- 自报薄弱点
# 与 yj/store.py 的 marks 表结构一致，数据互通
def get_marks(user_id):
    """用户自己勾选的薄弱考点（不依赖做题，是画像的第二个数据来源）"""
    with conn() as c:
        rows = c.execute("SELECT node_id FROM marks WHERE user_id=?",
                         (user_id,)).fetchall()
    return {r["node_id"] for r in rows}


def set_marks(user_id, node_ids):
    """
    整体替换：界面上的多选一次提交，比逐个增删简单可靠。

    防御：传进来单个字符串时报错而不是**按字符拆开**（"DS-01-01" 会变成
    {'D','S','-','0','1'} 写进库，这种脏数据很难查）。实测踩过。
    """
    if isinstance(node_ids, str):
        raise TypeError("set_marks 需要集合，收到单个字符串；"
                        "传 {node_id} 而不是 node_id")
    ensure_user(user_id)
    with conn() as c:
        c.execute("DELETE FROM marks WHERE user_id=?", (user_id,))
        c.executemany("INSERT OR IGNORE INTO marks(user_id, node_id, created_at) "
                      "VALUES(?,?,?)",
                      [(user_id, n, datetime.datetime.now().isoformat(timespec="seconds"))
                       for n in node_ids])
    return len(node_ids)


# ---------------------------------------------------------------- 大题自评
# 综合应用题没有标准答案可自动判分，但学生需要"我到底掌握了没有"的记录。
# 这里用 answers 表存**自评**：source='selfcheck'，chosen 编码自评结果。
# 为什么不猜一个对错：自评是用户自己给的判断，和自动判分是两回事，
# 必须分开记录（source 字段区分），界面上也不能把自评说成"答对了"。
SELF_OK = "self:ok"          # 我做对了
SELF_REVIEW = "self:review"  # 需要再看一遍


def get_selfcheck(user_id):
    """返回 {question_id: 'self:ok' | 'self:review'}"""
    with conn() as c:
        rows = c.execute("SELECT question_id, chosen FROM answers "
                         "WHERE user_id=? AND source='selfcheck'",
                         (user_id,)).fetchall()
    return {r["question_id"]: r["chosen"] for r in rows}


def set_selfcheck(user_id, question_id, verdict):
    """记录大题自评。verdict 取 SELF_OK / SELF_REVIEW。"""
    if verdict not in (SELF_OK, SELF_REVIEW):
        raise ValueError(f"未知自评结果: {verdict}")
    return record_answer(user_id, question_id, verdict,
                         is_correct=(verdict == SELF_OK), source="selfcheck")


# ---------------------------------------------------------------- 大题自评分
# 综合应用题**不能自动判分**（41–47 是手写解答题），但"我这次能拿几分"
# 是学生真正关心的 —— 所以让用户自己按步骤给分，并把分数存下来。
#
# 数据怎么存：chosen 字段编码为 "score:<得分>"，source='selfscore'。
# 与自动判分（source='practice'）严格分开，界面上也不会说成"判分结果"。
def set_selfscore(user_id, question_id, score, total):
    """
    记录大题自评分。score 为得分（允许 0.5 步进），total 为该题总分。

    校验：分数必须落在 [0, total] 内。越界直接拒绝 —— 与其存一个
    不可能的分数（比如 13 分题填了 99），不如让界面报错。
    """
    try:
        sc = float(score)
    except (TypeError, ValueError):
        return False, "请输入数字"
    if sc < 0 or sc > float(total):
        return False, f"分数要在 0 – {total} 之间"
    return record_answer(user_id, question_id, f"score:{sc:g}",
                         is_correct=False, source="selfscore"), ""


def get_selfscore(user_id):
    """返回 {question_id: 自评得分(float)}"""
    out = {}
    with conn() as c:
        rows = c.execute("SELECT question_id, chosen FROM answers "
                         "WHERE user_id=? AND source='selfscore'",
                         (user_id,)).fetchall()
    for r in rows:
        try:
            out[r["question_id"]] = float(str(r["chosen"]).split(":", 1)[1])
        except (IndexError, ValueError):
            continue
    return out


# ---------------------------------------------------------------- 清空历史
# 为什么需要：测评时最怕"这条作答是我之前随手点出来的" —— 画像、诊断、路径
# 全都建立在作答记录上，脏数据会让演示结果不可信。
#
# 【绝对不能碰的表】cache —— 里面是 742 条 LLM 生成结果（讲义、720 道单选解析、
# 综合题解析）。清掉它等于把花过钱和时间生成的内容全扔了，下次运行要重新生成。
# 所以下面所有清空函数都**只操作 answers / marks / users**。
def reset_user(user_id):
    """
    清空**某个用户**的全部历史：作答记录 + 考点勾选。
    保留 users 里那一行（用户还在，只是没数据了）。

    返回被清掉的 (作答条数, 勾选条数) —— 让界面能如实报告做了什么，
    而不是只说"已清空"。
    """
    with conn() as c:
        n_a = c.execute("SELECT COUNT(*) FROM answers WHERE user_id=?",
                        (user_id,)).fetchone()[0]
        n_m = c.execute("SELECT COUNT(*) FROM marks WHERE user_id=?",
                        (user_id,)).fetchone()[0]
        c.execute("DELETE FROM answers WHERE user_id=?", (user_id,))
        c.execute("DELETE FROM marks WHERE user_id=?", (user_id,))
    return n_a, n_m


def purge_others(keep=("demo",)):
    """
    清掉**除白名单外**所有用户的历史与用户记录（测评环境清理用）。

    实测积累情况：76 个用户里只有 1 个是真人（demo），其余 75 个是开发/测试
    留下的（bw_paper、reg_ok、testuser、各种 8 位随机 id）。它们不影响正确性，
    但会让"用户数"之类的统计看起来很脏。

    keep：保留的用户 id（默认保留 demo —— 它是有 32 条作答的演示画像）。
    返回 {清除的作答数, 清除的勾选数, 清除的用户数}。
    """
    keep = tuple(keep or ())
    ph = ",".join("?" for _ in keep) or "''"
    with conn() as c:
        n_a = c.execute(f"DELETE FROM answers WHERE user_id NOT IN ({ph})",
                        keep).rowcount
        n_m = c.execute(f"DELETE FROM marks WHERE user_id NOT IN ({ph})",
                        keep).rowcount
        n_u = c.execute(f"DELETE FROM users WHERE user_id NOT IN ({ph})",
                        keep).rowcount
    return {"作答": n_a, "勾选": n_m, "用户": n_u}


def stats():
    """给界面显示"现在库里有什么" —— 清空前让用户知道自己在删什么"""
    with conn() as c:
        return {
            "用户数": c.execute("SELECT COUNT(*) FROM users").fetchone()[0],
            "作答条数": c.execute("SELECT COUNT(*) FROM answers").fetchone()[0],
            "勾选条数": c.execute("SELECT COUNT(*) FROM marks").fetchone()[0],
            "LLM缓存条数": c.execute("SELECT COUNT(*) FROM cache").fetchone()[0],
        }


# ---------------------------------------------------------------------------
# AI 评阅结果落库
# ---------------------------------------------------------------------------
# 用户要求"AI 评分可以加入总分" —— 那就必须**存下来**：
# 不落库的话刷新就没了，既没法算总分、也看不到"上次写成什么样"。
#
# 单独一张表（而不是塞进 answers）：
#   answers.chosen 存的是选项字母，语义是"客观题作答"；
#   AI 评阅有档次、问题清单、建议，结构完全不同，混进去会污染那张表。
def _ensure_ai_table(c):
    c.execute("""
        CREATE TABLE IF NOT EXISTS ai_grades (
            user_id     TEXT NOT NULL,
            question_id TEXT NOT NULL,
            task        TEXT NOT NULL,      -- TRANSLATION / WRITING
            band        TEXT,               -- 档次（如"第二档"）
            position    TEXT,               -- 上段/中段/下段
            score       REAL,               -- 按官方档位折算的分数
            score_max   REAL,               -- 该题满分
            payload     TEXT,               -- 完整评阅结果（JSON）
            answer_hash TEXT,               -- 作答内容的哈希（判断是否重评）
            graded_at   TEXT NOT NULL,
            PRIMARY KEY (user_id, question_id)
        )
    """)


def save_ai_grade(user_id, question_id, task, band, position, score,
                  score_max, payload_json, answer_hash):
    """写入/覆盖一次 AI 评阅结果。"""
    import json as _json
    ensure_user(user_id)
    with conn() as c:
        _ensure_ai_table(c)
        c.execute("""
            INSERT INTO ai_grades(user_id, question_id, task, band, position,
                                  score, score_max, payload, answer_hash, graded_at)
            VALUES(?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(user_id, question_id) DO UPDATE SET
                band=excluded.band, position=excluded.position,
                score=excluded.score, score_max=excluded.score_max,
                payload=excluded.payload, answer_hash=excluded.answer_hash,
                graded_at=excluded.graded_at
        """, (user_id, question_id, task, band, position, score, score_max,
              payload_json, answer_hash,
              datetime.datetime.now().isoformat(timespec="seconds")))


def get_ai_grades(user_id):
    """取该用户所有 AI 评阅结果 {question_id: {...}}。"""
    import json as _json
    with conn() as c:
        _ensure_ai_table(c)
        rows = c.execute("SELECT * FROM ai_grades WHERE user_id=?",
                         (user_id,)).fetchall()
    out = {}
    for r in rows:
        try:
            payload = _json.loads(r["payload"] or "{}")
        except Exception:                                   # noqa: BLE001
            payload = {}
        out[r["question_id"]] = {
            "task": r["task"], "band": r["band"], "position": r["position"],
            "score": r["score"], "score_max": r["score_max"],
            "graded_at": r["graded_at"], "payload": payload,
        }
    return out
