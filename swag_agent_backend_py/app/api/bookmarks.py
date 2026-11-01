"""常用网站 REST 端点：/bookmarks*（8 个）。对齐 Java `WebsiteController`。"""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.db.base import get_db
from app.domains.auth.service import AuthUser
from app.domains.sites import icon as icon_service
from app.domains.sites import service, views

router = APIRouter(prefix="/bookmarks", tags=["bookmarks"])

_MEDIA_TYPE = re.compile(r"^[-\w.]+/[-\w.+]+$")


class FolderRequest(BaseModel):
    """分类名称和父分类编号；parentId 为空表示顶层。"""
    name: str | None = None
    parentId: int | None = None


class BookmarkRequest(BaseModel):
    """书签编辑字段；沿用前端 camelCase 键名，无需前端另做转换。"""
    name: str | None = None
    url: str | None = None
    description: str | None = None
    iconUrl: str | None = None
    folderId: int | None = None


@router.get("")
def list_library(
    folderId: int | None = Query(default=None),  # noqa: N803 - 保持 Java/JSON 原名
    q: str | None = Query(default=None),
    unclassified: bool = Query(default=False),
    user: AuthUser = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    """读取分类树及书签；可按直属分类、关键字或未分类筛选。"""
    return views.library_to_dict(service.library(db, user.id, folderId, q, unclassified))


@router.post("/folders")
def create_folder(
    body: FolderRequest,
    user: AuthUser = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    """为当前用户新建网站分类，转换为前端所需字段返回。"""
    node = service.create_folder(db, user.id, body.name, body.parentId)
    return views.folder_to_dict(node)


@router.patch("/folders/{folder_id}")
def update_folder(
    folder_id: int,
    body: FolderRequest,
    user: AuthUser = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    """重命名或移动网站分类，目录成环检查由业务层负责。"""
    node = service.update_folder(db, user.id, folder_id, body.name, body.parentId)
    return views.folder_to_dict(node)


@router.delete("/folders/{folder_id}")
def delete_folder(
    folder_id: int,
    cascade: bool = Query(default=False),
    user: AuthUser = Depends(current_user),
    db: Session = Depends(get_db),
) -> Response:
    """删除分类；cascade=false 时非空分类返回冲突，避免直接连内容删除。"""
    service.delete_folder(db, user.id, folder_id, cascade)
    return Response(status_code=200)


@router.post("")
def create_bookmark(
    body: BookmarkRequest,
    user: AuthUser = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    """将表单数据交给网站服务，创建书签后返回展示字段。"""
    view = service.create_bookmark(
        db, user.id, body.name, body.url, body.description, body.iconUrl, body.folderId
    )
    return views.bookmark_to_dict(view)


@router.patch("/{bookmark_id}")
def update_bookmark(
    bookmark_id: int,
    body: BookmarkRequest,
    user: AuthUser = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    """将编辑字段交给业务层，修改当前用户的书签。"""
    view = service.update_bookmark(
        db,
        user.id,
        bookmark_id,
        body.name,
        body.url,
        body.description,
        body.iconUrl,
        body.folderId,
    )
    return views.bookmark_to_dict(view)


@router.get("/{bookmark_id}/icon")
def bookmark_icon(
    bookmark_id: int,
    user: AuthUser = Depends(current_user),
    db: Session = Depends(get_db),
) -> Response:
    """返回用户书签的图标二进制；首次无缓存时尝试抓取，找不到返回 404。"""
    found = icon_service.icon_for(db, user.id, bookmark_id)
    if found is None:
        return Response(status_code=404)
    data, content_type = found
    media_type = content_type if _MEDIA_TYPE.match(content_type) else "application/octet-stream"
    return Response(
        content=data,
        media_type=media_type,
        headers={"Cache-Control": "no-cache, private"},
    )


@router.delete("/{bookmark_id}")
def delete_bookmark(
    bookmark_id: int,
    user: AuthUser = Depends(current_user),
    db: Session = Depends(get_db),
) -> Response:
    """删除当前用户书签，成功返回 200 空响应。"""
    service.delete_bookmark(db, user.id, bookmark_id)
    return Response(status_code=200)
