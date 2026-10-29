"""会话历史 + 用户记忆 API 测试（SQLite 内存库，不连真实 MySQL）。

覆盖：响应字段/epoch ms、Java 排序规则、收藏与排序号、成对删除、清空、
404/400 语义、user-memory 的 chat-core 委托与本地降级。
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import app.db.models  # noqa: F401  (注册所有表)
from app.api.conversations import router as conversations_router
from app.api.user_memory import router as user_memory_router
from app.core.timeutil import epoch_ms
from app.db.models import ChatConversation, ChatMessage, ChatUserMemory, ChatUserMemorySetting
from app.domains.chat import service as chat_service

DT = datetime(2026, 10, 1, 12, 0, 0)


def _conversation(db, **overrides) -> ChatConversation:
    data = {
        "user_id": 1,
        "title": "",
        "created_at": DT,
        "updated_at": DT,
        "favorite": False,
        "favorite_note": None,
        "favorite_order": None,
        "favorited_at": None,
    }
    data.update(overrides)
    conversation = ChatConversation(**data)
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation


def _message(db, conversation: ChatConversation, role: str, content: str, moment: datetime | None = None) -> ChatMessage:
    message = ChatMessage(
        conversation_id=conversation.id,
        user_id=conversation.user_id,
        role=role,
        content=content,
        created_at=moment or DT,
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    return message


def _headers(user_id: int = 1, role: str = "USER") -> dict[str, str]:
    return {"x-test-user-id": str(user_id), "x-test-role": role}


# ---------------------------------------------------------------------------
# 纯映射 / 排序
# ---------------------------------------------------------------------------


def test_conversation_response_fields_and_epoch_ms(sqlite_session):
    favorited = datetime(2026, 10, 2, 8, 30, 0)
    conversation = _conversation(
        sqlite_session,
        title="hello",
        favorite=True,
        favorite_note="备注",
        favorite_order=2,
        favorited_at=favorited,
        updated_at=datetime(2026, 10, 3, 9, 0, 0),
    )

    body = chat_service.conversation_response(conversation)

    assert body == {
        "id": conversation.id,
        "title": "hello",
        "favorite": True,
        "favoriteNote": "备注",
        "favoriteOrder": 2,
        "favoritedAtMs": epoch_ms(favorited),
        "createdAtMs": epoch_ms(DT),
        "updatedAtMs": epoch_ms(datetime(2026, 10, 3, 9, 0, 0)),
    }


def test_conversation_response_null_favorited_at_is_zero(sqlite_session):
    conversation = _conversation(sqlite_session)
    body = chat_service.conversation_response(conversation)
    assert body["favoritedAtMs"] == 0
    assert body["favoriteNote"] is None
    assert body["favoriteOrder"] is None
    assert body["favorite"] is False


def test_list_order_favorites_first_then_order_then_updated(sqlite_session):
    # 收藏：order=1 在前，order=NULL 排收藏区最后；未收藏按 updated_at 倒序。
    c_order1 = _conversation(sqlite_session, title="fav-order1", favorite=True, favorite_order=1)
    c_order_null = _conversation(sqlite_session, title="fav-null", favorite=True, favorite_order=None)
    c_recent = _conversation(sqlite_session, title="plain-new", updated_at=datetime(2026, 10, 5, 0, 0, 0))
    c_old = _conversation(sqlite_session, title="plain-old", updated_at=datetime(2026, 10, 2, 0, 0, 0))

    rows = chat_service.list_conversations(sqlite_session, 1)

    assert [row["title"] for row in rows] == [
        c_order1.title,
        c_order_null.title,
        c_recent.title,
        c_old.title,
    ]


def test_list_isolated_by_user(sqlite_session):
    _conversation(sqlite_session, user_id=1, title="mine")
    _conversation(sqlite_session, user_id=2, title="other")
    assert [row["title"] for row in chat_service.list_conversations(sqlite_session, 1)] == ["mine"]


def test_paired_message_ids_rules(sqlite_session):
    conversation = _conversation(sqlite_session)
    m1 = _message(sqlite_session, conversation, "user", "q1")
    m2 = _message(sqlite_session, conversation, "assistant", "a1")
    m3 = _message(sqlite_session, conversation, "user", "q2")
    messages = [m1, m2, m3]

    # 提问 → 带上紧随回答
    assert chat_service.paired_message_ids(messages, 0) == [m1.id, m2.id]
    # 回答 → 带上紧邻提问
    assert chat_service.paired_message_ids(messages, 1) == [m2.id, m1.id]
    # 末尾单独提问 → 只删自己
    assert chat_service.paired_message_ids(messages, 2) == [m3.id]


def test_normalize_note_truncates_and_blank_to_none():
    assert chat_service.normalize_note(None) is None
    assert chat_service.normalize_note("   ") is None
    assert chat_service.normalize_note("  hi  ") == "hi"
    assert chat_service.normalize_note("x" * 130) == "x" * 120


# ---------------------------------------------------------------------------
# 会话 REST
# ---------------------------------------------------------------------------


def test_create_list_and_user_isolation_api(client_factory, sqlite_session):
    client = client_factory(conversations_router, sqlite_session)

    created = client.post("/chat/conversations", json={"title": "hi"}, headers=_headers(7))
    assert created.status_code == 200
    body = created.json()
    assert body["title"] == "hi"
    assert body["favorite"] is False
    assert body["createdAtMs"] > 0
    assert set(body) == {
        "id",
        "title",
        "favorite",
        "favoriteNote",
        "favoriteOrder",
        "favoritedAtMs",
        "createdAtMs",
        "updatedAtMs",
    }

    # 空 body 也允许（Java @RequestBody(required = false)），标题为空串。
    empty = client.post("/chat/conversations", headers=_headers(7))
    assert empty.status_code == 200
    assert empty.json()["title"] == ""

    own = client.get("/chat/conversations", headers=_headers(7))
    assert own.status_code == 200
    assert len(own.json()) == 2
    assert client.get("/chat/conversations", headers=_headers(8)).json() == []


def test_messages_foreign_or_missing_404(client_factory, sqlite_session):
    conversation = _conversation(sqlite_session, user_id=1)
    _message(sqlite_session, conversation, "user", "q")
    client = client_factory(conversations_router, sqlite_session)

    assert client.get(f"/chat/conversations/{conversation.id}/messages", headers=_headers(2)).status_code == 404
    assert client.get("/chat/conversations/99999/messages", headers=_headers(1)).status_code == 404


def test_messages_list_fields(client_factory, sqlite_session):
    conversation = _conversation(sqlite_session, user_id=1)
    _message(sqlite_session, conversation, "user", "q")
    _message(sqlite_session, conversation, "assistant", "a")
    client = client_factory(conversations_router, sqlite_session)

    response = client.get(f"/chat/conversations/{conversation.id}/messages", headers=_headers(1))
    assert response.status_code == 200
    assert [m["role"] for m in response.json()] == ["user", "assistant"]
    assert set(response.json()[0]) == {"id", "role", "content"}


def test_delete_message_pair_returns_remaining_and_rebuilds(client_factory, sqlite_session, monkeypatch):
    conversation = _conversation(sqlite_session, user_id=1)
    m1 = _message(sqlite_session, conversation, "user", "q1")
    m2 = _message(sqlite_session, conversation, "assistant", "a1")
    m3 = _message(sqlite_session, conversation, "user", "q2")
    m4 = _message(sqlite_session, conversation, "assistant", "a2")

    rebuilds: list[tuple[int, int]] = []
    monkeypatch.setattr(
        chat_service, "_rebuild_memory_safely", lambda db, cid, uid: rebuilds.append((cid, uid))
    )

    client = client_factory(conversations_router, sqlite_session)
    response = client.delete(
        f"/chat/conversations/{conversation.id}/messages/{m1.id}", headers=_headers(1)
    )

    assert response.status_code == 200
    assert [m["id"] for m in response.json()] == [m3.id, m4.id]
    assert rebuilds == [(conversation.id, 1)]
    assert [m.id for m in chat_service.repository.list_messages(sqlite_session, conversation.id)] == [
        m3.id,
        m4.id,
    ]
    assert m2.id not in [m["id"] for m in response.json()]


def test_delete_message_pair_from_assistant(client_factory, sqlite_session):
    conversation = _conversation(sqlite_session, user_id=1)
    m1 = _message(sqlite_session, conversation, "user", "q")
    _message(sqlite_session, conversation, "assistant", "a")
    client = client_factory(conversations_router, sqlite_session)

    response = client.delete(
        f"/chat/conversations/{conversation.id}/messages/{m1.id + 1}", headers=_headers(1)
    )
    assert response.status_code == 200
    assert response.json() == []


def test_delete_message_missing_404(client_factory, sqlite_session):
    conversation = _conversation(sqlite_session, user_id=1)
    client = client_factory(conversations_router, sqlite_session)
    response = client.delete(f"/chat/conversations/{conversation.id}/messages/9999", headers=_headers(1))
    assert response.status_code == 404
    assert response.json()["message"] == "消息不存在"


def test_favorite_lifecycle(client_factory, sqlite_session):
    first = _conversation(sqlite_session, user_id=1)
    second = _conversation(sqlite_session, user_id=1)
    client = client_factory(conversations_router, sqlite_session)

    # 首次收藏排序号 = maxFavoriteOrder(-1) + 1 = 0（Java 语义）。
    r1 = client.put(
        f"/chat/conversations/{first.id}/favorite",
        json={"favorite": True, "note": "  重要  "},
        headers=_headers(1),
    )
    assert r1.status_code == 200
    assert r1.json()["favorite"] is True
    assert r1.json()["favoriteNote"] == "重要"
    assert r1.json()["favoriteOrder"] == 0
    assert r1.json()["favoritedAtMs"] > 0

    r2 = client.put(
        f"/chat/conversations/{second.id}/favorite", json={"favorite": True}, headers=_headers(1)
    )
    assert r2.json()["favoriteOrder"] == 1

    # 取消收藏：备注/排序号/收藏时间一并清空。
    r3 = client.put(
        f"/chat/conversations/{first.id}/favorite", json={"favorite": False}, headers=_headers(1)
    )
    assert r3.json()["favorite"] is False
    assert r3.json()["favoriteNote"] is None
    assert r3.json()["favoriteOrder"] is None
    assert r3.json()["favoritedAtMs"] == 0

    missing = client.put(
        f"/chat/conversations/{second.id}/favorite", json={}, headers=_headers(1)
    )
    assert missing.status_code == 400
    assert missing.json()["message"] == "缺少 favorite 参数"

    unknown = client.put(
        "/chat/conversations/99999/favorite", json={"favorite": True}, headers=_headers(1)
    )
    assert unknown.status_code == 404


def test_reorder_favorites_and_list(client_factory, sqlite_session):
    a = _conversation(sqlite_session, user_id=1, title="a", favorite=True, favorite_order=0)
    b = _conversation(sqlite_session, user_id=1, title="b", favorite=True, favorite_order=1)
    client = client_factory(conversations_router, sqlite_session)

    response = client.put(
        "/chat/conversations/favorites/order", json={"ids": [b.id, a.id]}, headers=_headers(1)
    )
    assert response.status_code == 200
    assert [row["id"] for row in response.json()[:2]] == [b.id, a.id]
    assert response.json()[0]["favoriteOrder"] == 0
    assert response.json()[1]["favoriteOrder"] == 1

    # 空 body 等价 Java request == null：不改排序，直接返回当前列表。
    empty = client.put("/chat/conversations/favorites/order", headers=_headers(1))
    assert empty.status_code == 200


def test_delete_conversation_and_clear_all(client_factory, sqlite_session, monkeypatch):
    mine1 = _conversation(sqlite_session, user_id=1)
    _message(sqlite_session, mine1, "user", "q")
    mine2 = _conversation(sqlite_session, user_id=1)
    other = _conversation(sqlite_session, user_id=2)

    rebuilds: list[tuple[int, int]] = []
    monkeypatch.setattr(
        chat_service, "_rebuild_memory_safely", lambda db, cid, uid: rebuilds.append((cid, uid))
    )
    client = client_factory(conversations_router, sqlite_session)

    deleted = client.delete(f"/chat/conversations/{mine1.id}", headers=_headers(1))
    assert deleted.status_code == 200
    assert deleted.content == b""
    assert rebuilds == [(mine1.id, 1)]

    assert client.delete(f"/chat/conversations/{mine1.id}", headers=_headers(1)).status_code == 404
    assert (
        client.delete(f"/chat/conversations/{other.id}", headers=_headers(1)).status_code == 404
    )

    cleared = client.delete("/chat/conversations", headers=_headers(1))
    assert cleared.status_code == 200
    assert cleared.json() == {"deleted": 1}
    assert rebuilds[-1] == (mine2.id, 1)

    assert client.get("/chat/conversations", headers=_headers(1)).json() == []
    assert len(client.get("/chat/conversations", headers=_headers(2)).json()) == 1


# ---------------------------------------------------------------------------
# 用户记忆（本地降级 + chat-core 委托）
# ---------------------------------------------------------------------------


def _memory(db, user_id: int, content: str, updated_at: datetime) -> ChatUserMemory:
    row = ChatUserMemory(
        user_id=user_id,
        content=content,
        created_at=updated_at,
        updated_at=updated_at,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_user_memory_fallback_panel_default_enabled_and_order(client_factory, sqlite_session, monkeypatch):
    import app.api.user_memory as user_memory_api

    monkeypatch.setattr(user_memory_api, "_memory_module", lambda: None)
    older = _memory(sqlite_session, 1, "older", datetime(2026, 10, 1))
    newer = _memory(sqlite_session, 1, "newer", datetime(2026, 10, 2))
    _memory(sqlite_session, 2, "other-user", datetime(2026, 10, 3))

    client = client_factory(user_memory_router, sqlite_session)
    response = client.get("/chat/user-memory", headers=_headers(1))

    assert response.status_code == 200
    body = response.json()
    # 没有 setting 行时默认启用（Java isEnabled 语义）。
    assert body["enabled"] is True
    assert [item["id"] for item in body["items"]] == [newer.id, older.id]
    assert body["items"][0] == {
        "id": newer.id,
        "content": "newer",
        "createdAtMs": epoch_ms(datetime(2026, 10, 2)),
    }


def test_user_memory_fallback_settings_and_delete(client_factory, sqlite_session, monkeypatch):
    import app.api.user_memory as user_memory_api

    monkeypatch.setattr(user_memory_api, "_memory_module", lambda: None)
    mine = _memory(sqlite_session, 1, "mine", datetime(2026, 10, 1))
    other = _memory(sqlite_session, 2, "other", datetime(2026, 10, 1))
    client = client_factory(user_memory_router, sqlite_session)

    disabled = client.put("/chat/user-memory/settings", json={"enabled": False}, headers=_headers(1))
    assert disabled.status_code == 200
    assert client.get("/chat/user-memory", headers=_headers(1)).json()["enabled"] is False

    # 缺省字段按 false（Java 基本类型 boolean）。
    client.put("/chat/user-memory/settings", json={}, headers=_headers(1))
    assert client.get("/chat/user-memory", headers=_headers(1)).json()["enabled"] is False

    assert client.delete(f"/chat/user-memory/{other.id}", headers=_headers(1)).status_code == 404
    assert client.delete("/chat/user-memory/9999", headers=_headers(1)).status_code == 404
    assert client.delete(f"/chat/user-memory/{mine.id}", headers=_headers(1)).status_code == 200
    assert client.get("/chat/user-memory", headers=_headers(1)).json()["items"] == []


def test_user_memory_delegates_to_chat_core(client_factory, sqlite_session, monkeypatch):
    import app.api.user_memory as user_memory_api

    calls: list[tuple] = []

    fake = SimpleNamespace(
        get_panel=lambda db, uid: calls.append(("panel", uid)) or {"enabled": True, "items": []},
        set_enabled=lambda db, uid, enabled: calls.append(("set", uid, enabled)),
        delete_memory=lambda db, uid, mid: calls.append(("delete", uid, mid)),
    )
    monkeypatch.setattr(user_memory_api, "_memory_module", lambda: fake)
    memory = _memory(sqlite_session, 3, "x", datetime(2026, 10, 1))
    client = client_factory(user_memory_router, sqlite_session)

    assert client.get("/chat/user-memory", headers=_headers(3)).json() == {"enabled": True, "items": []}
    client.put("/chat/user-memory/settings", json={"enabled": True}, headers=_headers(3))
    client.delete(f"/chat/user-memory/{memory.id}", headers=_headers(3))

    assert calls == [("panel", 3), ("set", 3, True), ("delete", 3, memory.id)]


def test_user_memory_settings_row_upsert(sqlite_session):
    from app.api.user_memory import _local_get_panel, _local_set_enabled

    _local_set_enabled(sqlite_session, 5, False)
    row = sqlite_session.get(ChatUserMemorySetting, 5)
    assert row is not None and row.enabled is False

    _local_set_enabled(sqlite_session, 5, True)
    sqlite_session.refresh(row)
    assert row.enabled is True
    assert _local_get_panel(sqlite_session, 5)["enabled"] is True


def test_user_memory_integrates_with_real_chat_core_module(client_factory, sqlite_session, monkeypatch):
    """chat-core 已落地时，路由必须真正委托 app.memory.user_memory（而非本地降级）。"""
    import app.memory.user_memory as core

    class _NoPG:
        def __enter__(self):
            raise RuntimeError("pg down")

        def __exit__(self, *_exc):
            return False

    # 删记忆时 chat-core 会尽力删 PG 向量；测试环境不连 PG。
    monkeypatch.setattr(core, "pg_connection", lambda: _NoPG())
    memory = _memory(sqlite_session, 1, "real-core", datetime(2026, 10, 1))
    client = client_factory(user_memory_router, sqlite_session)

    panel = client.get("/chat/user-memory", headers=_headers(1))
    assert panel.status_code == 200
    assert panel.json()["enabled"] is True
    assert [item["id"] for item in panel.json()["items"]] == [memory.id]

    assert client.put("/chat/user-memory/settings", json={"enabled": False}, headers=_headers(1)).status_code == 200
    assert client.get("/chat/user-memory", headers=_headers(1)).json()["enabled"] is False

    assert client.delete(f"/chat/user-memory/{memory.id}", headers=_headers(1)).status_code == 200
    assert client.get("/chat/user-memory", headers=_headers(1)).json()["items"] == []


def test_delete_conversation_calls_real_rebuild_memory(client_factory, sqlite_session, monkeypatch):
    """chat-core 的 app.memory.rebuild.rebuild_memory 到位后，删会话必须调用它重建记忆。"""
    import app.memory.long as long_memory

    calls: list[tuple[str, list]] = []
    monkeypatch.setattr(
        long_memory,
        "rebuild_conversation_vectors",
        lambda key, messages: calls.append((str(key), messages)),
    )
    monkeypatch.setattr(chat_service, "_REBUILD_IMPORT_ATTEMPTED", False)
    monkeypatch.setattr(chat_service, "_REBUILD_MEMORY", None)

    conversation = _conversation(sqlite_session, user_id=1)
    _message(sqlite_session, conversation, "user", "q")
    _message(sqlite_session, conversation, "assistant", "a")
    client = client_factory(conversations_router, sqlite_session)

    assert client.delete(f"/chat/conversations/{conversation.id}", headers=_headers(1)).status_code == 200
    # 会话已删 → 重建时剩余消息为空，等价「清空向量记忆」。
    assert calls == [(str(conversation.id), [])]
