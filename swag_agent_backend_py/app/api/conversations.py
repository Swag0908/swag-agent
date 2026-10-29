"""会话历史 REST：/chat/conversations/*（8 个端点）。

字段/排序/收藏/404 语义严格对齐 Java `ChatConversationController`；
所有时间字段输出 epoch 毫秒。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.db.base import get_db
from app.domains.chat import service

router = APIRouter(prefix="/chat/conversations", tags=["conversations"])


class CreateRequest(BaseModel):
    title: str | None = None


class FavoriteRequest(BaseModel):
    favorite: bool | None = None
    note: str | None = None


class FavoriteOrderRequest(BaseModel):
    ids: list[int] | None = None


@router.get("")
def list_conversations(user=Depends(current_user), db: Session = Depends(get_db)) -> list[dict]:
    return service.list_conversations(db, user.id)


@router.post("")
def create_conversation(
    body: CreateRequest | None = None,
    user=Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    title = body.title if body is not None else None
    return service.create_conversation(db, user.id, title)


@router.delete("")
def clear_conversations(user=Depends(current_user), db: Session = Depends(get_db)) -> dict:
    return service.clear_all(db, user.id)


# 静态路径先声明，再声明 /{conversation_id}/... 动态段（保持与 Java 相同的匹配结果）。
@router.put("/favorites/order")
def reorder_favorites(
    body: FavoriteOrderRequest | None = None,
    user=Depends(current_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    ids = body.ids if body is not None else None
    return service.reorder_favorites(db, user.id, ids)


@router.get("/{conversation_id}/messages")
def list_messages(
    conversation_id: int, user=Depends(current_user), db: Session = Depends(get_db)
) -> list[dict]:
    return service.list_messages(db, user.id, conversation_id)


@router.delete("/{conversation_id}")
def delete_conversation(
    conversation_id: int, user=Depends(current_user), db: Session = Depends(get_db)
) -> Response:
    service.delete_conversation(db, user.id, conversation_id)
    return Response(status_code=200)


@router.put("/{conversation_id}/favorite")
def set_favorite(
    conversation_id: int,
    body: FavoriteRequest | None = None,
    user=Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    favorite = body.favorite if body is not None else None
    note = body.note if body is not None else None
    return service.set_favorite(db, user.id, conversation_id, favorite, note)


@router.delete("/{conversation_id}/messages/{message_id}")
def delete_message(
    conversation_id: int,
    message_id: int,
    user=Depends(current_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    return service.delete_message_pair(db, user.id, conversation_id, message_id)
