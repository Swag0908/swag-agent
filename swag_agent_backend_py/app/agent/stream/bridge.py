"""流式桥：把「模型流 + 工具循环」翻译成 7 个 SSE 事件。

语义与 Java `ChatStreamBridge`（`J/chat/stream/ChatStreamBridge.java`）1:1：

1. `ready` 永远第一条、`done` 正常结束时最后一条；异常时用**单个 `error` 事件替换整条流**，
   不再发 `done`（`ChatStreamBridge.java:75-82`）。
2. 正文/过程分界线 = 本轮流**是否已经出现过工具事件**：
   工具事件之前出现的文字 → `content`（当时无法预知）；之后 → `reasoning`（只展示不落库）。
3. 收尾 `finalize`（逐行等价 `onComplete`，`:127-154`）：本轮流跑过工具时，
   - 工具后的最后一段文字就是最终回答 → 先（若工具前发过正文）补 `segment_boundary{"final_answer"}`，
     再发一条**完整** `content`（不是删 `reasoning`，前端收到 content 会收起思考块）；
   - 模型只调工具、之后没再说话 → 正文留空，只发 `segment_boundary{"tool_only"}`。
4. 工具事件必须成对：执行前 `RUNNING`，执行后 `SUCCEEDED`/`FAILED`，带同一个 `call_id` 与 `duration_ms`。

与 Java 的实现差异（**等价而非同构**）：
- Java 靠 Spring AI Observation + auditId 信箱旁路拿工具状态；这里直接读 `delta.tool_calls` 分片
  （DeepSeek 原始 SSE 就带 `index/id/function{name,arguments}`，字节码与官方文档均已核实）。
- 单一 async generator 显式 `yield`，不需要 `Sinks`/`cache()`/`takeUntilOther`，
  因此不会再有「旁路互等挂死」「流水线被订阅两次导致正文翻倍」那两个坑。
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any

from app.agent import llm
from app.agent.stream import describer, events
from app.agent.tools import load_all
from app.agent.tools.registry import ToolCtx, dispatch
from app.config import settings
from app.core.errors import ConfirmationRequired

logger = logging.getLogger(__name__)

StreamFactory = Callable[[list[dict[str, Any]], str], AsyncIterator[Any]]


@dataclass
class TurnState:
    """一轮聊天的临时状态（等价 Java `ChatStreamBridge.State`）。"""

    answer: list[str] = field(default_factory=list)  # 当前被视为「最终回答」的文字
    reasoning: list[str] = field(default_factory=list)  # 工具之后的过渡文字
    has_tool_events: bool = False  # 本轮是否跑过工具（正文/过程的分界线）
    has_content_before_tool: bool = False
    tool_calls: list[dict[str, Any]] = field(default_factory=list)  # 诊断用：本轮所有工具调用

    @property
    def final_answer(self) -> str:
        return "".join(self.answer)

    def reset(self) -> None:
        self.answer.clear()
        self.reasoning.clear()
        self.has_tool_events = False
        self.has_content_before_tool = False
        self.tool_calls.clear()


@dataclass
class _PendingToolCall:
    index: int
    name: str = ""
    call_id: str | None = None
    arguments: str = ""


def _get(obj: Any, key: str, default: Any = None) -> Any:
    """同时兼容 openai SDK 对象与测试里的 fake dict/对象。"""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _choices(chunk: Any) -> list[Any]:
    return list(_get(chunk, "choices") or [])


async def _aiter_chunks(factory: StreamFactory, messages: list[dict[str, Any]], model: str) -> AsyncIterator[Any]:
    stream = factory(messages, model)
    if inspect.isawaitable(stream):  # 允许 factory 返回 awaitable(AsyncIterator)
        stream = await stream
    async for chunk in stream:
        yield chunk


async def stream_turn(
    messages: list[dict[str, Any]],
    model: str,
    ctx: ToolCtx,
    *,
    conversation_id: int | None = None,
    stream_factory: StreamFactory | None = None,
    state: TurnState | None = None,
    max_rounds: int | None = None,
    on_confirmation: str = "error",
    on_error: str = "event",
) -> AsyncIterator[events.SseEvent]:
    """执行一轮（可能多轮工具）对话，逐步产出 SSE 事件。

    Args:
        messages: 可变的消息列表；工具循环会往里追加 assistant/tool 消息。
        stream_factory: 流式来源；默认 `llm.open_stream`，测试注入 fake。
        state: 外部持有的一轮状态（API 层用它取最终回答落库）。
        on_confirmation: 危险工具需要确认时 —— `"error"` 发 error 事件（SSE 语义），
            `"raise"` 抛出交给上层转 409（非流式端点用）。
        on_error: 模型/工具异常时 —— `"event"` 发 error 事件结束流（SSE 语义），
            `"raise"` 继续向上抛（非流式端点用，Java 侧是 500）。
    """
    load_all()
    factory = stream_factory or llm.open_stream
    st = state if state is not None else TurnState()
    rounds = max_rounds if max_rounds is not None else settings.max_tool_rounds

    yield events.ready(conversation_id)
    _record_event("AGENT_STARTED", "STARTED", agentName="chatClient", modelName=model)

    try:
        for _ in range(max(1, rounds)):
            pending: dict[int, _PendingToolCall] = {}
            reasoning_parts: list[str] = []
            round_text: list[str] = []

            async for chunk in _aiter_chunks(factory, messages, model):
                for choice in _choices(chunk):
                    delta = _get(choice, "delta")
                    if delta is None:
                        continue
                    # 思考模式的思维链：只回传给模型（带 tools 时 DeepSeek 要求逐轮回传），不发事件。
                    rc = _get(delta, "reasoning_content")
                    if isinstance(rc, str) and rc:
                        reasoning_parts.append(rc)
                    text = _get(delta, "content")
                    if isinstance(text, str) and text:
                        round_text.append(text)
                        if st.has_tool_events:
                            st.reasoning.append(text)
                            yield events.reasoning(text)
                        else:
                            st.answer.append(text)
                            st.has_content_before_tool = True
                            yield events.content(text)
                    for raw_call in _get(delta, "tool_calls") or []:
                        index = int(_get(raw_call, "index", 0) or 0)
                        slot = pending.setdefault(index, _PendingToolCall(index=index))
                        call_id = _get(raw_call, "id")
                        if isinstance(call_id, str) and call_id:
                            slot.call_id = call_id
                        function = _get(raw_call, "function")
                        if function is not None:
                            name = _get(function, "name")
                            if isinstance(name, str) and name:
                                slot.name = name
                            fragment = _get(function, "arguments")
                            if isinstance(fragment, str) and fragment:
                                slot.arguments += fragment

            if not pending:
                break  # 本轮没有工具调用 → 对话结束

            messages.append(
                _assistant_message(round_text, pending, reasoning_parts)
            )
            for index in sorted(pending):
                call = pending[index]
                name = call.name or "unknown"
                activity = describer.describe(name, call.arguments)
                yield events.tool_call(name, "RUNNING", activity.display, activity.detail, call.call_id)

                started = time.monotonic()
                try:
                    ok, output = await _execute_tool(name, call.arguments, ctx, call.call_id)
                except ConfirmationRequired:
                    duration_ms = int((time.monotonic() - started) * 1000)
                    yield events.tool_call(
                        name, "FAILED", activity.display, activity.detail, call.call_id, duration_ms
                    )
                    raise
                duration_ms = int((time.monotonic() - started) * 1000)
                status = "SUCCEEDED" if ok else "FAILED"
                yield events.tool_call(name, status, activity.display, activity.detail, call.call_id, duration_ms)
                st.has_tool_events = True
                st.tool_calls.append(
                    {
                        "name": name,
                        "call_id": call.call_id,
                        "status": status,
                        "duration_ms": duration_ms,
                        "arguments": call.arguments,
                        "ok": ok,
                    }
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.call_id or f"call_{index}",
                        "content": output,
                    }
                )
    except (asyncio.CancelledError, GeneratorExit):
        raise  # 客户端断开：交给 API 层 finally 落库
    except ConfirmationRequired as exc:
        if on_confirmation == "raise":
            raise
        _record_event("AGENT_WAITING_CONFIRMATION", "WAITING_CONFIRMATION", errorMessage=str(exc))
        yield events.error(_confirmation_message(exc))
        return
    except Exception as exc:  # noqa: BLE001 - 模型/工具异常不能炸掉 HTTP 连接
        logger.exception("stream_turn failed: %s", exc)
        _record_event("AGENT_FAILED", "FAILED", errorMessage=str(exc))
        if on_error == "raise":
            raise
        yield events.error(str(exc).strip() or "服务异常")
        return

    _record_event("AGENT_COMPLETED", "SUCCEEDED")
    for event in finalize(st):
        yield event
    yield events.done()


def finalize(state: TurnState) -> list[events.SseEvent]:
    """收尾：逐行等价 Java `ChatStreamBridge.onComplete`（`:127-154`）。"""
    if not state.has_tool_events:
        return []  # 没干过活：正文早已按 content 发完
    final_answer = "".join(state.reasoning)
    pre_tool_text_was_answer = bool(state.answer)
    state.answer.clear()
    state.reasoning.clear()
    if not final_answer:
        # 模型只调工具、没再说话：正文留空，前端把铺垫搬进思考过程即可
        return [events.segment_boundary("tool_only")] if pre_tool_text_was_answer else []
    state.answer.append(final_answer)
    out: list[events.SseEvent] = []
    if pre_tool_text_was_answer:
        # 工具前那段是「我先查一下」式铺垫，前端要把它从正文区搬走
        out.append(events.segment_boundary("final_answer"))
    out.append(events.content(final_answer))  # 转正 = 再发一条完整 content
    return out


def _assistant_message(
    round_text: list[str],
    pending: dict[int, _PendingToolCall],
    reasoning_parts: list[str],
) -> dict[str, Any]:
    message: dict[str, Any] = {
        "role": "assistant",
        "content": "".join(round_text) or None,
        "tool_calls": [
            {
                "id": call.call_id or f"call_{index}",
                "type": "function",
                "function": {"name": call.name or "unknown", "arguments": call.arguments or "{}"},
            }
            for index, call in sorted(pending.items())
        ],
    }
    reasoning = "".join(reasoning_parts)
    if reasoning:
        # DeepSeek 思考模式 + tools：下一轮必须带回 reasoning_content，否则 400。
        message["reasoning_content"] = reasoning
    return message


async def _execute_tool(name: str, arguments: str, ctx: ToolCtx, call_id: str | None) -> tuple[bool, str]:
    """执行工具；审计旁路尽力调用（模块缺失/异常都不影响聊天）。"""
    _record_tool_requested(name, arguments, ctx, call_id)
    await _check_confirmation(name, arguments, ctx, call_id)
    return await dispatch(name, arguments, ctx)


# ---------------------------------------------------------------------------
# 审计旁路（audit-builder 提供；模块不存在时全部 no-op）
# ---------------------------------------------------------------------------


def _audit_recorder():
    try:
        from app.audit import recorder  # noqa: PLC0415 - 可选模块，延迟导入
    except Exception:  # noqa: BLE001 - 未实现/导入失败都按不可用处理
        return None
    return recorder


def _record_event(event_type: str, execution_status: str | None = None, **fields: Any) -> None:
    recorder = _audit_recorder()
    if recorder is None:
        return
    try:
        recorder.record_event(event_type, execution_status, **fields)
    except Exception:  # noqa: BLE001 - 审计失败不能影响聊天
        logger.debug("audit record_event failed: %s", event_type, exc_info=True)


def _record_tool_requested(name: str, arguments: str, ctx: ToolCtx, call_id: str | None) -> None:
    recorder = _audit_recorder()
    if recorder is None:
        return
    try:
        parsed = json.loads(arguments or "{}")
        payload = parsed if isinstance(parsed, dict) else {"input": parsed}
    except json.JSONDecodeError:
        payload = {"raw": arguments}
    try:
        recorder.record_tool_requested(name, payload, ctx.audit_id, ctx.user_id)
    except Exception:  # noqa: BLE001
        logger.debug("audit record_tool_requested failed: %s", name, exc_info=True)


async def _check_confirmation(name: str, arguments: str, ctx: ToolCtx, call_id: str | None) -> None:
    recorder = _audit_recorder()
    if recorder is None:
        return
    checker = getattr(recorder, "check_tool_confirmation", None)
    if checker is None:
        return
    try:
        parsed = json.loads(arguments or "{}")
        payload = parsed if isinstance(parsed, dict) else {"input": parsed}
    except json.JSONDecodeError:
        payload = {"raw": arguments}
    try:
        result = checker(name, payload, ctx)
        if inspect.isawaitable(result):
            await result
    except ConfirmationRequired:
        raise
    except Exception:  # noqa: BLE001
        logger.debug("audit check_tool_confirmation failed: %s", name, exc_info=True)


def _confirmation_message(exc: ConfirmationRequired) -> str:
    extra = getattr(exc, "extra", None) or {}
    tool_name = extra.get("toolName") or "该工具"
    confirmation_id = extra.get("confirmationId")
    if confirmation_id:
        return f"{tool_name} 需要用户确认后才能执行（confirmationId={confirmation_id}）"
    return f"{tool_name} 需要用户确认后才能执行"


__all__ = ["TurnState", "StreamFactory", "stream_turn", "finalize"]
