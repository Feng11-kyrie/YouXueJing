#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
快照序列化工具。

为什么单独有这么一个文件
------------------------
多智能体链路的状态里带有 `marks`(用户自报的薄弱考点), 它是 **set**。
set 在链路内部是对的(判重、交并差都靠它), 但 `json.dump` 不认识它:

    TypeError: Object of type set is not JSON serializable

这个坑的形态很恶劣 —— 预跑脚本跑完 6 个 Agent、打印完"复核 Agent 考纲校验通过",
**在最后一步写文件时才崩**; 而且它只在"路演兜底"这条路径上崩, 平时开发跑界面
完全遇不到。等真到路演现场想用快照兜底时才发现, 就已经晚了。

所以处理方式是:
  1. 不在链路状态里把 set 改成 list —— 那会破坏下游 set 语义;
  2. 在**序列化边界**统一做一次类型归一化(写快照时 + 读快照时都做),
     这样即使某个快照文件是旧版本/手工改过的, 回放也不会炸。
"""
import datetime


def to_jsonable(obj):
    """
    把对象树递归转成 JSON 可序列化的结构。

    覆盖本项目实际会出现、且 json 不认的类型:
      set / frozenset → 排序后的 list(排序让快照 diff 稳定、可读)
      tuple           → list
      datetime/date   → ISO 字符串
    dict 的非字符串键统一 str() 化(json 只允许字符串键)。
    其他未知类型退化为 str(obj), 保证**永远不抛异常** ——
    兜底机制本身不能成为失败点。
    """
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (set, frozenset)):
        # 混合类型集合无法直接排序(如 str 与 int), 退化按字符串排, 只求稳定
        try:
            return sorted(to_jsonable(x) for x in obj)
        except TypeError:
            return sorted((to_jsonable(x) for x in obj), key=str)
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(x) for x in obj]
    if isinstance(obj, (datetime.datetime, datetime.date)):
        return obj.isoformat()
    return str(obj)
