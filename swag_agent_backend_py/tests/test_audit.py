"""审计模块单测：digest 跨语言 parity、recorder 35 列、中间件、查询端点。

原则：全部跑在 SQLite 内存库上，不连真实 MySQL；需要中间件的用例通过
monkeypatch ``app.audit.recorder.SessionLocal`` 注入测试 Session 工厂。
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
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.db.models  # noqa: F401  （注册所有表到 Base.metadata）
from app.audit import confirmation, recorder
from app.audit.context import (
    AuditContext,
    audit_context,
    current_audit_id,
    current_user_id,
)
from app.audit.digest import (
    action_digest,
    canonicalize_json,
    json_text_for_event_data,
    raw_tool_input,
    sha256,
)
from app.audit.events import (
    AuditEventType,
    execution_status_for_http,
    event_type_for_http,
)
from app.audit.middleware import AuditMiddleware
from app.api import audit as audit_api
from app.config import settings
from app.core.errors import install_error_handlers
from app.core.middleware import AuthMiddleware
from app.core.timeutil import now
from app.db.base import Base
from app.db.models import AppUser, AuditConfirmation, AuditEvent

# ---------------------------------------------------------------------------
# Java 侧真值（由 swag_agent_backend/target/classes 里的 AuditDigest.class +
# jackson-databind 3.1.4 实际跑出来，见 tests 说明：跨语言 parity 基线）
# ---------------------------------------------------------------------------
JAVA_GOLDENS = {
    "sha256_audit": "b81f37a043a6f767e7c94d105f4bd31282f3ecc20680bb9d09bd93461cf4c863",
    "sha256_empty": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "sha256_hello": "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824",
    "act_plain": "fbffa2423310779492b8db32e1a31a108036b94d40912ea525b14bc2188328df",
    "act_email": "0cc7635ae1e571d7b467b8759b3e6030c2e30ad5dc9154bb4edeb6a7ff42af5a",
    "act_nonjson": "ab1f4e068fc6750820fd8eddf477367297509be9f1d7fa49f111fb892e85884c",
    "act_unicode": "ac9602a9de378afe487315469b6f198d4b114bb4473fec0e993bfe99d56c7a05",
    "act_nullinput": "fe8edeeb98cc6d3b93cf2d57000254b84bd9eba34b4df7ce4b87db8b937b7703",
}


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


def _context(**overrides) -> AuditContext:
    base = dict(
        audit_id=str(uuid4()),
        request_id="req-1",
        tenant_id="default",
        actor_id="7",
        session_id=None,
        confirmation_id=None,
        conversation_id=None,
    )
    base.update(overrides)
    return AuditContext(**base)


def _events(factory: sessionmaker) -> list[AuditEvent]:
    with factory() as db:
        return list(db.scalars(select(AuditEvent)).all())


def _event_of_type(factory: sessionmaker, event_type: str) -> AuditEvent:
    rows = [e for e in _events(factory) if e.event_type == event_type]
    assert rows, f"no {event_type} event recorded"
    return rows[-1]


class _StateMiddleware:
    """测试用：模拟 AuthMiddleware 已写入 request.state 的鉴权结果。"""

    def __init__(self, app):  # noqa: ANN001
        self.app = app

    async def __call__(self, scope, receive, send):  # noqa: ANN001
        if scope["type"] == "http":
            state = scope.setdefault("state", {})
            state["user_id"] = 7
            state["role"] = "USER"
        await self.app(scope, receive, send)


def _audit_test_app() -> FastAPI:
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/ping")
    def ping() -> dict:
        return {"auditId": current_audit_id(), "userId": current_user_id()}

    @app.get("/boom")
    def boom() -> dict:
        raise confirmation.invalid_error("nope")

    @app.get("/crash")
    def crash() -> dict:
        raise RuntimeError("kaboom")

    @app.get("/auth/zipkin-access")
    def zipkin_access() -> dict:
        return {"ok": True}

    app.add_middleware(AuditMiddleware)
    app.add_middleware(_StateMiddleware)
    return app


def _add_event(
    db: Session,
    audit_id: str,
    event_type: str,
    *,
    execution_status: str | None = None,
    actor_id: str | None = None,
    event_data: dict | None = None,
    trace_id: str | None = None,
    occurred_at=None,
    conversation_id: str | None = None,
) -> AuditEvent:
    ts = occurred_at or now()
    event = AuditEvent(
        event_id=str(uuid4()),
        audit_id=audit_id,
        request_id=None,
        source_event_id=None,
        trace_id=trace_id,
        span_id=None,
        parent_span_id=None,
        parent_event_id=None,
        tenant_id="default",
        session_id=None,
        conversation_id=conversation_id,
        actor_type="USER",
        actor_id=actor_id,
        actor_display_name=None,
        event_type=event_type,
        execution_status=execution_status,
        agent_name=None,
        agent_version=None,
        model_name=None,
        tool_name=None,
        tool_call_id=None,
        confirmation_id=None,
        action_digest=None,
        input_ref=None,
        input_digest=None,
        output_ref=None,
        output_digest=None,
        event_data=event_data or {},
        error_code=None,
        error_message=None,
        occurred_at=ts,
        recorded_at=ts,
        schema_version=1,
        previous_hash=None,
        event_hash=None,
    )
    db.add(event)
    db.commit()
    return event


# ---------------------------------------------------------------------------
# 1) digest 跨语言 parity（Java golden）
# ---------------------------------------------------------------------------


def test_sha256_matches_java_goldens() -> None:
    assert sha256("audit") == JAVA_GOLDENS["sha256_audit"]
    assert sha256("hello") == JAVA_GOLDENS["sha256_hello"]
    assert sha256("") == JAVA_GOLDENS["sha256_empty"]
    assert sha256(None) == JAVA_GOLDENS["sha256_empty"]


def test_canonicalize_json_matches_java_goldens() -> None:
    # Java: {"a":[2,3],"b":1} —— 对象字段排序、无分隔空格、非 ASCII 不转义
    assert canonicalize_json('{"b":1,"a":[2, 3]}') == '{"a":[2,3],"b":1}'
    assert canonicalize_json('{"name":"中文","emoji":"😀"}') == '{"emoji":"😀","name":"中文"}'
    assert canonicalize_json('{"z":{"b":true,"a":null},"a":1.5}') == (
        '{"a":1.5,"z":{"a":null,"b":true}}'
    )
    # 空白输入 → ""；非法 JSON 原样返回（Java 同样）
    assert canonicalize_json("   ") == ""
    assert canonicalize_json(None) == ""
    assert canonicalize_json("not json {") == "not json {"


def test_action_digest_matches_java_goldens() -> None:
    assert action_digest("danger_tool", '{"a": 1, "b": [2, 3]}') == JAVA_GOLDENS["act_plain"]
    assert action_digest("danger_tool", '{"b": [2,3], "a": 1}') == JAVA_GOLDENS["act_plain"]
    assert (
        action_digest("sendEmail", '{"recipient":"user@example.com","subject":"hello"}')
        == JAVA_GOLDENS["act_email"]
    )
    assert (
        action_digest("sendEmail", '{"subject":"hello","recipient":"user@example.com"}')
        == JAVA_GOLDENS["act_email"]
    )
    assert action_digest("shell", "rm -rf /tmp/x") == JAVA_GOLDENS["act_nonjson"]
    assert action_digest("备注", '{"内容":"中文"}') == JAVA_GOLDENS["act_unicode"]
    assert action_digest("t", None) == JAVA_GOLDENS["act_nullinput"]


def test_raw_tool_input_is_stable_for_dict() -> None:
    assert raw_tool_input({"b": 1, "a": [2, 3]}) == '{"a":[2,3],"b":1}'
    assert raw_tool_input('{"b":1,"a":2}') == '{"b":1,"a":2}'
    assert raw_tool_input(None) == ""


def test_event_data_json_text_uses_mysql_shape() -> None:
    text = json_text_for_event_data({"method": "GET", "a": [1, 2], "b": {"y": 1, "x": 2}})
    assert text == '{"a": [1, 2], "b": {"x": 2, "y": 1}, "method": "GET"}'


def test_execution_status_mapping() -> None:
    assert execution_status_for_http(200) == "SUCCEEDED"
    assert execution_status_for_http(302) == "SUCCEEDED"
    assert execution_status_for_http(400) == "REJECTED"
    assert execution_status_for_http(403) == "REJECTED"
    assert execution_status_for_http(409) == "WAITING_CONFIRMATION"
    assert execution_status_for_http(500) == "FAILED"
    assert event_type_for_http(200) == AuditEventType.REQUEST_COMPLETED
    assert event_type_for_http(409) == AuditEventType.REQUEST_COMPLETED
    assert event_type_for_http(500) == AuditEventType.REQUEST_FAILED


# ---------------------------------------------------------------------------
# 2) recorder：35 列 / 截断 / 降级
# ---------------------------------------------------------------------------


def test_audit_event_has_35_columns() -> None:
    assert len(AuditEvent.__table__.columns) == 35


def test_record_event_writes_all_columns(session_factory) -> None:
    ctx = _context(conversation_id="42")
    with audit_context(ctx):
        event_id = recorder.record_event(
            AuditEventType.TOOL_CALL_REQUESTED,
            "REQUESTED",
            actor_type="AGENT",
            trace_id="trace-1",
            span_id="span-1",
            parent_span_id="parent-span-1",
            parent_event_id=str(uuid4()),
            agent_name="chatClient",
            agent_version="2.0.0",
            model_name="deepseek-v4-flash",
            tool_name="todo_create",
            tool_call_id="call-1",
            confirmation_id=str(uuid4()),
            action_digest="a" * 64,
            input_ref="memory://in",
            input_digest="b" * 64,
            output_ref="memory://out",
            output_digest="c" * 64,
            event_data={"foo": "bar"},
            error_code="Oops",
            error_message="boom",
        )
    assert event_id is not None

    event = _event_of_type(session_factory, AuditEventType.TOOL_CALL_REQUESTED)
    assert event.event_id == event_id
    assert event.audit_id == ctx.audit_id
    assert event.request_id == "req-1"
    assert event.tenant_id == "default"
    assert event.actor_type == "AGENT"
    assert event.actor_id == "7"
    assert event.conversation_id == "42"
    assert event.trace_id == "trace-1"
    assert event.span_id == "span-1"
    assert event.parent_span_id == "parent-span-1"
    assert event.parent_event_id is not None
    assert event.agent_name == "chatClient"
    assert event.agent_version == "2.0.0"
    assert event.model_name == "deepseek-v4-flash"
    assert event.tool_name == "todo_create"
    assert event.tool_call_id == "call-1"
    assert event.confirmation_id is not None
    assert event.action_digest == "a" * 64
    assert event.input_ref == "memory://in"
    assert event.input_digest == "b" * 64
    assert event.output_ref == "memory://out"
    assert event.output_digest == "c" * 64
    assert event.event_data == {"foo": "bar"}
    assert event.error_code == "Oops"
    assert event.error_message == "boom"
    assert event.execution_status == "REQUESTED"
    assert event.event_type == AuditEventType.TOOL_CALL_REQUESTED
    assert event.occurred_at is not None
    assert event.recorded_at is not None
    assert event.schema_version == 1
    # 哈希链未实现：与 Java 一致恒 NULL
    assert event.previous_hash is None
    assert event.event_hash is None
    assert event.source_event_id is None
    assert event.actor_display_name is None
    assert event.session_id is None


def test_record_event_truncates_error_message(session_factory) -> None:
    with audit_context(_context()):
        recorder.record_event("REQUEST_FAILED", "FAILED", error_message="x" * 5000)
    event = _event_of_type(session_factory, "REQUEST_FAILED")
    assert len(event.error_message) == recorder.ERROR_MESSAGE_LIMIT


def test_record_event_without_context_is_noop(session_factory) -> None:
    assert recorder.record_event(AuditEventType.REQUEST_RECEIVED, "RECEIVED") is None
    assert _events(session_factory) == []


def test_record_event_degrades_when_db_unavailable(monkeypatch) -> None:
    def _broken():  # noqa: ANN202
        raise RuntimeError("db down")

    monkeypatch.setattr(recorder, "SessionLocal", _broken)
    with audit_context(_context()):
        assert recorder.record_event(AuditEventType.REQUEST_RECEIVED, "RECEIVED") is None


def test_record_tool_events(session_factory, monkeypatch) -> None:
    monkeypatch.setattr(settings, "audit_include_tool_content", False)
    args = {"title": "买牛奶"}
    with audit_context(_context()):
        tool_call_id = recorder.record_tool_requested("todo_create", args)
        assert tool_call_id
        recorder.record_tool_started("todo_create", tool_call_id, args)
        recorder.record_tool_succeeded("todo_create", tool_call_id, "已创建", args)
        recorder.record_tool_failed("todo_create", tool_call_id, ValueError("bad"), args)

    requested = _event_of_type(session_factory, AuditEventType.TOOL_CALL_REQUESTED)
    assert requested.tool_call_id == tool_call_id
    assert requested.action_digest == action_digest("todo_create", raw_tool_input(args))
    assert requested.input_digest == sha256(raw_tool_input(args))
    assert requested.event_data == {"inputLength": len(raw_tool_input(args))}

    started = _event_of_type(session_factory, AuditEventType.TOOL_CALL_STARTED)
    succeeded = _event_of_type(session_factory, AuditEventType.TOOL_CALL_SUCCEEDED)
    failed = _event_of_type(session_factory, AuditEventType.TOOL_CALL_FAILED)
    assert started.tool_call_id == tool_call_id
    assert succeeded.output_digest == sha256("已创建")
    assert succeeded.event_data == {"outputLength": len("已创建")}
    assert failed.error_code == "ValueError"
    assert failed.error_message == "bad"


# ---------------------------------------------------------------------------
# 3) 中间件：X-Audit-Id / contextvars / 请求事件 / 跳过期探针 / 401 先于审计
# ---------------------------------------------------------------------------


def test_middleware_sets_audit_header_and_request_events(session_factory) -> None:
    client = TestClient(_audit_test_app())
    response = client.get("/ping", headers={"X-Tenant-Id": "tenant-9", "X-Request-Id": "req-42"})
    assert response.status_code == 200

    audit_id = response.headers["X-Audit-Id"]
    assert response.json() == {"auditId": audit_id, "userId": 7}

    received = _event_of_type(session_factory, AuditEventType.REQUEST_RECEIVED)
    completed = _event_of_type(session_factory, AuditEventType.REQUEST_COMPLETED)
    assert received.audit_id == audit_id
    assert received.tenant_id == "tenant-9"
    assert received.actor_id == "7"
    assert received.request_id == "req-42"
    assert received.actor_type == "USER"
    assert received.event_data["method"] == "GET"
    assert received.event_data["path"] == "/ping"
    assert received.execution_status == "RECEIVED"

    assert completed.audit_id == audit_id
    assert completed.execution_status == "SUCCEEDED"
    assert completed.event_data["httpStatus"] == 200


def test_middleware_resolves_conversation_id(session_factory) -> None:
    client = TestClient(_audit_test_app())
    client.get("/ping?conversationId=abc")
    received = _event_of_type(session_factory, AuditEventType.REQUEST_RECEIVED)
    assert received.conversation_id == "abc"

    client.get("/ping", headers={"X-Conversation-Id": "xyz"})
    received = _event_of_type(session_factory, AuditEventType.REQUEST_RECEIVED)
    assert received.conversation_id == "xyz"


def test_middleware_skips_zipkin_gate_probe(session_factory) -> None:
    client = TestClient(_audit_test_app())
    response = client.get("/auth/zipkin-access")
    assert response.status_code == 200
    assert "X-Audit-Id" not in response.headers
    assert _events(session_factory) == []


def test_middleware_maps_409_to_waiting_confirmation(session_factory) -> None:
    client = TestClient(_audit_test_app())
    response = client.get("/boom")
    assert response.status_code == 409
    assert response.json()["code"] == "CONFIRMATION_INVALID"
    completed = _event_of_type(session_factory, AuditEventType.REQUEST_COMPLETED)
    assert completed.execution_status == "WAITING_CONFIRMATION"


def test_middleware_records_failed_on_unhandled_exception(session_factory) -> None:
    client = TestClient(_audit_test_app(), raise_server_exceptions=False)
    response = client.get("/crash")
    assert response.status_code == 500
    failed = _event_of_type(session_factory, AuditEventType.REQUEST_FAILED)
    assert failed.execution_status == "FAILED"
    assert failed.error_code == "RuntimeError"
    assert failed.error_message == "kaboom"


def test_middleware_reuses_audit_id_for_approved_confirmation(session_factory) -> None:
    original_audit_id = str(uuid4())
    confirmation_id = str(uuid4())
    with session_factory() as db:
        db.add(
            AuditConfirmation(
                confirmation_id=confirmation_id,
                audit_id=original_audit_id,
                tool_call_id="call-1",
                tenant_id="default",
                actor_id="7",
                tool_name="danger_tool",
                canonical_input="{}",
                action_digest="d" * 64,
                status=confirmation.ConfirmationStatus.APPROVED,
                requested_at=now(),
                decided_at=now(),
                expires_at=now() + timedelta(seconds=600),
            )
        )
        db.commit()

    client = TestClient(_audit_test_app())
    response = client.get("/ping", headers={"X-Confirmation-Id": confirmation_id})
    assert response.status_code == 200
    assert response.headers["X-Audit-Id"] == original_audit_id


def test_middleware_degrades_when_db_unavailable(session_factory, monkeypatch) -> None:
    def _broken():  # noqa: ANN202
        raise RuntimeError("db down")

    monkeypatch.setattr(recorder, "SessionLocal", _broken)
    client = TestClient(_audit_test_app())
    response = client.get("/ping")
    # 审计写不进去，但业务请求照常成功且仍回填 X-Audit-Id
    assert response.status_code == 200
    assert response.headers["X-Audit-Id"]


def test_401_happens_before_audit(session_factory) -> None:
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/protected")
    def protected() -> dict:
        return {"ok": True}

    app.add_middleware(AuditMiddleware)
    app.add_middleware(AuthMiddleware)  # 外层：未登录直接 401 短路

    client = TestClient(app)
    response = client.get("/protected")
    assert response.status_code == 401
    assert response.json() == {"code": "UNAUTHORIZED", "message": "请先登录"}
    assert "X-Audit-Id" not in response.headers
    assert _events(session_factory) == []


# ---------------------------------------------------------------------------
# 4) 查询端点：/audit/events/{id}、/audit/chains
# ---------------------------------------------------------------------------

EVENT_VIEW_KEYS = {
    "eventId",
    "auditId",
    "requestId",
    "traceId",
    "spanId",
    "parentSpanId",
    "tenantId",
    "actorType",
    "actorId",
    "eventType",
    "executionStatus",
    "agentName",
    "modelName",
    "toolName",
    "toolCallId",
    "confirmationId",
    "actionDigest",
    "inputDigest",
    "outputDigest",
    "eventData",
    "errorCode",
    "errorMessage",
    "occurredAt",
    "recordedAt",
}


def _seed_chain_a(db: Session) -> str:
    audit_id = str(uuid4())
    base = now() - timedelta(minutes=2)
    _add_event(
        db,
        audit_id,
        AuditEventType.REQUEST_RECEIVED,
        actor_id="1",
        event_data={"method": "POST", "path": "/test/chat/stream/events"},
        trace_id="trace-a",
        occurred_at=base,
    )
    _add_event(
        db,
        audit_id,
        AuditEventType.TOOL_CALL_REQUESTED,
        actor_id="1",
        event_data={"inputLength": 2},
        trace_id="trace-a",
        occurred_at=base + timedelta(seconds=1),
    )
    _add_event(
        db,
        audit_id,
        AuditEventType.REQUEST_COMPLETED,
        execution_status="SUCCEEDED",
        actor_id="1",
        event_data={"method": "POST", "path": "/test/chat/stream/events", "httpStatus": 200},
        trace_id="trace-a",
        occurred_at=base + timedelta(seconds=2),
    )
    return audit_id


def _seed_chain_b(db: Session) -> str:
    audit_id = str(uuid4())
    base = now() - timedelta(minutes=1)
    _add_event(
        db,
        audit_id,
        AuditEventType.REQUEST_RECEIVED,
        actor_id="2",
        event_data={"method": "GET", "path": "/todo/items"},
        occurred_at=base,
    )
    _add_event(
        db,
        audit_id,
        AuditEventType.REQUEST_COMPLETED,
        execution_status="REJECTED",
        actor_id="2",
        event_data={"method": "GET", "path": "/todo/items", "httpStatus": 403},
        occurred_at=base + timedelta(seconds=1),
    )
    return audit_id


def test_get_audit_events(client_factory, sqlite_session) -> None:
    audit_id = _seed_chain_a(sqlite_session)
    client = client_factory(audit_api.router, sqlite_session)

    response = client.get(f"/audit/events/{audit_id}", headers={"X-Test-User-Id": "1"})
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 3
    for row in rows:
        assert set(row) == {"event", "zipkinTraceUrl"}
        assert set(row["event"]) == EVENT_VIEW_KEYS
        assert row["event"]["auditId"] == audit_id
        assert row["event"]["occurredAt"].endswith("Z")
        assert row["event"]["recordedAt"].endswith("Z")
        # eventData 必须是 JSON 字符串（二次编码），不能是对象
        assert isinstance(row["event"]["eventData"], str)
        assert row["zipkinTraceUrl"] == "/zipkin/traces/trace-a"
    assert [row["event"]["eventType"] for row in rows] == [
        AuditEventType.REQUEST_RECEIVED,
        AuditEventType.TOOL_CALL_REQUESTED,
        AuditEventType.REQUEST_COMPLETED,
    ]


def test_get_audit_events_rejects_bad_uuid(client_factory, sqlite_session) -> None:
    client = client_factory(audit_api.router, sqlite_session)
    response = client.get("/audit/events/not-a-uuid", headers={"X-Test-User-Id": "1"})
    assert response.status_code == 400
    assert response.json()["status"] == 400


def test_get_audit_events_unknown_chain_returns_empty(client_factory, sqlite_session) -> None:
    client = client_factory(audit_api.router, sqlite_session)
    response = client.get(f"/audit/events/{uuid4()}", headers={"X-Test-User-Id": "1"})
    assert response.status_code == 200
    assert response.json() == []


def test_get_audit_chains_admin(client_factory, sqlite_session) -> None:
    audit_a = _seed_chain_a(sqlite_session)
    audit_b = _seed_chain_b(sqlite_session)
    sqlite_session.add(
        AppUser(
            id=1,
            username="alice",
            password_hash="x",
            display_name="Alice",
            role="ADMIN",
            created_at=now(),
        )
    )
    sqlite_session.commit()

    client = client_factory(audit_api.router, sqlite_session)
    response = client.get(
        "/audit/chains?limit=30",
        headers={"X-Test-User-Id": "1", "X-Test-Role": "ADMIN"},
    )
    assert response.status_code == 200
    chains = response.json()
    assert [chain["auditId"] for chain in chains] == [audit_b, audit_a]

    chain_a = chains[1]
    assert chain_a["status"] == "SUCCEEDED"
    assert chain_a["httpStatus"] == 200
    assert chain_a["method"] == "POST"
    assert chain_a["path"] == "/test/chat/stream/events"
    assert chain_a["actorId"] == "1"
    assert chain_a["actorName"] == "alice"
    assert chain_a["eventCount"] == 3
    assert chain_a["traceId"] == "trace-a"
    assert chain_a["zipkinTraceUrl"] == "/zipkin/traces/trace-a"
    assert chain_a["startedAt"].endswith("Z")
    assert chain_a["endedAt"].endswith("Z")

    chain_b = chains[0]
    assert chain_b["status"] == "REJECTED"
    assert chain_b["httpStatus"] == 403
    assert chain_b["actorId"] == "2"
    assert chain_b["actorName"] == "2"  # 查不到用户时回退 actorId
    assert chain_b["traceId"] is None
    assert chain_b["zipkinTraceUrl"] is None


def test_get_audit_chains_limit_clamped(client_factory, sqlite_session) -> None:
    _seed_chain_a(sqlite_session)
    _seed_chain_b(sqlite_session)
    client = client_factory(audit_api.router, sqlite_session)
    headers = {"X-Test-User-Id": "1", "X-Test-Role": "ADMIN"}

    assert len(client.get("/audit/chains?limit=1", headers=headers).json()) == 1
    assert len(client.get("/audit/chains?limit=0", headers=headers).json()) == 1
    assert len(client.get("/audit/chains?limit=-5", headers=headers).json()) == 1
    assert len(client.get("/audit/chains?limit=999", headers=headers).json()) == 2


def test_get_audit_chains_requires_admin(client_factory, sqlite_session) -> None:
    client = client_factory(audit_api.router, sqlite_session)
    response = client.get(
        "/audit/chains",
        headers={"X-Test-User-Id": "1", "X-Test-Role": "USER"},
    )
    assert response.status_code == 403


def test_get_audit_chains_empty(client_factory, sqlite_session) -> None:
    client = client_factory(audit_api.router, sqlite_session)
    response = client.get(
        "/audit/chains",
        headers={"X-Test-User-Id": "1", "X-Test-Role": "ADMIN"},
    )
    assert response.status_code == 200
    assert response.json() == []


# ---------------------------------------------------------------------------
# 5) 审计总开关 settings.audit_enabled=False：完全跳过写库（只读集成冒烟用）
# ---------------------------------------------------------------------------


def test_audit_disabled_skips_middleware_writes(session_factory, monkeypatch) -> None:
    monkeypatch.setattr(settings, "audit_enabled", False)
    client = TestClient(_audit_test_app())
    response = client.get("/ping", headers={"X-Tenant-Id": "tenant-9"})
    assert response.status_code == 200
    # 不写请求事件、不加 X-Audit-Id，也不建审计上下文（路由里的 auditId 为 None）
    assert "X-Audit-Id" not in response.headers
    assert response.json() == {"auditId": None, "userId": None}
    assert _events(session_factory) == []


def test_audit_disabled_skips_recorder_writes(session_factory, monkeypatch) -> None:
    monkeypatch.setattr(settings, "audit_enabled", False)
    with audit_context(_context()):
        assert recorder.record_event(AuditEventType.REQUEST_RECEIVED, "RECEIVED") is None
        assert recorder.record_tool_requested("todo_create", {"title": "x"})
    assert _events(session_factory) == []
