"""会话历史领域服务。

对齐 Java `ChatConversationController` / `ChatConversationService`：
- 列表排序、收藏/备注/排序号、标题、epoch 毫秒输出；
- 删除单条消息时「提问 + 紧随回答」成对删除；
- 删除会话/清空/删消息后调用 chat-core 的 `rebuild_memory(db, conversation_id, user_id)`。
  chat-core 尚未落地时降级为 no-op（只记日志），不阻断会话删除。
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.errors import BadRequest, NotFound
from app.core.timeutil import epoch_ms, now, truncate_to_second
from app.db.models import AuditEvent, AuditPayload, ChatConversation, ChatMessage
from app.domains.chat import repository

logger = logging.getLogger(__name__)

__all__ = [
    "conversation_response",
    "message_response",
    "list_conversations",
    "create_conversation",
    "list_messages",
    "delete_conversation",
    "clear_all",
    "set_favorite",
    "reorder_favorites",
    "delete_message_pair",
    "paired_message_ids",
    "normalize_note",
]

_REBUILD_MEMORY: Callable[[Session, int, int], None] | None = None
_REBUILD_IMPORT_ATTEMPTED = False


def _load_rebuild_memory() -> Callable[[Session, int, int], None] | None:
    """按 chat-core 约定的位置查找记忆重建函数（不存在则返回 None）。

    任务约定 `app.memory.rebuild.rebuild_memory`；CONTRACTS 同时把同名函数列在
    `app.memory.user_memory` 下，两处都尝试，先命中先用。
    """
    global _REBUILD_MEMORY, _REBUILD_IMPORT_ATTEMPTED
    if _REBUILD_IMPORT_ATTEMPTED:
        return _REBUILD_MEMORY
    _REBUILD_IMPORT_ATTEMPTED = True
    try:
        from app.memory.rebuild import rebuild_memory  # type: ignore[import-not-found]

        _REBUILD_MEMORY = rebuild_memory
        return _REBUILD_MEMORY
    except ImportError:
        pass
    try:
        from app.memory.user_memory import rebuild_memory  # type: ignore[import-not-found]

        _REBUILD_MEMORY = rebuild_memory
        return _REBUILD_MEMORY
    except ImportError:
        # TODO(chat-core): app/memory/rebuild.py 落地后此分支自然失效；
        # 若最终函数名/参数变化，需要同步更新这里的两个 import 路径。
        logger.debug("chat-core 的 rebuild_memory 尚未提供，会话删除暂不重建记忆")
        return None


def _rebuild_memory_safely(db: Session, conversation_id: int, user_id: int) -> None:
    """删除历史后尝试同步记忆副本；重建失败只记日志，不撤销历史删除。"""
    rebuild = _load_rebuild_memory()
    if rebuild is None:
        return
    try:
        rebuild(db, conversation_id, user_id)
    except Exception:  # noqa: BLE001 - 记忆重建失败不能影响已成功的删除操作
        logger.warning("会话 %s 的记忆重建失败（已忽略）", conversation_id, exc_info=True)


def conversation_response(conversation: ChatConversation) -> dict:
    """将会话对象转成前端字段，时间统一为毫秒时间戳。"""
    return {
        "id": conversation.id,
        "title": conversation.title or "",
        "favorite": bool(conversation.favorite),
        "favoriteNote": conversation.favorite_note,
        "favoriteOrder": conversation.favorite_order,
        # Java：null 时间统一输出 0，前端按本地日期分组。
        "favoritedAtMs": epoch_ms(conversation.favorited_at),
        "createdAtMs": epoch_ms(conversation.created_at),
        "updatedAtMs": epoch_ms(conversation.updated_at),
    }


def message_response(message: ChatMessage) -> dict:
    """将一条消息转成前端展示字段。"""
    return {"id": message.id, "role": message.role, "content": message.content}


def _now_second() -> datetime:
    # chat_* 表是 DATETIME(0)，写前截断微秒。
    return truncate_to_second(now()) or now()


def list_conversations(db: Session, user_id: int) -> list[dict]:
    """只列出当前用户的会话，排序交给数据访问层。"""
    return [conversation_response(row) for row in repository.list_conversations(db, user_id)]


def create_conversation(db: Session, user_id: int, title: str | None) -> dict:
    """先创建空会话目录；发送首条提问时可自动生成标题。"""
    conversation = repository.create_conversation(db, user_id, title or "", _now_second())
    return conversation_response(conversation)


def _require_conversation(db: Session, user_id: int, conversation_id: int) -> ChatConversation:
    """同时检查存在性和用户归属，越权与不存在统一返回“会话不存在”。"""
    conversation = repository.get_conversation(db, conversation_id, user_id)
    if conversation is None:
        raise NotFound("会话不存在")
    return conversation


def list_messages(db: Session, user_id: int, conversation_id: int) -> list[dict]:
    """先确认会话属于当前用户，再按顺序返回其中的消息。"""
    _require_conversation(db, user_id, conversation_id)
    return [message_response(row) for row in repository.list_messages(db, conversation_id)]


def _delete_audit_events(db: Session, conversation_id: int) -> None:
    """等价 Java AuditConversationRepository.deleteByConversationId。失败只记日志。"""
    try:
        conversation_key = str(conversation_id)
        audit_ids = select(AuditEvent.audit_id).where(AuditEvent.conversation_id == conversation_key)
        db.execute(delete(AuditPayload).where(AuditPayload.audit_id.in_(audit_ids)))
        db.execute(delete(AuditEvent).where(AuditEvent.conversation_id == conversation_key))
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
        logger.warning("会话 %s 的审计记录清理失败", conversation_id, exc_info=True)


def delete_conversation(db: Session, user_id: int, conversation_id: int) -> None:
    """删除自己的会话和正文，再尽力清理对应记忆及审计记录。"""
    if not repository.delete_conversation(db, conversation_id, user_id):
        raise NotFound("会话不存在")
    # 删除后记忆应从「空历史」重建（等价 Java clearAssistantMemory）。
    _rebuild_memory_safely(db, conversation_id, user_id)
    _delete_audit_events(db, conversation_id)


def clear_all(db: Session, user_id: int) -> dict:
    """删除当前用户全部会话，并逐个清理记忆和审计副本。"""
    deleted_ids = repository.delete_all_conversations(db, user_id)
    for conversation_id in deleted_ids:
        _rebuild_memory_safely(db, conversation_id, user_id)
        _delete_audit_events(db, conversation_id)
    return {"deleted": len(deleted_ids)}


def normalize_note(note: str | None) -> str | None:
    """Java：null 保持 null；trim 后空串归 null；超 120 字截断。"""
    if note is None:
        return None
    trimmed = note.strip()
    if not trimmed:
        return None
    return trimmed if len(trimmed) <= 120 else trimmed[:120]


def _resolve_favorite_order(db: Session, user_id: int, conversation: ChatConversation) -> int:
    if conversation.favorite and conversation.favorite_order is not None:
        return int(conversation.favorite_order)
    return repository.max_favorite_order(db, user_id) + 1


def set_favorite(
    db: Session, user_id: int, conversation_id: int, favorite: bool | None, note: str | None
) -> dict:
    """保存收藏开关、备注和顺序；取消收藏时清空收藏相关信息。"""
    if favorite is None:
        raise BadRequest("缺少 favorite 参数")
    conversation = _require_conversation(db, user_id, conversation_id)
    normalized_note = normalize_note(note)
    favorite_order = _resolve_favorite_order(db, user_id, conversation) if favorite else None
    if not repository.set_favorite(
        db,
        conversation_id,
        user_id,
        bool(favorite),
        normalized_note,
        favorite_order,
        _now_second(),
    ):
        raise NotFound("会话不存在")
    refreshed = _require_conversation(db, user_id, conversation_id)
    return conversation_response(refreshed)


def reorder_favorites(db: Session, user_id: int, ordered_ids: Sequence[int] | None) -> list[dict]:
    """更新当前用户已有收藏的顺序，再返回会话列表。"""
    repository.reorder_favorites(db, user_id, list(ordered_ids) if ordered_ids else None)
    return list_conversations(db, user_id)


def paired_message_ids(messages: Sequence[ChatMessage], index: int) -> list[int]:
    """与目标消息配对的 id 集合（Java ChatConversationService.pairedMessageIds）。

    目标是提问 → 带上紧随其后的回答；目标是回答 → 带上紧邻的提问。
    """
    ids = [messages[index].id]
    if messages[index].role == "user":
        if index + 1 < len(messages) and messages[index + 1].role == "assistant":
            ids.append(messages[index + 1].id)
    elif index > 0 and messages[index - 1].role == "user":
        ids.append(messages[index - 1].id)
    return ids


def delete_message_pair(db: Session, user_id: int, conversation_id: int, message_id: int) -> list[dict]:
    """删除目标消息及相邻配对的提问/回答，然后从剩余历史重建记忆。"""
    _require_conversation(db, user_id, conversation_id)
    messages = repository.list_messages(db, conversation_id)
    index = next((i for i, message in enumerate(messages) if message.id == message_id), -1)
    if index < 0:
        raise NotFound("消息不存在")

    pair_ids = paired_message_ids(messages, index)
    deleted = repository.delete_messages(db, conversation_id, user_id, pair_ids)
    if deleted == 0:
        raise NotFound("消息不存在或不属于当前用户")

    # chat-core 的 rebuild_memory 从数据库剩余消息重建短期/向量记忆。
    _rebuild_memory_safely(db, conversation_id, user_id)
    removed = set(pair_ids)
    return [message_response(message) for message in messages if message.id not in removed]
