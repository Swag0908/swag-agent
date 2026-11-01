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
    """手动新增待办的表单字段，日期和时间先作为文本接收。"""
    title: str | None = None
    note: str | None = None
    dueDate: str | None = None
    dueTime: str | None = None


class UpdateRequest(BaseModel):
    """修改待办时提交的完整业务字段，合法性由服务层检查。"""
    title: str | None = None
    note: str | None = None
    dueDate: str | None = None
    dueTime: str | None = None


class DeferRequest(BaseModel):
    """延期请求体，newDate 支持约定的日期文本。"""
    newDate: str | None = None


def _required_date(value: str | None, message: str):
    """解析必须提供的日期，缺失或无法得到日期时返回业务错误。"""
    parsed = service.parse_date(value, None)
    if parsed is None:
        raise BadRequest(message)
    return parsed


@router.get("/today")
def today(user: AuthUser = Depends(current_user), db: Session = Depends(get_db)) -> list[dict]:
    """先补齐昨天的统计，再返回当前用户今天的待办。"""
    rollover.ensure_settled(db, user.id)
    return [views.item_to_dict(item) for item in service.list_today(db, user.id)]


@router.post("")
def create(
    body: CreateRequest,
    user: AuthUser = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    """从页面表单创建待办；请求来源标记与聊天工具创建作区分。"""
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
    """解析日期范围并查询当前用户待办，输出统一的前端字段。"""
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
    """把路径中的待办编号及完整编辑内容交给业务层修改。"""
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
    """将自己的待办标记完成，返回修改后的条目。"""
    return views.item_to_dict(service.complete(db, user.id, str(item_id)))


@router.patch("/{item_id}/defer")
def defer(
    item_id: int,
    body: DeferRequest,
    user: AuthUser = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    """将自己的待办延期；没有给出新日期时默认明天。"""
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
    """删除自己的待办，成功返回空响应。"""
    service.delete(db, user.id, str(item_id))
    return Response(status_code=200)


@router.get("/stats/daily")
def stats(
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = Query(default=None),
    user: AuthUser = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    """查询日统计；缺省读取截至今天的七天范围，并补齐历史结算。"""
    rollover.ensure_settled(db, user.id)
    to_date = service.parse_date(to, timeutil.today())
    from_date = service.parse_date(from_, to_date - timedelta(days=6))
    return [views.stat_to_dict(stat) for stat in service.stats(db, user.id, from_date, to_date)]
