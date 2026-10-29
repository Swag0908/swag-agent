"""聊天服务层：把 runner + bridge 组装成三种响应（SSE / 纯文本流 / 非流式）。

路由放在 `app.api.legacy_chat`（按 CONTRACTS §5.1：`legacy_chat` 覆盖 `/test/chat*` 3 个端点），
本模块只提供可复用、可测试的组装函数。

关键点：
- **首字节要早**：SSE/纯文本流都不能被任何中间层缓冲（契约 R2）；
- **落库放 `finally`**：正常结束、异常、客户端 abort 都要保存已生成内容；
- 落库用**新 Session**：SSE 可能在请求 Session 关闭之后才结束。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from fastapi.responses import Response, StreamingResponse
from sqlalchemy.orm import Session

from app.agent import runner
from app.agent.stream import events
from app.agent.stream.bridge import StreamFactory, TurnState, stream_turn
from app.db.base import SessionLocal

logger = logging.getLogger(__name__)

SSE_MEDIA_TYPE = "text/event-stream"
TEXT_MEDIA_TYPE = "text/plain"
STREAM_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}


def prepare(
    db: Session,
    user_id: int,
    model: int,
    user_input: str,
    conversation_id: int | None,
) -> tuple[runner.TurnContext, list[dict[str, Any]]]:
    """校验会话/模型 → 落 user 消息 → 组装消息（同步，调用方用线程池包一层）。"""
    turn = runner.prepare_turn(db, user_id, model, user_input, conversation_id)
    messages = runner.build_messages(db, turn)
    return turn, messages


def _finalize(turn: runner.TurnContext, answer: str) -> None:
    """SSE/流式收尾落库：用独立 Session，异常只记日志。"""
    try:
        with SessionLocal() as db:
            runner.finalize_turn(db, turn, answer)
    except Exception:  # noqa: BLE001 - 落库失败不能影响已推完的流
        logger.warning("收尾落库失败：conversation=%s", turn.conversation_id, exc_info=True)


async def run_once(
    turn: runner.TurnContext,
    messages: list[dict[str, Any]],
    *,
    stream_factory: StreamFactory | None = None,
) -> str:
    """非流式：跑完工具循环，返回最终回答（ConfirmationRequired 会向上抛 → 409）。"""
    state = TurnState()
    async for _event in stream_turn(
        messages,
        turn.model,
        runner.ensure_tool_ctx(turn),
        conversation_id=turn.conversation_id,
        stream_factory=stream_factory,
        state=state,
        on_confirmation="raise",
        on_error="raise",
    ):
        pass
    return state.final_answer


def sse_response(
    turn: runner.TurnContext,
    messages: list[dict[str, Any]],
    *,
    stream_factory: StreamFactory | None = None,
) -> StreamingResponse:
    """`GET /test/chat/stream/events`：7 个事件逐条帧化输出。"""
    state = TurnState()

    async def event_stream() -> AsyncIterator[str]:
        try:
            async for event in stream_turn(
                messages,
                turn.model,
                runner.ensure_tool_ctx(turn),
                conversation_id=turn.conversation_id,
                stream_factory=stream_factory,
                state=state,
                on_confirmation="error",
            ):
                yield event.encode()
        finally:
            # 正常/异常/客户端 abort 都会到这里（同步执行，避免 finally 里被取消）
            _finalize(turn, state.final_answer)

    return StreamingResponse(event_stream(), media_type=SSE_MEDIA_TYPE, headers=dict(STREAM_HEADERS))


def plain_stream_response(
    turn: runner.TurnContext,
    messages: list[dict[str, Any]],
    *,
    stream_factory: StreamFactory | None = None,
) -> StreamingResponse:
    """`GET /test/chat/stream`（旧接口）：纯文本逐块输出，错误内联 `\\n\\n[错误] ...`。

    Java 语义（`J/contoller/TestController.java:125-146`）：累积**所有**文字块（含错误文本）落库，
    客户端中断也保存已生成部分。这里 content + reasoning 都算「文字」，按到达顺序原样输出，
    因此和 Java 的 `.stream().content()` 观感一致（工具状态不输出）。
    """
    buffer: list[str] = []
    finalize_started = False

    async def text_stream() -> AsyncIterator[str]:
        nonlocal finalize_started
        try:
            async for event in stream_turn(
                messages,
                turn.model,
                runner.ensure_tool_ctx(turn),
                conversation_id=turn.conversation_id,
                stream_factory=stream_factory,
                state=TurnState(),
                on_confirmation="error",
            ):
                if event.name == events.SEGMENT_BOUNDARY:
                    # 进入收尾阶段：后面的 content 是「转正」补发的那段，
                    # 其文字已作为 reasoning 流过（纯文本流不区分），不能再吐一遍。
                    finalize_started = True
                    continue
                if event.name in (events.CONTENT, events.REASONING):
                    if finalize_started and event.name == events.CONTENT:
                        continue
                    text = str(event.data.get("text") or "")
                    if text:
                        buffer.append(text)
                        yield text
                elif event.name == events.ERROR:
                    inline = f"\n\n[错误] {event.data.get('message') or '服务异常'}"
                    buffer.append(inline)
                    yield inline
        finally:
            _finalize(turn, "".join(buffer))

    return StreamingResponse(text_stream(), media_type=TEXT_MEDIA_TYPE, headers=dict(STREAM_HEADERS))


def plain_response(text: str) -> Response:
    """`GET /test/chat`：一次返回纯文本（Java 默认 `text/plain;charset=UTF-8`）。"""
    return Response(content=text or "", media_type=TEXT_MEDIA_TYPE)


def finalize_now(turn: runner.TurnContext, answer: str) -> None:
    """非流式端点用：请求内直接落库（Session 尚在使用中）。"""
    _finalize(turn, answer)


__all__ = [
    "SSE_MEDIA_TYPE",
    "TEXT_MEDIA_TYPE",
    "STREAM_HEADERS",
    "prepare",
    "run_once",
    "sse_response",
    "plain_stream_response",
    "plain_response",
    "finalize_now",
]
