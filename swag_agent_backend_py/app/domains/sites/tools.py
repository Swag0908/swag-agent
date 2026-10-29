"""常用网站工具（8 个）——schema 与 description 逐字对齐 Java `WebsiteTools`。

约定：
- 用户身份从 `ToolCtx.user_id` 取；
- 业务失败返回中文文案、不抛异常（Java 用 try/catch ResponseStatusException + reason()）；
- 分类/网站引用支持 `#id`、名称、完整网址，同名歧义时要求用户按 #id 指定。
"""

from __future__ import annotations

from urllib.parse import urlsplit

from starlette.concurrency import run_in_threadpool

from app.agent.tools.registry import ToolCtx, tool
from app.core.errors import AppError
from app.domains.sites import service as site_service
from app.domains.sites import views

EMPTY_PARAMS = {"type": "object", "properties": {}, "required": []}

LIST_FOLDERS_DESC = (
    "列出当前用户（我）常用网站菜单里的「分类树」：每个分类的 #id、名称、"
    "层级路径、内含网站数。其它网站工具请优先按这里的 #id 引用分类"
)
LIST_BOOKMARKS_DESC = (
    "查询当前用户（我）常用网站菜单里的网站列表：每条含 #id、名称、网址、"
    "所属分类、备注。keyword 可空（空=全部），按名称/网址/备注模糊匹配；"
    "categoryId 传分类 #id 只查该分类直属的网站。可用于查找网站 #id 以便修改/删除，或添加前查重"
)
ADD_BOOKMARK_DESC = (
    "把网站添加到当前用户（我）的常用网站菜单（用户维度，只会加到我的菜单）。"
    "url 必填。category 可空（空=未分类），支持分类 #id 或分类名；"
    "分类名必须与现有分类完全一致：若不存在，除非用户已明确同意新建，否则先向用户确认是"
    "「新建同名分类」还是「放入含义相近的现有分类」（可先用 listSiteFolders 查看），"
    "用户同意新建后再调用并把 createCategoryIfMissing 设为 true。"
    "若该网址已存在会直接返回已有记录，不会重复添加。"
    "name 不填默认取网址域名作为名称，icon 留空前端会自动取图标"
)
UPDATE_BOOKMARK_DESC = (
    "修改已添加的网站。ref 为网站 #id 或完整网址或名称；"
    "只传需要改的字段，未传的字段保留原值；category 传「未分类」可把网站移出分类；"
    "传新分类 #id/分类名可移动；改网址时会检查是否与其它网站重复"
)
DELETE_BOOKMARK_DESC = (
    "从当前用户（我）的常用网站菜单里删除一个网站。ref 为网站 #id 或完整网址或名称；"
    "删除是不可恢复操作，请先向用户确认再调用"
)
CREATE_FOLDER_DESC = (
    "在当前用户（我）的常用网站菜单里新建一个分类文件夹。"
    "name 必填；parentCategory 可空=顶层分类，支持父分类 #id 或父分类名。"
    "若已存在同名分类会提示，请先向用户确认是直接使用还是仍要新建"
)
UPDATE_FOLDER_DESC = (
    "重命名或移动当前用户（我）的分类文件夹。"
    "folderRef 为分类 #id 或分类名；newName 可空=不改名；"
    "parentCategory 可空=保持当前位置，传「根目录」可移到顶层"
)
DELETE_FOLDER_DESC = (
    "删除当前用户（我）的一个分类文件夹。cascade=false（默认）时，"
    "若分类下还有网站或子分类会返回提示而不删除，需先向用户确认后"
    "再以 cascade=true 级联删除其中的网站和子分类；删除不可恢复，请先确认"
)

ROOT_TOKENS = {"未分类", "无", "无分类", "根目录", "root"}


def _session():  # noqa: ANN202 - 便于测试 monkeypatch
    from app.db.base import SessionLocal

    return SessionLocal()


def _run(fn, *args):  # noqa: ANN001
    def call():
        with _session() as db:
            return fn(db, *args)

    return run_in_threadpool(call)


def _user_id(ctx: ToolCtx) -> int | None:
    value = getattr(ctx, "user_id", None)
    return int(value) if value is not None else None


# ---------------------------------------------------------------------------
# 内部索引与引用解析（对应 Java WebsiteTools 私有方法）
# ---------------------------------------------------------------------------


