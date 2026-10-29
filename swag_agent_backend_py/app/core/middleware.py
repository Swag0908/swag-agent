"""纯 ASGI 鉴权中间件：复刻 Java AuthFilter。

- 公开路径白名单；其余必须带有效 Bearer token。
- 未登录返回固定 401 body。
- 解析成功后把 user_id/role 写入 request.state，供依赖与审计中间件使用。
"""

from __future__ import annotations

import logging

from starlette.concurrency import run_in_threadpool
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.db.base import SessionLocal
from app.domains.auth.service import resolve_token

logger = logging.getLogger(__name__)

_PUBLIC_PREFIXES = (
    "/auth/register",
    "/auth/login",
    "/auth/zipkin-access",
    "/actuator/",
    "/error",
)


def is_public_path(path: str) -> bool:
    return any(path.startswith(prefix) for prefix in _PUBLIC_PREFIXES)


def bearer_token(headers: Headers) -> str | None:
    value = headers.get("authorization")
    if not value or not value.startswith("Bearer "):
        return None
    return value[len("Bearer ") :].strip()


def _resolve(token: str | None):  # noqa: ANN202
    if not token:
        return None
    with SessionLocal() as db:
        return resolve_token(db, token)


class AuthMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        token = bearer_token(headers)
        path = scope.get("path", "")
        try:
            user = await run_in_threadpool(_resolve, token)
        except Exception:  # noqa: BLE001
            logger.exception("resolve token failed")
            user = None

        if user is None and not is_public_path(path):
            response = JSONResponse(
                status_code=401,
                content={"code": "UNAUTHORIZED", "message": "请先登录"},
                media_type="application/json;charset=UTF-8",
            )
            await response(scope, receive, send)
            return

        state = scope.setdefault("state", {})
        state["user_id"] = user.id if user else None
        state["role"] = user.role if user else None
        state["auth_token"] = token
        await self.app(scope, receive, send)
