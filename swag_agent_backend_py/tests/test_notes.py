"""Markdown 笔记模块单测：路径安全 / 回收站 / 树 / 导入 / 附件 / 16 端点。

全部使用 tmp_path，不碰真实 notes-data，不连 MySQL/PG。
"""

from __future__ import annotations

import json

import pytest

from app.api.notes import router as notes_router
from app.config import settings
from app.core.errors import AppError
from app.domains.notes import views
from app.domains.notes.import_service import NotesImportService, UploadPart
from app.domains.notes.service import (
    TRASH_DIR,
    UNCLASSIFIED,
    NotesService,
    guard,
)
from app.domains.notes.trash import purge_expired_trash_all_users


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def notes_root(tmp_path, monkeypatch):
    root = tmp_path / "notes-data"
    monkeypatch.setattr(settings, "notes_root", str(root))
    # 默认不开放任何本地导入根目录，需要时由用例单独 monkeypatch
    monkeypatch.setattr(settings, "notes_import_roots", "")
    return root


@pytest.fixture()
def service(notes_root) -> NotesService:
    return NotesService(notes_root)


@pytest.fixture()
def importer(service) -> NotesImportService:
    return NotesImportService(service)


@pytest.fixture()
def client(client_factory, sqlite_session, notes_root):
    """TestClient：conftest 的 _UserMiddleware 默认把请求当成 user_id=1。

    依赖 notes_root 以确保所有 HTTP 用例都跑在 tmp_path 下，绝不碰真实 notes-data。
    """
    assert notes_root  # 依赖注入，触发 settings.notes_root monkeypatch
    return client_factory(notes_router, sqlite_session)


# ---------------------------------------------------------------------------
# 1. 路径安全：绝对路径 / .. / 点开头 / 符号链接逃逸
# ---------------------------------------------------------------------------


def test_guard_rejects_unsafe_relative_paths(service):
    home = service.ensure_home(1)
    unsafe = [
        "/etc/passwd.md",  # 绝对路径
        "../escape.md",  # 上跳
        "a/../../escape.md",
        ".hidden/a.md",  # 点开头段
        ".trash/a.md",  # 保留目录
        "a./b.md",  # 段以点结尾
        "a/b\x00.md",  # 控制字符
        "a//b.md",  # 空段
    ]
    for rel in unsafe:
        with pytest.raises(AppError) as exc:
            guard(home, rel)
        assert exc.value.status_code == 400, rel

    assert guard(home, "a/b.md") == home / "a" / "b.md"


def test_guard_rejects_non_markdown_and_empty(service):
    with pytest.raises(AppError) as exc:
        service.read(1, "a.txt")
    assert exc.value.status_code == 400
    assert "仅支持 .md" in exc.value.message

    with pytest.raises(AppError) as exc:
        service.read(1, "   ")
    assert exc.value.status_code == 400


def test_symlink_escape_is_forbidden(service, tmp_path):
    home = service.ensure_home(1)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.md").write_text("secret", encoding="utf-8")
    (home / "link").symlink_to(outside, target_is_directory=True)

    with pytest.raises(AppError) as exc:
        service.read(1, "link/secret.md")
    assert exc.value.status_code == 403
    assert "笔记目录" in exc.value.message


# ---------------------------------------------------------------------------
# 2. 目录树：目录优先、大小写不敏感排序、隐藏项/非 md/符号链接过滤
# ---------------------------------------------------------------------------


def test_tree_ordering_and_filtering(service):
    home = service.ensure_home(1)
    (home / "b").mkdir()
    (home / "A").mkdir()
    (home / "b" / "z.md").write_text("z", encoding="utf-8")
    (home / "b" / "a.md").write_text("a", encoding="utf-8")
    (home / "A" / "x.md").write_text("x", encoding="utf-8")
    (home / UNCLASSIFIED / "n.md").write_text("n", encoding="utf-8")
    (home / "note.md").write_text("root", encoding="utf-8")
    (home / "ignore.txt").write_text("ignored", encoding="utf-8")
    (home / ".hidden").mkdir()
    (home / ".hidden" / "h.md").write_text("h", encoding="utf-8")
    (home / "link.md").symlink_to(home / "note.md")

    tree = service.tree(1)
    assert isinstance(tree, views.Node)
    assert tree.name == "user-1"
    assert tree.path == ""
    assert tree.type == "dir"
    assert [(child.name, child.type) for child in tree.children] == [
        ("A", "dir"),
        ("b", "dir"),
        (UNCLASSIFIED, "dir"),
        ("note.md", "file"),
    ]
    b_dir = next(child for child in tree.children if child.name == "b")
    assert [child.name for child in b_dir.children] == ["a.md", "z.md"]
    assert [child.path for child in b_dir.children] == ["b/a.md", "b/z.md"]
    assert b_dir.children[0].children == []


