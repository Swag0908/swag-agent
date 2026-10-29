"""短期记忆：直接从 `chat_message` 读最近 N 条（等价 Java `MessageWindowChatMemory(maxMessages=40)`）。

为什么不用 `SPRING_AI_CHAT_MEMORY` 作为读源：
- 迁移文档 §6.7 明确限制该表「必须先 DELETE 再整窗 INSERT」，Python 增量 append 会破坏 Java 的窗口；
- `chat_message` 是唯一事实来源（与前端展示同源），读它最不容易漂移。

`SPRING_AI_CHAT_MEMORY` 仍提供**整窗重写**能力（`rebuild_from_chat_messages`），
供 Java/Python 双跑期兼容；由 `settings.dual_write_chat_memory` 控制是否在每轮后自动重写。
"""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.timeutil import now, truncate_to_second
from app.db.models import ChatMessage, SpringAiChatMemory

logger = logging.getLogger(__name__)

MAX_MESSAGES = 40
_MEMORY_TYPES = {"user": "USER", "assistant": "ASSISTANT"}


def load_history(
    db: Session,
    conversation_id: int | str | None,
    max_messages: int = MAX_MESSAGES,
) -> list[dict[str, str]]:
    """按 id 升序返回最近 `max_messages` 条 [{"role","content"}]（只含 user/assistant）。"""
    if conversation_id is None:
        return []
    try:
        conv_id = int(conversation_id)
    except (TypeError, ValueError):
        return []
    limit = max(1, int(max_messages or MAX_MESSAGES))
    rows = db.execute(
        select(ChatMessage.role, ChatMessage.content)
        .where(
            ChatMessage.conversation_id == conv_id,
            ChatMessage.role.in_(tuple(_MEMORY_TYPES)),
        )
        .order_by(ChatMessage.id.desc())
        .limit(limit)
    ).all()
    history = [
        {"role": role, "content": content}
        for role, content in reversed(rows)
        if isinstance(content, str) and content.strip()
    ]
    return history


def insert_message(
    db: Session,
    conversation_id: int,
    user_id: int,
    role: str,
    content: str,
    *,
    at: datetime | None = None,
    commit: bool = True,
) -> int | None:
    """写一条 chat_message；空内容不写（对齐 Java：assistant 为空不插库）。"""
    if not content or not content.strip():
        return None
    message = ChatMessage(
        conversation_id=int(conversation_id),
        user_id=int(user_id),
        role=role,
        content=content,
        created_at=truncate_to_second(at or now()),
    )
    db.add(message)
    if commit:
        db.commit()
    else:
        db.flush()
    return int(message.id) if message.id is not None else None


def append_turn(
    db: Session,
    conversation_id: int,
    user_id: int,
    user_text: str,
    assistant_text: str,
) -> None:
    """一次追加「提问 + 回答」两条消息（供会话/导入等复用）。"""
    stamp = truncate_to_second(now())
    insert_message(db, conversation_id, user_id, "user", user_text, at=stamp, commit=False)
    insert_message(db, conversation_id, user_id, "assistant", assistant_text, at=stamp, commit=False)
    db.commit()
    if settings.dual_write_chat_memory:
        rebuild_from_chat_messages(db, conversation_id, user_id)


def rebuild_from_chat_messages(db: Session, conversation_id: int, user_id: int) -> None:
    """按剩余 chat_message 整窗重写 `SPRING_AI_CHAT_MEMORY`（最近 40 条）。

    语义与 Java `JdbcChatMemoryRepository.saveAll` 一致：先 DELETE 该会话全部行，再按
    sequence_id=0..n-1 重插；`type` 用大写枚举，`timestamp` 截断到秒。
    失败只记日志：消息本身已在 `chat_message` 中，记忆重建失败不该让调用方报错。
    """
    conv_key = str(conversation_id)
    try:
        rows = db.execute(
            select(ChatMessage.role, ChatMessage.content, ChatMessage.created_at)
            .where(
                ChatMessage.conversation_id == int(conversation_id),
                ChatMessage.role.in_(tuple(_MEMORY_TYPES)),
            )
            .order_by(ChatMessage.id)
        ).all()
        window = [row for row in rows if isinstance(row[1], str) and row[1].strip()][-MAX_MESSAGES:]
        db.execute(delete(SpringAiChatMemory).where(SpringAiChatMemory.conversation_id == conv_key))
        for sequence_id, (role, content, created_at) in enumerate(window):
            db.add(
                SpringAiChatMemory(
                    conversation_id=conv_key,
                    sequence_id=sequence_id,
                    content=content,
                    type=_MEMORY_TYPES.get(role, role.upper()),
                    timestamp=truncate_to_second(created_at) or truncate_to_second(now()),
                )
            )
        db.commit()
    except Exception:  # noqa: BLE001 - 兼容表失败不影响主链路
        db.rollback()
        logger.warning("重建 SPRING_AI_CHAT_MEMORY 失败：conversation=%s", conversation_id, exc_info=True)


def clear_memory_window(db: Session, conversation_id: int) -> None:
    """删会话时清掉短期兼容表（真实来源 chat_message 由会话模块删除）。"""
    try:
        db.execute(delete(SpringAiChatMemory).where(SpringAiChatMemory.conversation_id == str(conversation_id)))
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
        logger.warning("清理 SPRING_AI_CHAT_MEMORY 失败：conversation=%s", conversation_id, exc_info=True)


def history_length(db: Session, conversation_id: int) -> int:
    rows = db.execute(
        select(ChatMessage.id).where(ChatMessage.conversation_id == int(conversation_id))
    ).all()
    return len(rows)


__all__: list[str] = [
    "MAX_MESSAGES",
    "load_history",
    "insert_message",
    "append_turn",
    "rebuild_from_chat_messages",
    "clear_memory_window",
    "history_length",
]
