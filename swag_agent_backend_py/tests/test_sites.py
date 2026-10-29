"""常用网站模块单测：URL 规范化、文件夹树/计数、级联删除、图标缓存、REST 与工具 schema。

只用 SQLite 内存库；图标网络请求全部 monkeypatch，不发真实外网请求。
"""

from __future__ import annotations

import asyncio
import types
from contextlib import nullcontext

import pytest

from app.core.errors import AppError, BadRequest, NotFound
from app.db.models import WebsiteBookmark
from app.domains.sites import icon as icon_service
from app.domains.sites import repository, service


def _folder(db, user_id=1, name="开发工具", parent_id=None):
    return service.create_folder(db, user_id, name, parent_id)


def _bookmark(db, user_id=1, name="GitHub", url="github.com", folder_id=None):
    return service.create_bookmark(db, user_id, name, url, "代码托管", None, folder_id)


# ---------------------------------------------------------------------------
# URL 规范化
# ---------------------------------------------------------------------------


def test_normalize_url_adds_https_and_keeps_original():
    assert service.normalize_url("github.com") == "https://github.com"
    assert service.normalize_url("  https://github.com/a?b=1  ") == "https://github.com/a?b=1"
    assert service.normalize_url("http://example.com:8080/x") == "http://example.com:8080/x"
    # Java URI 允许超范围端口，只要端口是数字
    assert service.normalize_url("https://example.com:99999/x") == "https://example.com:99999/x"


def test_normalize_url_rejects_blank_and_non_http():
    with pytest.raises(BadRequest) as exc:
        service.normalize_url("   ")
    assert exc.value.message == "网址不能为空"
    with pytest.raises(BadRequest) as exc2:
        service.normalize_url("ftp://example.com")
    assert exc2.value.message == "请输入合法的 http/https 网址"
    with pytest.raises(BadRequest) as exc3:
        service.normalize_url("https://exa mple.com")
    assert exc3.value.message == "请输入合法的网址"
    with pytest.raises(BadRequest) as exc4:
        service.normalize_url("https://example.com:abc/x")
    assert exc4.value.message == "请输入合法的网址"


# ---------------------------------------------------------------------------
# 文件夹树与过滤
# ---------------------------------------------------------------------------


def test_library_tree_counts_subtree_and_filter_is_direct_only(sqlite_session):
    dev = _folder(sqlite_session, name="开发")
    child = _folder(sqlite_session, name="Python", parent_id=dev.id)
    _folder(sqlite_session, name="生活")
    github = _bookmark(sqlite_session, name="GitHub", url="github.com", folder_id=child.id)
    other = _bookmark(sqlite_session, name="Example", url="example.com")

    lib = service.library(sqlite_session, 1, None, None, False)
    assert len(lib.folders) == 2
    dev_node = next(node for node in lib.folders if node.name == "开发")
    # 树节点计数含子孙；但 folderId 过滤只查直属
    assert dev_node.bookmark_count == 1
    assert len(service.library(sqlite_session, 1, dev.id, None, False).bookmarks) == 0
    assert [b.id for b in service.library(sqlite_session, 1, child.id, None, False).bookmarks] == [
        github.id
    ]
    assert [b.id for b in service.library(sqlite_session, 1, None, None, True).bookmarks] == [other.id]
    assert [b.id for b in service.library(sqlite_session, 1, None, "git", False).bookmarks] == [
        github.id
    ]
    assert service.library(sqlite_session, 1, None, None, False).total == 2


def test_folder_name_validation_and_limit(sqlite_session):
    with pytest.raises(BadRequest) as exc:
        _folder(sqlite_session, name="  ")
    assert exc.value.message == "文件夹名称不能为空"
    with pytest.raises(BadRequest) as exc2:
        _folder(sqlite_session, name="x" * 65)
    assert exc2.value.message == "名称不能超过 64 个字符"