# ---------------------------------------------------------------------------
# 3. 文件读写：409 不覆盖、404 父目录、413 大小限制
# ---------------------------------------------------------------------------


def test_create_conflict_never_overwrites(service):
    saved = service.create(1, "未分类/a.md", "hello")
    assert saved.path == "未分类/a.md"
    assert saved.size == 5
    with pytest.raises(AppError) as exc:
        service.create(1, "未分类/a.md", "changed")
    assert exc.value.status_code == 409
    assert service.read(1, "未分类/a.md").content == "hello"
    # PUT 覆盖写
    service.save(1, "未分类/a.md", "world")
    assert service.read(1, "未分类/a.md").content == "world"


def test_create_parent_missing_is_404(service):
    with pytest.raises(AppError) as exc:
        service.create(1, "不存在的目录/a.md", "x")
    assert exc.value.status_code == 404


def test_note_size_limit_413(service, monkeypatch):
    monkeypatch.setattr("app.domains.notes.service._max_note_bytes", lambda: 4)
    with pytest.raises(AppError) as exc:
        service.create(1, "未分类/big.md", "12345")
    assert exc.value.status_code == 413


def test_create_unique_appends_suffix(service):
    first = service.create_unique(1, UNCLASSIFIED, "note.md", "v1")
    second = service.create_unique(1, UNCLASSIFIED, "note.md", "v2")
    assert first.path == "未分类/note.md"
    assert second.path == "未分类/note (1).md"


def test_rename_rules(service):
    service.create_dir(1, "工作")
    with pytest.raises(AppError) as exc:
        service.rename(1, UNCLASSIFIED, "别的名字")
    assert exc.value.status_code == 400
    assert "系统文件夹" in exc.value.message

    service.create(1, "工作/a.md", "a")
    with pytest.raises(AppError) as exc:
        service.rename(1, "工作", "x.md")
    assert exc.value.status_code == 400

    service.create(1, "工作/b.md", "b")
    with pytest.raises(AppError) as exc:
        service.rename(1, "工作/a.md", "工作/b.md")
    assert exc.value.status_code == 409

    service.rename(1, "工作/a.md", "工作/c.md")
    assert service.read(1, "工作/c.md").content == "a"


# ---------------------------------------------------------------------------
# 4. 回收站：entry.json 是 properties 文本、恢复冲突加 (n)、坏条目清理
# ---------------------------------------------------------------------------


def test_entry_json_is_properties_not_json(service):
    service.create(1, "未分类/a.md", "hello")
    service.delete_file(1, "未分类/a.md")

    trash_dir = service.home_dir(1) / TRASH_DIR
    entries = list(trash_dir.iterdir())
    assert len(entries) == 1
    meta_text = (entries[0] / "entry.json").read_text(encoding="utf-8")
    assert "originalPath=未分类/a.md" in meta_text
    assert "kind=file" in meta_text
    assert "deletedAt=" in meta_text
    with pytest.raises(ValueError):
        json.loads(meta_text)  # 绝不能当 JSON 解析

    trash = service.list_trash(1)
    assert len(trash) == 1
    assert trash[0].originalPath == "未分类/a.md"
    assert trash[0].name == "a.md"
    assert trash[0].kind == "file"
    assert isinstance(trash[0].deletedAt, int) and trash[0].deletedAt > 0


def test_restore_conflict_appends_suffix(service):
    service.create(1, "未分类/a.md", "v1")
    service.delete_file(1, "未分类/a.md")
    entry_id = service.list_trash(1)[0].id

    service.create(1, "未分类/a.md", "v2")  # 占住原路径
    service.restore(1, entry_id)

    assert service.read(1, "未分类/a.md").content == "v2"
    assert service.read(1, "未分类/a (1).md").content == "v1"
    assert service.list_trash(1) == []


