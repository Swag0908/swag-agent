"""FastAPI 依赖：当前用户、管理员、DB session。"""

from __future__ import annotations

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.errors import Forbidden, Unauthorized
from app.db.base import get_db
from app.domains.auth.service import ROLE_ADMIN, AuthUser

__all__ = ["get_db", "current_user", "require_admin", "UserDep", "DbDep"]


def current_user(request: Request) -> AuthUser:
    user_id = getattr(request.state, "user_id", None)
    role = getattr(request.state, "role", None)
    if user_id is None:
        raise Unauthorized()
    return AuthUser(id=int(user_id), role=role or "USER")


def require_admin(user: AuthUser = Depends(current_user)) -> AuthUser:
    if user.role != ROLE_ADMIN:
        raise Forbidden("仅管理员可执行该操作")
    return user


UserDep = Depends(current_user)
DbDep = Depends(get_db)
