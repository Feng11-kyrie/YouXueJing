#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用户自带 API Key 的存取（BYOK）。

存哪里：**浏览器 cookie**（`app.storage.browser`），不是数据库。
理由：
  · 用户自己的密钥，存在他自己的浏览器里最自然
  · 存进数据库意味着服务端明文保存所有用户的密钥 —— 一旦泄露影响面大
  · 本项目没有配置 `storage_secret`（`app.storage.user` 需要它），
    而 `app.storage.browser` 不需要

注意：`app.storage.browser` 只能在**页面请求上下文**里读写，
在定时器/后台任务里访问会抛异常 —— 所以这里全部包了 try。
"""
from nicegui import app

_FIELDS = ("yj_llm_key", "yj_llm_base", "yj_llm_model")

PROVIDERS = {
    "DeepSeek": {"base": "https://api.deepseek.com/v1", "model": "deepseek-chat",
                 "备注": "便宜，中文好；每次评阅约 ¥0.006"},
    "通义千问": {"base": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                 "model": "qwen-plus", "备注": "阿里云，兼容 OpenAI 协议"},
    "智谱 GLM": {"base": "https://open.bigmodel.cn/api/paas/v4",
                 "model": "glm-4-flash", "备注": "有免费额度"},
    "OpenAI": {"base": "https://api.openai.com/v1", "model": "gpt-4o-mini",
               "备注": "按美元计费"},
}


def get():
    """取用户配置的 {key, base, model}（没有就返回空）。"""
    try:
        return {
            "key": app.storage.browser.get(_FIELDS[0]) or "",
            "base": app.storage.browser.get(_FIELDS[1]) or "",
            "model": app.storage.browser.get(_FIELDS[2]) or "",
        }
    except Exception:                                       # noqa: BLE001
        return {"key": "", "base": "", "model": ""}


def set_key(key, base="", model=""):
    try:
        app.storage.browser[_FIELDS[0]] = (key or "").strip()
        app.storage.browser[_FIELDS[1]] = (base or "").strip()
        app.storage.browser[_FIELDS[2]] = (model or "").strip()
        return True
    except Exception:                                       # noqa: BLE001
        return False


def clear():
    return set_key("", "", "")


def has_key():
    return bool(get()["key"])
