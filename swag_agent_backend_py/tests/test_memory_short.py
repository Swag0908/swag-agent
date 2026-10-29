"""短期/长期/用户记忆的降级与重建测试（SQLite + monkeypatch，不连真实 MySQL/PG/Ollama）。

覆盖：
1. 短期记忆直接读 `chat_message` 最近 40 条、按 id 升序；
2. 落库辅助（insert_message/append_turn）的空值语义；
3. `SPRING_AI_CHAT_MEMORY` 整窗重写：DELETE + sequence 0..n-1 + 大写 type + 微秒截断；
4. 长期向量链路降级：Ollama 不可用 / PG 不可用都返回空、不抛；
5. 用户长期记忆：开关缺省开启、面板 payload、删除不存在→404、300 字截断、召回降级最近 N 条；
6. 提示词三段中的「用户长期记忆」确实来自 MySQL（向量降级路径）。
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.agent import prompt as prompt_module
from app.core.errors import NotFound
from app.core.timeutil import now, truncate_to_second
from app.db.models import (
    ChatConversation,
    ChatMessage,
    ChatUserMemory,
    ChatUserMemorySetting,
    SpringAiChatMemory,
)
from app.memory import long as long_memory
from app.memory import short as short_memory
from app.memory import user_memory
from app.memory.rebuild import rebuild_conversation_memory


def _conversation(db, user_id: int = 1) -> ChatConversation:
    stamp = truncate_to_second(now())
    conversation = ChatConversation(
        user_id=user_id, title="", created_at=stamp, updated_at=stamp, favorite=False
    )
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation


# ---------------------------------------------------------------------------
# 1) 短期记忆
# ---------------------------------------------------------------------------


def test_load_history_returns_last_40_in_ascending_order(sqlite_session):
    conversation = _conversation(sqlite_session)
    base = truncate_to_second(now()) - timedelta(minutes=45)
    for index in range(45):
        short_memory.insert_message(
            sqlite_session,
            conversation.id,
            1,
            "user" if index % 2 == 0 else "assistant",
            f"msg-{index}",
            at=base + timedelta(seconds=index),
        )

    history = short_memory.load_history(sqlite_session, conversation.id)
    assert len(history) == 40
    assert history[0]["content"] == "msg-5"  # 丢掉最旧的 5 条
    assert history[-1]["content"] == "msg-44"
    assert all(message["role"] in {"user", "assistant"} for message in history)

    # 太少/缺省
    assert short_memory.load_history(sqlite_session, None) == []
    assert len(short_memory.load_history(sqlite_session, conversation.id, max_messages=7)) == 7


def test_insert_message_skips_blank_and_append_turn_writes_pair(sqlite_session):
    conversation = _conversation(sqlite_session)
    assert short_memory.insert_message(sqlite_session, conversation.id, 1, "assistant", "  ") is None

    short_memory.append_turn(sqlite_session, conversation.id, 1, "问题", "回答")
    rows = sqlite_session.execute(
        select(ChatMessage.role, ChatMessage.content).where(ChatMessage.conversation_id == conversation.id)
    ).all()
    assert rows == [("user", "问题"), ("assistant", "回答")]
    # dual_write 默认关闭 → 不碰兼容表
    assert sqlite_session.execute(select(SpringAiChatMemory)).all() == []


# ---------------------------------------------------------------------------
# 2) SPRING_AI_CHAT_MEMORY 整窗重写
# ---------------------------------------------------------------------------


def test_rebuild_from_chat_messages_rewrites_window(sqlite_session):
    conversation = _conversation(sqlite_session)
    stamp = truncate_to_second(now())
    # 先放一条脏数据 + 45 条真实消息
    sqlite_session.add(
        SpringAiChatMemory(
            conversation_id=str(conversation.id),
            sequence_id=999,
            content="stale",
            type="USER",
            timestamp=stamp,
        )
    )
    sqlite_session.commit()
    for index in range(45):
        short_memory.insert_message(
            sqlite_session,
            conversation.id,
            1,
            "user" if index % 2 == 0 else "assistant",
            f"m{index}",
            at=stamp + timedelta(seconds=index),
        )

    short_memory.rebuild_from_chat_messages(sqlite_session, conversation.id, 1)

    rows = sqlite_session.execute(
        select(SpringAiChatMemory)
        .where(SpringAiChatMemory.conversation_id == str(conversation.id))
        .order_by(SpringAiChatMemory.sequence_id)
    ).scalars().all()
    assert len(rows) == 40  # 只保留窗口内 40 条
    assert [row.sequence_id for row in rows] == list(range(40))
    assert rows[0].content == "m5"  # 丢掉最旧的 5 条，m5 是奇数 → assistant
    assert rows[0].type == "ASSISTANT"
    assert rows[1].type == "USER"
    assert all(row.timestamp.microsecond == 0 for row in rows)
    assert "stale" not in {row.content for row in rows}


# ---------------------------------------------------------------------------
# 3) 长期向量链路降级
# ---------------------------------------------------------------------------


def test_recall_semantic_degrades_when_ollama_or_pg_unavailable(monkeypatch):
    monkeypatch.setattr(long_memory, "embed_sync", lambda text: None)
    assert long_memory.recall_semantic(None, "12", "今天聊了什么") == []

    monkeypatch.setattr(long_memory, "embed_sync", lambda text: [0.1, 0.2, 0.3])

    def _boom():
        raise RuntimeError("pg down")

    monkeypatch.setattr(long_memory, "pg_connection", _boom)
    assert long_memory.recall_semantic(None, "12", "今天聊了什么") == []
    assert long_memory.recall_semantic(None, None, "q") == []
    assert long_memory.recall_semantic(None, "12", "") == []
    # 删除也降级（不抛）
    long_memory.delete_conversation_vectors("12")
    assert long_memory.store_message_vector("12", "内容", "USER") is False


def test_rebuild_conversation_memory_survives_vector_failure(sqlite_session, monkeypatch):
    conversation = _conversation(sqlite_session)
    short_memory.append_turn(sqlite_session, conversation.id, 1, "问", "答")
    monkeypatch.setattr(long_memory, "delete_conversation_vectors", lambda cid: None)
    monkeypatch.setattr(long_memory, "store_message_vector", lambda *args, **kwargs: True)

    rebuild_conversation_memory(sqlite_session, conversation.id, 1)

    rows = sqlite_session.execute(
        select(SpringAiChatMemory.content)
        .where(SpringAiChatMemory.conversation_id == str(conversation.id))
        .order_by(SpringAiChatMemory.sequence_id)
    ).scalars().all()
    assert rows == ["问", "答"]


# ---------------------------------------------------------------------------
# 4) 用户长期记忆
# ---------------------------------------------------------------------------


def test_user_memory_defaults_enabled_and_panel_payload(sqlite_session):
    assert user_memory.is_enabled(sqlite_session, 1) is True  # 无设置行 = 开启
    assert user_memory.get_panel(sqlite_session, 1) == {"enabled": True, "items": []}

    stamp = truncate_to_second(now())
    sqlite_session.add(ChatUserMemory(user_id=1, content="偏好 Markdown", created_at=stamp, updated_at=stamp))
    sqlite_session.commit()
    panel = user_memory.get_panel(sqlite_session, 1)
    assert panel["enabled"] is True
    assert panel["items"][0]["content"] == "偏好 Markdown"
    assert panel["items"][0]["createdAtMs"] > 0

    user_memory.set_enabled(sqlite_session, 1, False)
    assert sqlite_session.get(ChatUserMemorySetting, 1).enabled is False
    assert user_memory.get_panel(sqlite_session, 1)["enabled"] is False
    # 关闭后不召回
    assert user_memory.recall(sqlite_session, 1, "任何问题") == []


def test_user_memory_delete_and_not_found(sqlite_session, monkeypatch):
    stamp = truncate_to_second(now())
    memory = ChatUserMemory(user_id=1, content="x", created_at=stamp, updated_at=stamp)
    sqlite_session.add(memory)
    sqlite_session.commit()

    deleted: list[int] = []

    class _Conn:
        def execute(self, *args, **kwargs):  # noqa: ANN002, ANN003
            return self

        def commit(self) -> None:
            return None

    class _Ctx:
        def __enter__(self):
            return _Conn()

        def __exit__(self, *args):  # noqa: ANN002
            return False

    monkeypatch.setattr(user_memory, "pg_connection", lambda: _Ctx())
    user_memory.delete_memory(sqlite_session, 1, int(memory.id))
    deleted.append(int(memory.id))
    assert sqlite_session.get(ChatUserMemory, deleted[0]) is None

    with pytest.raises(NotFound):
        user_memory.delete_memory(sqlite_session, 1, 999999)


def test_user_memory_normalize_and_recall_degrade(sqlite_session, monkeypatch):
    assert user_memory.normalize_content("  a   b  ") == "a b"
    long_text = user_memory.normalize_content("字" * 400)
    assert len(long_text) == 301 and long_text.endswith("…")

    stamp = truncate_to_second(now())
    for index in range(3):
        sqlite_session.add(
            ChatUserMemory(
                user_id=2,
                content=f"记忆{index}",
                created_at=stamp + timedelta(seconds=index),
                updated_at=stamp + timedelta(seconds=index),
            )
        )
    sqlite_session.commit()

    # 向量不可用 → 降级最近 N 条（按 updated_at 倒序）
    monkeypatch.setattr(long_memory, "embed_sync", lambda text: None)
    assert user_memory.recall(sqlite_session, 2, "任意", top_k=2) == ["记忆2", "记忆1"]


def test_prompt_injects_user_memory_from_mysql(sqlite_session, monkeypatch):
    stamp = truncate_to_second(now())
    sqlite_session.add(ChatUserMemory(user_id=3, content="用户偏好表格", created_at=stamp, updated_at=stamp))
    sqlite_session.commit()
    monkeypatch.setattr(long_memory, "embed_sync", lambda text: None)
    monkeypatch.setattr(prompt_module, "_skill_guide", lambda db: "")

    system_prompt = prompt_module.build_system_prompt(sqlite_session, 3, "帮我整理")
    assert "【该用户的长期记忆档案" in system_prompt
    assert "1. 用户偏好表格\n" in system_prompt
    assert system_prompt.startswith(prompt_module.SYSTEM_PROMPT)


def test_user_memory_created_at_ms_roundtrip(sqlite_session):
    stamp = datetime(2026, 10, 28, 16, 30, 0)
    memory = ChatUserMemory(user_id=4, content="x", created_at=stamp, updated_at=stamp)
    sqlite_session.add(memory)
    sqlite_session.commit()
    panel = user_memory.get_panel(sqlite_session, 4)
    assert panel["items"][0]["createdAtMs"] == user_memory.epoch_ms(stamp)
