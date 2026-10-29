"""SSE 事件模型与编码（契约见 `docs/python-migration/01-api-contract.md` §4）。

硬约束（前端零改动）：
- 7 个事件名：ready / content / reasoning / tool_call / segment_boundary / error / done；
- `data` 是**单行紧凑 JSON**，**扁平**形状（`{"text": ...}` / `{"name": ...}`），键名 snake_case；
  Java 原实现外层多一层 `{"type": ..., "data": {...}}` 包装，但前端解析器直接读扁平字段
  （`swag_agent_web/src/api/chat.js:69`、`swag_agent_web/src/composables/useChat.js:341-361`），
  收到包装会得到 `data.text === undefined`，流式正文/工具状态不显示。为保持前端零改动，
  Python 按前端实际消费的形状输出；`ready`/`done` 仍保留空对象，避免前端读字段出错。
- 帧格式 `event: <name>\\ndata: <json>\\n\\n`；无 id/retry/注释心跳；
- `ready` / `done` 的 `data` 不可省略（`done` 为 `{}`）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

READY = "ready"
CONTENT = "content"
REASONING = "reasoning"
TOOL_CALL = "tool_call"
SEGMENT_BOUNDARY = "segment_boundary"
ERROR = "error"
DONE = "done"

EVENT_NAMES = (READY, CONTENT, REASONING, TOOL_CALL, SEGMENT_BOUNDARY, ERROR, DONE)


@dataclass(frozen=True)
class SseEvent:
    """一条待编码的事件；事件名走 SSE 的 `event:` 行，`data` 是扁平 JSON。"""

    name: str
    data: dict[str, Any] = field(default_factory=dict)

    def payload(self) -> dict[str, Any]:
        # 与 Java 的差异：Java 发 {"type": name, "data": {...}}，但前端 api/chat.js 直接
        # 读 data.text / data.name，所以这里只发内层字段，保证前端零改动。
        return dict(self.data)

    def encode(self) -> str:
        body = json.dumps(self.payload(), ensure_ascii=False, separators=(",", ":"))
        return f"event: {self.name}\ndata: {body}\n\n"


def _event(name: str, **data: Any) -> SseEvent:
    return SseEvent(name=name, data=data)


def ready(conversation_id: int | None = None) -> SseEvent:
    return _event(READY, conversation_id=conversation_id)


def content(text: str) -> SseEvent:
    return _event(CONTENT, text=text)


def reasoning(text: str) -> SseEvent:
    return _event(REASONING, text=text)


def tool_call(
    name: str,
    status: str,
    display: str,
    detail: str | None = None,
    call_id: str | None = None,
    duration_ms: int | None = None,
) -> SseEvent:
    """工具状态事件；字段顺序与省略规则对齐 `ChatStreamEvent.toolCall`。"""
    data: dict[str, Any] = {"name": name, "status": status, "display": display}
    if detail is not None and detail.strip():
        data["detail"] = detail
    if call_id is not None:
        data["call_id"] = call_id
    if duration_ms is not None:
        data["duration_ms"] = duration_ms
    return SseEvent(name=TOOL_CALL, data=data)


def segment_boundary(reason: str) -> SseEvent:
    return _event(SEGMENT_BOUNDARY, reason=reason)


def error(message: str) -> SseEvent:
    return _event(ERROR, message=message)


def done() -> SseEvent:
    return _event(DONE)


__all__ = [
    "READY",
    "CONTENT",
    "REASONING",
    "TOOL_CALL",
    "SEGMENT_BOUNDARY",
    "ERROR",
    "DONE",
    "EVENT_NAMES",
    "SseEvent",
    "ready",
    "content",
    "reasoning",
    "tool_call",
    "segment_boundary",
    "error",
    "done",
]