def _library(db, uid: int) -> views.Library:  # noqa: ANN001
    return site_service.library(db, uid, None, None, False)


def _index_of(lib: views.Library) -> dict[int, views.FolderNode]:
    index: dict[int, views.FolderNode] = {}
    _flatten(lib.folders, index)
    return index


def _flatten(nodes: list[views.FolderNode], out: dict[int, views.FolderNode]) -> None:
    for node in nodes:
        out[node.id] = node
        if node.children:
            _flatten(node.children, out)


def _append_folder_tree(lines: list[str], nodes: list[views.FolderNode], depth: int) -> None:
    for node in nodes:
        lines.append(f"{'  ' * depth}#{node.id} {node.name}（{node.bookmark_count} 个网站）")
        if node.children:
            _append_folder_tree(lines, node.children, depth + 1)


def _ids_by_folder_name(index: dict[int, views.FolderNode], name: str) -> list[int]:
    return [node.id for node in index.values() if node.name.strip().lower() == name.lower()]


def _list_folder_ids(index: dict[int, views.FolderNode], ids: list[int]) -> str:
    return "、".join(f"#{fid} {_folder_name(index, fid)}" for fid in ids)


def _ambiguous_folders_message(index: dict[int, views.FolderNode], ids: list[int]) -> str:
    return f"同名分类有多个：{_list_folder_ids(index, ids)}。请让用户确认用哪一个（可按 #id 指定）。"


def _existing_folders_line(index: dict[int, views.FolderNode]) -> str:
    parts = [f"#{node.id} {node.name}" for node in index.values()]
    return "、".join(parts) if parts else "暂无分类"


def _folder_name(index: dict[int, views.FolderNode], folder_id: int) -> str:
    node = index.get(folder_id)
    return node.name if node is not None else f"#{folder_id}"


def _path_of(index: dict[int, views.FolderNode], folder_id: int) -> str:
    parts: list[str] = []
    current: int | None = folder_id
    while current is not None:
        node = index.get(current)
        if node is None:
            break
        parts.insert(0, node.name)
        current = node.parent_id
    return "/".join(parts)


def _resolve_folder_id(index: dict[int, views.FolderNode], ref: str) -> int | None:
    clean = ref.strip()
    parsed = _parse_id(clean)
    if parsed is not None:
        if parsed in index:
            return parsed
        raise AppError(400, f"分类不存在：#{parsed}，请先用 listSiteFolders 查看现有分类。")
    if _is_root_token(clean):
        return None
    ids = _ids_by_folder_name(index, clean)
    if not ids:
        raise AppError(
            400,
            f"未找到名为「{clean}」的分类（现有分类：{_existing_folders_line(index)}）。"
            "请先询问用户是新建该分类还是放入含义相近的现有分类。",
        )
    if len(ids) > 1:
        raise AppError(400, _ambiguous_folders_message(index, ids))
    return ids[0]


def _resolve_bookmark(
    index: dict[int, views.FolderNode], lib: views.Library, ref: str
) -> views.BookmarkView:
    clean = ref.strip()
    parsed = _parse_id(clean)
    if parsed is not None:
        for bookmark in lib.bookmarks:
            if bookmark.id == parsed:
                return bookmark
        raise AppError(400, f"没有找到网站 #{parsed}，请先用 listSiteBookmarks 确认 #id。")

    url_candidate: str | None = None
    if "://" in clean or (" " not in clean and "." in clean):
        try:
            url_candidate = site_service.normalize_url(clean)
        except AppError:
            url_candidate = None

    url_matches = [
        b for b in lib.bookmarks if url_candidate is not None and b.url.lower() == url_candidate.lower()
    ]
    name_matches = [b for b in lib.bookmarks if b.name.strip().lower() == clean.lower()]
    if len(url_matches) == 1:
        return url_matches[0]
    if len(url_matches) > 1:
        raise AppError(
            400,
            f"该网址对应多条记录：{_bookmark_ids_text(url_matches)}，请让用户按 #id 指定。",
        )
    if len(name_matches) == 1:
        return name_matches[0]
    if len(name_matches) > 1:
        raise AppError(
            400, f"同名网站有多个：{_bookmark_ids_text(name_matches)}，请让用户按 #id 指定。"
        )
    raise AppError(400, f"没有找到「{clean}」对应的网站，请先用 listSiteBookmarks 查询确认 #id。")


