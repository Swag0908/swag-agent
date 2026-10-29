"""Zipkin 访问票据校验入口（nginx auth_request 使用）。

公开路径，但只认 HttpOnly Cookie；204 放行 / 401 未登录 / 403 非管理员。
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy.orm import Session

from app.config import settings
from app.db.base import SessionLocal
from app.domains.auth import service

router = APIRouter(tags=["zipkin"])


@router.get("/auth/zipkin-access")
def zipkin_access(request: Request) -> Response:
    token = request.cookies.get(settings.zipkin_cookie_name)
    if not token:
        return PlainTextResponse("请先登录", status_code=401)
    with SessionLocal() as db:
        user = service.resolve_token(db, token)
    if user is None:
        return PlainTextResponse("请先登录", status_code=401)
    if user.role != service.ROLE_ADMIN:
        return PlainTextResponse("仅管理员可查看调用链", status_code=403)
    return Response(status_code=204)
