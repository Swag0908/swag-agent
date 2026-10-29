"""Markdown 笔记 REST 接口（16 个端点，路径/字段/错误码与 Java `NotesController` 对齐）。

路径均为用户笔记目录内的相对路径（``/`` 分隔，UTF-8），如 ``工作/周报.md``；
文件操作仅接受 ``.md`` 笔记。删除一律先进回收站（7 天后清理），可恢复。
"""

from __future__ import annotations

import urllib.parse

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from app.api.deps import current_user
from app.config import settings
from app.core.errors import AppError, BadRequest
from app.domains.auth.service import AuthUser
from app.domains.notes.import_service import UploadPart, get_import_service
from app.domains.notes.service import get_notes_service

router = APIRouter(prefix="/notes", tags=["notes"])


# ---------------------------------------------------------------------------
# 请求体模型（字段可空与 Java record 一致，controller 层做非空校验）
# ---------------------------------------------------------------------------


class SaveRequest(BaseModel):
    path: str | None = None
    content: str | None = None


class DirRequest(BaseModel):
    path: str | None = None


class RenameRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_: str | None = Field(default=None, alias="from")
    to: str | None = None


class LocalImportRequest(BaseModel):
    sourcePaths: list[str] | None = None
    targetDir: str | None = None


def _blank(value: str | None) -> bool:
    return value is None or not value.strip()


def _empty_ok() -> Response:
    """Java void 端点：200 + 空体。"""
    return Response(status_code=200)


def _content_disposition(file_name: str, inline: bool) -> str:
    disposition = "inline" if inline else "attachment"
    if file_name.isascii():
        quoted = file_name.replace("\\", "\\\\").replace('"', '\\"')
        return f'{disposition}; filename="{quoted}"'
    # Java: ContentDisposition.filename(name, UTF_8) → RFC 5987 filename*
    return f"{disposition}; filename*=UTF-8''{urllib.parse.quote(file_name, safe='')}"


# ---------------------------------------------------------------------------
# 目录树 / 文件读写
# ---------------------------------------------------------------------------


@router.get("/tree")
def get_tree(user: AuthUser = Depends(current_user)):
    """用户笔记目录树（根为 user-<id>，根 path 为空串）。"""
    return get_notes_service().tree(user.id)


@router.get("/file")
def read_file(path: str = Query(...), user: AuthUser = Depends(current_user)):
    """读取一篇笔记源码。"""
    return get_notes_service().read(user.id, path)


@router.post("/file")
def create_file(request: SaveRequest, user: AuthUser = Depends(current_user)):
    """新建笔记：同名已存在时 409，绝不覆盖。"""
    if _blank(request.path):
        raise BadRequest("笔记路径不能为空")
    return get_notes_service().create(user.id, request.path, request.content)


@router.put("/file")
def save_file(request: SaveRequest, user: AuthUser = Depends(current_user)):
    """保存（新建或整体覆盖）一篇笔记。"""
    if _blank(request.path):
        raise BadRequest("笔记路径不能为空")
    return get_notes_service().save(user.id, request.path, request.content)


@router.delete("/file")
def delete_file(path: str = Query(...), user: AuthUser = Depends(current_user)):
    """删除笔记 → 移入回收站（可恢复）。"""
    get_notes_service().delete_file(user.id, path)
    return _empty_ok()


# ---------------------------------------------------------------------------
# 导入
# ---------------------------------------------------------------------------


@router.get("/import/config")
def import_config(user: AuthUser = Depends(current_user)):
    """当前实例允许本地导入的根目录。"""
    del user
    return get_import_service().config()


@router.post("/import/local")
def import_local(
    request: LocalImportRequest | None = None,
    user: AuthUser = Depends(current_user),
):
    """从运行后端的机器上、配置允许的目录内批量导入 Markdown。"""
    if request is None:
        raise BadRequest("请求体不能为空")
    return get_import_service().import_local(user.id, request.sourcePaths, request.targetDir)


