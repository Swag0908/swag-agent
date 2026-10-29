"""内容摘要算法：必须与 Java ``AuditDigest`` 逐字节一致（跨语言 parity）。

Java 实现（``swag_agent_backend/.../audit/core/AuditDigest.java``）：

- ``sha256(content)``：``SHA-256(content.getBytes(UTF_8))``，小写 hex；null 视作 ""。
- ``canonicalizeJson(input)``：空/空白 → ""；用 Jackson 解析后重新序列化，
  开启 ``SerializationFeature.ORDER_MAP_ENTRIES_BY_KEYS``；解析失败 → 返回原文。
- ``actionDigest(toolName, input)``：``sha256(toolName + "\\n" + canonicalizeJson(input))``。

对应 Python 规范化 JSON 参数固定为
``json.dumps(parsed, sort_keys=True, separators=(",", ":"), ensure_ascii=False)``
（见 ``docs/python-migration/03-ai-core-mapping.md`` §5）。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

__all__ = [
    "sha256",
    "canonicalize_json",
    "action_digest",
    "raw_tool_input",
    "json_text_for_event_data",
]


def _null_safe(value: str | None) -> str:
    return "" if value is None else value


def sha256(content: str | None) -> str:
    """原始内容的 SHA-256 小写 hex；None 与 "" 等价（Java ``nullSafe``）。"""
    return hashlib.sha256(_null_safe(content).encode("utf-8")).hexdigest()


def canonicalize_json(input: str | None) -> str:
    """JSON 规范化；非 JSON 输入原样返回（对齐 Java ``canonicalizeJson``）。"""
    if input is None or not input.strip():
        return ""
    try:
        parsed = json.loads(input)
    except (ValueError, TypeError):
        return input
    try:
        return json.dumps(parsed, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    except (TypeError, ValueError):
        # Jackson 理论上不会失败；Python 侧极端对象（如超大递归）降级为原文
        return input


def action_digest(tool_name: str | None, input: str | None) -> str:
    """用户确认绑定的动作摘要：``sha256(toolName + "\\n" + canonicalJson)``。"""
    return sha256(_null_safe(tool_name) + "\n" + canonicalize_json(input))


def raw_tool_input(arguments: Any) -> str:
    """工具入参 → 原始 JSON 文本。

    Java 侧拿到的是模型给出的 JSON 字符串；Python 的 tool dispatch 可能传 dict，
    这里固定成规范形式，保证同一入参的 ``inputDigest`` 可复现。
    """
    if arguments is None:
        return ""
    if isinstance(arguments, str):
        return arguments
    try:
        return json.dumps(arguments, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    except (TypeError, ValueError):
        return str(arguments)


def json_text_for_event_data(value: Any) -> str | None:
    """把 ``audit_event.event_data``（JSON 列）还原成 Java 响应的 JSON 字符串。

    Java 查询侧对 JSON 列取 ``getString()``，即 MySQL 规范化后的 JSON 文本
    （对象 key 有序、``", "`` / ``": "`` 分隔）。这里复刻同样的文本形态，
    让 ``GET /audit/events/{auditId}`` 的 ``eventData`` 保持“字符串里再装 JSON”。
    """
    if value is None:
        return None
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, sort_keys=True, separators=(", ", ": "), ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)
