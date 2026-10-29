"""用户长期记忆（ChatGPT Memory 式）：等价 Java `UserMemoryService`
（`J/memory/UserMemoryService.java`）。

- 本体在 MySQL：`chat_user_memory` + 用户级开关 `chat_user_memory_setting`（缺省=开启）。
- 向量副本在 PG：`public.chat_user_memory_vec`（768 维，无索引，`memory_id` = MySQL 主键）。
- 召回 topK=5；向量链路（Ollama/PG）异常时**降级为最近 N 条文本**，功能不整体失效。
- 单条内容压缩空白后最多 300 字（超出加 `…`）。
- 跨库无事务：先写 MySQL 并提交，再尽力写 PG；PG 失败只告警。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.errors import NotFound
from app.core.timeutil import epoch_ms, now, truncate_to_second
from app.db.models import ChatUserMemory, ChatUserMemorySetting
from app.db.pg import pg_connection
from app.memory import long as long_memory

logger = logging.getLogger(__name__)

DEFAULT_TOP_K = 5
MAX_CONTENT_LENGTH = 300

_VEC_UPSERT_SQL = text(
    "INSERT INTO public.chat_user_memory_vec (memory_id, user_id, content, embedding) "
    "VALUES (:memory_id, :user_id, :content, CAST(:embedding AS vector)) "
    "ON CONFLICT (memory_id) DO UPDATE "
    "SET content = EXCLUDED.content, embedding = EXCLUDED.embedding"
)
_VEC_SEARCH_SQL = text(
    "SELECT content FROM public.chat_user_memory_vec "
    "WHERE user_id = :user_id "
    "ORDER BY embedding <=> CAST(:embedding AS vector) "
    "LIMIT :top_k"
)
_VEC_DELETE_SQL = text("DELETE FROM public.chat_user_memory_vec WHERE memory_id = :memory_id")


# ---------------------------------------------------------------------------
# 读写
# ---------------------------------------------------------------------------


def normalize_content(raw: str | None) -> str:
    flat = " ".join((raw or "").split())
    if len(flat) <= MAX_CONTENT_LENGTH:
        return flat
    return flat[:MAX_CONTENT_LENGTH] + "…"


def list_items(db: Session, user_id: int) -> list[ChatUserMemory]:
    return list(
        db.execute(
            select(ChatUserMemory)
            .where(ChatUserMemory.user_id == int(user_id))
            .order_by(ChatUserMemory.updated_at.desc(), ChatUserMemory.id.desc())
        )
        .scalars()
        .all()
    )


def is_enabled(db: Session, user_id: int | None) -> bool:
    """开关缺省视为开启（新用户没有设置行时返回 True）。"""
    if user_id is None:
        return False
    row = db.get(ChatUserMemorySetting, int(user_id))
    return True if row is None else bool(row.enabled)


def set_enabled(db: Session, user_id: int, enabled: bool) -> None:
    user_id = int(user_id)
    row = db.get(ChatUserMemorySetting, user_id)
    stamp = truncate_to_second(now())
    if row is None:
        db.add(ChatUserMemorySetting(user_id=user_id, enabled=bool(enabled), updated_at=stamp))
    else:
        row.enabled = bool(enabled)
        row.updated_at = stamp
    db.commit()


def get_panel(db: Session, user_id: int) -> dict[str, Any]:
    """`GET /chat/user-memory` 的 payload：{enabled, items:[{id,content,createdAtMs}]}。"""
    items = [
        {"id": int(memory.id), "content": memory.content, "createdAtMs": epoch_ms(memory.created_at)}
        for memory in list_items(db, user_id)
    ]
    return {"enabled": is_enabled(db, user_id), "items": items}


def delete_memory(db: Session, user_id: int, memory_id: int) -> None:
    """删一条记忆：先删 MySQL（不存在→404），再尽力删 PG 向量。"""
    user_id = int(user_id)
    memory_id = int(memory_id)
    memory = db.execute(
        select(ChatUserMemory).where(
            ChatUserMemory.id == memory_id,
            ChatUserMemory.user_id == user_id,
        )
    ).scalar_one_or_none()
    if memory is None:
        raise NotFound("记忆不存在")
    db.delete(memory)
    db.commit()
    try:
        with pg_connection() as conn:
            conn.execute(_VEC_DELETE_SQL, {"memory_id": memory_id})
            conn.commit()
    except Exception as exc:  # noqa: BLE001 - PG 失败只告警
        logger.warning("删除用户 %s 记忆向量失败：%s", user_id, exc)


# ---------------------------------------------------------------------------
# 召回 / 保存
# ---------------------------------------------------------------------------


def _recent_contents(db: Session, user_id: int, top_k: int) -> list[str]:
    """降级路径：本体内最近 N 条（含向量化失败的记忆）。"""
    rows = db.execute(
        select(ChatUserMemory.content)
        .where(ChatUserMemory.user_id == int(user_id))
        .order_by(ChatUserMemory.updated_at.desc(), ChatUserMemory.id.desc())
        .limit(max(1, int(top_k)))
    ).all()
    return [row[0] for row in rows if isinstance(row[0], str) and row[0].strip()]


def recall(db: Session, user_id: int | None, query: str, top_k: int = DEFAULT_TOP_K) -> list[str]:
    """按提问语义召回 topK 条；向量失败或为空时降级最近 N 条。"""
    if user_id is None or not is_enabled(db, user_id):
        return []
    k = max(1, int(top_k or DEFAULT_TOP_K))
    contents: list[str] = []
    try:
        embedding = long_memory.embed_sync(query or "")
        if embedding is not None:
            with pg_connection() as conn:
                rows = conn.execute(
                    _VEC_SEARCH_SQL,
                    {
                        "user_id": int(user_id),
                        "embedding": long_memory.vector_literal(embedding),
                        "top_k": k,
                    },
                ).fetchall()
            contents = [row[0] for row in rows if isinstance(row[0], str) and row[0].strip()]
    except Exception as exc:  # noqa: BLE001 - 向量链路异常走降级
        logger.warning("用户 %s 记忆向量召回失败，降级最近记忆：%s", user_id, exc)
    if contents:
        return contents
    return _recent_contents(db, user_id, k)


class IllegalStateError(RuntimeError):
    """Java `IllegalStateException` 的等价物（长期记忆关闭时抛）。"""


async def remember(db: Session, user_id: int, content: str) -> str:
    """保存一条精炼事实；向量副本尽力同步（失败仅降级，不影响本体）。"""
    user_id = int(user_id)
    if not is_enabled(db, user_id):
        raise IllegalStateError("长期记忆功能当前处于关闭状态，请先在「我的记忆」中开启")
    normalized = normalize_content(content)
    if not normalized:
        raise ValueError("记忆内容不能为空")
    stamp = truncate_to_second(now())
    memory = ChatUserMemory(
        user_id=user_id,
        content=normalized,
        created_at=stamp,
        updated_at=stamp,
    )
    db.add(memory)
    db.commit()
    db.refresh(memory)
    await _save_vector(int(memory.id), user_id, normalized)
    return normalized


async def _save_vector(memory_id: int, user_id: int, content: str) -> None:
    try:
        embedding = await long_memory.embed_async(content)
        if embedding is None:
            return
        with pg_connection() as conn:
            conn.execute(
                _VEC_UPSERT_SQL,
                {
                    "memory_id": memory_id,
                    "user_id": user_id,
                    "content": content,
                    "embedding": long_memory.vector_literal(embedding),
                },
            )
            conn.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("用户 %s 记忆向量化失败（将回退最近记忆注入）：%s", user_id, exc)


# ---------------------------------------------------------------------------
# 重建（实现放 rebuild.py，这里按契约暴露同名函数）
# ---------------------------------------------------------------------------


def rebuild_memory(db: Session, conversation_id: int, user_id: int) -> None:
    from app.memory.rebuild import rebuild_conversation_memory  # noqa: PLC0415 - 避免循环导入

    rebuild_conversation_memory(db, conversation_id, user_id)


def created_at_ms(memory: ChatUserMemory) -> int:
    return epoch_ms(memory.created_at)


__all__ = [
    "DEFAULT_TOP_K",
    "MAX_CONTENT_LENGTH",
    "IllegalStateError",
    "normalize_content",
    "list_items",
    "is_enabled",
    "set_enabled",
    "get_panel",
    "delete_memory",
    "recall",
    "remember",
    "rebuild_memory",
]
