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
    username: str | None = None
    password: str | None = None
    displayName: str | None = None
    registerCode: str | None = None


class LoginRequest(BaseModel):
    username: str | None = None
    password: str | None = None


def _issue_cookie(response: Response, token: str) -> None:
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
    return {
        "token": token,
        "userId": user.id,
        "username": user.username,
        "displayName": user.display_name,
        "role": user.role,
    }


@router.post("/register")
def register(body: RegisterRequest, response: Response, db: Session = Depends(get_db)) -> dict:
    service.assert_can_register(db, body.registerCode)
    user = service.create_user(db, body.username or "", body.password or "", body.displayName, service.ROLE_USER)
    token, _ = service.login(db, body.username or "", body.password or "")
    _issue_cookie(response, token)
    return _auth_body(token, user)


@router.post("/login")
def login(body: LoginRequest, response: Response, db: Session = Depends(get_db)) -> dict:
    token, user = service.login(db, body.username or "", body.password or "")
    _issue_cookie(response, token)
    return _auth_body(token, user)


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> Response:
    token = getattr(request.state, "auth_token", None)
    service.logout(db, token)
    _clear_cookie(response)
    return Response(status_code=200)


@router.get("/me")
def me(request: Request, response: Response, db: Session = Depends(get_db), user=Depends(current_user)) -> dict:
    record = service.find_by_id(db, user.id)
    if record is None:
        raise AppError(401, "请先登录")
    token = getattr(request.state, "auth_token", None)
    _issue_cookie(response, token or "")
    return _auth_body(None, record)