def _bookmark_ids_text(items: list[views.BookmarkView]) -> str:
    return "、".join(f"#{b.id} {b.name}" for b in items)


def _parse_id(text: str) -> int | None:
    value = text[1:] if text.startswith("#") else text
    if not value or not value.isdigit():
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _is_root_token(text: str) -> bool:
    return text.strip().lower() in ROOT_TOKENS


def _clean(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    return value.strip()


def _truthy(value: bool | str | None) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes"}
    return False


def _default_name(normalized_url: str) -> str:
    try:
        host = urlsplit(normalized_url).hostname
    except ValueError:
        return normalized_url
    if not host:
        return normalized_url
    return host[4:] if host.startswith("www.") else host


# ---------------------------------------------------------------------------
# 同步实现（在 threadpool 中执行）
# ---------------------------------------------------------------------------


def _list_site_folders(db, uid: int) -> str:  # noqa: ANN001
    lib = _library(db, uid)
    index = _index_of(lib)
    if not lib.folders:
        return (
            "常用网站菜单里还没有分类。可对未分类的网站直接使用 addSiteBookmark，"
            "或用 createSiteFolder 先建分类。"
        )
    lines = [f"我的常用网站分类（共 {len(index)} 个）："]
    _append_folder_tree(lines, lib.folders, 0)
    unclassified = sum(1 for b in lib.bookmarks if b.folder_id is None)
    if unclassified > 0:
        lines.append(f"未分类网站：{unclassified} 个（未归入任何分类）")
    return "\n".join(lines).strip()


def _list_site_bookmarks(db, uid: int, keyword, category_id) -> str:  # noqa: ANN001
    lib = _library(db, uid)
    index = _index_of(lib)

    folder_id: int | None = None
    unclassified = False
    if category_id is not None and category_id.strip():
        parsed = _parse_id(category_id)
        if parsed is not None:
            if parsed in index:
                folder_id = parsed
            else:
                return f"分类不存在：#{parsed}，请先用 listSiteFolders 查看现有分类。"
        elif _is_root_token(category_id):
            unclassified = True
        else:
            ids = _ids_by_folder_name(index, category_id.strip())
            if not ids:
                return f"未找到名为「{category_id.strip()}」的分类，请先用 listSiteFolders 查看现有分类。"
            if len(ids) > 1:
                return _ambiguous_folders_message(index, ids)
            folder_id = ids[0]

    keyword = None if keyword is None or not keyword.strip() else keyword
    if keyword is None and folder_id is None and not unclassified:
        bookmark_views = lib.bookmarks
    else:
        bookmark_views = site_service.library(db, uid, folder_id, keyword, unclassified).bookmarks

    if not bookmark_views:
        if keyword is not None:
            return f"没有找到匹配「{keyword}」的网站。"
        if folder_id is not None:
            return f"分类「{_folder_name(index, folder_id)}」下还没有网站。"
        if unclassified:
            return "未分类下还没有网站。"
        return "常用网站菜单还是空的，可以直接用 addSiteBookmark 添加。"

    lines = [f"我的常用网站（共 {len(bookmark_views)} 个）："]
    for bookmark in bookmark_views:
        line = f"#{bookmark.id} {bookmark.name}"
        if bookmark.folder_id is not None:
            line += f"（分类：{_path_of(index, bookmark.folder_id)}）"
        else:
            line += "（未分类）"
        line += f"\n  网址：{bookmark.url}"
        if bookmark.description is not None and bookmark.description.strip():
            line += f"\n  备注：{bookmark.description}"
        lines.append(line)
    return "\n".join(lines).strip()


def _add_site_bookmark(db, uid, url, name, description, category, create_if_missing) -> str:  # noqa: ANN001
    if url is None or not url.strip():
        return "网址不能为空，请让用户补充网站链接。"
    normalized = site_service.normalize_url(url)

    lib = _library(db, uid)
    index = _index_of(lib)
    for bookmark in lib.bookmarks:
        if bookmark.url.lower() == normalized.lower():
            location = (
                f"（分类：{_path_of(index, bookmark.folder_id)}）"
                if bookmark.folder_id is not None
                else "（未分类）"
            )
            return (
                f"该网址已在我的常用网站里：#{bookmark.id} {bookmark.name}{location}，"
                "无需重复添加。如需移动分类或改名可用 updateSiteBookmark。"
            )

    folder_id: int | None = None
    if category is not None and category.strip():
        parsed = _parse_id(category)
        if parsed is not None:
            if parsed not in index:
                return f"分类不存在：#{parsed}，请先用 listSiteFolders 查看现有分类。"
            folder_id = parsed
        elif _is_root_token(category):
            folder_id = None
        else:
            ids = _ids_by_folder_name(index, category.strip())
            if len(ids) == 1:
                folder_id = ids[0]
            elif len(ids) > 1:
                return _ambiguous_folders_message(index, ids)
            else:
                if not _truthy(create_if_missing):
                    return (
                        f"我的分类里没有「{category.strip()}」。现有分类："
                        f"{_existing_folders_line(index)}"
                        "。请先询问用户：新建该分类，还是放入含义相近的现有分类？"
                        "用户同意新建后再调用本工具并传 createCategoryIfMissing=true。"
                    )
                created = site_service.create_folder(db, uid, category.strip(), None)
                folder_id = created.id

    final_name = _clean(name) or _default_name(normalized)
    view = site_service.create_bookmark(db, uid, final_name, normalized, _clean(description), None, folder_id)
    location = (
        f"（分类：{_folder_name(index, folder_id)}）" if folder_id is not None else "（未分类）"
    )
    return f"已添加到常用网站：#{view.id} {view.name}{location}。网址：{view.url}"


def _update_site_bookmark(db, uid, ref, name, url, description, category) -> str:  # noqa: ANN001
    if ref is None or not ref.strip():
        return "请提供要修改的网站（#id、网址或名称）。"
    lib = _library(db, uid)
    index = _index_of(lib)
    current = _resolve_bookmark(index, lib, ref)

    final_name = name.strip() if name is not None and name.strip() else current.name
    final_url = current.url
    if url is not None and url.strip():
        final_url = site_service.normalize_url(url)
        for bookmark in lib.bookmarks:
            if bookmark.id != current.id and bookmark.url.lower() == final_url.lower():
                return (
                    f"已有其它网站使用该网址：#{bookmark.id} {bookmark.name}，"
                    "为避免重复请先与用户确认是否仍要修改。"
                )

    if description is None:
        final_description = current.description
    elif not description.strip():
        final_description = None
    else:
        final_description = description.strip()

    final_icon = current.icon_url
    folder_id = current.folder_id
    if category is not None and category.strip():
        folder_id = _resolve_folder_id(index, category)

    view = site_service.update_bookmark(
        db, uid, current.id, final_name, final_url, final_description, final_icon, folder_id
    )
    location = (
        f"（分类：{_folder_name(index, view.folder_id)}）"
        if view.folder_id is not None
        else "（未分类）"
    )
    return f"已更新网站 #{view.id} {view.name}{location}"


def _delete_site_bookmark(db, uid, ref) -> str:  # noqa: ANN001
    lib = _library(db, uid)
    index = _index_of(lib)
    target = _resolve_bookmark(index, lib, ref)
    site_service.delete_bookmark(db, uid, target.id)
    return f"已从常用网站删除：#{target.id} {target.name}（{target.url}）。"


def _create_site_folder(db, uid, name, parent_category) -> str:  # noqa: ANN001
    if name is None or not name.strip():
        return "分类名称不能为空，请让用户补充。"
    clean_name = name.strip()
    lib = _library(db, uid)
    index = _index_of(lib)
    same = _ids_by_folder_name(index, clean_name)
    if same:
        return (
            f"已存在同名分类：{_list_folder_ids(index, same)}。"
            "请先询问用户是直接使用现有分类，还是仍要新建一个。"
        )
    parent_id: int | None = None
    if parent_category is not None and parent_category.strip():
        parent_id = _resolve_folder_id(index, parent_category)
    created = site_service.create_folder(db, uid, clean_name, parent_id)
    location = (
        f"（上级：{_folder_name(index, parent_id)}）" if parent_id is not None else "（顶层分类）"
    )
    return f"已新建分类 #{created.id} {created.name}{location}"


def _update_site_folder(db, uid, folder_ref, new_name, parent_category) -> str:  # noqa: ANN001
    lib = _library(db, uid)
    index = _index_of(lib)
    folder_id = _resolve_folder_id(index, folder_ref)
    folder = index.get(folder_id) if folder_id is not None else None
    if folder is None:
        # Java 对「根目录」这类无 id 的 ref 会 NPE；这里收敛成可转述的失败文案。
        return "更新失败：没有找到对应分类。"

    final_name = folder.name
    if new_name is not None and new_name.strip():
        clean_name = new_name.strip()
        if clean_name != folder.name:
            same = _ids_by_folder_name(index, clean_name)
            if same:
                return (
                    f"已存在同名分类：{_list_folder_ids(index, same)}，"
                    "为避免混乱请先与用户确认。"
                )
        final_name = clean_name

    parent_id = folder.parent_id
    if parent_category is not None and parent_category.strip():
        parent_id = _resolve_folder_id(index, parent_category)
    site_service.update_folder(db, uid, folder_id, final_name, parent_id)
    location = (
        f"（上级：{_folder_name(index, parent_id)}）" if parent_id is not None else "（顶层分类）"
    )
    return f"已更新分类 #{folder_id} {final_name}{location}"


def _delete_site_folder(db, uid, folder_ref, cascade) -> str:  # noqa: ANN001
    lib = _library(db, uid)
    index = _index_of(lib)
    folder_id = _resolve_folder_id(index, folder_ref)
    label = _folder_name(index, folder_id)
    is_cascade = _truthy(cascade)
    site_service.delete_folder(db, uid, folder_id, is_cascade)
    suffix = "（含其中网站与子分类）" if is_cascade else ""
    return f"已删除分类 {label}{suffix}。"


# ---------------------------------------------------------------------------
# 工具注册
# ---------------------------------------------------------------------------


@tool(name="listSiteFolders", description=LIST_FOLDERS_DESC, parameters=EMPTY_PARAMS, side_effect="read")
async def list_site_folders(ctx: ToolCtx) -> str:
    uid = _user_id(ctx)
    if uid is None:
        return "未登录，无法操作常用网站"
    try:
        return await _run(_list_site_folders, uid)
    except AppError as exc:
        return exc.message


@tool(
    name="listSiteBookmarks",
    description=LIST_BOOKMARKS_DESC,
    parameters={
        "type": "object",
        "properties": {
            "keyword": {"type": "string", "description": "搜索关键词，匹配名称/网址/备注，可为空"},
            "categoryId": {"type": "string", "description": "分类 #id，只列出该分类下的网站，可为空"},
        },
        "required": ["keyword", "categoryId"],
    },
    side_effect="read",
)
async def list_site_bookmarks(keyword: str, categoryId: str, ctx: ToolCtx) -> str:  # noqa: N803
    uid = _user_id(ctx)
    if uid is None:
        return "未登录，无法操作常用网站"
    try:
        return await _run(_list_site_bookmarks, uid, keyword, categoryId)
    except AppError as exc:
        return exc.message


@tool(
    name="addSiteBookmark",
    description=ADD_BOOKMARK_DESC,
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "网站链接，必填，如 https://github.com"},
            "name": {"type": "string", "description": "网站名称，可为空，留空默认取网址域名"},
            "description": {"type": "string", "description": "备注/用途，可为空"},
            "category": {
                "type": "string",
                "description": "分类 #id 或分类名，可为空（空=未分类），如「#12」或「开发工具」",
            },
            "createCategoryIfMissing": {
                "type": "boolean",
                "description": "分类不存在时是否自动新建同名分类；仅当用户明确同意新建时才传 true",
            },
        },
        "required": ["url", "name", "description", "category", "createCategoryIfMissing"],
    },
    side_effect="write",
)
async def add_site_bookmark(
    url: str,
    name: str,
    description: str,
    category: str,
    createCategoryIfMissing: bool,  # noqa: N803
    ctx: ToolCtx,
) -> str:
    uid = _user_id(ctx)
    if uid is None:
        return "未登录，无法操作常用网站"
    try:
        return await _run(_add_site_bookmark, uid, url, name, description, category, createCategoryIfMissing)
    except AppError as exc:
        return f"添加失败：{exc.message}"


