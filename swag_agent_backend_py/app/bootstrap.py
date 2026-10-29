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
    with SessionLocal() as db:
        _ensure_register_settings(db)
        _seed_admins(db)


def _ensure_register_settings(db) -> None:  # noqa: ANN001
    row = db.get(AppRegisterSetting, 1)
    if row is not None:
        return
    # 延迟导入避免循环
    from app.domains.auth.service import ensure_register_settings

    ensure_register_settings(db)
    logger.info("initialized app_register_setting")


def _seed_admins(db) -> None:  # noqa: ANN001
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
