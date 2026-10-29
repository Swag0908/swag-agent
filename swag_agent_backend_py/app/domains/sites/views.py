"""常用网站的视图对象：字段名与 Java `WebsiteViews` 完全一致。"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core import timeutil
from app.db.models import WebsiteBookmark


@dataclass
class FolderNode:
    id: int
    name: str
    parent_id: int | None
    sort_order: int
    bookmark_count: int
    children: list["FolderNode"] = field(default_factory=list)


@dataclass
class BookmarkView:
    id: int
    folder_id: int | None
    name: str
    url: str
    description: str | None
    icon_url: str | None
    sort_order: int
    created_at: object  # noqa: ANN401  datetime
    updated_at: object  # noqa: ANN401  datetime


@dataclass
class Library:
    folders: list[FolderNode]
    bookmarks: list[BookmarkView]
    total: int


def bookmark_view(bookmark: WebsiteBookmark) -> BookmarkView:
    return BookmarkView(
        id=bookmark.id,
        folder_id=bookmark.folder_id,
        name=bookmark.name,
        url=bookmark.url,
        description=bookmark.description,
        icon_url=bookmark.icon_url,
        sort_order=bookmark.sort_order,
        created_at=bookmark.created_at,
        updated_at=bookmark.updated_at,
    )


def folder_to_dict(node: FolderNode) -> dict:
    return {
        "id": node.id,
        "name": node.name,
        "parentId": node.parent_id,
        "sortOrder": node.sort_order,
        "bookmarkCount": node.bookmark_count,
        "children": [folder_to_dict(child) for child in node.children],
    }


def bookmark_to_dict(view: BookmarkView) -> dict:
    return {
        "id": view.id,
        "folderId": view.folder_id,
        "name": view.name,
        "url": view.url,
        "description": view.description,
        "iconUrl": view.icon_url,
        "sortOrder": view.sort_order,
        "createdAt": timeutil.local_datetime_json(view.created_at),
        "updatedAt": timeutil.local_datetime_json(view.updated_at),
    }


def library_to_dict(library: Library) -> dict:
    return {
        "folders": [folder_to_dict(node) for node in library.folders],
        "bookmarks": [bookmark_to_dict(view) for view in library.bookmarks],
        "total": library.total,
    }
