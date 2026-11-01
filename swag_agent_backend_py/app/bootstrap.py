"""启动初始化：与 Java 的 AuthSchemaInitializer / AdminUserSeeder / RegisterSettingsService 对齐。

只做“缺什么补什么”的幂等操作，不建业务表、不改结构。
"""

from __future__ import annotations

import logging

from sqlalchemy import select

from app.config import settings
from app.core.timeutil import now
from app.db.base import SessionLocal
from app.db.models import AppRegisterSetting, AppUser
from app.domains.auth.service import create_user, find_by_username

logger = logging.getLogger(__name__)


def bootstrap() -> None:
    """补齐注册设置和配置指定的管理员；业务表必须事先存在，重复启动不会重复创建用户。"""
    with SessionLocal() as db:
        _ensure_register_settings(db)
        _seed_admins(db)


def _ensure_register_settings(db) -> None:  # noqa: ANN001
    """注册开关使用 id=1 的单行配置；仅在配置缺失时初始化。"""
    row = db.get(AppRegisterSetting, 1)
    if row is not None:
        return
    # 延迟导入避免循环
    from app.domains.auth.service import ensure_register_settings

    ensure_register_settings(db)
    logger.info("initialized app_register_setting")


def _seed_admins(db) -> None:  # noqa: ANN001
    """配置了初始密码才补建管理员；已有同名账户会被提升为管理员。"""
    if not settings.auth_admin_password:
        return
    for username in settings.admin_usernames:
        if find_by_username(db, username) is not None:
            # 已存在则确保角色为 ADMIN（与 Java 一致）
            row = db.scalar(select(AppUser).where(AppUser.username == username))
            if row is not None and row.role != "ADMIN":
                row.role = "ADMIN"
                db.commit()
            continue
        create_user(db, username, settings.auth_admin_password, "管理员", "ADMIN")
        logger.info("seeded admin user %s", username)
