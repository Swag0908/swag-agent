"""常用网站业务逻辑：文件夹树与书签 CRUD，对齐 Java `WebsiteService`。

注意两个容易误读的点：
1. `GET /bookmarks?folderId=` 的过滤在 Java 里是**直属**文件夹（`folder_id = ?`），
   不含子孙目录；只有树节点上的 `bookmarkCount` 才是整棵子树的计数。
2. 更新书签时，只有 url 或 iconUrl 变化才清空已缓存图标。
"""

from __future__ import annotations

from urllib.parse import urlsplit

from sqlalchemy.orm import Session

from app.core import timeutil
from app.core.errors import AppError, BadRequest, NotFound
from app.db.models import WebsiteBookmark, WebsiteFolder
from app.domains.sites import repository, views


def library(
    db: Session,
    user_id: int,
    folder_id: int | None,
    query: str | None,
    unclassified_only: bool,
) -> views.Library:
    folders = repository.list_folders(db, user_id)
    all_bookmarks = repository.list_bookmarks(db, user_id, None, None, False)
    descendants = _build_descendants(folders)

    subtree_counts: dict[int, int] = {}
    for folder in folders:
        ids: set[int] = set()
        _collect_folder_ids(folder.id, descendants, ids)
        count = 0
        for bookmark in all_bookmarks:
            if bookmark.folder_id is not None and bookmark.folder_id in ids:
                count += 1
        subtree_counts[folder.id] = count

    tree = _build_tree(folders, subtree_counts, None)
    filtered = repository.list_bookmarks(db, user_id, folder_id, query, unclassified_only)
    bookmark_views = [views.bookmark_view(bookmark) for bookmark in filtered]
    return views.Library(tree, bookmark_views, len(bookmark_views))


def create_folder(
    db: Session, user_id: int, name: str | None, parent_id: int | None
) -> views.FolderNode:
    clean_name = _require_name(name, "文件夹名称不能为空")
    _ensure_parent(db, user_id, parent_id)
    now = timeutil.now()
    folder = WebsiteFolder(
        user_id=user_id,
        name=clean_name,
        parent_id=parent_id,
        sort_order=_next_folder_order(db, user_id, parent_id),
        created_at=now,
        updated_at=now,
    )
    repository.insert_folder(db, folder)
    db.commit()
    return views.FolderNode(folder.id, folder.name, folder.parent_id, folder.sort_order, 0, [])


def update_folder(
    db: Session, user_id: int, folder_id: int, name: str | None, parent_id: int | None
) -> views.FolderNode:
    folder = _resolve_folder(db, user_id, folder_id)
    clean_name = _require_name(name, "文件夹名称不能为空")
    _ensure_parent(db, user_id, parent_id)
    if parent_id is not None:
        _ensure_not_descendant(db, user_id, folder_id, parent_id)
    folder.name = clean_name
    folder.parent_id = parent_id
    folder.updated_at = timeutil.now()
    repository.update_folder(db, folder)
    db.commit()
    return views.FolderNode(folder.id, folder.name, folder.parent_id, folder.sort_order, 0, [])


def delete_folder(db: Session, user_id: int, folder_id: int, cascade: bool) -> None:
    _resolve_folder(db, user_id, folder_id)
    folders = repository.list_folders(db, user_id)
    descendants = _build_descendants(folders)
    ids: set[int] = set()
    _collect_folder_ids(folder_id, descendants, ids)

    bookmarks = repository.list_bookmarks(db, user_id, None, None, False)
    bookmark_count = sum(1 for b in bookmarks if b.folder_id is not None and b.folder_id in ids)
    child_folder_count = len(ids) - 1

    if not cascade and (bookmark_count > 0 or child_folder_count > 0):
        suffix = f"和 {child_folder_count} 个子文件夹" if child_folder_count > 0 else ""
        raise AppError(409, f"该文件夹不为空，确认删除其中的 {bookmark_count} 个网站{suffix}？")

    id_list = list(ids)
    repository.delete_bookmarks_by_folders(db, id_list, user_id)
    repository.delete_folders(db, id_list, user_id)
    db.commit()


def create_bookmark(
    db: Session,
    user_id: int,
    name: str | None,
    url: str | None,
    description: str | None,
    icon_url: str | None,
    folder_id: int | None,
) -> views.BookmarkView:
    clean_name = _require_name(name, "网站名称不能为空")
    clean_url = normalize_url(url)
    _ensure_folder(db, user_id, folder_id)
    now = timeutil.now()
    bookmark = WebsiteBookmark(
        user_id=user_id,
        folder_id=folder_id,
        name=clean_name,
        url=clean_url,
        description=_clean_nullable(description),
        icon_url=_clean_nullable(icon_url),
        sort_order=_next_bookmark_order(db, user_id, folder_id),
        created_at=now,
        updated_at=now,
    )
    repository.insert_bookmark(db, bookmark)
    db.commit()
    return views.bookmark_view(bookmark)


