"""ASGI 审计中间件（对齐 Java ``AuditContextFilter``）。

装配顺序（``app/main.py``）：先 ``add_middleware(AuditMiddleware)`` 再加 ``AuthMiddleware``，
Starlette 后加的在外层，因此 **鉴权先执行**、审计只处理已鉴权（或公开白名单）的请求。
未登录的 401 在 AuditMiddleware 之外短路，不会产生审计事件（与 Java AuthFilter 先于
AuditContextFilter 一致）。

职责：

1. 生成/恢复 ``audit_id``（携带 ``X-Confirmation-Id`` 且票据 APPROVED 时复用原链）；
   解析 ``request_id``、``tenant_id``（默认 default）、``conversation_id``
   （``X-Conversation-Id`` 头，GET 另接受查询参数 ``conversationId``）。
2. 用 ``contextvars`` 建立审计上下文，供 recorder/确认服务使用。
3. 写 ``REQUEST_RECEIVED`` / ``REQUEST_COMPLETED`` / ``REQUEST_FAILED``。
4. 响应头回填 ``X-Audit-Id``。
5. ``/auth/zipkin-access`` 整条请求不审计（nginx auth_request 探针，不是用户操作）。
6. DB 不可用时降级：审计写入由 recorder 吞异常，中间件本身绝不阻断请求。
"""

from __future__ import annotations

import logging
from functools import partial
from urllib.parse import parse_qs
from uuid import uuid4

from starlette.concurrency import run_in_threadpool
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.audit import confirmation, recorder
from app.audit.context import AuditContext, audit_context, parse_uuid
from app.audit.events import (
    AuditEventType,
    AuditExecutionStatus,
    event_type_for_http,
    execution_status_for_http,
)

logger = logging.getLogger(__name__)

AUDIT_ID_HEADER = "X-Audit-Id"
CONFIRMATION_ID_HEADER = "X-Confirmation-Id"
REQUEST_ID_HEADER = "X-Request-Id"
USER_ID_HEADER = "X-User-Id"
TENANT_ID_HEADER = "X-Tenant-Id"
CONVERSATION_ID_HEADER = "X-Conversation-Id"
CONVERSATION_ID_PARAM = "conversationId"

#: nginx auth_request 内部探针路径，整条请求不审计（Java ``ZIPKIN_GATE_PROBE_PATH``）
ZIPKIN_GATE_PROBE_PATH = "/auth/zipkin-access"

DEFAULT_TENANT_ID = "default"
ANONYMOUS_ACTOR_ID = "anonymous"


