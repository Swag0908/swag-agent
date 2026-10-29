"""旧聊天端点（保留兼容，前端 SSE 已在用第三个）：

- `GET /test/chat`              纯文本回答（非流式）
- `GET /test/chat/stream`       纯文本逐块流（工具状态不输出，错误内联）
- `GET /test/chat/stream/events` SSE（7 事件，前端正式使用）

契约：`docs/python-migration/01-api-contract.md` §3.6/§4；实现：`app/api/chat.py` + `app/agent/**`。
按 CONTRACTS §5.1 归属表，这三个 `/test/chat*` 端点都放在本模块。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.api import chat as chat_service
from app.api.deps import current_user
from app.db.base import get_db
from app.domains.auth.service import AuthUser

router = APIRouter(tags=["chat"])

_MODEL_DESC = "1=flash，2=pro；其它值 400 model must be 1 or 2"


async def _prepare(
    db: Session,
    user: AuthUser,
    model: int,
    user_input: str,
    conversation_id: int | None,
):
    """在线程池里做同步准备（会话校验 + 先落 user 消息 + 组装提示词/记忆）。"""
    return await run_in_threadpool(
        chat_service.prepare, db, user.id, model, user_input, conversation_id
    )


@router.get("/test/chat")
async def chat_once(
    model: int = Query(1, description=_MODEL_DESC),
    userInput: str = Query(..., alias="userInput"),  # noqa: N803 - 保持 Java 参数名
    conversationId: int | None = Query(None, alias="conversationId"),  # noqa: N803
    user: AuthUser = Depends(current_user),
    db: Session = Depends(get_db),
):
    """非流式：返回纯文本回答；模型异常 → 500，需确认 → 409。"""
    turn, messages = await _prepare(db, user, model, userInput, conversationId)
    answer = await chat_service.run_once(turn, messages)
    await run_in_threadpool(chat_service.finalize_now, turn, answer)
    return chat_service.plain_response(answer)


@router.get("/test/chat/stream")
async def chat_stream_plain(
    model: int = Query(1, description=_MODEL_DESC),
    userInput: str = Query(..., alias="userInput"),  # noqa: N803
    conversationId: int | None = Query(None, alias="conversationId"),  # noqa: N803
    user: AuthUser = Depends(current_user),
    db: Session = Depends(get_db),
):
    """旧纯文本流：逐块输出正文；模型异常时内联追加 `\\n\\n[错误] ...` 并继续。"""
    turn, messages = await _prepare(db, user, model, userInput, conversationId)
    return chat_service.plain_stream_response(turn, messages)


@router.get("/test/chat/stream/events")
async def chat_stream_events(
    request: Request,  # noqa: ARG001 - 仅用于 FastAPI 生命周期/断开感知，保留语义
    model: int = Query(1, description=_MODEL_DESC),
    userInput: str = Query(..., alias="userInput"),  # noqa: N803
    conversationId: int | None = Query(None, alias="conversationId"),  # noqa: N803
    user: AuthUser = Depends(current_user),
    db: Session = Depends(get_db),
):
    """前端正式使用：SSE，7 个事件逐条下发；客户端 abort 仍落库已生成内容。"""
    turn, messages = await _prepare(db, user, model, userInput, conversationId)
    return chat_service.sse_response(turn, messages)


__all__ = ["router"]
