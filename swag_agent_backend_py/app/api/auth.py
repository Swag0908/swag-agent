"""认证端点：/auth/register|login|logout|me。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.config import settings
from app.core.errors import AppError
from app.db.base import get_db
from app.domains.auth import service

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    """注册请求的 JSON 字段；允许缺省值以便业务层返回与旧版一致的提示。"""
    username: str | None = None
    password: str | None = None
    displayName: str | None = None
    registerCode: str | None = None


class LoginRequest(BaseModel):
    """登录请求结构；Pydantic 负责解析 JSON，密码是否正确由认证服务检查。"""
    username: str | None = None
    password: str | None = None


def _issue_cookie(response: Response, token: str) -> None:
    """附加仅供 Zipkin 路径使用的 HttpOnly Cookie；普通 API 仍使用 Bearer 令牌。"""
    if not token:
        return
    response.set_cookie(
        key=settings.zipkin_cookie_name,
        value=token,
        max_age=settings.token_ttl_days * 86400,
        path=settings.zipkin_cookie_path,
        httponly=True,
        samesite="lax",
        secure=settings.zipkin_cookie_secure,
    )


def _clear_cookie(response: Response) -> None:
    response.delete_cookie(key=settings.zipkin_cookie_name, path=settings.zipkin_cookie_path)


def _auth_body(token: str | None, user: service.UserRecord) -> dict:
    """挑选允许返回前端的账户字段，避免泄露内部密码哈希。"""
    return {
        "token": token,
        "userId": user.id,
        "username": user.username,
        "displayName": user.display_name,
        "role": user.role,
    }


@router.post("/register")
def register(body: RegisterRequest, response: Response, db: Session = Depends(get_db)) -> dict:
    """检查注册码、创建普通用户并自动登录，返回令牌和账户信息。"""
    service.assert_can_register(db, body.registerCode)
    user = service.create_user(db, body.username or "", body.password or "", body.displayName, service.ROLE_USER)
    token, _ = service.login(db, body.username or "", body.password or "")
    _issue_cookie(response, token)
    return _auth_body(token, user)


@router.post("/login")
def login(body: LoginRequest, response: Response, db: Session = Depends(get_db)) -> dict:
    """验证账号密码并返回登录令牌，同时设置 Zipkin 访问 Cookie。"""
    token, user = service.login(db, body.username or "", body.password or "")
    _issue_cookie(response, token)
    return _auth_body(token, user)


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> Response:
    """注销当前 Bearer 令牌并构造空响应；Cookie 清理由注入的 response 对象承接。"""
    token = getattr(request.state, "auth_token", None)
    service.logout(db, token)
    _clear_cookie(response)
    return Response(status_code=200)


@router.get("/me")
def me(request: Request, response: Response, db: Session = Depends(get_db), user=Depends(current_user)) -> dict:
    """按可信身份查询账户信息并续发 Zipkin Cookie；此接口不签发新的 API 令牌。"""
    record = service.find_by_id(db, user.id)
    if record is None:
        raise AppError(401, "请先登录")
    token = getattr(request.state, "auth_token", None)
    _issue_cookie(response, token or "")
    return _auth_body(None, record)
