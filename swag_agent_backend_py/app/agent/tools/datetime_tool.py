"""当前时间工具：等价 Java `DateTimeTools#getCurrentTime`（`J/tool/DateTimeTools.java:11-15`）。

Java 返回 `LocalDateTime.now().atZone(zone).toString()`，例如
`2026-10-28T16:25:25.123456+08:00`；Python 用 `datetime.now(Asia/Shanghai).isoformat()` 对齐。
"""

from __future__ import annotations

from datetime import datetime

from app.agent.tools.registry import ToolCtx, tool
from app.core.timeutil import TZ


@tool(
    "getCurrentTime",
    "当用户询问时间，回答对应时区的具体时间",
    {"type": "object", "properties": {}, "required": []},
    needs_user=False,
    side_effect="none",
)
async def get_current_time(ctx: ToolCtx) -> str:  # noqa: ARG001 - 契约要求签名带 ctx
    return datetime.now(TZ).isoformat()


__all__ = ["get_current_time"]