def test_restore_falls_back_to_unclassified(service):
    service.create_dir(1, "工作")
    service.create(1, "工作/a.md", "x")
    service.delete_file(1, "工作/a.md")
    entry_id = service.list_trash(1)[0].id

    (service.home_dir(1) / "工作").rmdir()  # 原父目录消失

    service.restore(1, entry_id)
    assert service.read(1, "未分类/a.md").content == "x"


def test_purge_expired_and_bad_entries(service, notes_root):
    service.create(1, "未分类/old.md", "old")
    service.delete_file(1, "未分类/old.md")
    trash_dir = service.home_dir(1) / TRASH_DIR
    old_entry = next(trash_dir.iterdir())
    (old_entry / "entry.json").write_text(
        "originalPath=未分类/old.md\nkind=file\ndeletedAt=1\n", encoding="utf-8"
    )

    # 坏条目：kind 非法（会被判为坏条目清理）
    bad = trash_dir / "badentry-1234"
    bad.mkdir()
    (bad / "entry.json").write_text(
        "originalPath=未分类/x.md\nkind=weird\ndeletedAt=9999999999999\n", encoding="utf-8"
    )
    (bad / "note.md").write_text("x", encoding="utf-8")

    assert service.purge_trash_home(service.home_dir(1)) == 2
    assert not old_entry.exists()
    assert not bad.exists()


def test_purge_all_users_entrypoint(service, notes_root):
    service.create(1, "未分类/a.md", "a")
    service.delete_file(1, "未分类/a.md")
    entry = next((service.home_dir(1) / TRASH_DIR).iterdir())
    (entry / "entry.json").write_text(
        "originalPath=未分类/a.md\nkind=file\ndeletedAt=1\n", encoding="utf-8"
    )
    # 另一个用户目录不受影响
    service.ensure_home(2)

    assert purge_expired_trash_all_users(None) == 1


# ---------------------------------------------------------------------------
# 5. 删除文件夹：trash / flatten
# ---------------------------------------------------------------------------


def test_flatten_moves_only_markdown(service):
    service.create_dir(1, "工作/子")
    service.create(1, "工作/a.md", "a")
    service.create(1, "工作/子/b.md", "b")
    (service.home_dir(1) / "工作" / "image.png").write_bytes(b"png")

    service.delete_dir_flatten(1, "工作")

    home = service.home_dir(1)
    assert not (home / "工作").exists()
    assert (home / UNCLASSIFIED / "a.md").read_text(encoding="utf-8") == "a"
    assert (home / UNCLASSIFIED / "b.md").read_text(encoding="utf-8") == "b"
    assert not (home / UNCLASSIFIED / "image.png").exists()


def test_flatten_conflict_appends_suffix(service):
    service.create(1, "未分类/a.md", "keep")
    service.create_dir(1, "工作")
    service.create(1, "工作/a.md", "flat")

    service.delete_dir_flatten(1, "工作")

    assert service.read(1, "未分类/a.md").content == "keep"
    assert service.read(1, "未分类/a (1).md").content == "flat"


def test_delete_dir_to_trash_and_restore(service):
    service.create_dir(1, "工作")
    service.create(1, "工作/a.md", "a")
    service.delete_dir_to_trash(1, "工作")

    assert not (service.home_dir(1) / "工作").exists()
    trash = service.list_trash(1)
    assert len(trash) == 1 and trash[0].kind == "dir"

    service.restore(1, trash[0].id)
    assert service.read(1, "工作/a.md").content == "a"


def test_clear_trash(service):
    service.create(1, "未分类/a.md", "a")
    service.create(1, "未分类/b.md", "b")
    service.delete_file(1, "未分类/a.md")
    service.delete_file(1, "未分类/b.md")
    assert len(service.list_trash(1)) == 2
    service.clear_trash(1)
    assert service.list_trash(1) == []
    assert not (service.home_dir(1) / TRASH_DIR).exists()


# ---------------------------------------------------------------------------
# 6. 导入：本地白名单 / 上传 relativePaths / 附件复制与链接改写 / 资源读取
# ---------------------------------------------------------------------------


