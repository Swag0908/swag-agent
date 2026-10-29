"""认证领域服务单测（SQLite，不连真实 MySQL）。"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.errors import AppError, BadRequest, Forbidden
from app.core.timeutil import now
from app.db.models import AppRegisterSetting, AppUser, AuthToken
from app.domains.auth import service


def test_register_settings_initialized(sqlite_session):
    service.ensure_register_settings(sqlite_session)
    row = sqlite_session.get(AppRegisterSetting, 1)
    assert row is not None
    assert row.registration_enabled is True
    assert len(row.register_code) == 14  # XXXX-XXXX-XXXX
    assert row.register_code.count("-") == 2


def test_create_and_login(sqlite_session):
    user = service.create_user(sqlite_session, "alice", "secret1", None, service.ROLE_USER)
    assert user.display_name == "alice"
    token, logged = service.login(sqlite_session, "alice", "secret1")
    assert logged.id == user.id
    resolved = service.resolve_token(sqlite_session, token)
    assert resolved is not None and resolved.id == user.id

    with pytest.raises(AppError) as exc:
        service.login(sqlite_session, "alice", "wrong")
    assert exc.value.status_code == 401

    service.logout(sqlite_session, token)
    assert service.resolve_token(sqlite_session, token) is None


def test_duplicate_username(sqlite_session):
    service.create_user(sqlite_session, "bob", "secret1", None, service.ROLE_USER)
    with pytest.raises(AppError) as exc:
        service.create_user(sqlite_session, "bob", "secret1", None, service.ROLE_USER)
    assert exc.value.status_code == 409


def test_token_expiry(sqlite_session):
    user = service.create_user(sqlite_session, "carol", "secret1", None, service.ROLE_USER)
    token = "11111111-1111-1111-1111-111111111111"
    sqlite_session.add(
        AuthToken(token=token, user_id=user.id, expires_at=now() - timedelta(seconds=1), created_at=now())
    )
    sqlite_session.commit()
    assert service.resolve_token(sqlite_session, token) is None


def test_register_gate(sqlite_session):
    service.ensure_register_settings(sqlite_session)
    code = sqlite_session.get(AppRegisterSetting, 1).register_code

    service.assert_can_register(sqlite_session, code.lower())  # 大小写不敏感
    with pytest.raises(BadRequest):
        service.assert_can_register(sqlite_session, "WRONG-CODE")
    with pytest.raises(BadRequest):
        service.assert_can_register(sqlite_session, None)

    service.update_register_settings(sqlite_session, False, None, admin_id=1)
    with pytest.raises(Forbidden):
        service.assert_can_register(sqlite_session, code)

    service.update_register_settings(sqlite_session, True, "abcdef", admin_id=1)
    assert service.get_register_settings(sqlite_session)["registerCode"] == "ABCDEF"
    with pytest.raises(BadRequest):
        service.update_register_settings(sqlite_session, True, "123", admin_id=1)

    new_code = service.regenerate_register_code(sqlite_session, admin_id=1)["registerCode"]
    assert new_code != "ABCDEF"


def test_admin_role_rules(sqlite_session):
    admin = service.create_user(sqlite_session, "root1", "secret1", None, service.ROLE_ADMIN)
    assert service.count_admins(sqlite_session) == 1
    service.update_role(sqlite_session, admin.id, service.ROLE_USER)
    assert service.count_admins(sqlite_session) == 0
    with pytest.raises(Forbidden):
        service.require_admin(sqlite_session, admin.id)
