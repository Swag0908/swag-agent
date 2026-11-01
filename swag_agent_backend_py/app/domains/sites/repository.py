"""常用网站的数据访问层（SQLAlchemy 2.0），对齐 Java `WebsiteRepository`。"""

from __future__ import annotations

from sqlalchemy import delete as sa_delete
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db.models import WebsiteBookmark, WebsiteFolder


def list_folders(db: Session, user_id: int) -> list[WebsiteFolder]:
    """读取当前用户分类，按排序值和编号排列。"""
    stmt = (
        select(WebsiteFolder)
        .where(WebsiteFolder.user_id == user_id)
        .order_by(WebsiteFolder.sort_order, WebsiteFolder.id)
    )
    return list(db.scalars(stmt).all())


def find_folder(db: Session, folder_id: int) -> WebsiteFolder | None:
    """仅按主键查分类；权限判断由 service 补充。"""
    return db.get(WebsiteFolder, folder_id)


def insert_folder(db: Session, folder: WebsiteFolder) -> WebsiteFolder:
    """插入分类并取得编号；与其他变动一起由 service 提交。"""
    db.add(folder)
    db.flush()
    return folder


def update_folder(db: Session, folder: WebsiteFolder) -> None:
    """同步分类修改到当前事务，不单独提交。"""
    db.add(folder)
    db.flush()


def delete_folders(db: Session, ids: list[int], user_id: int) -> None:
    """同时限制用户和分类编号批量删除，不单独提交。"""
    if not ids:
        return
    db.execute(
        sa_delete(WebsiteFolder).where(WebsiteFolder.id.in_(ids), WebsiteFolder.user_id == user_id)
    )
    db.flush()


def list_bookmarks(
    db: Session,
    user_id: int,
    folder_id: int | None,
    query: str | None,
    unclassified_only: bool,
) -> list[WebsiteBookmark]:
    """按用户隔离，再应用未分类、直属分类和关键字条件。"""
    stmt = select(WebsiteBookmark).where(WebsiteBookmark.user_id == user_id)
    if unclassified_only:
        stmt = stmt.where(WebsiteBookmark.folder_id.is_(None))
    elif folder_id is not None:
        stmt = stmt.where(WebsiteBookmark.folder_id == folder_id)
    if query is not None and query.strip():
        pattern = f"%{query.strip().lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(WebsiteBookmark.name).like(pattern),
                func.lower(WebsiteBookmark.url).like(pattern),
                func.lower(func.coalesce(WebsiteBookmark.description, "")).like(pattern),
            )
        )
    stmt = stmt.order_by(WebsiteBookmark.sort_order, WebsiteBookmark.id)
    return list(db.scalars(stmt).all())


def find_bookmark(db: Session, bookmark_id: int) -> WebsiteBookmark | None:
    """仅按主键查书签；调用方必须再核对归属。"""
    return db.get(WebsiteBookmark, bookmark_id)


def insert_bookmark(db: Session, bookmark: WebsiteBookmark) -> WebsiteBookmark:
    """插入书签并取得编号，不单独提交事务。"""
    db.add(bookmark)
    db.flush()
    return bookmark


def update_bookmark(db: Session, bookmark: WebsiteBookmark) -> None:
    """同步书签修改到当前事务，不单独提交。"""
    db.add(bookmark)
    db.flush()


def delete_bookmark(db: Session, bookmark: WebsiteBookmark) -> None:
    """删除已由上层验证归属的书签，不单独提交。"""
    db.delete(bookmark)
    db.flush()


def delete_bookmarks_by_folders(db: Session, folder_ids: list[int], user_id: int) -> None:
    """按用户和分类集合删除书签，供删除分类子树使用。"""
    if not folder_ids:
        return
    db.execute(
        sa_delete(WebsiteBookmark).where(
            WebsiteBookmark.folder_id.in_(folder_ids), WebsiteBookmark.user_id == user_id
        )
    )
    db.flush()


def find_cached_icon(db: Session, bookmark_id: int, user_id: int) -> tuple[bytes, str] | None:
    """同时按书签和用户查询图标缓存；没有二进制数据则视为未缓存。"""
    stmt = select(WebsiteBookmark.icon_data, WebsiteBookmark.icon_content_type).where(
        WebsiteBookmark.id == bookmark_id,
        WebsiteBookmark.user_id == user_id,
        WebsiteBookmark.icon_data.is_not(None),
    )
    row = db.execute(stmt).first()
    if row is None:
        return None
    data, content_type = row
    return bytes(data), content_type or "application/octet-stream"


def store_cached_icon(
    db: Session, bookmark: WebsiteBookmark, data: bytes, content_type: str
) -> None:
    """保存图标二进制及媒体类型；最终提交由调用方负责。"""
    bookmark.icon_data = data
    bookmark.icon_content_type = content_type
    db.add(bookmark)
    db.flush()


def clear_cached_icon(db: Session, bookmark: WebsiteBookmark) -> None:
    """清空旧图标数据及媒体类型，下一次读取会尝试重新发现。"""
    bookmark.icon_data = None
    bookmark.icon_content_type = None
    db.add(bookmark)
    db.flush()