def test_import_local_requires_absolute_paths(importer, tmp_path, monkeypatch):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    monkeypatch.setattr(settings, "notes_import_roots", str(allowed))
    # 相对路径在逐文件阶段被记录为失败项（Java 同语义：单条失败不中断批次）
    result = importer.import_local(1, ["relative/a.md"], None)
    assert result.imported == []
    assert len(result.failed) == 1
    assert "必须使用绝对路径" in result.failed[0].reason


def test_import_local_requires_configured_root(importer, tmp_path):
    source = tmp_path / "a.md"
    source.write_text("x", encoding="utf-8")
    with pytest.raises(AppError) as exc:
        importer.import_local(1, [str(source)], None)
    assert exc.value.status_code == 403
    assert "import-roots" in exc.value.message


def test_import_local_rejects_paths_outside_roots(importer, tmp_path, monkeypatch):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    monkeypatch.setattr(settings, "notes_import_roots", str(allowed))
    outside = tmp_path / "outside.md"
    outside.write_text("x", encoding="utf-8")

    result = importer.import_local(1, [str(outside)], None)
    assert result.imported == []
    assert len(result.failed) == 1
    assert "路径不在允许导入的目录内" in result.failed[0].reason


def test_import_local_copies_attachment_and_rewrites_links(importer, service, tmp_path, monkeypatch):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "pic.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    markdown = source_dir / "note.md"
    markdown.write_text(
        "![i](pic.png)\n![[pic.png]]\n<img src=\"pic.png\">\n", encoding="utf-8"
    )
    monkeypatch.setattr(settings, "notes_import_roots", str(source_dir))

    result = importer.import_local(1, [str(markdown)], None)

    assert result.failed == []
    assert result.imported == ["未分类/note.md"]
    assert result.attachmentsCopied == 1
    content = service.read(1, "未分类/note.md").content
    assert content.count("/api/notes/resource?bundle=") == 3
    bundles = list((service.home_dir(1) / ".resources").iterdir())
    assert len(bundles) == 1
    assert (bundles[0] / "pic.png").read_bytes() == b"\x89PNG\r\n\x1a\n"


def test_import_local_records_item_failure(importer, tmp_path, monkeypatch):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    monkeypatch.setattr(settings, "notes_import_roots", str(allowed))
    not_md = allowed / "a.txt"
    not_md.write_text("x", encoding="utf-8")
    missing = allowed / "missing.md"

    result = importer.import_local(1, [str(not_md), str(missing)], None)
    assert result.imported == []
    assert len(result.failed) == 2
    assert any("仅支持导入 .md" in item.reason for item in result.failed)


def test_import_uploads_with_relative_attachment(importer, service):
    parts = [
        UploadPart("folder/note.md", "note.md", "![i](pic.png)".encode("utf-8")),
        UploadPart("folder/pic.png", "pic.png", b"\x89PNGdata"),
    ]
    result = importer.import_uploads(1, parts, None)

    assert result.failed == []
    assert result.imported == ["未分类/note.md"]
    assert result.attachmentsCopied == 1
    content = service.read(1, "未分类/note.md").content
    assert "/api/notes/resource?bundle=" in content


def test_import_uploads_rejects_escape_and_duplicates(importer):
    with pytest.raises(AppError) as exc:
        importer.import_uploads(1, [UploadPart("../evil.md", "evil.md", b"x")], None)
    assert exc.value.status_code == 400

    with pytest.raises(AppError) as exc:
        importer.import_uploads(1, [UploadPart("a.txt", "a.txt", b"x")], None)
    assert exc.value.status_code == 400
    assert "没有 .md" in exc.value.message

    with pytest.raises(AppError) as exc:
        importer.import_uploads(
            1,
            [
                UploadPart("a.md", "a.md", b"x"),
                UploadPart("a.md", "a.md", b"y"),
            ],
            None,
        )
    assert exc.value.status_code == 400
    assert "重复路径" in exc.value.message


