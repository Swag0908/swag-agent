"""管理员端点：/auth/admin/*（仅 ADMIN）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.core.errors import BadRequest, NotFound
from app.core.timeutil import epoch_ms
from app.db.base import get_db
from app.domains.auth import service

router = APIRouter(prefix="/auth/admin", tags=["admin"], dependencies=[Depends(require_admin)])


class UpdateSettingsRequest(BaseModel):
    registrationEnabled: bool | None = None
    registerCode: str | None = None


class RoleRequest(BaseModel):
    role: str | None = None


def _settings_response(data: dict) -> dict:
    return {
        "registrationEnabled": data["registrationEnabled"],
        "registerCode": data["registerCode"],
        "updatedAtMs": data["updatedAtMs"],
    }


@router.get("/register-settings")
def get_settings(db: Session = Depends(get_db)) -> dict:
    return _settings_response(service.get_register_settings(db))


@router.put("/register-settings")
def update_settings(
    body: UpdateSettingsRequest, admin=Depends(require_admin), db: Session = Depends(get_db)
) -> dict:
    data = service.update_register_settings(db, body.registrationEnabled, body.registerCode, admin.id)
    return _settings_response(data)


@router.post("/register-settings/regenerate")
def regenerate(admin=Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    return _settings_response(service.regenerate_register_code(db, admin.id))


@router.get("/users")
def list_users(db: Session = Depends(get_db)) -> list[dict]:
    return [
        {
            "id": u.id,
            "username": u.username,
            "displayName": u.display_name,
            "role": u.role or service.ROLE_USER,
            "createdAtMs": epoch_ms(u.created_at),
        }
        for u in service.list_users(db)
    ]


@router.put("/users/{user_id}/role")
def update_role(
    user_id: int, body: RoleRequest, admin=Depends(require_admin), db: Session = Depends(get_db)
) -> dict:
    role = (body.role or "").strip().upper()
    if role not in service.ROLES:
        raise BadRequest("角色只能是 ADMIN 或 USER")
    if admin.id == user_id:
        raise BadRequest("不能修改自己的角色")
    target = service.find_by_id(db, user_id)
    if target is None:
        raise NotFound("用户不存在")
    if target.role == service.ROLE_ADMIN and role == service.ROLE_USER and service.count_admins(db) <= 1:
        raise BadRequest("至少保留一名管理员")
    service.update_role(db, user_id, role)
    return {
        "id": target.id,
        "username": target.username,
        "displayName": target.display_name,
        "role": role,
        "createdAtMs": epoch_ms(target.created_at),
    }
