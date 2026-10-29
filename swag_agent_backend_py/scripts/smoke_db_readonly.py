#!/usr/bin/env python3
"""真实 MySQL 只读冒烟：确认 Python 模型/连接与现有库兼容（不写任何数据）。

用法：
    cd swag_agent_backend_py
    .venv/bin/python scripts/smoke_db_readonly.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select, text

from app.db.base import SessionLocal, engine
from app.db.models import (
    AppUser,
    AuditEvent,
    ChatConversation,
    ChatMessage,
    SpringAiChatMemory,
    TodoItem,
    WebsiteBookmark,
)


def main() -> int:
    with engine.connect() as conn:
        version = conn.execute(text("SELECT VERSION()")).scalar()
        tz = conn.execute(text("SELECT @@session.time_zone")).scalar()
    print(f"mysql version={version} session_tz={tz}")

    with SessionLocal() as db:
        rows = {
            "app_user": db.scalar(select(func.count()).select_from(AppUser)),
            "chat_conversation": db.scalar(select(func.count()).select_from(ChatConversation)),
            "chat_message": db.scalar(select(func.count()).select_from(ChatMessage)),
            "SPRING_AI_CHAT_MEMORY": db.scalar(select(func.count()).select_from(SpringAiChatMemory)),
            "todo_item": db.scalar(select(func.count()).select_from(TodoItem)),
            "website_bookmark": db.scalar(select(func.count()).select_from(WebsiteBookmark)),
            "audit_event": db.scalar(select(func.count()).select_from(AuditEvent)),
        }
    for name, count in rows.items():
        print(f"{name:28s} {count}")

    with SessionLocal() as db:
        conv = db.scalar(select(ChatConversation).order_by(ChatConversation.id.desc()).limit(1))
        if conv:
            print(
                "latest conversation:",
                conv.id,
                conv.user_id,
                repr(conv.title),
                conv.created_at,
                conv.updated_at,
            )
        mem = db.scalar(select(SpringAiChatMemory).limit(1))
        if mem:
            print("memory row sample: conversation_id=", mem.conversation_id, "type=", mem.type)
    return 0


if __name__ == "__main__":
    sys.exit(main())
