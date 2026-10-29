"""常用网站的数据访问层（SQLAlchemy 2.0），对齐 Java `WebsiteRepository`。"""

from __future__ import annotations

from sqlalchemy import delete as sa_delete
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db.models import WebsiteBookmark, WebsiteFolder


def list_folders(db: Session, user_id: int) -> list[WebsiteFolder]:
    stmt = (
        select(WebsiteFolder)
        .where(WebsiteFolder.user_id == user_id)
        .order_by(WebsiteFolder.sort_order, WebsiteFolder.id)
    )
    return list(db.scalars(stmt).all())


def find_folder(db: Session, folder_id: int) -> WebsiteFolder | None:
    return db.get(WebsiteFolder, folder_id)


def insert_folder(db: Session, folder: WebsiteFolder) -> WebsiteFolder:
    db.add(folder)
    db.flush()
    return folder


def update_folder(db: Session, folder: WebsiteFolder) -> None:
    db.add(folder)
    db.flush()


def delete_folders(db: Session, ids: list[int], user_id: int) -> None:
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
    return db.get(WebsiteBookmark, bookmark_id)


def insert_bookmark(db: Session, bookmark: WebsiteBookmark) -> WebsiteBookmark:
    db.add(bookmark)
    db.flush()
    return bookmark


def update_bookmark(db: Session, bookmark: WebsiteBookmark) -> None:
    db.add(bookmark)
    db.flush()


def delete_bookmark(db: Session, bookmark: WebsiteBookmark) -> None:
    db.delete(bookmark)
    db.flush()


def delete_bookmarks_by_folders(db: Session, folder_ids: list[int], user_id: int) -> None:
    if not folder_ids:
        return
    db.execute(
        sa_delete(WebsiteBookmark).where(
            WebsiteBookmark.folder_id.in_(folder_ids), WebsiteBookmark.user_id == user_id
        )
    )
    db.flush()


def find_cached_icon(db: Session, bookmark_id: int, user_id: int) -> tuple[bytes, str] | None:
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
    bookmark.icon_data = data
    bookmark.icon_content_type = content_type
    db.add(bookmark)
    db.flush()


def clear_cached_icon(db: Session, bookmark: WebsiteBookmark) -> None:
    bookmark.icon_data = None
    bookmark.icon_content_type = None
    db.add(bookmark)
    db.flush()
