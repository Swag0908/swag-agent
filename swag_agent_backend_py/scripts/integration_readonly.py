#!/usr/bin/env python3
"""只读集成冒烟：用真实 MySQL + 临时 token 跑一遍读接口，结束后删除临时 token。

不写业务数据。审计通过 AUDIT_ENABLED=false 关闭，避免往 audit_event 写测试记录。
用法：
    cd swag_agent_backend_py
    AUDIT_ENABLED=false .venv/bin/python scripts/integration_readonly.py
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("AUDIT_ENABLED", "false")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.core.timeutil import now, today  # noqa: E402
from app.db.base import SessionLocal  # noqa: E402
from app.db.models import AuditEvent, AuthToken, ChatConversation  # noqa: E402
from app.main import app  # noqa: E402


def show(name: str, response) -> dict | list | None:
    ctype = response.headers.get("content-type", "")
    body = None
    if "json" in ctype:
        try:
            body = response.json()
        except Exception:  # noqa: BLE001
            body = None
    summary = body
    if isinstance(body, list):
        summary = f"list[{len(body)}] first={json.dumps(body[0], ensure_ascii=False)[:160] if body else ''}"
    elif isinstance(body, dict):
        summary = json.dumps(body, ensure_ascii=False)[:240]
    print(f"{name:42s} {response.status_code} {summary}")
    return body


def main() -> int:
    with SessionLocal() as db:
        conv = db.scalar(select(ChatConversation).order_by(ChatConversation.id.desc()).limit(1))
        conversation_id = conv.id if conv else None
        audit_id = db.scalar(select(AuditEvent.audit_id).order_by(AuditEvent.recorded_at.desc()).limit(1))
        token = str(uuid.uuid4())
        db.add(AuthToken(token=token, user_id=1, expires_at=now() + timedelta(minutes=10), created_at=now()))
        db.commit()

    headers = {"Authorization": f"Bearer {token}"}
    try:
        with TestClient(app) as client:
            show("health", client.get("/actuator/health"))
            body = show("auth/me", client.get("/auth/me", headers=headers))
            assert body and body["userId"] == 1 and body["role"] == "ADMIN", body

            show("conversations", client.get("/chat/conversations", headers=headers))
            if conversation_id:
                show(f"conversation {conversation_id} messages",
                     client.get(f"/chat/conversations/{conversation_id}/messages", headers=headers))
            show("user memory", client.get("/chat/user-memory", headers=headers))
            show("bookmarks", client.get("/bookmarks", headers=headers))

            start = (today() - timedelta(days=6)).isoformat()
            end = today().isoformat()
            show("todos range", client.get("/todo", params={"from": start, "to": end}, headers=headers))
            show("todo stats", client.get("/todo/stats/daily", headers=headers))
            show("notes tree", client.get("/notes/tree", headers=headers))
            show("skills", client.get("/auth/admin/skills", headers=headers))
            show("audit chains", client.get("/audit/chains", params={"limit": 3}, headers=headers))
            if audit_id:
                show("audit events", client.get(f"/audit/events/{audit_id}", headers=headers))
            show("zipkin access (cookie)", client.get(
                "/auth/zipkin-access", cookies={"swag_zipkin_token": token}))
            show("401 no token", client.get("/chat/conversations"))
    finally:
        with SessionLocal() as db:
            db.query(AuthToken).filter(AuthToken.token == token).delete()
            db.commit()
        print("\ntemporary token removed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
