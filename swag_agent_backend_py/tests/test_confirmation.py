"""危险操作确认测试：5 状态机、一次性消费、过期、409 包络、审批端点。

全部跑 SQLite 内存库；需要写审计事件的地方通过 monkeypatch
``app.audit.recorder.SessionLocal`` 注入测试 Session 工厂，不连真实 MySQL。
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import timedelta
from typing import Iterator
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.db.models  # noqa: F401
from app.audit import confirmation, recorder
from app.audit.confirmation import ConfirmationStatus
from app.audit.context import AuditContext
from app.audit.digest import action_digest, canonicalize_json, raw_tool_input
from app.audit.tool_audit import check_tool_confirmation, record_tool_requested
from app.api import audit as audit_api
from app.config import settings
from app.core.errors import ConfirmationInvalid, ConfirmationRequired, install_error_handlers
from app.core.timeutil import now
from app.db.base import Base
from app.db.models import AuditConfirmation, AuditEvent

DANGER_TOOL = "notes_delete"


# ---------------------------------------------------------------------------
# fixtures / helpers
# ---------------------------------------------------------------------------


@contextmanager
def _sqlite_factory() -> Iterator[sessionmaker]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    yield factory


@pytest.fixture()
def session_factory(monkeypatch) -> Iterator[sessionmaker]:
    with _sqlite_factory() as factory:
        monkeypatch.setattr(recorder, "SessionLocal", factory)
        yield factory


@pytest.fixture()
def danger_tools(monkeypatch) -> None:
    monkeypatch.setattr(settings, "audit_confirmation_required_tools", DANGER_TOOL)


class _ToolCtx:
    """模拟 chat-core 的 ToolCtx（只带审计相关字段）。"""

    def __init__(self, user_id=1, audit_id=None, conversation_id=None, confirmation_id=None):
        self.user_id = user_id
        self.audit_id = audit_id or str(uuid4())
        self.conversation_id = conversation_id
        self.confirmation_id = confirmation_id


def _context(actor_id: str = "1", tenant_id: str = "default", audit_id: str | None = None):
    return AuditContext(
        audit_id=audit_id or str(uuid4()),
        request_id="req-1",
        tenant_id=tenant_id,
        actor_id=actor_id,
    )


def _events(factory: sessionmaker) -> list[AuditEvent]:
    with factory() as db:
        return list(db.scalars(select(AuditEvent)).all())


def _event_types(factory: sessionmaker) -> list[str]:
    return [event.event_type for event in _events(factory)]


def _request_ticket(factory: sessionmaker, ctx: AuditContext | None = None, **kwargs) -> ConfirmationRequired:
    """建一张 PENDING 票据并返回待抛出的 409 异常。"""
    ctx = ctx or _context()
    args = {"title": "x"}
    raw = raw_tool_input(args)
    return confirmation.request_confirmation(
        DANGER_TOOL,
        "call-1",
        canonicalize_json(raw),
        action_digest(DANGER_TOOL, raw),
        context=ctx,
        **kwargs,
    )


def _ticket_row(factory: sessionmaker, confirmation_id: str) -> AuditConfirmation:
    with factory() as db:
        row = db.get(AuditConfirmation, confirmation_id)
        assert row is not None
        return row


# ---------------------------------------------------------------------------
# 1) 状态机（service 层）
# ---------------------------------------------------------------------------


def test_requires_confirmation_reads_config(monkeypatch) -> None:
    monkeypatch.setattr(settings, "audit_confirmation_required_tools", "")
    assert confirmation.requires_confirmation(DANGER_TOOL) is False
    monkeypatch.setattr(settings, "audit_confirmation_required_tools", f"{DANGER_TOOL},other")
    assert confirmation.requires_confirmation(DANGER_TOOL) is True
    assert confirmation.requires_confirmation("other") is True
    assert confirmation.requires_confirmation("todo_list") is False


def test_parse_decision_is_case_insensitive() -> None:
    assert confirmation.parse_decision("approved") == "APPROVED"
    assert confirmation.parse_decision(" Denied ") == "DENIED"
    with pytest.raises(ConfirmationInvalid) as excinfo:
        confirmation.parse_decision("maybe")
    assert excinfo.value.extra["code"] == "CONFIRMATION_INVALID"
    with pytest.raises(ConfirmationInvalid):
        confirmation.parse_decision(None)


def test_request_confirmation_creates_pending_ticket(session_factory) -> None:
    ctx = _context()
    error = _request_ticket(session_factory, ctx)

    assert isinstance(error, ConfirmationRequired)
    assert error.status_code == 409
    assert error.extra["code"] == "CONFIRMATION_REQUIRED"
    assert error.extra["auditId"] == ctx.audit_id
    assert error.extra["toolName"] == DANGER_TOOL
    assert error.extra["requestedAt"].endswith("Z")
    assert error.extra["expiresAt"].endswith("Z")
    assert error.extra["confirmationId"]

    row = _ticket_row(session_factory, error.extra["confirmationId"])
    assert row.status == ConfirmationStatus.PENDING
    assert row.tenant_id == "default"
    assert row.actor_id == "1"
    assert row.tool_name == DANGER_TOOL
    assert row.decided_at is None
    assert row.consumed_at is None
    assert row.expires_at - row.requested_at == timedelta(
        seconds=settings.audit_confirmation_ttl_seconds
    )

    events = _events(session_factory)
    assert len(events) == 1
    assert events[0].event_type == "CONFIRMATION_REQUESTED"
    assert events[0].execution_status == "PENDING"
    assert events[0].audit_id == ctx.audit_id
    assert events[0].confirmation_id == row.confirmation_id
    assert events[0].tool_name == DANGER_TOOL


def test_decide_approve_then_consume_once(session_factory) -> None:
    ctx = _context()
    error = _request_ticket(session_factory, ctx)
    confirmation_id = error.extra["confirmationId"]

    decided = confirmation.decide(confirmation_id, "APPROVED", "看起来没问题", context=ctx)
    assert decided.status == ConfirmationStatus.APPROVED
    assert decided.decision_reason == "看起来没问题"
    assert decided.decided_at is not None

    consumed = confirmation.consume_approval(
        confirmation_id, DANGER_TOOL, decided.action_digest, context=ctx
    )
    assert consumed.status == ConfirmationStatus.CONSUMED
    assert consumed.consumed_at is not None

    with pytest.raises(ConfirmationInvalid) as excinfo:
        confirmation.consume_approval(
            confirmation_id, DANGER_TOOL, decided.action_digest, context=ctx
        )
    assert excinfo.value.extra["code"] == "CONFIRMATION_INVALID"

    events = _events(session_factory)
    assert [event.event_type for event in events] == [
        "CONFIRMATION_REQUESTED",
        "CONFIRMATION_APPROVED",
        "CONFIRMATION_CONSUMED",
    ]
    approved = events[1]
    assert approved.audit_id == ctx.audit_id
    assert approved.actor_type == "USER"
    assert approved.actor_id == "1"
    assert approved.event_data == {"reason": "看起来没问题"}


def test_decide_deny_then_consume_fails(session_factory) -> None:
    ctx = _context()
    error = _request_ticket(session_factory, ctx)
    confirmation_id = error.extra["confirmationId"]

    denied = confirmation.decide(confirmation_id, "DENIED", None, context=ctx)
    assert denied.status == ConfirmationStatus.DENIED

    with pytest.raises(ConfirmationInvalid):
        confirmation.consume_approval(confirmation_id, DANGER_TOOL, denied.action_digest, context=ctx)

    assert _event_types(session_factory) == [
        "CONFIRMATION_REQUESTED",
        "CONFIRMATION_DENIED",
    ]


def test_consume_requires_matching_action(session_factory) -> None:
    ctx = _context()
    error = _request_ticket(session_factory, ctx)
    confirmation_id = error.extra["confirmationId"]
    confirmation.decide(confirmation_id, "APPROVED", None, context=ctx)

    with pytest.raises(ConfirmationInvalid) as excinfo:
        confirmation.consume_approval(confirmation_id, DANGER_TOOL, "f" * 64, context=ctx)
    assert "does not match" in excinfo.value.message

    with pytest.raises(ConfirmationInvalid):
        confirmation.consume_approval(confirmation_id, "other_tool", "d" * 64, context=ctx)

    # 失败不改变票据状态，仍可用正确动作消费
    assert _ticket_row(session_factory, confirmation_id).status == ConfirmationStatus.APPROVED


def test_consume_requires_approved_status(session_factory) -> None:
    ctx = _context()
    error = _request_ticket(session_factory, ctx)
    confirmation_id = error.extra["confirmationId"]

    with pytest.raises(ConfirmationInvalid) as excinfo:
        confirmation.consume_approval(confirmation_id, DANGER_TOOL, "d" * 64, context=ctx)
    assert "not approved" in excinfo.value.message


def test_decide_rejects_non_pending(session_factory) -> None:
    ctx = _context()
    error = _request_ticket(session_factory, ctx)
    confirmation_id = error.extra["confirmationId"]
    confirmation.decide(confirmation_id, "APPROVED", None, context=ctx)

    with pytest.raises(ConfirmationInvalid) as excinfo:
        confirmation.decide(confirmation_id, "DENIED", None, context=ctx)
    assert "not pending" in excinfo.value.message


def test_actor_and_tenant_binding(session_factory) -> None:
    ctx = _context(actor_id="1")
    error = _request_ticket(session_factory, ctx)
    confirmation_id = error.extra["confirmationId"]

    with pytest.raises(ConfirmationInvalid) as excinfo:
        confirmation.decide(confirmation_id, "APPROVED", None, context=_context(actor_id="2"))
    assert "does not belong" in excinfo.value.message

    with pytest.raises(ConfirmationInvalid):
        confirmation.decide(
            confirmation_id, "APPROVED", None, context=_context(actor_id="1", tenant_id="other")
        )
    assert _ticket_row(session_factory, confirmation_id).status == ConfirmationStatus.PENDING


def test_expired_ticket_is_marked_expired(session_factory) -> None:
    ctx = _context()
    error = _request_ticket(session_factory, ctx)
    confirmation_id = error.extra["confirmationId"]

    with session_factory() as db:
        row = db.get(AuditConfirmation, confirmation_id)
        row.expires_at = now() - timedelta(seconds=1)
        db.commit()

    with pytest.raises(ConfirmationInvalid) as excinfo:
        confirmation.decide(confirmation_id, "APPROVED", None, context=ctx)
    assert "expired" in excinfo.value.message

    # 与 Java noRollbackFor 一致：EXPIRED 状态要落库，不能被回滚
    row = _ticket_row(session_factory, confirmation_id)
    assert row.status == ConfirmationStatus.EXPIRED
    assert "CONFIRMATION_EXPIRED" in _event_types(session_factory)

    with pytest.raises(ConfirmationInvalid):
        confirmation.consume_approval(confirmation_id, DANGER_TOOL, row.action_digest, context=ctx)


def test_resolve_audit_id_for_retry(session_factory) -> None:
    ctx = _context(actor_id="7")
    error = _request_ticket(session_factory, ctx)
    confirmation_id = error.extra["confirmationId"]

    # 未审批 → 不复用
    assert (
        confirmation.resolve_audit_id_for_retry(
            confirmation_id, tenant_id="default", actor_id="7"
        )
        is None
    )

    confirmation.decide(confirmation_id, "APPROVED", None, context=ctx)
    assert (
        confirmation.resolve_audit_id_for_retry(
            confirmation_id, tenant_id="default", actor_id="7"
        )
        == ctx.audit_id
    )
    # 租户/用户不匹配 → 不复用
    assert (
        confirmation.resolve_audit_id_for_retry(
            confirmation_id, tenant_id="other", actor_id="7"
        )
        is None
    )
    assert (
        confirmation.resolve_audit_id_for_retry(
            confirmation_id, tenant_id="default", actor_id="8"
        )
        is None
    )

    # 过期 → 不复用
    with session_factory() as db:
        row = db.get(AuditConfirmation, confirmation_id)
        row.expires_at = now() - timedelta(seconds=1)
        db.commit()
    assert (
        confirmation.resolve_audit_id_for_retry(
            confirmation_id, tenant_id="default", actor_id="7"
        )
        is None
    )


# ---------------------------------------------------------------------------
# 2) 409 包络
# ---------------------------------------------------------------------------


def test_confirmation_required_envelope(session_factory) -> None:
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/need")
    def need() -> dict:  # noqa: ANN202
        raise _request_ticket(session_factory)

    client = TestClient(app)
    response = client.get("/need")
    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "CONFIRMATION_REQUIRED"
    assert body["toolName"] == DANGER_TOOL
    assert body["requestedAt"].endswith("Z")
    assert body["expiresAt"].endswith("Z")
    assert body["nextStep"]
    assert body["confirmationId"]
    assert body["auditId"]


def test_confirmation_invalid_envelope() -> None:
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/bad")
    def bad() -> dict:  # noqa: ANN202
        raise confirmation.invalid_error("Confirmation not found")

    client = TestClient(app)
    response = client.get("/bad")
    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "CONFIRMATION_INVALID"
    assert body["message"] == "Confirmation not found"
    assert body["timestamp"].endswith("Z")


# ---------------------------------------------------------------------------
# 3) tool_audit（chat-core 接口）
# ---------------------------------------------------------------------------


async def test_check_tool_confirmation_noop_when_not_required(
    session_factory, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "audit_confirmation_required_tools", "")
    assert await check_tool_confirmation("todo_list", {"q": 1}, _ToolCtx()) is None
    assert _events(session_factory) == []


async def test_check_tool_confirmation_requests_ticket(
    session_factory, danger_tools, monkeypatch
) -> None:
    ctx = _ToolCtx(user_id=1)
    with pytest.raises(ConfirmationRequired) as excinfo:
        await check_tool_confirmation(DANGER_TOOL, {"title": "x"}, ctx)
    error = excinfo.value
    assert error.extra["toolName"] == DANGER_TOOL
    assert error.extra["auditId"] == ctx.audit_id
    with session_factory() as db:
        row = db.get(AuditConfirmation, error.extra["confirmationId"])
        assert row.status == ConfirmationStatus.PENDING
        assert row.actor_id == "1"


async def test_check_tool_confirmation_consumes_approved_ticket(
    session_factory, danger_tools
) -> None:
    ctx = _ToolCtx(user_id=1)
    with pytest.raises(ConfirmationRequired) as excinfo:
        await check_tool_confirmation(DANGER_TOOL, {"title": "x"}, ctx)
    confirmation_id = excinfo.value.extra["confirmationId"]

    with session_factory() as db:
        confirmation.decide(
            confirmation_id,
            "APPROVED",
            None,
            context=_context(actor_id="1", audit_id=ctx.audit_id),
            db=db,
        )
        db.close()

    approved_ctx = _ToolCtx(user_id=1, audit_id=ctx.audit_id, confirmation_id=confirmation_id)
    consumed_id = await check_tool_confirmation(DANGER_TOOL, {"title": "x"}, approved_ctx)
    assert consumed_id == confirmation_id
    assert _ticket_row(session_factory, confirmation_id).status == ConfirmationStatus.CONSUMED

    # 再次使用同一票据 → ConfirmationInvalid
    with pytest.raises(ConfirmationInvalid):
        await check_tool_confirmation(DANGER_TOOL, {"title": "x"}, approved_ctx)


async def test_check_tool_confirmation_rejects_digest_mismatch(
    session_factory, danger_tools
) -> None:
    ctx = _ToolCtx(user_id=1)
    with pytest.raises(ConfirmationRequired) as excinfo:
        await check_tool_confirmation(DANGER_TOOL, {"title": "x"}, ctx)
    confirmation_id = excinfo.value.extra["confirmationId"]
    with session_factory() as db:
        confirmation.decide(
            confirmation_id, "APPROVED", None, context=_context(actor_id="1"), db=db
        )
        db.close()

    with pytest.raises(ConfirmationInvalid):
        await check_tool_confirmation(
            DANGER_TOOL,
            {"title": "different"},
            _ToolCtx(user_id=1, confirmation_id=confirmation_id),
        )


async def test_tool_audit_never_breaks_chat_when_db_down(monkeypatch) -> None:
    def _broken():  # noqa: ANN202
        raise RuntimeError("db down")

    monkeypatch.setattr(recorder, "SessionLocal", _broken)
    monkeypatch.setattr(settings, "audit_confirmation_required_tools", "")

    # 不需要确认：完全不碰 DB
    assert await check_tool_confirmation("todo_list", {}, _ToolCtx()) is None

    # recorder 写失败：返回 tool_call_id，不抛异常
    tool_call_id = await record_tool_requested("todo_list", {"q": 1}, ctx=_ToolCtx())
    assert tool_call_id


# ---------------------------------------------------------------------------
# 4) 确认端点
# ---------------------------------------------------------------------------


def _seed_ticket(factory: sessionmaker, actor_id: str = "1") -> tuple[str, str]:
    """直接建一张 PENDING 票据，返回 (confirmation_id, audit_id)。"""
    ctx = _context(actor_id=actor_id)
    error = _request_ticket(factory, ctx)
    return error.extra["confirmationId"], ctx.audit_id


def test_get_confirmation_endpoint(client_factory, session_factory) -> None:
    confirmation_id, audit_id = _seed_ticket(session_factory)
    with session_factory() as db:
        client = client_factory(audit_api.router, db)
        response = client.get(
            f"/audit/confirmations/{confirmation_id}",
            headers={"X-Test-User-Id": "1"},
        )
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "confirmationId",
        "auditId",
        "toolName",
        "status",
        "requestedAt",
        "decidedAt",
        "expiresAt",
        "consumedAt",
    }
    assert body["confirmationId"] == confirmation_id
    assert body["auditId"] == audit_id
    assert body["toolName"] == DANGER_TOOL
    assert body["status"] == "PENDING"
    assert body["decidedAt"] is None
    assert body["consumedAt"] is None
    assert body["requestedAt"].endswith("Z")
    assert body["expiresAt"].endswith("Z")


def test_get_confirmation_not_found(client_factory, session_factory) -> None:
    with session_factory() as db:
        client = client_factory(audit_api.router, db)
        response = client.get(f"/audit/confirmations/{uuid4()}", headers={"X-Test-User-Id": "1"})
    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "CONFIRMATION_INVALID"
    assert body["message"] == "Confirmation not found"


def test_get_confirmation_bad_uuid(client_factory, session_factory) -> None:
    with session_factory() as db:
        client = client_factory(audit_api.router, db)
        response = client.get("/audit/confirmations/nope", headers={"X-Test-User-Id": "1"})
    assert response.status_code == 400


def test_decide_endpoint_approved(client_factory, session_factory) -> None:
    confirmation_id, _audit_id = _seed_ticket(session_factory)
    with session_factory() as db:
        client = client_factory(audit_api.router, db)
        response = client.post(
            f"/audit/confirmations/{confirmation_id}/decision",
            json={"decision": "approved", "reason": "ok"},
            headers={"X-Test-User-Id": "1"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "APPROVED"
    assert body["decidedAt"].endswith("Z")
    assert _ticket_row(session_factory, confirmation_id).status == ConfirmationStatus.APPROVED
    assert "CONFIRMATION_APPROVED" in _event_types(session_factory)


def test_decide_endpoint_invalid_decision(client_factory, session_factory) -> None:
    confirmation_id, _audit_id = _seed_ticket(session_factory)
    with session_factory() as db:
        client = client_factory(audit_api.router, db)
        response = client.post(
            f"/audit/confirmations/{confirmation_id}/decision",
            json={"decision": "maybe"},
            headers={"X-Test-User-Id": "1"},
        )
    assert response.status_code == 409
    assert response.json()["code"] == "CONFIRMATION_INVALID"


def test_decide_endpoint_null_decision(client_factory, session_factory) -> None:
    confirmation_id, _audit_id = _seed_ticket(session_factory)
    with session_factory() as db:
        client = client_factory(audit_api.router, db)
        response = client.post(
            f"/audit/confirmations/{confirmation_id}/decision",
            json={},
            headers={"X-Test-User-Id": "1"},
        )
    assert response.status_code == 409
    assert response.json()["code"] == "CONFIRMATION_INVALID"


def test_decide_endpoint_missing_body(client_factory, session_factory) -> None:
    confirmation_id, _audit_id = _seed_ticket(session_factory)
    with session_factory() as db:
        client = client_factory(audit_api.router, db)
        response = client.post(
            f"/audit/confirmations/{confirmation_id}/decision",
            headers={"X-Test-User-Id": "1"},
        )
    assert response.status_code == 400


def test_decide_endpoint_actor_mismatch(client_factory, session_factory) -> None:
    confirmation_id, _audit_id = _seed_ticket(session_factory, actor_id="99")
    with session_factory() as db:
        client = client_factory(audit_api.router, db)
        response = client.post(
            f"/audit/confirmations/{confirmation_id}/decision",
            json={"decision": "APPROVED"},
            headers={"X-Test-User-Id": "1"},
        )
    assert response.status_code == 409
    assert response.json()["code"] == "CONFIRMATION_INVALID"


def test_decide_endpoint_non_pending(client_factory, session_factory) -> None:
    confirmation_id, _audit_id = _seed_ticket(session_factory)
    with session_factory() as db:
        client = client_factory(audit_api.router, db)
        first = client.post(
            f"/audit/confirmations/{confirmation_id}/decision",
            json={"decision": "APPROVED"},
            headers={"X-Test-User-Id": "1"},
        )
        second = client.post(
            f"/audit/confirmations/{confirmation_id}/decision",
            json={"decision": "DENIED"},
            headers={"X-Test-User-Id": "1"},
        )
    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["code"] == "CONFIRMATION_INVALID"


# ---------------------------------------------------------------------------
# 5) 审计总开关关闭：确认业务照常，但不写 audit_event（只读集成冒烟用）
# ---------------------------------------------------------------------------


def test_confirmation_works_without_audit_events_when_disabled(
    session_factory, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "audit_enabled", False)
    ctx = _context()
    error = _request_ticket(session_factory, ctx)
    confirmation_id = error.extra["confirmationId"]

    with session_factory() as db:
        row = db.get(AuditConfirmation, confirmation_id)
        assert row is not None
        assert row.status == ConfirmationStatus.PENDING
    assert _events(session_factory) == []

    decided = confirmation.decide(confirmation_id, "APPROVED", "ok", context=ctx)
    consumed = confirmation.consume_approval(
        confirmation_id, DANGER_TOOL, decided.action_digest, context=ctx
    )
    assert consumed.status == ConfirmationStatus.CONSUMED
    assert _events(session_factory) == []
