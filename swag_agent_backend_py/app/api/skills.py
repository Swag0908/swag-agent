"""技能管理端 REST：/auth/admin/skills/*（5 个端点，仅 ADMIN）。

返回字段严格对齐 Java `SkillAdminController.SkillView`：
{name, description, enabled, source, bodyChars, filePath}；安装返回
{installed, skills}。启停状态存 skill_state，缺行=启用。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.core.errors import BadRequest, NotFound
from app.db.base import get_db
from app.skills import installer
from app.skills.registry import SkillManifest, SkillRegistry, get_registry

router = APIRouter(
    prefix="/auth/admin/skills",
    tags=["skills"],
    dependencies=[Depends(require_admin)],
)


class ToggleRequest(BaseModel):
    """技能启停请求；enabled 缺失时返回明确的业务错误。"""
    enabled: bool | None = None


class InstallRequest(BaseModel):
    """技能仓库地址及仓库内路径，供安装器定位 SKILL.md。"""
    repoUrl: str | None = None
    skillPath: str | None = None


def _to_view(registry: SkillRegistry, manifest: SkillManifest, disabled: set[str]) -> dict:
    return {
        "name": manifest.name,
        "description": manifest.description,
        "enabled": manifest.name not in disabled,
        "source": manifest.source,
        "bodyChars": len(manifest.body),
        "filePath": manifest.file_path,
    }


def _views(db: Session) -> list[dict]:
    registry = get_registry()
    manifests = registry.list(db)  # 先按 mtime 决定是否重扫，并清理消失技能的状态行
    disabled = registry.disabled_names(db)
    return [_to_view(registry, manifest, disabled) for manifest in manifests]


@router.get("")
def list_skills(db: Session = Depends(get_db)) -> list[dict]:
    """管理员查看有效技能及全局启停状态。"""
    return _views(db)


@router.put("/{name}")
def toggle_skill(
    name: str,
    body: ToggleRequest | None = None,
    db: Session = Depends(get_db),
) -> dict:
    """启停已有技能；后续组装系统提示词时采用新状态。"""
    if body is None or body.enabled is None:
        raise BadRequest("缺少 enabled 字段")
    registry = get_registry()
    if not registry.set_enabled(db, name, bool(body.enabled)):
        raise NotFound(f"技能不存在：{name}")
    manifest = registry.find(name)
    if manifest is None:
        raise NotFound(f"技能不存在：{name}")
    return _to_view(registry, manifest, registry.disabled_names(db))


@router.post("/refresh")
def refresh_skills(db: Session = Depends(get_db)) -> list[dict]:
    """强制重扫技能目录，用于正文变更或安装后的刷新。"""
    get_registry().refresh(db)
    return _views(db)


@router.post("/install")
def install_skill(body: InstallRequest | None = None, db: Session = Depends(get_db)) -> dict:
    """从仓库安装或覆盖外部技能，返回安装名称和最新技能列表。"""
    if body is None:
        raise BadRequest("请求体不能为空")
    installed = installer.install(body.repoUrl, body.skillPath, db=db)
    return {"installed": installed, "skills": _views(db)}


@router.delete("/{name}")
def delete_skill(name: str, db: Session = Depends(get_db)) -> Response:
    """删除外部技能目录；内置技能只能禁用，不能在此删除。"""
    if not get_registry().delete_external(db, name):
        raise BadRequest(f"技能不存在或为内置技能，无法删除：{name}")
    return Response(status_code=200)
