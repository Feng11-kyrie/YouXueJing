#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LLM 调用封装。

设计要点
--------
1. **可配置**: 通过环境变量或 .streamlit/secrets.toml 提供 key, 不硬编码。
   DeepSeek / 通义 / 智谱 / OpenAI 等只要兼容 OpenAI 协议, 改 base_url 与 model 即可。

2. **无 key 时进入"演示模式"** —— 关键取舍:
   演示模式**不假装是 AI 生成的**。它返回的是"用真实数据填的模板"
   (考纲结构 + 真题考频 + 你的掌握度), 并在界面上明确标注。
   这既保证路演能跑, 又不产生"我用了 AI"的虚假表述 —— 验收要求结论必须真实。

3. **预跑缓存**: 相同 (任务, 输入) 直接读 SQLite 缓存。
   路演最怕现场调 API 转圈, 演示路径提前跑一遍存好即可秒出。

4. **超时 + 重试 + 降级**: 任何失败都退回模板, 不阻断链路。
"""
import os
import json
import hashlib
import time

from . import store

# ---------------------------------------------------------------- 配置
DEFAULTS = {
    "base_url": "https://api.deepseek.com/v1",
    "model": "deepseek-chat",
    "timeout": 60,
    "retries": 2,
    "temperature": 0.3,
}


def _secrets():
    """从 streamlit secrets 或环境变量读配置(两者都没有则视为未配置)"""
    cfg = dict(DEFAULTS)
    # 1) st.secrets（部署时用）
    try:
        import streamlit as st
        sec = st.secrets.get("llm", {}) if hasattr(st, "secrets") else {}
        for k in cfg:
            if k in sec:
                cfg[k] = sec[k]
    except Exception:
        pass
    # 2) 环境变量（覆盖）
    env_map = {"LLM_API_KEY": "api_key", "LLM_BASE_URL": "base_url",
               "LLM_MODEL": "model"}
    for env, key in env_map.items():
        if os.environ.get(env):
            cfg[key] = os.environ[env]
    return cfg


def status():
    """返回 (是否已配置, 说明文字)"""
    cfg = _secrets()
    if cfg.get("api_key"):
        return True, f"已配置：{cfg['model']} @ {cfg['base_url']}"
    return False, "未配置 API key —— 当前为演示模式（模板 + 真实数据，非 AI 生成）"


def _cache_key(task, payload):
    raw = json.dumps({"t": task, "p": payload}, ensure_ascii=False, sort_keys=True)
    return "llm:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def complete(task, prompt, payload=None, use_cache=True):
    """
    统一调用入口。

    返回 {text, source}，source ∈ {"cache", "llm", "template", "error"}
    上层可据此在界面上标注内容来源 —— 这是"表述真实"的技术保障。
    """
    cfg = _secrets()
    key = _cache_key(task, payload if payload is not None else prompt)
    if use_cache:
        hit = store.cache_get(key)
        if hit:
            return {"text": hit["text"], "source": "cache"}

    if not cfg.get("api_key"):
        return {"text": None, "source": "template"}

    last_err = None
    for attempt in range(cfg["retries"] + 1):
        try:
            from openai import OpenAI
            client = OpenAI(api_key=cfg["api_key"], base_url=cfg["base_url"],
                            timeout=cfg["timeout"])
            resp = client.chat.completions.create(
                model=cfg["model"],
                temperature=cfg["temperature"],
                messages=[
                    {"role": "system",
                     "content": "你是 408 考研学习助理。只依据给定的考点与真题统计作答，"
                                "不要编造考纲外的知识点。输出使用中文 Markdown。"},
                    {"role": "user", "content": prompt},
                ],
            )
            text = resp.choices[0].message.content or ""
            if use_cache:
                store.cache_set(key, {"text": text, "task": task})
            return {"text": text, "source": "llm"}
        except Exception as e:                      # noqa: BLE001
            last_err = e
            if attempt < cfg["retries"]:
                time.sleep(1.5 * (attempt + 1))
    return {"text": None, "source": "error", "error": str(last_err)[:200]}