@router.post("/import/upload")
async def import_upload(
    files: list[UploadFile] = File(...),
    relativePaths: list[str] | None = Form(default=None),
    targetDir: str | None = Form(default=None),
    user: AuthUser = Depends(current_user),
):
    """浏览器批量上传；relativePaths 保留目录层级以便解析并复制引用附件。"""
    parts: list[UploadPart] = []
    for index, upload in enumerate(files):
        content = await upload.read()
        relative = (
            relativePaths[index]
            if relativePaths is not None and index < len(relativePaths)
            else None
        )
        parts.append(UploadPart(relative, upload.filename, content))

    # 复刻 Spring multipart 层限制（解析阶段即拒绝，早于业务逐文件限额）：
    # 单文件 20 MiB / 整个请求 100 MiB → HTTP 413。
    if sum(len(part.content) for part in parts) > settings.notes_max_import_total_bytes:
        raise AppError(413, "上传请求超过大小上限")
    for part in parts:
        if len(part.content) > settings.notes_max_attachment_bytes:
            raise AppError(413, f"上传文件超过大小上限：{part.original_filename}")

    return await run_in_threadpool(
        get_import_service().import_uploads, user.id, parts, targetDir
    )


@router.get("/resource")
def read_resource(
    bundle: str = Query(...),
    name: str = Query(...),
    user: AuthUser = Depends(current_user),
):
    """仅向当前用户返回其导入时复制的资源；危险类型强制下载。"""
    view = get_import_service().resource(user.id, bundle, name)
    headers = {
        "X-Content-Type-Options": "nosniff",
        "Content-Disposition": _content_disposition(view.fileName, view.inline),
    }
    return FileResponse(view.path, media_type=view.contentType, headers=headers)


# ---------------------------------------------------------------------------
# 文件夹 / 重命名
# ---------------------------------------------------------------------------


@router.post("/dir")
def create_dir(request: DirRequest, user: AuthUser = Depends(current_user)):
    """新建文件夹（可含子路径，自动创建父级）。"""
    if _blank(request.path):
        raise BadRequest("文件夹路径不能为空")
    get_notes_service().create_dir(user.id, request.path)
    return _empty_ok()


@router.delete("/dir")
def delete_dir(
    path: str = Query(...),
    mode: str = Query(default="trash"),
    user: AuthUser = Depends(current_user),
):
    """删除文件夹：mode=trash 整体进回收站；mode=flatten 笔记平铺进「未分类」。"""
    service = get_notes_service()
    if mode == "flatten":
        service.delete_dir_flatten(user.id, path)
    elif mode == "trash":
        service.delete_dir_to_trash(user.id, path)
    else:
        raise BadRequest("mode 仅支持 trash / flatten")
    return _empty_ok()


@router.post("/rename")
def rename(request: RenameRequest, user: AuthUser = Depends(current_user)):
    """重命名 / 移动文件或文件夹。"""
    get_notes_service().rename(user.id, request.from_, request.to)
    return _empty_ok()


# ---------------------------------------------------------------------------
# 回收站（静态 /trash 声明在 /trash/{id} 之前，避免路由匹配顺序变化）
# ---------------------------------------------------------------------------


@router.get("/trash")
def list_trash(user: AuthUser = Depends(current_user)):
    """回收站条目列表（顺带清理过期条目）。"""
    return get_notes_service().list_trash(user.id)


@router.delete("/trash")
def clear_trash(user: AuthUser = Depends(current_user)):
    """清空回收站。"""
    get_notes_service().clear_trash(user.id)
    return _empty_ok()


@router.post("/trash/{trash_id}/restore")
def restore_trash(trash_id: str, user: AuthUser = Depends(current_user)):
    """恢复回收站条目（原目录仍在 → 放回原处，否则进「未分类」）。"""
    get_notes_service().restore(user.id, trash_id)
    return _empty_ok()


@router.delete("/trash/{trash_id}")
def delete_trash_entry(trash_id: str, user: AuthUser = Depends(current_user)):
    """永久删除某条回收站记录。"""
    get_notes_service().delete_trash_entry(user.id, trash_id)
    return _empty_ok()