def test_import_local_chinese_attachment_name(importer, service, tmp_path, monkeypatch):
    source_dir = tmp_path / "source-cn"
    source_dir.mkdir()
    (source_dir / "图片.png").write_bytes(b"\x89PNGcn")
    (source_dir / "note.md").write_text("![图](图片.png)", encoding="utf-8")
    monkeypatch.setattr(settings, "notes_import_roots", str(source_dir))

    result = importer.import_local(1, [str(source_dir / "note.md")], None)
    assert result.attachmentsCopied == 1
    content = service.read(1, "未分类/note.md").content
    assert "%E5%9B%BE%E7%89%87.png" in content  # Java URLEncoder 同款编码

    bundle = next((service.home_dir(1) / ".resources").iterdir()).name
    view = importer.resource(1, bundle, "图片.png")
    assert view.inline is True
    assert view.fileName == "图片.png"


def test_resource_attachment_is_not_inline(importer, service, tmp_path, monkeypatch):
    source_dir = tmp_path / "source-txt"
    source_dir.mkdir()
    (source_dir / "notes.txt").write_text("hello", encoding="utf-8")
    (source_dir / "note.md").write_text("[t](notes.txt)", encoding="utf-8")
    monkeypatch.setattr(settings, "notes_import_roots", str(source_dir))
    importer.import_local(1, [str(source_dir / "note.md")], None)

    bundle = next((service.home_dir(1) / ".resources").iterdir()).name
    view = importer.resource(1, bundle, "notes.txt")
    assert view.inline is False
    assert view.contentType == "text/plain"


def test_resource_reader_validation(importer, service, tmp_path, monkeypatch):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "pic.png").write_bytes(b"\x89PNG")
    (source_dir / "note.md").write_text("![i](pic.png)", encoding="utf-8")
    monkeypatch.setattr(settings, "notes_import_roots", str(source_dir))
    importer.import_local(1, [str(source_dir / "note.md")], None)

    bundle = next((service.home_dir(1) / ".resources").iterdir()).name
    view = importer.resource(1, bundle, "pic.png")
    assert view.contentType == "image/png"
    assert view.inline is True
    assert view.path.read_bytes() == b"\x89PNG"

    with pytest.raises(AppError) as exc:
        importer.resource(1, "not-a-uuid", "pic.png")
    assert exc.value.status_code == 400

    with pytest.raises(AppError) as exc:
        importer.resource(1, bundle, "../note.md")
    assert exc.value.status_code == 400

    with pytest.raises(AppError) as exc:
        importer.resource(1, bundle, "missing.png")
    assert exc.value.status_code == 404

    # 别的用户读不到
    with pytest.raises(AppError) as exc:
        importer.resource(2, bundle, "pic.png")
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# 7. HTTP 端点（TestClient + conftest 的测试用鉴权中间件）
# ---------------------------------------------------------------------------


def test_api_tree_and_file_crud(client):
    response = client.get("/notes/tree")
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "user-1"
    assert body["path"] == ""
    assert body["type"] == "dir"
    assert [child["name"] for child in body["children"]] == [UNCLASSIFIED]

    response = client.post("/notes/dir", json={"path": "工作/子"})
    assert response.status_code == 200
    assert response.content == b""

    response = client.post("/notes/file", json={"path": "工作/子/a.md", "content": "hi"})
    assert response.status_code == 200
    saved = response.json()
    assert saved["path"] == "工作/子/a.md"
    assert saved["size"] == 2
    assert isinstance(saved["modified"], int)

    response = client.post("/notes/file", json={"path": "工作/子/a.md", "content": "again"})
    assert response.status_code == 409
    assert response.json()["status"] == 409

    response = client.get("/notes/file", params={"path": "工作/子/a.md"})
    assert response.status_code == 200
    file_view = response.json()
    assert file_view["content"] == "hi"
    assert file_view["name"] == "a.md"

    response = client.put("/notes/file", json={"path": "工作/子/a.md", "content": "v2"})
    assert response.status_code == 200

    response = client.post("/notes/rename", json={"from": "工作/子/a.md", "to": "工作/b.md"})
    assert response.status_code == 200

    response = client.get("/notes/file", params={"path": "工作/b.md"})
    assert response.json()["content"] == "v2"