@tool(
    name="updateSiteBookmark",
    description=UPDATE_BOOKMARK_DESC,
    parameters={
        "type": "object",
        "properties": {
            "ref": {"type": "string", "description": "要修改的网站：#id、完整网址或名称"},
            "name": {"type": "string", "description": "新的网站名称，可空=不改"},
            "url": {"type": "string", "description": "新的网址，可空=不改"},
            "description": {"type": "string", "description": "新的备注，可空=不改；传空字符串可清空备注"},
            "category": {
                "type": "string",
                "description": "目标分类 #id 或分类名；传「未分类」=移出分类；可空=分类不变",
            },
        },
        "required": ["ref", "name", "url", "description", "category"],
    },
    side_effect="write",
)
async def update_site_bookmark(
    ref: str, name: str, url: str, description: str, category: str, ctx: ToolCtx
) -> str:
    uid = _user_id(ctx)
    if uid is None:
        return "未登录，无法操作常用网站"
    try:
        return await _run(_update_site_bookmark, uid, ref, name, url, description, category)
    except AppError as exc:
        return f"修改失败：{exc.message}"


@tool(
    name="deleteSiteBookmark",
    description=DELETE_BOOKMARK_DESC,
    parameters={
        "type": "object",
        "properties": {"ref": {"type": "string", "description": "要删除的网站：#id、完整网址或名称"}},
        "required": ["ref"],
    },
    side_effect="delete",
)
async def delete_site_bookmark(ref: str, ctx: ToolCtx) -> str:
    uid = _user_id(ctx)
    if uid is None:
        return "未登录，无法操作常用网站"
    try:
        return await _run(_delete_site_bookmark, uid, ref)
    except AppError as exc:
        return f"删除失败：{exc.message}"


