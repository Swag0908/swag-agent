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
    """请求处理所需的最小身份，只含用户编号与角色，不含密码哈希。"""
    id: int
    role: str


@dataclass(frozen=True)
class UserRecord:
    """服务层使用的用户快照；API 必须挑选可公开字段，不能直接返回整个对象。"""
    id: int
    username: str
    password_hash: str
    display_name: str | None
    role: str
    created_at: datetime


def _to_record(user: AppUser) -> UserRecord:
    """把数据库用户对象转成独立快照，离开数据库会话后仍可读取字段。"""
    return UserRecord(
        id=user.id,
        username=user.username,
        password_hash=user.password_hash,
        display_name=user.display_name,
        role=user.role or ROLE_USER,
        created_at=user.created_at,
    )


def find_by_username(db: Session, username: str) -> UserRecord | None:
    """去掉用户名首尾空白后精确查询；查不到返回 None。"""
    row = db.scalar(select(AppUser).where(AppUser.username == (username or "").strip()))
    return _to_record(row) if row else None


def find_by_id(db: Session, user_id: int) -> UserRecord | None:
    """按主键查用户并返回快照；查不到返回 None。"""
    row = db.get(AppUser, user_id)
    return _to_record(row) if row else None


def list_users(db: Session) -> list[UserRecord]:
    """按创建时间和编号倒序返回用户快照，供管理员列表使用。"""
    rows = db.scalars(select(AppUser).order_by(AppUser.created_at.desc(), AppUser.id.desc())).all()
    return [_to_record(r) for r in rows]


def count_admins(db: Session) -> int:
    """统计管理员数量，供修改角色前检查是否至少保留一名管理员。"""
    return int(db.scalar(select(func.count()).select_from(AppUser).where(AppUser.role == ROLE_ADMIN)) or 0)


def _validate_new_user(username: str, password: str) -> tuple[str, str]:
    """验证用户名和密码长度；用户名去掉首尾空白，密码保留原值。"""
    name = (username or "").strip()
    if not 3 <= len(name) <= 64:
        raise BadRequest("用户名长度需在 3-64 位之间")
    if password is None or len(password) < 6:
        raise BadRequest("密码长度至少 6 位")
    return name, password


def create_user(db: Session, username: str, password: str, display_name: str | None, role: str) -> UserRecord:
    """校验输入、哈希密码并保存账户；用户名冲突回滚事务并返回 409 业务异常。"""
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
    """核对密码后签发随机令牌并保存有效期；错误时统一提示用户名或密码错误。"""
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
    """查询令牌是否存在、未过期且用户仍存在；成功返回身份，失败返回 None。"""
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
    """删除当前令牌使本次登录失效；不会删除同一用户的其他登录令牌。"""
    if token and token.strip():
        db.execute(delete(AuthToken).where(AuthToken.token == token.strip()))
        db.commit()


def update_role(db: Session, user_id: int, role: str) -> None:
    """保存指定用户的角色；角色合法性及管理员保留规则由上层检查。"""
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
    """生成三组四字符的随机注册码，避开易混淆字符。"""
    groups = ["".join(secrets.choice(_ALPHABET) for _ in range(4)) for _ in range(3)]
    return "-".join(groups)


def ensure_register_settings(db: Session) -> None:
    """缺少 id=1 的注册配置时补建，并随机生成初始注册码。"""
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
    """读取注册开关、注册码和更新时间，返回管理员接口所需字段。"""
    row = _require_settings(db)
    return {
        "registrationEnabled": bool(row.registration_enabled),
        "registerCode": row.register_code,
        "updatedAtMs": epoch_ms(row.updated_at),
    }


def assert_can_register(db: Session, register_code: str | None) -> None:
    """同时检查注册是否开放和注册码是否匹配；通过后调用方才能创建普通用户。"""
    row = _require_settings(db)
    if not row.registration_enabled:
        raise Forbidden("注册功能当前已关闭，请联系管理员")
    provided = (register_code or "").strip().upper()
    if not secrets.compare_digest(row.register_code, provided):
        raise BadRequest("注册码不正确，请向管理员获取")


def update_register_settings(
    db: Session, registration_enabled: bool | None, register_code: str | None, admin_id: int
) -> dict:
    """管理员修改注册开关或注册码，记录操作者并提交。"""
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
    """随机替换注册码；旧注册码随后不能通过注册校验。"""
    row = _require_settings(db)
    row.register_code = _generate_code()
    row.updated_by = admin_id
    row.updated_at = now()
    db.commit()
    return get_register_settings(db)


def require_admin(db: Session, user_id: int) -> UserRecord:
    """直接从数据库验证某个用户是否为管理员，供需要重新查角色的业务路径使用。"""
    record = find_by_id(db, user_id)
    if record is None or record.role != ROLE_ADMIN:
        raise Forbidden("仅管理员可执行该操作")
    return record