def test_api_errors_and_payload_limit(client, monkeypatch):
    response = client.get("/notes/file", params={"path": "missing.md"})
    assert response.status_code == 404
    body = response.json()
    assert body["status"] == 404 and body["path"] == "/notes/file"

    response = client.get("/notes/file", params={"path": "../escape.md"})
    assert response.status_code == 400

    response = client.post("/notes/file", json={"path": "   ", "content": "x"})
    assert response.status_code == 400
    assert response.json()["message"] == "笔记路径不能为空"

    response = client.post("/notes/dir", json={})
    assert response.status_code == 400

    monkeypatch.setattr(settings, "notes_max_markdown_bytes", 4)
    response = client.post("/notes/file", json={"path": "未分类/big.md", "content": "12345"})
    assert response.status_code == 413


def test_api_delete_dir_mode_validation(client):
    client.post("/notes/dir", json={"path": "工作"})
    response = client.delete("/notes/dir", params={"path": "工作", "mode": "nope"})
    assert response.status_code == 400
    assert "mode 仅支持" in response.json()["message"]


def test_api_trash_flow(client):
    client.post("/notes/file", json={"path": "未分类/a.md", "content": "a"})
    response = client.delete("/notes/file", params={"path": "未分类/a.md"})
    assert response.status_code == 200
    assert response.content == b""

    response = client.get("/notes/trash")
    assert response.status_code == 200
    trash = response.json()
    assert len(trash) == 1
    assert trash[0]["originalPath"] == "未分类/a.md"
    assert trash[0]["kind"] == "file"
    assert isinstance(trash[0]["deletedAt"], int)
    entry_id = trash[0]["id"]

    response = client.post(f"/notes/trash/{entry_id}/restore")
    assert response.status_code == 200
    assert client.get("/notes/trash").json() == []

    client.delete("/notes/file", params={"path": "未分类/a.md"})
    response = client.delete(f"/notes/trash/{entry_id}")
    assert response.status_code == 404  # 该条目已用于恢复，编号不存在

    entry_id = client.get("/notes/trash").json()[0]["id"]
    response = client.delete(f"/notes/trash/{entry_id}")
    assert response.status_code == 200
    assert client.get("/notes/trash").json() == []


def test_api_clear_trash(client):
    client.post("/notes/file", json={"path": "未分类/a.md", "content": "a"})
    client.delete("/notes/file", params={"path": "未分类/a.md"})
    assert len(client.get("/notes/trash").json()) == 1
    response = client.delete("/notes/trash")
    assert response.status_code == 200
    assert client.get("/notes/trash").json() == []


def test_api_import_config(client):
    response = client.get("/notes/import/config")
    assert response.status_code == 200
    assert response.json() == {"localRoots": []}


