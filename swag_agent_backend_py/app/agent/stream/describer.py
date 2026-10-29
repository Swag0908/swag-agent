"""工具状态「说人话」：等价 Java `ToolActivityDescriber`
（`J/chat/stream/ToolActivityDescriber.java:48-148`）。

规则逐条移植：
1. 动作词优先取人工词表 `ACTION_WORDS`；未收录的工具用工具自身 `description` 的第一句兜底
   （按 `。；;` 与换行切，超过 18 字截断加 `…`）；仍取不到则用工具名。
2. 参数摘要按 `DETAIL_KEYS` 顺序挑第一个非空标量；都没有则取第一个非空标量；
   解析失败退化成整段文本。
3. 摘要压缩空白、超过 48 字截断加 `…`。
4. display = `正在{动作}…` 或 `正在{动作}：{摘要}`。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from app.agent.tools.registry import get_tool

logger = logging.getLogger(__name__)

DETAIL_MAX_CHARS = 48
FALLBACK_MAX_CHARS = 18

# 与 Java 逐字对齐（保留尚未出现的工具名，便于后续 domain 工具直接复用文案）。
ACTION_WORDS: dict[str, str] = {
    # 时间
    "getCurrentTime": "查看当前时间",
    # 联网搜索
    "webSearch": "联网搜索",
    "searchWeb": "联网搜索",
    # 待办
    "listTodayTodos": "读取今日待办",
    "listTodosByDate": "读取指定日期的待办",
    "listTodos": "读取待办",
    "createTodo": "创建待办",
    "updateTodo": "修改待办",
    "completeTodo": "完成待办",
    "deferTodo": "推迟待办",
    "deleteTodo": "删除待办",
    "getTodoStatistics": "统计待办",
    "listOverdueTodos": "查找逾期待办",
    # 常用网站
    "listSiteFolders": "读取网站分类",
    "listSiteBookmarks": "读取常用网站",
    "addSiteBookmark": "添加常用网站",
    "updateSiteBookmark": "修改常用网站",
    "deleteSiteBookmark": "删除常用网站",
    "createSiteFolder": "新建网站分类",
    "updateSiteFolder": "修改网站分类",
    "deleteSiteFolder": "删除网站分类",
    # 长期记忆
    "rememberUserMemory": "记住这条信息",
    "recallUserMemory": "回忆你的档案",
    "listUserMemories": "翻阅你的档案",
    "forgetUserMemory": "忘掉某条记忆",
    "deleteUserMemory": "删除某条记忆",
}

# 参数摘要优先读取的字段（顺序敏感）。
DETAIL_KEYS = ("query", "keyword", "name", "title", "url", "content", "text", "ref", "date", "id")


@dataclass(frozen=True)
class Activity:
    display: str
    detail: str | None


def describe(tool_name: str, arguments: str | dict[str, Any] | None) -> Activity:
    action = ACTION_WORDS.get(tool_name) or _fallback_action(tool_name)
    detail = _detail(arguments)
    display = f"正在{action}…" if detail is None else f"正在{action}：{detail}"
    return Activity(display=display, detail=detail)


def _fallback_action(tool_name: str) -> str:
    spec = get_tool(tool_name)
    if spec is not None and spec.description.strip():
        first = _split_first_sentence(spec.description)
        if first:
            return first if len(first) <= FALLBACK_MAX_CHARS else first[:FALLBACK_MAX_CHARS] + "…"
    return tool_name


def _split_first_sentence(description: str) -> str:
    text = description.strip()
    for index, char in enumerate(text):
        if char in "。；;\n":
            return text[:index].strip()
    return text


def _detail(arguments: str | dict[str, Any] | None) -> str | None:
    if arguments is None:
        return None
    if isinstance(arguments, dict):
        return _detail_from_object(arguments)
    raw = str(arguments).strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return _truncate(raw)
    if not isinstance(parsed, dict):
        return _truncate(raw)
    return _detail_from_object(parsed)


def _detail_from_object(payload: dict[str, Any]) -> str | None:
    for key in DETAIL_KEYS:
        value = payload.get(key)
        if _is_scalar(value) and str(value).strip():
            return _truncate(str(value))
    for value in payload.values():
        if _is_scalar(value) and str(value).strip():
            return _truncate(str(value))
    return None


def _is_scalar(value: Any) -> bool:
    return isinstance(value, (str, int, float, bool))


def _truncate(text: str) -> str | None:
    flat = " ".join(text.split())
    if not flat:
        return None
    return flat if len(flat) <= DETAIL_MAX_CHARS else flat[:DETAIL_MAX_CHARS] + "…"


__all__ = ["Activity", "ACTION_WORDS", "DETAIL_KEYS", "DETAIL_MAX_CHARS", "describe"]
