"""审计事件 / 调用链只读查询（对齐 Java ``JdbcAuditQueryRepository`` 与查询服务）。

- ``GET /audit/events/{auditId}``：一条审计链的全部事件，按发生时间正序。
- ``GET /audit/chains?limit``：按 ``audit_id`` 聚合的最近调用链，供管理端列表。

IDL 字段与 Java record 一致（camelCase）；所有 Instant 输出 ``Z`` 结尾。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit.digest import json_text_for_event_data
from app.audit.events import REQUEST_EVENT_TYPES, AuditEventType
from app.config import settings
from app.core.timeutil import iso_instant
from app.db.models import AppUser, AuditEvent

logger = logging.getLogger(__name__)

DEFAULT_LIMIT = 30
MAX_LIMIT = 200


def _zipkin_trace_url(trace_id: str | None) -> str | None:
    """对齐 ``ZipkinTraceLinkBuilder``：同源相对地址 ``/zipkin/traces/{traceId}``。"""
    if not trace_id or not trace_id.strip():
        return None
    base_url = (settings.audit_zipkin_ui_base_url or "").rstrip("/")
    return f"{base_url}/zipkin/traces/{trace_id}"


def _event_view(event: AuditEvent) -> dict[str, Any]:
    """``AuditEventView``（注意 ``eventData`` 是 JSON 字符串，不是对象）。"""
    return {
        "eventId": event.event_id,
        "auditId": event.audit_id,
        "requestId": event.request_id,
        "traceId": event.trace_id,
        "spanId": event.span_id,
        "parentSpanId": event.parent_span_id,
        "tenantId": event.tenant_id,
        "actorType": event.actor_type,
        "actorId": event.actor_id,
        "eventType": event.event_type,
        "executionStatus": event.execution_status,
        "agentName": event.agent_name,
        "modelName": event.model_name,
        "toolName": event.tool_name,
        "toolCallId": event.tool_call_id,
        "confirmationId": event.confirmation_id,
        "actionDigest": event.action_digest,
        "inputDigest": event.input_digest,
        "outputDigest": event.output_digest,
        "eventData": json_text_for_event_data(event.event_data),
        "errorCode": event.error_code,
        "errorMessage": event.error_message,
        "occurredAt": iso_instant(event.occurred_at),
        "recordedAt": iso_instant(event.recorded_at),
    }


def event_responses(db: Session, audit_id: str) -> list[dict[str, Any]]:
    """``GET /audit/events/{auditId}`` 响应（Java 返回 ``List<AuditEventResponse>``）。"""
    events = db.scalars(
        select(AuditEvent)
        .where(AuditEvent.audit_id == audit_id)
        .order_by(
            AuditEvent.occurred_at.asc(),
            AuditEvent.recorded_at.asc(),
            AuditEvent.event_id.asc(),
        )
    ).all()
    return [
        {
            "event": _event_view(event),
            "zipkinTraceUrl": _zipkin_trace_url(event.trace_id),
        }
        for event in events
    ]


def _event_data_map(event: AuditEvent | None) -> dict[str, Any]:
    """event_data 是历史遗留自由 JSON，解析失败一律降级为空（不能拖垮列表）。"""
    if event is None or event.event_data is None:
        return {}
    value = event.event_data
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return dict(parsed) if isinstance(parsed, dict) else {}
        except (ValueError, TypeError):
            return {}
    return {}


def _text(value: Any) -> str | None:
    return None if value is None else str(value)


def _number(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


def _user_names(db: Session) -> dict[str, str]:
    """一次拉全量用户映射；查不到就退回显示 actorId（Java 同样降级）。"""
    try:
        rows = db.execute(select(AppUser.id, AppUser.username)).all()
        return {str(user_id): (username or "") for user_id, username in rows}
    except Exception:  # noqa: BLE001
        logger.warning("failed to load usernames for audit chains", exc_info=True)
        return {}


def chain_views(db: Session, limit: int) -> list[dict[str, Any]]:
    """``GET /audit/chains`` 响应（``limit`` 钳制 1..200，默认 30）。"""
    size = max(1, min(int(limit if limit is not None else DEFAULT_LIMIT), MAX_LIMIT))

    summary_rows = db.execute(
        select(
            AuditEvent.audit_id,
            func.min(AuditEvent.occurred_at).label("started_at"),
            func.max(AuditEvent.occurred_at).label("ended_at"),
            func.count().label("event_count"),
        )
        .group_by(AuditEvent.audit_id)
        .order_by(func.max(AuditEvent.occurred_at).desc())
        .limit(size)
    ).all()
    if not summary_rows:
        return []

    audit_ids = [row.audit_id for row in summary_rows]
    request_events = db.scalars(
        select(AuditEvent)
        .where(
            AuditEvent.event_type.in_(REQUEST_EVENT_TYPES),
            AuditEvent.audit_id.in_(audit_ids),
        )
        .order_by(AuditEvent.occurred_at.asc(), AuditEvent.recorded_at.asc())
    ).all()

    events_by_chain: dict[str, list[AuditEvent]] = {}
    for event in request_events:
        events_by_chain.setdefault(event.audit_id, []).append(event)

    user_names = _user_names(db)

    views: list[dict[str, Any]] = []
    for row in summary_rows:
        events = events_by_chain.get(row.audit_id, [])
        received: AuditEvent | None = None
        finished: AuditEvent | None = None
        for event in events:
            if event.event_type == AuditEventType.REQUEST_RECEIVED:
                if received is None:
                    received = event
            else:
                finished = event

        received_data = _event_data_map(received)
        finished_data = _event_data_map(finished)

        trace_id: str | None = None
        for event in events:
            if event.trace_id and event.trace_id.strip():
                trace_id = event.trace_id
                break

        if finished is not None:
            status = finished.execution_status
        elif received is not None:
            status = "IN_PROGRESS"
        else:
            status = "UNKNOWN"

        actor_id = received.actor_id if received is not None else None
        views.append(
            {
                "auditId": row.audit_id,
                "startedAt": iso_instant(row.started_at),
                "endedAt": iso_instant(row.ended_at),
                "eventCount": int(row.event_count or 0),
                "actorId": actor_id,
                "actorName": (
                    user_names.get(actor_id, actor_id) if actor_id is not None else None
                ),
                "method": _text(received_data.get("method")),
                "path": _text(received_data.get("path")),
                "httpStatus": _number(finished_data.get("httpStatus")),
                "status": status,
                "traceId": trace_id,
                "zipkinTraceUrl": _zipkin_trace_url(trace_id),
            }
        )
    return views


__all__ = [
    "DEFAULT_LIMIT",
    "MAX_LIMIT",
    "event_responses",
    "chain_views",
]