def test_update_folder_move_and_cycle_guard(sqlite_session):
    dev = _folder(sqlite_session, name="开发")
    child = _folder(sqlite_session, name="Python", parent_id=dev.id)
    updated = service.update_folder(sqlite_session, 1, child.id, "Python3", None)
    assert updated.name == "Python3" and updated.parent_id is None
    moved = service.update_folder(sqlite_session, 1, child.id, "Python3", dev.id)
    assert moved.parent_id == dev.id
    with pytest.raises(BadRequest) as exc:
        service.update_folder(sqlite_session, 1, dev.id, "开发", child.id)
    assert exc.value.message == "不能把文件夹移动到它自己的子文件夹下"
    with pytest.raises(NotFound) as exc2:
        service.update_folder(sqlite_session, 1, 999, "x", None)
    assert exc2.value.message == "文件夹不存在：#999"


def test_delete_folder_requires_cascade_when_not_empty(sqlite_session):
    dev = _folder(sqlite_session, name="开发")
    child = _folder(sqlite_session, name="Python", parent_id=dev.id)
    _bookmark(sqlite_session, folder_id=child.id)
    with pytest.raises(AppError) as exc:
        service.delete_folder(sqlite_session, 1, dev.id, False)
    assert exc.value.status_code == 409
    assert exc.value.message == "该文件夹不为空，确认删除其中的 1 个网站和 1 个子文件夹？"

    service.delete_folder(sqlite_session, 1, dev.id, True)
    lib = service.library(sqlite_session, 1, None, None, False)
    assert lib.folders == [] and lib.bookmarks == []


def test_delete_empty_folder_without_cascade(sqlite_session):
    folder = _folder(sqlite_session, name="空的")
    service.delete_folder(sqlite_session, 1, folder.id, False)
    assert service.library(sqlite_session, 1, None, None, False).folders == []


# ---------------------------------------------------------------------------
# 书签 CRUD / 图标缓存清理
# ---------------------------------------------------------------------------


def test_create_bookmark_normalizes_and_sorts(sqlite_session):
    first = _bookmark(sqlite_session, name="A", url="a.com")
    second = _bookmark(sqlite_session, name="B", url="b.com")
    assert first.url == "https://a.com"
    assert first.sort_order == 0 and second.sort_order == 1


def test_update_bookmark_clears_icon_only_when_source_changes(sqlite_session):
    bookmark = _bookmark(sqlite_session)
    entity = sqlite_session.get(WebsiteBookmark, bookmark.id)
    repository.store_cached_icon(sqlite_session, entity, b"png", "image/png")
    sqlite_session.commit()

    # 仅改名：保留图标缓存
    changed = service.update_bookmark(
        sqlite_session, 1, bookmark.id, "GitHub2", bookmark.url, bookmark.description, None, None
    )
    assert changed.name == "GitHub2"
    assert (
        sqlite_session.get(WebsiteBookmark, bookmark.id).icon_data is not None
    )

    # 改 URL：清空图标缓存
    service.update_bookmark(
        sqlite_session, 1, bookmark.id, "GitHub2", "github.io", bookmark.description, None, None
    )
    refreshed = sqlite_session.get(WebsiteBookmark, bookmark.id)
    assert refreshed.icon_data is None and refreshed.icon_content_type is None


def test_bookmark_missing_and_cross_user(sqlite_session):
    bookmark = _bookmark(sqlite_session, user_id=2)
    with pytest.raises(NotFound) as exc:
        service.delete_bookmark(sqlite_session, 1, bookmark.id)
    assert exc.value.message == f"网站不存在：#{bookmark.id}"


def test_update_bookmark_requires_name_and_valid_url(sqlite_session):
    bookmark = _bookmark(sqlite_session)
    with pytest.raises(BadRequest) as exc:
        service.update_bookmark(sqlite_session, 1, bookmark.id, "", "x.com", None, None, None)
    assert exc.value.message == "网站名称不能为空"
    with pytest.raises(BadRequest) as exc2:
        service.update_bookmark(sqlite_session, 1, bookmark.id, "x", "ftp://x", None, None, None)
    assert exc2.value.message == "请输入合法的 http/https 网址"


# ---------------------------------------------------------------------------
# 图标发现（全部 monkeypatch，无网络）
# ---------------------------------------------------------------------------


