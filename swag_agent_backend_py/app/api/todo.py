"""待办与统计 REST 端点：/todo*（8 个）。字段/状态码/文案对齐 Java `TodoController`。"""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.core import timeutil
from app.core.errors import BadRequest
from app.db.base import get_db
from app.domains.auth.service import AuthUser
from app.domains.todo import rollover, service, views

router = APIRouter(prefix="/todo", tags=["todo"])


class CreateRequest(BaseModel):
    title: str | None = None
    note: str | None = None
    dueDate: str | None = None
    dueTime: str | None = None


class UpdateRequest(BaseModel):
    title: str | None = None
    note: str | None = None
    dueDate: str | None = None
    dueTime: str | None = None


class DeferRequest(BaseModel):
    newDate: str | None = None


def _required_date(value: str | None, message: str):
    parsed = service.parse_date(value, None)
    if parsed is None:
        raise BadRequest(message)
    return parsed


@router.get("/today")
def today(user: AuthUser = Depends(current_user), db: Session = Depends(get_db)) -> list[dict]:
    rollover.ensure_settled(db, user.id)
    return [views.item_to_dict(item) for item in service.list_today(db, user.id)]


@router.post("")
def create(
    body: CreateRequest,
    user: AuthUser = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    item = service.create(
        db,
        user.id,
        body.title,
        body.note,
        service.parse_date(body.dueDate, timeutil.today()),
        service.parse_time(body.dueTime),
        "MANUAL",
    )
    return views.item_to_dict(item)


@router.get("")
def range_items(
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = Query(default=None),
    user: AuthUser = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    start = _required_date(from_, "请提供开始日期")
    end = _required_date(to, "请提供结束日期")
    items = service.list_by_date_range(db, user.id, start, end)
    return [views.item_to_dict(item) for item in items]


@router.patch("/{item_id}")
def update(
    item_id: int,
    body: UpdateRequest,
    user: AuthUser = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    item = service.update(
        db,
        user.id,
        str(item_id),
        body.title,
        body.note,
        _required_date(body.dueDate, "请选择待办日期"),
        service.parse_time(body.dueTime),
    )
    return views.item_to_dict(item)


@router.patch("/{item_id}/complete")
def complete(
    item_id: int,
    user: AuthUser = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    return views.item_to_dict(service.complete(db, user.id, str(item_id)))


@router.patch("/{item_id}/defer")
def defer(
    item_id: int,
    body: DeferRequest,
    user: AuthUser = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    item = service.defer(
        db,
        user.id,
        str(item_id),
        service.parse_date(body.newDate, timeutil.today() + timedelta(days=1)),
    )
    return views.item_to_dict(item)


@router.delete("/{item_id}")
def delete(
    item_id: int,
    user: AuthUser = Depends(current_user),
    db: Session = Depends(get_db),
) -> Response:
    service.delete(db, user.id, str(item_id))
    return Response(status_code=200)


@router.get("/stats/daily")
def stats(
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = Query(default=None),
    user: AuthUser = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    rollover.ensure_settled(db, user.id)
    to_date = service.parse_date(to, timeutil.today())
    from_date = service.parse_date(from_, to_date - timedelta(days=6))
    return [views.stat_to_dict(stat) for stat in service.stats(db, user.id, from_date, to_date)]
