"""单轮聊天编排：会话归属、落库、消息组装、记忆读写。

等价 Java `TestController` 的私有方法组：
- `resolveConversation`（`J/contoller/TestController.java:266-279`）
- `persistUserMessage`（`:281-287`，标题 40 字，见 `:306-310`）
- `buildSystemPrompt`（`:238-256`，实现挪到 `prompt.py`）
- `memoryConversationId`（`:312-320`）
- `toolContext`（`:322-328`）
- `doFinally` 落库（`:206-224`）

落库规则（契约 §4.4）：
1. 有 `conversationId` 时，**先**写 user 消息并生成标题，再调模型；
2. 助手消息只写最终回答（`state.answer`），空则不写；
3. 无论正常/异常/客户端中断，都 `touch` 会话；
4. 落库异常只记日志，不能污染 SSE 流。

注意：`TurnContext` 只保存 `conversation_id`，不跨 session 持有 ORM 对象——
SSE 的落库发生在另一个 Session（请求 Session 可能已关闭），用 SQL UPDATE 按 id 操作最稳。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.agent import llm, prompt
from app.agent.stream.bridge import StreamFactory, TurnState, stream_turn
from app.agent.tools.registry import ToolCtx
from app.config import settings
from app.core.errors import NotFound
from app.core.timeutil import now, title_from_text, truncate_to_second
from app.db.models import ChatConversation
from app.memory import long as long_memory
from app.memory import short as short_memory

logger = logging.getLogger(__name__)


@dataclass
class TurnContext:
    user_id: int
    user_input: str
    model_id: int
    model: str
    conversation_id: int | None
    memory_key: str
    history: list[dict[str, str]] = field(default_factory=list)
    tool_ctx: ToolCtx | None = None


def resolve_conversation(db: Session, user_id: int, conversation_id: int | None) -> ChatConversation | None:
    """校验会话归属：缺省返回 None；不存在或不属于当前用户 → 404 `会话不存在`。"""
    if conversation_id is None:
        return None
    conversation = db.get(ChatConversation, int(conversation_id))
    if conversation is None or int(conversation.user_id) != int(user_id):
        raise NotFound("会话不存在")
    return conversation


def memory_conversation_id(conversation_id: int | None, user_id: int | None) -> str:
    """记忆隔离键：有会话用会话 id，否则退化为用户 id，再否则 anonymous。"""
    if conversation_id is not None:
        return str(conversation_id)
    if user_id is not None:
        return str(int(user_id))
    return "anonymous"


def _current_audit_id() -> str | None:
    try:
        from app.audit.context import current_audit_id  # noqa: PLC0415 - 可选模块
    except Exception:  # noqa: BLE001
        return None
    try:
        value = current_audit_id()
    except Exception:  # noqa: BLE001
        return None
    return str(value) if value else None


def prepare_turn(
    db: Session,
    user_id: int,
    model_id: int,
    user_input: str,
    conversation_id: int | None,
) -> TurnContext:
    """校验 + 历史预读 + 先落 user 消息（顺序与 Java 一致：先会话校验，再选模型）。"""
    conversation = resolve_conversation(db, user_id, conversation_id)
    model = llm.model_for(model_id)

    # 必须在写 user 消息之前读窗口，否则会把本轮提问重复带进上下文
    # （Java 的 advisor 读的是本轮之前的记忆，chat_message 只是展示用）。
    conv_id = conversation.id if conversation is not None else None
    history = short_memory.load_history(db, conv_id)

    if conv_id is not None:
        stamp = truncate_to_second(now())
        short_memory.insert_message(db, conv_id, user_id, "user", user_input, at=stamp)
        db.execute(
            update(ChatConversation)
            .where(
                ChatConversation.id == conv_id,
                (ChatConversation.title.is_(None)) | (ChatConversation.title == ""),
            )
            .values(title=title_from_text(user_input), updated_at=stamp)
        )
        db.execute(
            update(ChatConversation)
            .where(ChatConversation.id == conv_id)
            .values(updated_at=stamp)
        )
        db.commit()

    ctx = ToolCtx(
        user_id=int(user_id),
        audit_id=_current_audit_id(),
        conversation_id=conv_id,
        confirmation_id=None,
    )
    return TurnContext(
        user_id=int(user_id),
        user_input=user_input,
        model_id=int(model_id),
        model=model,
        conversation_id=conv_id,
        memory_key=memory_conversation_id(conv_id, user_id),
        history=history,
        tool_ctx=ctx,
    )


def build_messages(db: Session, turn: TurnContext) -> list[dict[str, Any]]:
    """[system(三段+长期记忆模板)] + 短期历史(≤40) + 当前提问。"""
    long_term = long_memory.recall_semantic(db, turn.memory_key, turn.user_input, top_k=5)
    system_prompt = prompt.build_system_prompt(
        db,
        turn.user_id,
        turn.user_input,
        long_term=long_term,
    )
    messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    messages.extend(turn.history)
    messages.append({"role": "user", "content": turn.user_input})
    return messages


def ensure_tool_ctx(turn: TurnContext) -> ToolCtx:
    if turn.tool_ctx is None:
        turn.tool_ctx = ToolCtx(
            user_id=turn.user_id,
            conversation_id=turn.conversation_id,
            audit_id=_current_audit_id(),
        )
    return turn.tool_ctx


async def run_turn_events(
    messages: list[dict[str, Any]],
    turn: TurnContext,
    *,
    state: TurnState | None = None,
    stream_factory: StreamFactory | None = None,
    on_confirmation: str = "error",
    on_error: str = "event",
):
    """薄封装：把 turn 的模型/工具上下文喂给 bridge。"""
    async for event in stream_turn(
        messages,
        turn.model,
        ensure_tool_ctx(turn),
        conversation_id=turn.conversation_id,
        stream_factory=stream_factory,
        state=state,
        on_confirmation=on_confirmation,
        on_error=on_error,
    ):
        yield event


def finalize_turn(db: Session, turn: TurnContext, answer: str) -> None:
    """收尾落库：助手最终回答 + touch 会话 + 长期向量副本（全部尽力而为）。"""
    answer = answer or ""
    if turn.conversation_id is not None:
        try:
            if answer.strip():
                short_memory.insert_message(
                    db,
                    turn.conversation_id,
                    turn.user_id,
                    "assistant",
                    answer,
                    at=truncate_to_second(now()),
                )
            db.execute(
                update(ChatConversation)
                .where(ChatConversation.id == turn.conversation_id)
                .values(updated_at=truncate_to_second(now()))
            )
            db.commit()
        except Exception:  # noqa: BLE001 - 落库失败不能污染已推完的 SSE
            db.rollback()
            logger.warning("保存本轮助手回复失败：conversation=%s", turn.conversation_id, exc_info=True)
        if settings.dual_write_chat_memory:
            try:
                short_memory.rebuild_from_chat_messages(db, turn.conversation_id, turn.user_id)
            except Exception:  # noqa: BLE001
                logger.warning("双写短期记忆失败：conversation=%s", turn.conversation_id, exc_info=True)

    # 长期语义记忆：等价 advisor 的 after 阶段（无会话时也按 userId 键写入）
    try:
        long_memory.store_turn_vectors(turn.memory_key, turn.user_input, answer)
    except Exception:  # noqa: BLE001
        logger.warning("写对话长期记忆失败（已降级）：%s", turn.memory_key, exc_info=True)


async def complete_turn(
    db: Session,
    turn: TurnContext,
    *,
    stream_factory: StreamFactory | None = None,
) -> str:
    """非流式端点用：跑完一轮工具循环，只返回最终回答。"""
    messages = build_messages(db, turn)
    state = TurnState()
    async for _event in run_turn_events(
        messages,
        turn,
        state=state,
        stream_factory=stream_factory,
        on_confirmation="raise",
        on_error="raise",
    ):
        pass
    return state.final_answer


def touch_only(db: Session, turn: TurnContext) -> None:
    """异常路径：仍刷新会话时间（Java 的 doFinally 语义）。"""
    if turn.conversation_id is None:
        return
    try:
        db.execute(
            update(ChatConversation)
            .where(ChatConversation.id == turn.conversation_id)
            .values(updated_at=truncate_to_second(now()))
        )
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
        logger.warning("刷新会话时间失败：%s", turn.conversation_id, exc_info=True)


__all__ = [
    "TurnContext",
    "resolve_conversation",
    "memory_conversation_id",
    "prepare_turn",
    "build_messages",
    "ensure_tool_ctx",
    "run_turn_events",
    "complete_turn",
    "finalize_turn",
    "touch_only",
]