def update_bookmark(
    db: Session,
    user_id: int,
    bookmark_id: int,
    name: str | None,
    url: str | None,
    description: str | None,
    icon_url: str | None,
    folder_id: int | None,
) -> views.BookmarkView:
    bookmark = _resolve_bookmark(db, user_id, bookmark_id)
    clean_name = _require_name(name, "网站名称不能为空")
    clean_url = normalize_url(url)
    _ensure_folder(db, user_id, folder_id)
    clean_icon_url = _clean_nullable(icon_url)
    source_changed = clean_url != bookmark.url or clean_icon_url != bookmark.icon_url

    bookmark.name = clean_name
    bookmark.url = clean_url
    bookmark.description = _clean_nullable(description)
    bookmark.icon_url = clean_icon_url
    bookmark.folder_id = folder_id
    bookmark.updated_at = timeutil.now()
    repository.update_bookmark(db, bookmark)
    if source_changed:
        repository.clear_cached_icon(db, bookmark)
    db.commit()
    return views.bookmark_view(bookmark)


def delete_bookmark(db: Session, user_id: int, bookmark_id: int) -> None:
    bookmark = _resolve_bookmark(db, user_id, bookmark_id)
    repository.delete_bookmark(db, bookmark)
    db.commit()


def normalize_url(raw: str | None) -> str:
    """规范化网址：缺协议补 https://，仅允许 http/https。"""
    if raw is None or not raw.strip():
        raise BadRequest("网址不能为空")
    value = raw.strip()
    if "://" not in value:
        value = "https://" + value
    if any(ch.isspace() or ord(ch) < 0x20 or ord(ch) == 0x7F for ch in value):
        raise BadRequest("请输入合法的网址")
    try:
        parts = urlsplit(value)
        scheme = parts.scheme
        host = parts.hostname
    except ValueError as exc:
        raise BadRequest("请输入合法的网址") from exc
    if scheme is None or host is None or scheme.lower() not in {"http", "https"}:
        raise BadRequest("请输入合法的 http/https 网址")
    # java.net.URI 允许 99999 这类超范围端口（只校验“必须全为数字”），这里保持一致。
    authority = parts.netloc.rsplit("@", 1)[-1]
    if authority and not authority.startswith("["):
        _, sep, port_text = authority.rpartition(":")
        if sep and port_text and not port_text.isdigit():
            raise BadRequest("请输入合法的网址")
    try:
        host.encode("ascii")
    except UnicodeEncodeError as exc:
        # Java URI.getHost() 对非 ASCII 主机返回 null → 400
        raise BadRequest("请输入合法的 http/https 网址") from exc
    return value


def _build_tree(
    folders: list[WebsiteFolder], counts: dict[int, int], parent_id: int | None
) -> list[views.FolderNode]:
    result: list[views.FolderNode] = []
    for folder in folders:
        if folder.parent_id == parent_id:
            result.append(
                views.FolderNode(
                    id=folder.id,
                    name=folder.name,
                    parent_id=folder.parent_id,
                    sort_order=folder.sort_order,
                    bookmark_count=counts.get(folder.id, 0),
                    children=_build_tree(folders, counts, folder.id),
                )
            )
    return result


def _build_descendants(folders: list[WebsiteFolder]) -> dict[int, list[int]]:
    result: dict[int, list[int]] = {}
    for folder in folders:
        result.setdefault(folder.id, [])
        if folder.parent_id is not None:
            result.setdefault(folder.parent_id, []).append(folder.id)
    return result


def _collect_folder_ids(folder_id: int, descendants: dict[int, list[int]], result: set[int]) -> None:
    result.add(folder_id)
    for child in descendants.get(folder_id, []):
        if child not in result:
            _collect_folder_ids(child, descendants, result)


def _ensure_not_descendant(db: Session, user_id: int, folder_id: int, parent_id: int) -> None:
    folders = repository.list_folders(db, user_id)
    descendants = _build_descendants(folders)
    ids: set[int] = set()
    _collect_folder_ids(folder_id, descendants, ids)
    if parent_id in ids:
        raise BadRequest("不能把文件夹移动到它自己的子文件夹下")


def _ensure_parent(db: Session, user_id: int, parent_id: int | None) -> None:
    if parent_id is None:
        return
    _resolve_folder(db, user_id, parent_id)


def _ensure_folder(db: Session, user_id: int, folder_id: int | None) -> None:
    if folder_id is None:
        return
    _resolve_folder(db, user_id, folder_id)


def _resolve_folder(db: Session, user_id: int, folder_id: int) -> WebsiteFolder:
    folder = repository.find_folder(db, folder_id)
    if folder is None or folder.user_id != user_id:
        raise NotFound(f"文件夹不存在：#{folder_id}")
    return folder


def _resolve_bookmark(db: Session, user_id: int, bookmark_id: int) -> WebsiteBookmark:
    bookmark = repository.find_bookmark(db, bookmark_id)
    if bookmark is None or bookmark.user_id != user_id:
        raise NotFound(f"网站不存在：#{bookmark_id}")
    return bookmark


def _next_folder_order(db: Session, user_id: int, parent_id: int | None) -> int:
    return sum(1 for folder in repository.list_folders(db, user_id) if folder.parent_id == parent_id)


def _next_bookmark_order(db: Session, user_id: int, folder_id: int | None) -> int:
    return len(repository.list_bookmarks(db, user_id, folder_id, None, folder_id is None))


def _require_name(name: str | None, message: str) -> str:
    if name is None or not name.strip():
        raise BadRequest(message)
    value = name.strip()
    if len(value) > 64:
        raise BadRequest("名称不能超过 64 个字符")
    return value


def _clean_nullable(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    return value.strip()


__all__ = [
    "library",
    "create_folder",
    "update_folder",
    "delete_folder",
    "create_bookmark",
    "update_bookmark",
    "delete_bookmark",
    "normalize_url",
]
