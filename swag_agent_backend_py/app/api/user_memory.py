"""用户长期记忆 REST：/chat/user-memory/*（3 个端点）。

优先委托 chat-core 的 `app.memory.user_memory`（get_panel / set_enabled / delete_memory）。
该模块尚未落地时使用本地 ORM 降级实现（语义与 Java UserMemoryController 一致），
保证本文件可独立导入、路由可用；chat-core 到位后自动切换为正式实现。
"""

from __future__ import annotations

import logging
from types import ModuleType

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.core.errors import NotFound
from app.core.timeutil import epoch_ms, now, truncate_to_second
from app.db.base import get_db
from app.db.models import ChatUserMemory, ChatUserMemorySetting

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat/user-memory", tags=["user-memory"])


class SettingsRequest(BaseModel):
    # Java record 是基本类型 boolean：缺省字段按 false 处理。
    enabled: bool = False


def _memory_module() -> ModuleType | None:
    """chat-core 的用户记忆模块；不存在时返回 None（本地降级）。"""
    try:
        from app.memory import user_memory as module  # type: ignore[import-not-found]

        return module
    except ImportError:
        logger.debug("app.memory.user_memory 尚未提供，使用本地降级实现")
        return None


# ---------------------------------------------------------------------------
# 本地降级实现（chat-core 未落地时）
# ---------------------------------------------------------------------------


def _local_is_enabled(db: Session, user_id: int) -> bool:
    row = db.get(ChatUserMemorySetting, user_id)
    return True if row is None else bool(row.enabled)


def _local_get_panel(db: Session, user_id: int) -> dict:
    rows = db.scalars(
        select(ChatUserMemory)
        .where(ChatUserMemory.user_id == user_id)
        .order_by(ChatUserMemory.updated_at.desc(), ChatUserMemory.id.desc())
    ).all()
    return {
        "enabled": _local_is_enabled(db, user_id),
        "items": [
            {"id": row.id, "content": row.content, "createdAtMs": epoch_ms(row.created_at)} for row in rows
        ],
    }


def _local_set_enabled(db: Session, user_id: int, enabled: bool) -> None:
    updated_at = truncate_to_second(now())
    row = db.get(ChatUserMemorySetting, user_id)
    if row is None:
        db.add(ChatUserMemorySetting(user_id=user_id, enabled=bool(enabled), updated_at=updated_at))
    else:
        row.enabled = bool(enabled)
        row.updated_at = updated_at
    db.commit()


# ---------------------------------------------------------------------------
# 端点
# ---------------------------------------------------------------------------


def _memory_exists(db: Session, user_id: int, memory_id: int) -> bool:
    return (
        db.scalar(
            select(ChatUserMemory.id).where(
                ChatUserMemory.id == memory_id,
                ChatUserMemory.user_id == user_id,
            )
        )
        is not None
    )


@router.get("")
def get_user_memory(user=Depends(current_user), db: Session = Depends(get_db)) -> dict:
    module = _memory_module()
    if module is not None:
        return module.get_panel(db, user.id)
    return _local_get_panel(db, user.id)


@router.put("/settings")
def update_settings(
    body: SettingsRequest, user=Depends(current_user), db: Session = Depends(get_db)
) -> Response:
    module = _memory_module()
    if module is not None:
        module.set_enabled(db, user.id, bool(body.enabled))
    else:
        _local_set_enabled(db, user.id, bool(body.enabled))
    return Response(status_code=200)


@router.delete("/{memory_id}")
def delete_user_memory(
    memory_id: int, user=Depends(current_user), db: Session = Depends(get_db)
) -> Response:
    # 先判归属，保证「记忆不存在」返回 404（Java 语义），也避免依赖 chat-core 的返回值约定。
    if not _memory_exists(db, user.id, memory_id):
        raise NotFound("记忆不存在")

    module = _memory_module()
    if module is not None:
        module.delete_memory(db, user.id, memory_id)
    else:
        db.execute(
            delete(ChatUserMemory).where(
                ChatUserMemory.id == memory_id,
                ChatUserMemory.user_id == user.id,
            )
        )
        db.commit()
    return Response(status_code=200)
