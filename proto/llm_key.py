#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用户自带 API Key 的存取（BYOK）。

存哪里：**当前登录会话**（`app.storage.user`），不写数据库、不下发浏览器。
理由：
  · NiceGUI 的 `app.storage.browser` 是"初始请求前只能读、不能改"的加密 cookie，
    在按钮回调里赋值不会生效（实测保存后刷新就丢）—— 这是之前的 bug；
  · `app.storage.user` 是服务端会话存储，按钮回调里可写，刷新/换标签页仍在；
  · 不写 `data/yj.db`，退出登录时清空。

注意：`app.storage.user` 需要 `ui.run(storage_secret=...)`；app 已配置
（可用环境变量 `YJ_SECRET` 覆盖）。
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


def _store():
    """会话存储；兼容旧版存在 browser 里的值（只读迁移）。"""
    try:
        return app.storage.user
    except Exception:                                       # noqa: BLE001
        return None


def get():
    """取用户配置的 {key, base, model}（没有就返回空）。"""
    st = _store()
    if st is None:
        return {"key": "", "base": "", "model": ""}
    return {
        "key": st.get(_FIELDS[0]) or "",
        "base": st.get(_FIELDS[1]) or "",
        "model": st.get(_FIELDS[2]) or "",
    }


def set_key(key, base="", model=""):
    st = _store()
    if st is None:
        return False
    try:
        st[_FIELDS[0]] = (key or "").strip()
        st[_FIELDS[1]] = (base or "").strip()
        st[_FIELDS[2]] = (model or "").strip()
        return True
    except Exception:                                       # noqa: BLE001
        return False


def clear():
    return set_key("", "", "")


def has_key():
    return bool(get()["key"])