def test_api_import_local(client, tmp_path, monkeypatch):
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    (source_dir / "pic.png").write_bytes(b"\x89PNG")
    (source_dir / "note.md").write_text("![i](pic.png)", encoding="utf-8")
    monkeypatch.setattr(settings, "notes_import_roots", str(source_dir))

    response = client.post(
        "/notes/import/local",
        json={"sourcePaths": [str(source_dir / "note.md")], "targetDir": UNCLASSIFIED},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["imported"] == ["未分类/note.md"]
    assert body["failed"] == []
    assert body["warnings"] == []
    assert body["attachmentsCopied"] == 1

    # 通过 .resources 目录拿到 bundle 再走 HTTP 读取资源
    roots = list((settings.notes_root_path / "user-1" / ".resources").iterdir())
    bundle = roots[0].name
    response = client.get("/notes/resource", params={"bundle": bundle, "name": "pic.png"})
    assert response.status_code == 200
    assert response.content == b"\x89PNG"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-disposition"].startswith("inline")
    assert response.headers["content-type"].startswith("image/png")


def test_api_import_upload_and_resource(client):
    response = client.post(
        "/notes/import/upload",
        files=[
            ("files", ("note.md", "![i](pic.png)".encode("utf-8"), "text/markdown")),
            ("files", ("pic.png", b"\x89PNGupload", "image/png")),
        ],
        data={"relativePaths": ["upload/note.md", "upload/pic.png"], "targetDir": UNCLASSIFIED},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["imported"] == ["未分类/note.md"]
    assert body["attachmentsCopied"] == 1

    bundle = next((settings.notes_root_path / "user-1" / ".resources").iterdir()).name
    response = client.get("/notes/resource", params={"bundle": bundle, "name": "pic.png"})
    assert response.status_code == 200
    assert response.content == b"\x89PNGupload"


def test_api_import_upload_without_relative_paths(client):
    response = client.post(
        "/notes/import/upload",
        files=[("files", ("plain.md", b"# hi", "text/markdown"))],
        data={"targetDir": UNCLASSIFIED},
    )
    assert response.status_code == 200
    assert response.json()["imported"] == ["未分类/plain.md"]


def test_api_import_upload_size_limits(client, monkeypatch):
    monkeypatch.setattr(settings, "notes_max_attachment_bytes", 8)
    monkeypatch.setattr(settings, "notes_max_import_total_bytes", 32)
    response = client.post(
        "/notes/import/upload",
        files=[("files", ("big.md", b"0123456789", "text/markdown"))],
    )
    assert response.status_code == 413

    response = client.post(
        "/notes/import/upload",
        files=[
            ("files", ("a.md", b"01234567", "text/markdown")),
            ("files", ("b.md", b"01234567", "text/markdown")),
            ("files", ("c.md", b"01234567", "text/markdown")),
            ("files", ("d.md", b"01234567", "text/markdown")),
            ("files", ("e.md", b"01234567", "text/markdown")),
        ],
    )
    assert response.status_code == 413


def test_api_import_upload_requires_files(client):
    response = client.post("/notes/import/upload", files=[])
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# 8. Agent 工具 importLocalMarkdownNotes
# ---------------------------------------------------------------------------


class _Ctx:
    def __init__(self, user_id: int | None = 1) -> None:
        self.user_id = user_id


def test_tool_handler_success(service, tmp_path, monkeypatch):
    import asyncio

    from app.domains.notes import tools as notes_tools

    source_dir = tmp_path / "tool-src"
    source_dir.mkdir()
    (source_dir / "tool.md").write_text("hello", encoding="utf-8")
    monkeypatch.setattr(settings, "notes_import_roots", str(source_dir))
    monkeypatch.setattr(notes_tools, "get_import_service", lambda: NotesImportService(service))

    message = asyncio.run(
        notes_tools.import_local_markdown_notes([str(source_dir / "tool.md")], UNCLASSIFIED, _Ctx())
    )
    assert message.startswith("已导入 1 篇笔记：")
    assert "复制附件 0 个。" in message


def test_tool_handler_business_failures(service, monkeypatch):
    import asyncio

    from app.domains.notes import tools as notes_tools

    monkeypatch.setattr(notes_tools, "get_import_service", lambda: NotesImportService(service))
    monkeypatch.setattr(settings, "notes_import_roots", "")

    message = asyncio.run(
        notes_tools.import_local_markdown_notes(["/tmp/x.md"], UNCLASSIFIED, _Ctx())
    )
    assert "import-roots" in message

    message = asyncio.run(
        notes_tools.import_local_markdown_notes(["/tmp/x.md"], UNCLASSIFIED, _Ctx(user_id=None))
    )
    assert "未登录" in message


def test_tool_dispatch_through_registry(service, tmp_path, monkeypatch):
    """chat-core 的注册表就绪时，走 dispatch 端到端验证工具可用。"""
    import asyncio

    registry = pytest.importorskip("app.agent.tools.registry")
    import app.domains.notes.tools  # noqa: F401  （import 即注册）

    source_dir = tmp_path / "dispatch-src"
    source_dir.mkdir()
    (source_dir / "dispatch.md").write_text("hi", encoding="utf-8")
    monkeypatch.setattr(settings, "notes_import_roots", str(source_dir))

    ok, text = asyncio.run(
        registry.dispatch(
            "importLocalMarkdownNotes",
            {"sourcePaths": [str(source_dir / "dispatch.md")], "targetFolder": UNCLASSIFIED},
            registry.ToolCtx(user_id=1),
        )
    )
    assert ok is True
    assert text.startswith("已导入 1 篇笔记：")
    assert service.read(1, "未分类/dispatch.md").content == "hi"


def test_tool_registered_in_registry_if_available():
    registry = pytest.importorskip("app.agent.tools.registry")
    import app.domains.notes.tools as notes_tools  # noqa: F401  （import 即注册）

    spec = registry.REGISTRY.get("importLocalMarkdownNotes")
    assert spec is not None
    assert spec.parameters["required"] == ["sourcePaths", "targetFolder"]
    assert spec.needs_user is True