def test_is_public_http_uri_rejects_private_targets():
    assert icon_service.is_public_http_uri("http://127.0.0.1/x") is False
    assert icon_service.is_public_http_uri("http://10.0.0.5/x") is False
    assert icon_service.is_public_http_uri("http://[::1]/x") is False
    assert icon_service.is_public_http_uri("ftp://example.com/x") is False
    assert icon_service.is_public_http_uri("not-a-url") is False


def test_is_public_http_uri_accepts_public_ip(monkeypatch):
    monkeypatch.setattr(
        icon_service.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("93.184.216.34", 0))],
    )
    assert icon_service.is_public_http_uri("https://example.com/x") is True


def test_request_does_not_touch_private_hosts(monkeypatch):
    called = []
    monkeypatch.setattr(icon_service.httpx, "Client", lambda *a, **k: called.append(1))
    assert icon_service._request("http://127.0.0.1/favicon.ico", 100, "image/*") is None
    assert called == []


def test_discover_uses_declared_icon(monkeypatch):
    def fake_request(url, max_bytes, accept):  # noqa: ANN001
        if url == "https://site.test/":
            return (b'<link rel="icon" href="/i.png">', "text/html; charset=utf-8")
        if url == "https://site.test/i.png":
            return (b"PNGDATA", "image/png")
        return None

    monkeypatch.setattr(icon_service, "_request", fake_request)
    bookmark = types.SimpleNamespace(url="https://site.test/", icon_url=None)
    assert icon_service.discover(bookmark) == (b"PNGDATA", "image/png")


def test_discover_falls_back_to_favicon(monkeypatch):
    def fake_request(url, max_bytes, accept):  # noqa: ANN001
        if url == "https://site.test/":
            return (b"<html>no icons</html>", "text/html")
        if url == "https://site.test/favicon.ico":
            return (b"ICO", "image/x-icon")
        return None

    monkeypatch.setattr(icon_service, "_request", fake_request)
    bookmark = types.SimpleNamespace(url="https://site.test/", icon_url=None)
    assert icon_service.discover(bookmark) == (b"ICO", "image/x-icon")


def test_discover_skips_non_image_and_handles_bad_url(monkeypatch):
    monkeypatch.setattr(
        icon_service, "_request", lambda url, max_bytes, accept: (b"<html/>", "text/html")
    )
    bookmark = types.SimpleNamespace(url="https://site.test/", icon_url=None)
    assert icon_service.discover(bookmark) is None
    assert icon_service.discover(types.SimpleNamespace(url="not a url", icon_url=None)) is None


def test_icon_for_caches_discovered_icon(sqlite_session, monkeypatch):
    bookmark = _bookmark(sqlite_session)
    monkeypatch.setattr(icon_service, "discover", lambda bm: (b"CACHED", "image/png"))
    first = icon_service.icon_for(sqlite_session, 1, bookmark.id)
    assert first == (b"CACHED", "image/png")
    monkeypatch.setattr(
        icon_service, "discover", lambda bm: pytest.fail("第二次应直接读缓存，不应重新发现")
    )
    assert icon_service.icon_for(sqlite_session, 1, bookmark.id) == (b"CACHED", "image/png")
    with pytest.raises(NotFound):
        icon_service.icon_for(sqlite_session, 2, bookmark.id)


# ---------------------------------------------------------------------------
# REST 端点（8 个）
# ---------------------------------------------------------------------------


@pytest.fixture()
def client(client_factory, sqlite_session):
    from app.api.bookmarks import router

    return client_factory(router, sqlite_session)


def test_rest_library_and_folder_crud(client):
    created = client.post("/bookmarks/folders", json={"name": "开发"})
    assert created.status_code == 200
    folder = created.json()
    assert folder["name"] == "开发"
    assert folder["parentId"] is None and folder["bookmarkCount"] == 0 and folder["children"] == []

    renamed = client.patch(f"/bookmarks/folders/{folder['id']}", json={"name": "开发工具"})
    assert renamed.json()["name"] == "开发工具"

    library = client.get("/bookmarks").json()
    assert set(library) == {"folders", "bookmarks", "total"}
    assert [f["name"] for f in library["folders"]] == ["开发工具"]

    deleted = client.delete(f"/bookmarks/folders/{folder['id']}")
    assert deleted.status_code == 200 and deleted.content == b""
    assert client.get("/bookmarks").json()["folders"] == []


