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
    return {r["question_id"]: {"chosen": r["chosen"],
                               "is_correct": bool(r["is_correct"]),
                               "source": r["source"]} for r in rows}


def record_answer(user_id, question_id, chosen, is_correct, source="practice"):
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
                   datetime.datetime.now().isoformat(timespec="seconds")))
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