def _header(headers: Headers, name: str) -> str | None:
    value = headers.get(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _resolve_conversation_id(scope: Scope, headers: Headers) -> str | None:
    """Java 只在 GET 上读查询串（避免提前消费 POST 表单 body）。"""
    header_value = _header(headers, CONVERSATION_ID_HEADER.lower())
    if header_value:
        return header_value
    if str(scope.get("method", "")).upper() != "GET":
        return None
    raw_query = scope.get("query_string", b"")
    if not raw_query:
        return None
    try:
        params = parse_qs(raw_query.decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001
        return None
    values = params.get(CONVERSATION_ID_PARAM)
    if not values:
        return None
    for value in values:
        if value and value.strip():
            return value.strip()
    return None


def _resolve_retry_audit_id(confirmation_id: str | None, tenant_id: str, actor_id: str) -> str | None:
    """确认重试时恢复原 audit_id；DB 不可用/票据无效时降级为 None（新链）。"""
    if not confirmation_id:
        return None
    try:
        return confirmation.resolve_audit_id_for_retry(
            confirmation_id, tenant_id=tenant_id, actor_id=actor_id
        )
    except Exception:  # noqa: BLE001  审计降级：不能阻断业务请求
        logger.warning("resolve retry audit id failed; fallback to a new chain", exc_info=True)
        return None


async def _record_async(event_type: str, execution_status: str | None, **fields) -> None:
    """线程池里写审计事件；任何异常都被吞掉（已登录/业务请求不能被审计拖垮）。"""
    try:
        await run_in_threadpool(
            partial(recorder.record_event, event_type, execution_status, **fields)
        )
    except Exception:  # noqa: BLE001
        logger.warning("failed to record audit event %s from middleware", event_type, exc_info=True)


class AuditMiddleware:
    """纯 ASGI 审计中间件（不依赖 FastAPI，挂在 AuthMiddleware 内层）。"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # 审计总开关关闭：完全跳过审计机制（不建上下文、不读/写库、不写 X-Audit-Id），
        # 便于在真实库上做只读集成冒烟而不污染 audit_event。
        if scope["type"] != "http" or not recorder.audit_enabled():
            await self.app(scope, receive, send)
            return

        path = str(scope.get("path", ""))
        if path == ZIPKIN_GATE_PROBE_PATH:
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        state = scope.get("state")
        if not isinstance(state, dict):
            state = {}
            scope["state"] = state

        # 鉴权中间件把真实用户写入 request.state（请求头 X-User-Id 不可信）
        user_id = state.get("user_id")
        actor_id = str(user_id) if user_id is not None else ANONYMOUS_ACTOR_ID
        tenant_id = _header(headers, TENANT_ID_HEADER.lower()) or DEFAULT_TENANT_ID
        confirmation_id = parse_uuid(_header(headers, CONFIRMATION_ID_HEADER.lower()))
        request_id = _header(headers, REQUEST_ID_HEADER.lower()) or str(uuid4())

        audit_id = await run_in_threadpool(
            _resolve_retry_audit_id, confirmation_id, tenant_id, actor_id
        )
        if not audit_id:
            audit_id = str(uuid4())

        conversation_id = _resolve_conversation_id(scope, headers)

        context = AuditContext(
            audit_id=audit_id,
            request_id=request_id,
            tenant_id=tenant_id,
            actor_id=actor_id,
            session_id=None,
            confirmation_id=confirmation_id,
            conversation_id=conversation_id,
        )

        # 供 /audit/* 端点复用（与 Java 的 request attribute 等价）
        state["audit_id"] = audit_id
        state["tenant_id"] = tenant_id
        state["request_id"] = request_id
        state["conversation_id"] = conversation_id
        state["confirmation_id"] = confirmation_id

        method = str(scope.get("method", ""))
        client = scope.get("client")
        remote_address = client[0] if client else None
        response_status: dict[str, int] = {}

        async def send_with_audit_header(message: Message) -> None:
            if message["type"] == "http.response.start":
                response_status["status"] = int(message["status"])
                MutableHeaders(scope=message)[AUDIT_ID_HEADER] = audit_id
            await send(message)

        with audit_context(context):
            await _record_async(
                AuditEventType.REQUEST_RECEIVED,
                AuditExecutionStatus.RECEIVED,
                actor_type="USER",
                event_data={
                    "method": method,
                    "path": path,
                    "remoteAddress": remote_address,
                    "userAgent": headers.get("user-agent"),
                },
            )

            try:
                await self.app(scope, receive, send_with_audit_header)
            except Exception as exc:  # noqa: BLE001  记录后原样抛出，交给上层错误处理
                await _record_async(
                    AuditEventType.REQUEST_FAILED,
                    AuditExecutionStatus.FAILED,
                    actor_type="SYSTEM",
                    error_code=type(exc).__name__,
                    error_message=str(exc),
                    event_data={"method": method, "path": path},
                )
                raise

            status = response_status.get("status", 200)
            await _record_async(
                event_type_for_http(status),
                execution_status_for_http(status),
                actor_type="SYSTEM",
                event_data={
                    "method": method,
                    "path": path,
                    "httpStatus": status,
                },
            )


__all__ = [
    "AuditMiddleware",
    "AUDIT_ID_HEADER",
    "CONFIRMATION_ID_HEADER",
    "REQUEST_ID_HEADER",
    "USER_ID_HEADER",
    "TENANT_ID_HEADER",
    "CONVERSATION_ID_HEADER",
    "ZIPKIN_GATE_PROBE_PATH",
    "DEFAULT_TENANT_ID",
    "ANONYMOUS_ACTOR_ID",
]