def test_rest_folder_validation_and_cascade_conflict(client):
    bad = client.post("/bookmarks/folders", json={})
    assert bad.status_code == 400 and bad.json()["message"] == "文件夹名称不能为空"

    folder = client.post("/bookmarks/folders", json={"name": "开发"}).json()
    client.post(
        "/bookmarks",
        json={"name": "GitHub", "url": "github.com", "folderId": folder["id"]},
    )
    conflict = client.delete(f"/bookmarks/folders/{folder['id']}")
    assert conflict.status_code == 409
    assert conflict.json()["message"] == "该文件夹不为空，确认删除其中的 1 个网站？"
    ok = client.delete(f"/bookmarks/folders/{folder['id']}", params={"cascade": "true"})
    assert ok.status_code == 200
    assert client.get("/bookmarks").json()["total"] == 0


def test_rest_bookmark_crud_and_404(client):
    created = client.post(
        "/bookmarks",
        json={"name": "GitHub", "url": "github.com", "description": "代码托管"},
    ).json()
    assert created["url"] == "https://github.com"
    assert created["folderId"] is None
    assert set(created) == {
        "id",
        "folderId",
        "name",
        "url",
        "description",
        "iconUrl",
        "sortOrder",
        "createdAt",
        "updatedAt",
    }

    updated = client.patch(
        f"/bookmarks/{created['id']}", json={"name": "GitHub2", "url": "https://github.com"}
    ).json()
    assert updated["name"] == "GitHub2"

    missing = client.patch(f"/bookmarks/999", json={"name": "x", "url": "x.com"})
    assert missing.status_code == 404
    assert missing.json()["message"] == "网站不存在：#999"

    deleted = client.delete(f"/bookmarks/{created['id']}")
    assert deleted.status_code == 200 and deleted.content == b""


def test_rest_bookmark_validation(client):
    resp = client.post("/bookmarks", json={"name": "x", "url": ""})
    assert resp.status_code == 400 and resp.json()["message"] == "网址不能为空"
    resp = client.post("/bookmarks", json={"name": "x", "url": "ftp://x"})
    assert resp.status_code == 400 and resp.json()["message"] == "请输入合法的 http/https 网址"
    resp = client.post("/bookmarks", json={"name": "  ", "url": "x.com"})
    assert resp.status_code == 400 and resp.json()["message"] == "网站名称不能为空"


def test_rest_icon_404_and_cached_bytes(client, sqlite_session, monkeypatch):
    monkeypatch.setattr(icon_service, "discover", lambda bm: None)  # 不发真实外网请求
    missing = client.get("/bookmarks/999/icon")
    assert missing.status_code == 404

    bookmark = _bookmark(sqlite_session)
    assert client.get(f"/bookmarks/{bookmark.id}/icon").status_code == 404

    entity = sqlite_session.get(WebsiteBookmark, bookmark.id)
    repository.store_cached_icon(sqlite_session, entity, b"\x89PNG", "image/png")
    sqlite_session.commit()
    resp = client.get(f"/bookmarks/{bookmark.id}/icon")
    assert resp.status_code == 200
    assert resp.content == b"\x89PNG"
    assert resp.headers["content-type"] == "image/png"
    assert resp.headers["cache-control"] == "no-cache, private"


def test_rest_library_filters(client):
    folder = client.post("/bookmarks/folders", json={"name": "开发"}).json()
    client.post("/bookmarks", json={"name": "GitHub", "url": "github.com", "folderId": folder["id"]})
    client.post("/bookmarks", json={"name": "Example", "url": "example.com"})
    assert client.get("/bookmarks", params={"unclassified": "true"}).json()["total"] == 1
    assert client.get("/bookmarks", params={"folderId": folder["id"]}).json()["total"] == 1
    assert client.get("/bookmarks", params={"q": "git"}).json()["total"] == 1


