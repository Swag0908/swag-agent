"""FastAPI 依赖：当前用户、管理员、DB session。"""

from __future__ import annotations

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.errors import Forbidden, Unauthorized
from app.db.base import get_db
from app.domains.auth.service import ROLE_ADMIN, AuthUser

__all__ = ["get_db", "current_user", "require_admin", "UserDep", "DbDep"]


def current_user(request: Request) -> AuthUser:
    """读取鉴权中间件已确认的身份；不信任前端自行填写的用户编号。"""
    user_id = getattr(request.state, "user_id", None)
    role = getattr(request.state, "role", None)
    if user_id is None:
        raise Unauthorized()
    return AuthUser(id=int(user_id), role=role or "USER")


def require_admin(user: AuthUser = Depends(current_user)) -> AuthUser:
    """在已登录基础上要求 ADMIN 角色；用作管理员路由的 Depends 依赖。"""
    if user.role != ROLE_ADMIN:
        raise Forbidden("仅管理员可执行该操作")
    return user


# Depends 是给 FastAPI 的声明：“调用接口函数前，先替我获取这个值”。
# 当前用户和数据库会话都由后端提供，前端不需要、也不能提交这两个 Python 对象。
UserDep = Depends(current_user)
DbDep = Depends(get_db)
