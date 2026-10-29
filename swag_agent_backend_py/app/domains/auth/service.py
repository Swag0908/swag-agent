"""认证领域服务：用户、登录令牌、注册闸门。

保持 Java 端语义：不透明 UUID token、7 天 TTL、BCrypt、注册码闸门。
"""

from __future__ import annotations

import logging
import secrets
import string
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.core.errors import AppError, BadRequest, Forbidden, NotFound
from app.core.security import hash_password, new_token, verify_password
from app.core.timeutil import epoch_ms, now
from app.db.models import AppRegisterSetting, AppUser, AuthToken

logger = logging.getLogger(__name__)

ROLE_ADMIN = "ADMIN"
ROLE_USER = "USER"
ROLES = {ROLE_ADMIN, ROLE_USER}


@dataclass(frozen=True)
class AuthUser:
    id: int
    role: str


@dataclass(frozen=True)
class UserRecord:
    id: int
    username: str
    password_hash: str
    display_name: str | None
    role: str
    created_at: datetime


def _to_record(user: AppUser) -> UserRecord:
    return UserRecord(
        id=user.id,
        username=user.username,
        password_hash=user.password_hash,
        display_name=user.display_name,
        role=user.role or ROLE_USER,
        created_at=user.created_at,
    )


def find_by_username(db: Session, username: str) -> UserRecord | None:
    row = db.scalar(select(AppUser).where(AppUser.username == (username or "").strip()))
    return _to_record(row) if row else None


def find_by_id(db: Session, user_id: int) -> UserRecord | None:
    row = db.get(AppUser, user_id)
    return _to_record(row) if row else None


def list_users(db: Session) -> list[UserRecord]:
    rows = db.scalars(select(AppUser).order_by(AppUser.created_at.desc(), AppUser.id.desc())).all()
    return [_to_record(r) for r in rows]


def count_admins(db: Session) -> int:
    return int(db.scalar(select(func.count()).select_from(AppUser).where(AppUser.role == ROLE_ADMIN)) or 0)


def _validate_new_user(username: str, password: str) -> tuple[str, str]:
    name = (username or "").strip()
    if not 3 <= len(name) <= 64:
        raise BadRequest("用户名长度需在 3-64 位之间")
    if password is None or len(password) < 6:
        raise BadRequest("密码长度至少 6 位")
    return name, password


def create_user(db: Session, username: str, password: str, display_name: str | None, role: str) -> UserRecord:
    name, password = _validate_new_user(username, password)
    user = AppUser(
        username=name,
        password_hash=hash_password(password),
        display_name=(display_name or "").strip() or name,
        role=role,
        created_at=now(),
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise AppError(409, "用户名已存在") from exc
    db.refresh(user)
    return _to_record(user)


def login(db: Session, username: str, password: str) -> tuple[str, UserRecord]:
    record = find_by_username(db, username)
    if record is None or not verify_password(password, record.password_hash):
        raise AppError(401, "用户名或密码错误")
    token = new_token()
    created = now()
    db.add(
        AuthToken(
            token=token,
            user_id=record.id,
            expires_at=created + timedelta(days=settings.token_ttl_days),
            created_at=created,
        )
    )
    db.commit()
    return token, record


def resolve_token(db: Session, token: str | None) -> AuthUser | None:
    if not token or not token.strip():
        return None
    row = db.get(AuthToken, token.strip())
    if row is None:
        return None
    if row.expires_at <= now():
        return None
    user = db.get(AppUser, row.user_id)
    if user is None:
        return None
    return AuthUser(id=user.id, role=user.role or ROLE_USER)


def logout(db: Session, token: str | None) -> None:
    if token and token.strip():
        db.execute(delete(AuthToken).where(AuthToken.token == token.strip()))
        db.commit()


def update_role(db: Session, user_id: int, role: str) -> None:
    user = db.get(AppUser, user_id)
    if user is None:
        raise NotFound("用户不存在")
    user.role = role
    db.commit()


# ---------------------------------------------------------------------------
# 注册闸门（app_register_setting 单行表，id=1）
# ---------------------------------------------------------------------------

_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"


def _generate_code() -> str:
    groups = ["".join(secrets.choice(_ALPHABET) for _ in range(4)) for _ in range(3)]
    return "-".join(groups)


def ensure_register_settings(db: Session) -> None:
    row = db.get(AppRegisterSetting, 1)
    if row is None:
        db.add(
            AppRegisterSetting(
                id=1,
                register_code=_generate_code(),
                registration_enabled=True,
                updated_by=None,
                updated_at=now(),
            )
        )
        db.commit()


def _require_settings(db: Session) -> AppRegisterSetting:
    row = db.get(AppRegisterSetting, 1)
    if row is None:
        raise AppError(500, "注册设置未初始化")
    return row


def get_register_settings(db: Session) -> dict:
    row = _require_settings(db)
    return {
        "registrationEnabled": bool(row.registration_enabled),
        "registerCode": row.register_code,
        "updatedAtMs": epoch_ms(row.updated_at),
    }


def assert_can_register(db: Session, register_code: str | None) -> None:
    row = _require_settings(db)
    if not row.registration_enabled:
        raise Forbidden("注册功能当前已关闭，请联系管理员")
    provided = (register_code or "").strip().upper()
    if not secrets.compare_digest(row.register_code, provided):
        raise BadRequest("注册码不正确，请向管理员获取")


def update_register_settings(
    db: Session, registration_enabled: bool | None, register_code: str | None, admin_id: int
) -> dict:
    row = _require_settings(db)
    code = row.register_code
    if register_code is not None and register_code.strip():
        candidate = register_code.strip().upper()
        if not 6 <= len(candidate) <= 40:
            raise BadRequest("注册码长度需在 6-40 位之间")
        code = candidate
    row.register_code = code
    row.registration_enabled = row.registration_enabled if registration_enabled is None else bool(registration_enabled)
    row.updated_by = admin_id
    row.updated_at = now()
    db.commit()
    return get_register_settings(db)


def regenerate_register_code(db: Session, admin_id: int) -> dict:
    row = _require_settings(db)
    row.register_code = _generate_code()
    row.updated_by = admin_id
    row.updated_at = now()
    db.commit()
    return get_register_settings(db)


def require_admin(db: Session, user_id: int) -> UserRecord:
    record = find_by_id(db, user_id)
    if record is None or record.role != ROLE_ADMIN:
        raise Forbidden("仅管理员可执行该操作")
    return record