# ---------------------------------------------------------------------------
# 工具 schema（registry 由 chat-core 提供）
# ---------------------------------------------------------------------------


def test_site_tool_schemas_match_java():
    pytest.importorskip("app.agent.tools.registry")
    import app.domains.sites.tools  # noqa: F401  触发 @tool 注册
    from app.agent.tools.registry import REGISTRY

    names = {
        "listSiteFolders",
        "listSiteBookmarks",
        "addSiteBookmark",
        "updateSiteBookmark",
        "deleteSiteBookmark",
        "createSiteFolder",
        "updateSiteFolder",
        "deleteSiteFolder",
    }
    assert names <= set(REGISTRY)
    assert REGISTRY["listSiteFolders"].parameters == {
        "type": "object",
        "properties": {},
        "required": [],
    }
    add = REGISTRY["addSiteBookmark"]
    assert add.parameters["required"] == [
        "url",
        "name",
        "description",
        "category",
        "createCategoryIfMissing",
    ]
    assert add.parameters["properties"]["createCategoryIfMissing"]["type"] == "boolean"
    assert REGISTRY["deleteSiteFolder"].parameters["properties"]["cascade"]["type"] == "boolean"
    assert REGISTRY["updateSiteBookmark"].parameters["required"] == [
        "ref",
        "name",
        "url",
        "description",
        "category",
    ]
    assert REGISTRY["deleteSiteBookmark"].side_effect == "delete"


def test_site_tool_helpers():
    pytest.importorskip("app.agent.tools.registry")
    from app.domains.sites import tools as site_tools

    assert site_tools._parse_id("#12") == 12
    assert site_tools._parse_id("12") == 12
    assert site_tools._parse_id("#x") is None
    assert site_tools._is_root_token("未分类") is True
    assert site_tools._is_root_token("根目录") is True
    assert site_tools._is_root_token("开发") is False
    assert site_tools._default_name("https://www.github.com/a") == "github.com"
    assert site_tools._default_name("https://sub.example.com") == "sub.example.com"


def test_site_tool_business_failure_returns_text():
    pytest.importorskip("app.agent.tools.registry")
    from app.agent.tools.registry import ToolCtx
    from app.domains.sites import tools as site_tools

    result = asyncio.run(
        site_tools.add_site_bookmark(
            url="   ",
            name="",
            description="",
            category="",
            createCategoryIfMissing=False,
            ctx=ToolCtx(user_id=1),
        )
    )
    assert result == "网址不能为空，请让用户补充网站链接。"
    result = asyncio.run(site_tools.list_site_folders(ToolCtx(user_id=None)))
    assert result == "未登录，无法操作常用网站"


@pytest.mark.asyncio
async def test_dispatch_list_site_folders_via_registry(sqlite_session, monkeypatch):
    pytest.importorskip("app.agent.tools.registry")
    from app.agent.tools import load_all
    from app.agent.tools.registry import ToolCtx, dispatch

    load_all()
    from app.domains.sites import tools as site_tools

    _folder(sqlite_session, name="开发")
    _bookmark(sqlite_session, folder_id=1)
    monkeypatch.setattr(site_tools, "_session", lambda: nullcontext(sqlite_session))
    ok, text = await dispatch("listSiteFolders", {}, ToolCtx(user_id=1))
    assert ok is True
    assert "我的常用网站分类（共 1 个）" in text
    assert "#1 开发（1 个网站）" in text


def test_update_folder_tool_case_rename_hits_java_duplicate_quirk(sqlite_session):
    """Java 同名比较是区分大小写，但名字查重忽略大小写 → 仅改大小写会命中重复提示。"""
    pytest.importorskip("app.agent.tools.registry")
    from app.domains.sites import tools as site_tools

    _folder(sqlite_session, name="dev")
    result = site_tools._update_site_folder(sqlite_session, 1, "#1", "Dev", "")
    assert result.startswith("已存在同名分类：#1 dev")
