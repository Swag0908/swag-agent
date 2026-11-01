"""会话与消息的数据访问（SQLAlchemy 2.0）。

字段/排序严格对应 Java `ChatHistoryRepository`：
- 收藏置顶 → favorite_order 升序（NULL 落最后）→ updated_at 倒序 → id 倒序。
- 删除消息/会话时同时命中 user_id，避免越权。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import case, delete, func, select, update
from sqlalchemy.orm import Session

from app.db.models import ChatConversation, ChatMessage

__all__ = [
    "list_conversations",
    "get_conversation",
    "create_conversation",
    "list_messages",
    "delete_conversation",
    "delete_all_conversations",
    "max_favorite_order",
    "set_favorite",
    "reorder_favorites",
    "delete_messages",
]

# Java 端用 int 最大值把「未收藏/未排序」排到最后。
_ORDER_LAST = 2147483647


def list_conversations(db: Session, user_id: int) -> list[ChatConversation]:
    """查询当前用户会话：收藏优先，再按收藏顺序、更新时间和编号排序。"""
    stmt = (
        select(ChatConversation)
        .where(ChatConversation.user_id == user_id)
        .order_by(
            ChatConversation.favorite.desc(),
            case(
                (ChatConversation.favorite_order.is_(None), _ORDER_LAST),
                else_=ChatConversation.favorite_order,
            ).asc(),
            ChatConversation.updated_at.desc(),
            ChatConversation.id.desc(),
        )
    )
    return list(db.scalars(stmt).all())


def get_conversation(db: Session, conversation_id: int, user_id: int) -> ChatConversation | None:
    """按会话编号和用户编号共同查询，避免读到其他人的会话。"""
    return db.scalar(
        select(ChatConversation).where(
            ChatConversation.id == conversation_id,
            ChatConversation.user_id == user_id,
        )
    )


def create_conversation(db: Session, user_id: int, title: str, now: datetime) -> ChatConversation:
    """插入会话并提交，刷新后返回包含数据库生成编号的对象。"""
    conversation = ChatConversation(
        user_id=user_id,
        title=title or "",
        created_at=now,
        updated_at=now,
        favorite=False,
        favorite_note=None,
        favorite_order=None,
        favorited_at=None,
    )
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation


def list_messages(db: Session, conversation_id: int) -> list[ChatMessage]:
    """按编号顺序读取会话消息；调用方必须先检查会话归属。"""
    return list(
        db.scalars(
            select(ChatMessage).where(ChatMessage.conversation_id == conversation_id).order_by(ChatMessage.id)
        ).all()
    )


def delete_conversation(db: Session, conversation_id: int, user_id: int) -> bool:
    """验证归属后删除消息与会话并提交；不存在或越权返回 False。"""
    conversation = get_conversation(db, conversation_id, user_id)
    if conversation is None:
        return False
    db.execute(
        delete(ChatMessage).where(
            ChatMessage.conversation_id == conversation_id,
            ChatMessage.user_id == user_id,
        )
    )
    db.delete(conversation)
    db.commit()
    return True


def delete_all_conversations(db: Session, user_id: int) -> list[int]:
    """删除该用户全部会话与消息，返回被删除的会话编号用于清理副本。"""
    ids = list(
        db.scalars(
            select(ChatConversation.id).where(ChatConversation.user_id == user_id).order_by(ChatConversation.id)
        ).all()
    )
    if not ids:
        return ids
    db.execute(delete(ChatMessage).where(ChatMessage.user_id == user_id))
    db.execute(delete(ChatConversation).where(ChatConversation.user_id == user_id))
    db.commit()
    return ids


def max_favorite_order(db: Session, user_id: int) -> int:
    value = db.scalar(
        select(func.max(ChatConversation.favorite_order)).where(
            ChatConversation.user_id == user_id,
            ChatConversation.favorite.is_(True),
        )
    )
    return -1 if value is None else int(value)


def set_favorite(
    db: Session,
    conversation_id: int,
    user_id: int,
    favorite: bool,
    note: str | None,
    favorite_order: int | None,
    now: datetime,
) -> bool:
    """写入收藏状态并提交；重复收藏保留首次收藏时间。"""
    conversation = get_conversation(db, conversation_id, user_id)
    if conversation is None:
        return False
    if favorite:
        conversation.favorite = True
        conversation.favorite_note = note
        conversation.favorite_order = favorite_order
        # Java: favorited_at = COALESCE(favorited_at, now)，重复收藏不改首次收藏时间。
        conversation.favorited_at = conversation.favorited_at or now
    else:
        conversation.favorite = False
        conversation.favorite_note = None
        conversation.favorite_order = None
        conversation.favorited_at = None
    db.commit()
    return True


def reorder_favorites(db: Session, user_id: int, ordered_ids: list[int] | None) -> None:
    """仅更新属于当前用户且已收藏的会话，不接受借排序修改他人记录。"""
    if not ordered_ids:
        return
    for index, conversation_id in enumerate(ordered_ids):
        db.execute(
            update(ChatConversation)
            .where(
                ChatConversation.id == conversation_id,
                ChatConversation.user_id == user_id,
                ChatConversation.favorite.is_(True),
            )
            .values(favorite_order=index)
        )
    db.commit()


def delete_messages(db: Session, conversation_id: int, user_id: int, message_ids: list[int]) -> int:
    """同时限定会话、用户和消息编号执行删除并提交，返回删除数量。"""
    if not message_ids:
        return 0
    result = db.execute(
        delete(ChatMessage).where(
            ChatMessage.conversation_id == conversation_id,
            ChatMessage.user_id == user_id,
            ChatMessage.id.in_(message_ids),
        )
    )
    db.commit()
    return int(result.rowcount or 0)
