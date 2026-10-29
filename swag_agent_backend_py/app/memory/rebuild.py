"""记忆重建：对应 Java `ChatConversationService` 的删消息/删会话后重建逻辑
（`J/chat/ChatConversationService.java:137-201`）。

Java 的规则：两层记忆都是「先清空再重放」，比按内容精确删单条更可靠
（向量文档 id 是随机 UUID，没有与 `chat_message.id` 建立映射）。
- 短期：整窗重写 `SPRING_AI_CHAT_MEMORY`（最近 40 条）；
- 长期：删除该 `conversationId` 的全部 `vector_store` 文档，再按剩余消息重放。

失败只记日志：消息本身已经删/改成功，记忆重建失败不应该让删除操作看起来失败。
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ChatMessage
from app.memory import long as long_memory
from app.memory import short as short_memory

logger = logging.getLogger(__name__)

_MEMORY_ROLES = ("user", "assistant")


def _conversation_messages(db: Session, conversation_id: int) -> list[dict[str, str]]:
    rows = db.execute(
        select(ChatMessage.role, ChatMessage.content)
        .where(
            ChatMessage.conversation_id == int(conversation_id),
            ChatMessage.role.in_(_MEMORY_ROLES),
        )
        .order_by(ChatMessage.id)
    ).all()
    return [
        {"role": role, "content": content}
        for role, content in rows
        if isinstance(content, str) and content.strip()
    ]


def rebuild_conversation_memory(db: Session, conversation_id: int, user_id: int) -> None:
    """按剩余消息重建短期（兼容表）与长期（向量）两层记忆。"""
    messages = _conversation_messages(db, conversation_id)
    try:
        short_memory.rebuild_from_chat_messages(db, conversation_id, user_id)
    except Exception:  # noqa: BLE001
        logger.warning("重建短期记忆失败：conversation=%s", conversation_id, exc_info=True)
    try:
        long_memory.rebuild_conversation_vectors(str(conversation_id), messages[-short_memory.MAX_MESSAGES :])
    except Exception:  # noqa: BLE001
        logger.warning("重建长期记忆失败：conversation=%s", conversation_id, exc_info=True)


def clear_conversation_memory(db: Session, conversation_id: int) -> None:
    """删会话时清两层记忆（MySQL 历史由会话模块负责删除）。"""
    try:
        short_memory.clear_memory_window(db, conversation_id)
    except Exception:  # noqa: BLE001
        logger.warning("清理短期记忆失败：conversation=%s", conversation_id, exc_info=True)
    try:
        long_memory.delete_conversation_vectors(str(conversation_id))
    except Exception:  # noqa: BLE001
        logger.warning("清理长期记忆失败：conversation=%s", conversation_id, exc_info=True)


def rebuild_memory(db: Session, conversation_id: int, user_id: int) -> None:
    """契约别名（CONTRACTS §2 使用 `rebuild_memory` 这个名字）。"""
    rebuild_conversation_memory(db, conversation_id, user_id)


__all__ = ["rebuild_conversation_memory", "rebuild_memory", "clear_conversation_memory"]
