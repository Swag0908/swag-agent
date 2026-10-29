"""SQLAlchemy 模型：严格对应现有 MySQL schema（20 张表里业务使用的 18 张 + Spring AI 记忆表）。

注意：
- 这些模型只用于读写，不用于自动建表（生产库已有结构，DDL 由 Java/Flyway 拥有）。
- 列类型用可移植类型表达（Boolean/Text/JSON/DateTime），避免在测试库上编译 MySQL 专有类型失败。
- 精度差异在 service 层处理：DATETIME(0) 表写前截断微秒。
"""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Index,
    Integer,
    JSON,
    LargeBinary,
    Numeric,
    String,
    Text,
    Time,
)
from sqlalchemy.orm import Mapped, mapped_column

# SQLite 只有 INTEGER PRIMARY KEY 才会自增；测试库用 Integer 变体，MySQL 仍是 BIGINT。
BigIntPK = BigInteger().with_variant(Integer, "sqlite")

from app.db.base import Base


class AppUser(Base):
    __tablename__ = "app_user"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(128))
    display_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    role: Mapped[str] = mapped_column(String(16), default="USER")


class AuthToken(Base):
    __tablename__ = "auth_token"

    token: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class AppRegisterSetting(Base):
    __tablename__ = "app_register_setting"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    register_code: Mapped[str] = mapped_column(String(64))
    registration_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class ChatConversation(Base):
    __tablename__ = "chat_conversation"
    __table_args__ = (Index("idx_chat_conv_user", "user_id", "updated_at"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger)
    title: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)
    favorite: Mapped[bool] = mapped_column(Boolean, default=False)
    favorite_note: Mapped[str | None] = mapped_column(String(120), nullable=True)
    favorite_order: Mapped[int | None] = mapped_column(Integer, nullable=True)
    favorited_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ChatMessage(Base):
    __tablename__ = "chat_message"
    __table_args__ = (Index("idx_chat_msg_conv", "conversation_id", "id"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(BigInteger)
    user_id: Mapped[int] = mapped_column(BigInteger)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class SpringAiChatMemory(Base):
    __tablename__ = "SPRING_AI_CHAT_MEMORY"

    conversation_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    content: Mapped[str] = mapped_column(Text)
    type: Mapped[str] = mapped_column(String(10))
    timestamp: Mapped[datetime] = mapped_column(DateTime)
    sequence_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)


class ChatUserMemory(Base):
    __tablename__ = "chat_user_memory"
    __table_args__ = (Index("idx_user_memory_user", "user_id", "updated_at"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger)
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class ChatUserMemorySetting(Base):
    __tablename__ = "chat_user_memory_setting"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class TodoItem(Base):
    __tablename__ = "todo_item"
    __table_args__ = (
        Index("idx_todo_user_due_status", "user_id", "due_date", "status"),
        Index("idx_todo_user_created", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger)
    title: Mapped[str] = mapped_column(String(255))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    due_date: Mapped[date] = mapped_column(Date)
    due_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="TODO")
    source: Mapped[str] = mapped_column(String(16), default="CHAT")
    created_at: Mapped[datetime] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class TodoDeferLog(Base):
    __tablename__ = "todo_defer_log"
    __table_args__ = (Index("idx_defer_user_from", "user_id", "from_date"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    item_id: Mapped[int] = mapped_column(BigInteger)
    user_id: Mapped[int] = mapped_column(BigInteger)
    from_date: Mapped[date] = mapped_column(Date)
    to_date: Mapped[date] = mapped_column(Date)
    deferred_at: Mapped[datetime] = mapped_column(DateTime)


class TodoDailyStat(Base):
    __tablename__ = "todo_daily_stat"

    stat_date: Mapped[date] = mapped_column(Date, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    created_count: Mapped[int] = mapped_column(Integer, default=0)
    completed_count: Mapped[int] = mapped_column(Integer, default=0)
    pending_count: Mapped[int] = mapped_column(Integer, default=0)
    deferred_count: Mapped[int] = mapped_column(Integer, default=0)
    completion_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)


class WebsiteFolder(Base):
    __tablename__ = "website_folder"
    __table_args__ = (
        Index("idx_folder_user_parent", "user_id", "parent_id"),
        Index("idx_folder_user_created", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger)
    name: Mapped[str] = mapped_column(String(64))
    parent_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class WebsiteBookmark(Base):
    __tablename__ = "website_bookmark"
    __table_args__ = (
        Index("idx_bookmark_user_folder", "user_id", "folder_id"),
        Index("idx_bookmark_user_created", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger)
    folder_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    name: Mapped[str] = mapped_column(String(128))
    url: Mapped[str] = mapped_column(String(1024))
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    icon_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)
    icon_data: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    icon_content_type: Mapped[str | None] = mapped_column(String(100), nullable=True)


class SkillState(Base):
    __tablename__ = "skill_state"

    skill_name: Mapped[str] = mapped_column(String(128), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class AuditEvent(Base):
    __tablename__ = "audit_event"
    __table_args__ = (
        Index("idx_audit_event_audit_time", "audit_id", "occurred_at"),
        Index("idx_audit_event_trace", "trace_id"),
        Index("idx_audit_event_user_time", "tenant_id", "actor_id", "occurred_at"),
        Index("idx_audit_event_tool_call", "tool_call_id"),
        Index("idx_audit_event_confirmation", "confirmation_id"),
        Index("idx_audit_event_conversation", "conversation_id", "occurred_at"),
    )

    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    audit_id: Mapped[str] = mapped_column(String(36))
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_event_id: Mapped[str | None] = mapped_column(String(128), nullable=True, unique=True)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    span_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    parent_span_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    parent_event_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    tenant_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    session_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    actor_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    actor_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    actor_display_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    event_type: Mapped[str] = mapped_column(String(64))
    execution_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    agent_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    agent_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    tool_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    tool_call_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    confirmation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    action_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    input_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    input_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    output_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    output_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    event_data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime)
    recorded_at: Mapped[datetime] = mapped_column(DateTime)
    schema_version: Mapped[int] = mapped_column(Integer, default=1)
    previous_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    event_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    conversation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class AuditPayload(Base):
    __tablename__ = "audit_payload"

    payload_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    audit_id: Mapped[str] = mapped_column(String(36))
    payload_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    storage_uri: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    content_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    media_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    encryption_key_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    redaction_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AuditRequestSummary(Base):
    __tablename__ = "audit_request_summary"

    audit_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    tenant_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    user_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    request_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    request_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    final_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    risk_level: Mapped[str | None] = mapped_column(String(16), nullable=True)
    tool_call_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confirmation_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    failed_event_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    last_event_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    retention_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AuditConfirmation(Base):
    __tablename__ = "audit_confirmation"
    __table_args__ = (
        Index("idx_audit_confirmation_audit", "audit_id"),
        Index("idx_audit_confirmation_status_expiry", "status", "expires_at"),
    )

    confirmation_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    audit_id: Mapped[str] = mapped_column(String(36))
    tool_call_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    tenant_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    actor_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    tool_name: Mapped[str] = mapped_column(String(128))
    canonical_input: Mapped[str] = mapped_column(Text)
    action_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="PENDING")
    decision_reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


__all__ = [
    "AppUser",
    "AuthToken",
    "AppRegisterSetting",
    "ChatConversation",
    "ChatMessage",
    "SpringAiChatMemory",
    "ChatUserMemory",
    "ChatUserMemorySetting",
    "TodoItem",
    "TodoDeferLog",
    "TodoDailyStat",
    "WebsiteFolder",
    "WebsiteBookmark",
    "SkillState",
    "AuditEvent",
    "AuditPayload",
    "AuditRequestSummary",
    "AuditConfirmation",
]