@tool(
    name="createSiteFolder",
    description=CREATE_FOLDER_DESC,
    parameters={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "新分类名称，必填，如「开发工具」"},
            "parentCategory": {
                "type": "string",
                "description": "上级分类 #id 或分类名，可空=建为顶层分类",
            },
        },
        "required": ["name", "parentCategory"],
    },
    side_effect="write",
)
async def create_site_folder(name: str, parentCategory: str, ctx: ToolCtx) -> str:  # noqa: N803
    uid = _user_id(ctx)
    if uid is None:
        return "未登录，无法操作常用网站"
    try:
        return await _run(_create_site_folder, uid, name, parentCategory)
    except AppError as exc:
        return f"创建失败：{exc.message}"


@tool(
    name="updateSiteFolder",
    description=UPDATE_FOLDER_DESC,
    parameters={
        "type": "object",
        "properties": {
            "folderRef": {"type": "string", "description": "要修改的分类：#id 或分类名"},
            "newName": {"type": "string", "description": "新的分类名称，可空=不改名"},
            "parentCategory": {
                "type": "string",
                "description": "新的上级分类 #id 或分类名；传「根目录」=移到顶层；可空=不动",
            },
        },
        "required": ["folderRef", "newName", "parentCategory"],
    },
    side_effect="write",
)
async def update_site_folder(
    folderRef: str, newName: str, parentCategory: str, ctx: ToolCtx  # noqa: N803
) -> str:
    uid = _user_id(ctx)
    if uid is None:
        return "未登录，无法操作常用网站"
    try:
        return await _run(_update_site_folder, uid, folderRef, newName, parentCategory)
    except AppError as exc:
        return f"更新失败：{exc.message}"


@tool(
    name="deleteSiteFolder",
    description=DELETE_FOLDER_DESC,
    parameters={
        "type": "object",
        "properties": {
            "folderRef": {"type": "string", "description": "要删除的分类：#id 或分类名"},
            "cascade": {
                "type": "boolean",
                "description": "是否连同其中网站/子分类一并删除，默认 false；需用户明确同意级联删除才传 true",
            },
        },
        "required": ["folderRef", "cascade"],
    },
    side_effect="delete",
)
async def delete_site_folder(folderRef: str, cascade: bool, ctx: ToolCtx) -> str:  # noqa: N803
    uid = _user_id(ctx)
    if uid is None:
        return "未登录，无法操作常用网站"
    try:
        return await _run(_delete_site_folder, uid, folderRef, cascade)
    except AppError as exc:
        # Java 对非空分类未级联的 409 直接返回原因文案，供模型转述并征得同意。
        return exc.message


__all__ = [
    "list_site_folders",
    "list_site_bookmarks",
    "add_site_bookmark",
    "update_site_bookmark",
    "delete_site_bookmark",
    "create_site_folder",
    "update_site_folder",
    "delete_site_folder",
]
