#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SQLite 存储层。

三张表:
  users    用户(匿名, 由浏览器 localStorage 里的 uuid 标识, 不做注册登录)
  answers  答题记录
  cache    LLM 预跑缓存 —— 路演防断网/防 API 挂的关键: 演示路径的输出提前存好

为什么用 SQLite 而不是 session_state:
  画像必须跨刷新持久化, 否则用户做完诊断刷新一下就没了。
  SQLite 是单文件、零配置, 对单人项目是最优解。
"""
import os
import json
import sqlite3
import datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(BASE, "data", "yj.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id     TEXT PRIMARY KEY,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS answers (
    user_id      TEXT NOT NULL,
    question_id  TEXT NOT NULL,
    chosen       TEXT,
    is_correct   INTEGER NOT NULL,
    source       TEXT NOT NULL DEFAULT 'practice',   -- diagnostic | practice
    answered_at  TEXT NOT NULL,
    PRIMARY KEY (user_id, question_id)
);
CREATE TABLE IF NOT EXISTS marks (
    user_id     TEXT NOT NULL,
    node_id     TEXT NOT NULL,     -- 用户自己标记为薄弱的知识点(叶子考点)
    created_at  TEXT NOT NULL,
    PRIMARY KEY (user_id, node_id)
);
CREATE TABLE IF NOT EXISTS cache (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
"""


def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def conn():
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    with conn() as c:
        c.executescript(SCHEMA)


def ensure_user(user_id):
    with conn() as c:
        c.execute("INSERT OR IGNORE INTO users(user_id, created_at) VALUES(?,?)",
                  (user_id, _now()))


def record_answer(user_id, question_id, chosen, is_correct, source="practice"):
    ensure_user(user_id)
    with conn() as c:
        c.execute("""INSERT INTO answers(user_id, question_id, chosen, is_correct,
                                         source, answered_at)
                     VALUES(?,?,?,?,?,?)
                     ON CONFLICT(user_id, question_id) DO UPDATE SET
                       chosen=excluded.chosen,
                       is_correct=excluded.is_correct,
                       source=excluded.source,
                       answered_at=excluded.answered_at""",
                  (user_id, question_id, chosen, 1 if is_correct else 0, source, _now()))


def get_answers(user_id, source=None):
    """返回 {question_id: {'chosen':.., 'is_correct':bool, 'source':..}}"""
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


def reset_user(user_id):
    with conn() as c:
        c.execute("DELETE FROM answers WHERE user_id=?", (user_id,))
        c.execute("DELETE FROM marks WHERE user_id=?", (user_id,))


# ---------------------------------------------------------------- 自报薄弱点
def get_marks(user_id):
    """用户自己勾选的薄弱考点集合。这是**不依赖做题**的画像来源。"""
    with conn() as c:
        rows = c.execute("SELECT node_id FROM marks WHERE user_id=?",
                         (user_id,)).fetchall()
    return {r["node_id"] for r in rows}


def set_marks(user_id, node_ids):
    """整体替换用户的标记(界面上的多选一次提交, 比逐个增删简单可靠)。"""
    ensure_user(user_id)
    node_ids = set(node_ids)
    with conn() as c:
        c.execute("DELETE FROM marks WHERE user_id=?", (user_id,))
        c.executemany("INSERT OR IGNORE INTO marks(user_id,node_id,created_at) VALUES(?,?,?)",
                      [(user_id, n, _now()) for n in node_ids])


# ---------------------------------------------------------------- LLM 预跑缓存
def cache_get(key):
    with conn() as c:
        r = c.execute("SELECT value FROM cache WHERE key=?", (key,)).fetchone()
    return json.loads(r["value"]) if r else None


def cache_set(key, value):
    with conn() as c:
        c.execute("""INSERT INTO cache(key, value, created_at) VALUES(?,?,?)
                     ON CONFLICT(key) DO UPDATE SET
                       value=excluded.value, created_at=excluded.created_at""",
                  (key, json.dumps(value, ensure_ascii=False), _now()))


if __name__ == "__main__":
    init_db()
    print(f"数据库就绪: {DB}")
    with conn() as c:
        for t in ("users", "answers", "marks", "cache"):
            n = c.execute(f"SELECT COUNT(*) n FROM {t}").fetchone()["n"]
            print(f"  {t}: {n} 行")
