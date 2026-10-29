"""审计事件唯一写入口：追加写 ``audit_event`` 35 列（对齐 ``JdbcAuditRecorder``）。

设计要点：

1. 公共上下文（audit_id/request_id/tenant_id/actor_id/session_id/conversation_id）
   从 ``app.audit.context`` 自动补全；调用方只在需要覆盖时显式传。
2. ``event_data`` 存 JSON（对象），``error_message`` 截断 4000 字符 — 与 Java 一致。
3. **审计失败绝不打断业务**：所有对外函数整体 try/except 并记日志；返回 ``None``。
   （Java 端 recorder 会抛异常，Python 迁移按 CONTRACTS 要求降级为 best-effort。）
4. 写库风格：``Session`` + ORM；测试可 monkeypatch ``app.audit.recorder.SessionLocal``。
"""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from typing import Any, Iterator
from uuid import uuid4

from sqlalchemy.orm import Session

from app.audit.context import current_context
from app.audit.digest import action_digest, raw_tool_input, sha256
from app.audit.events import AuditEventType, event_type_name
from app.config import settings
from app.core.timeutil import now
from app.db.base import SessionLocal
from app.db.models import AuditEvent

logger = logging.getLogger(__name__)

#: Java ``JdbcAuditRecorder.truncate(errorMessage, 4000)``
ERROR_MESSAGE_LIMIT = 4000


@contextmanager
def session_scope(db: Session | None = None, *, commit: bool = True) -> Iterator[Session]:
    """获取写库 Session：外部传入则复用（``commit=True`` 时按服务事务提交），否则自建。

    - 自建分支：正常退出提交、异常回滚、最终关闭。
    - 传入分支：``commit=True`` 模拟 Java ``@Transactional`` 的服务级提交；
      ``commit=False`` 表示事务由调用方持有（recorder 挂在业务事务里时使用）。

    自建分支在异常时回滚，避免半截事务污染连接池。
    """
    if db is not None:
        try:
            yield db
            if commit:
                db.commit()
        except Exception:
            if commit:
                db.rollback()
            raise
        return
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _json_safe(value: Any) -> Any:
    """把 event_data 收敛成可 JSON 序列化的纯量结构（datetime 等降级为字符串）。"""
    if value is None:
        return None
    try:
        return json.loads(json.dumps(value, default=str, ensure_ascii=False))
    except (TypeError, ValueError):
        return str(value)


def _truncate(value: str | None, limit: int) -> str | None:
    if value is None or len(value) <= limit:
        return value
    return value[:limit]


def audit_enabled() -> bool:
    """审计总开关（``settings.audit_enabled``）。

    关闭时 recorder 完全跳过 ``audit_event`` 写库（只读集成冒烟/真实库调试时用），
    确认票据等业务表不受影响；所有调用方仍可安全调用（返回 None/id，不报错）。
    """
    return bool(getattr(settings, "audit_enabled", True))


def record_event(
    event_type: str,
    execution_status: str | None = None,
    *,
    db: Session | None = None,
    **fields: Any,
) -> str | None:
    """追加一条审计事件，返回 ``event_id``；任何失败都返回 None（不抛出）。

    可覆盖字段（关键字参数）：
    ``audit_id``、``request_id``、``trace_id``、``span_id``、``parent_span_id``、
    ``parent_event_id``、``tenant_id``、``session_id``、``actor_type``、``actor_id``、
    ``agent_name``、``agent_version``、``model_name``、``tool_name``、``tool_call_id``、
    ``confirmation_id``、``action_digest``、``input_ref``、``input_digest``、``output_ref``、
    ``output_digest``、``event_data``、``error_code``、``error_message``、``conversation_id``。
    """
    if not audit_enabled():
        return None
    try:
        ctx = current_context()
        audit_id = fields.pop("audit_id", None) or (ctx.audit_id if ctx is not None else None)
        if not audit_id:
            logger.warning("skip audit event %s: no audit context and no audit_id override", event_type)
            return None

        event_name = event_type_name(event_type)
        if not event_name:
            logger.warning("skip audit event: empty event_type")
            return None

        request_id = fields.pop("request_id", None) or (ctx.request_id if ctx is not None else None)
        tenant_id = fields.pop("tenant_id", None) or (ctx.tenant_id if ctx is not None else None)
        session_id = fields.pop("session_id", None) or (ctx.session_id if ctx is not None else None)
        conversation_id = fields.pop("conversation_id", None) or (
            ctx.conversation_id if ctx is not None else None
        )
        actor_type = fields.pop("actor_type", None) or "SYSTEM"
        actor_id = fields.pop("actor_id", None) or (ctx.actor_id if ctx is not None else None)

        event_data = fields.pop("event_data", None)
        confirmation_id = fields.pop("confirmation_id", None)
        error_message = _truncate(fields.pop("error_message", None), ERROR_MESSAGE_LIMIT)

        timestamp = now()
        event = AuditEvent(
            event_id=str(uuid4()),
            audit_id=str(audit_id),
            request_id=request_id,
            source_event_id=None,
            trace_id=fields.pop("trace_id", None),
            span_id=fields.pop("span_id", None),
            parent_span_id=fields.pop("parent_span_id", None),
            parent_event_id=fields.pop("parent_event_id", None),
            tenant_id=tenant_id,
            session_id=session_id,
            conversation_id=conversation_id,
            actor_type=actor_type,
            actor_id=actor_id,
            actor_display_name=None,
            event_type=event_name,
            execution_status=execution_status,
            agent_name=fields.pop("agent_name", None),
            agent_version=fields.pop("agent_version", None),
            model_name=fields.pop("model_name", None),
            tool_name=fields.pop("tool_name", None),
            tool_call_id=fields.pop("tool_call_id", None),
            confirmation_id=str(confirmation_id) if confirmation_id is not None else None,
            action_digest=fields.pop("action_digest", None),
            input_ref=fields.pop("input_ref", None),
            input_digest=fields.pop("input_digest", None),
            output_ref=fields.pop("output_ref", None),
            output_digest=fields.pop("output_digest", None),
            event_data=_json_safe(event_data) if event_data is not None else {},
            error_code=fields.pop("error_code", None),
            error_message=error_message,
            occurred_at=timestamp,
            recorded_at=timestamp,
            schema_version=1,
            # 哈希链未实现：Java 端 previous_hash/event_hash 恒为 NULL，迁移不要“顺手补”
            previous_hash=None,
            event_hash=None,
        )
        if fields:
            logger.debug("ignored unknown audit fields for %s: %s", event_name, sorted(fields))

        # 传入 db 时由调用方持有事务（recorder 只为业务事务追加事件，不提前提交）
        with session_scope(db, commit=False) as session:
            session.add(event)
            if db is not None:
                session.flush()
        return event.event_id
    except Exception:  # noqa: BLE001  审计失败不能影响业务
        logger.warning("failed to record audit event %r", event_type, exc_info=True)
        return None


def _resolve_audit_id(audit_id: str | None) -> str | None:
    ctx = current_context()
    return str(audit_id) if audit_id is not None else (ctx.audit_id if ctx is not None else None)


def _resolve_actor_id(user_id: int | str | None) -> str | None:
    ctx = current_context()
    if ctx is not None and ctx.actor_id is not None:
        return ctx.actor_id
    return str(user_id) if user_id is not None else None


def _tool_input_data(raw_input: str) -> dict[str, Any]:
    data: dict[str, Any] = {"inputLength": len(raw_input)}
    if settings.audit_include_tool_content:
        data["input"] = raw_input
    return data


def _tool_output_data(output: str | None) -> dict[str, Any]:
    text = "" if output is None else str(output)
    data: dict[str, Any] = {"outputLength": len(text)}
    if settings.audit_include_tool_content:
        data["output"] = text
    return data


def _tool_digests(tool_name: str, arguments: Any) -> tuple[str, str, str]:
    """返回 ``(raw_input, input_digest, action_digest)``。"""
    raw = raw_tool_input(arguments)
    return raw, sha256(raw), action_digest(tool_name, raw)


def record_tool_requested(
    tool_name: str,
    arguments: Any,
    audit_id: str | None = None,
    user_id: int | str | None = None,
    *,
    tool_call_id: str | None = None,
    conversation_id: str | None = None,
) -> str | None:
    """记录 ``TOOL_CALL_REQUESTED``，返回 ``tool_call_id``（即使审计失败也返回）。"""
    tool_call_id = tool_call_id or str(uuid4())
    try:
        raw, input_digest, digested_action = _tool_digests(tool_name, arguments)
        record_event(
            AuditEventType.TOOL_CALL_REQUESTED,
            "REQUESTED",
            audit_id=_resolve_audit_id(audit_id),
            actor_type="AGENT",
            actor_id=_resolve_actor_id(user_id),
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            action_digest=digested_action,
            input_digest=input_digest,
            event_data=_tool_input_data(raw),
            conversation_id=conversation_id,
        )
    except Exception:  # noqa: BLE001
        logger.warning("failed to record TOOL_CALL_REQUESTED for %s", tool_name, exc_info=True)
    return tool_call_id


def record_tool_started(
    tool_name: str,
    tool_call_id: str,
    arguments: Any = None,
    *,
    audit_id: str | None = None,
    user_id: int | str | None = None,
    confirmation_id: str | None = None,
    conversation_id: str | None = None,
) -> None:
    """记录 ``TOOL_CALL_STARTED``（确认通过、真正执行工具之前）。"""
    try:
        _raw, input_digest, digested_action = _tool_digests(tool_name, arguments)
        record_event(
            AuditEventType.TOOL_CALL_STARTED,
            "STARTED",
            audit_id=_resolve_audit_id(audit_id),
            actor_type="AGENT",
            actor_id=_resolve_actor_id(user_id),
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            confirmation_id=confirmation_id,
            action_digest=digested_action,
            input_digest=input_digest,
            conversation_id=conversation_id,
        )
    except Exception:  # noqa: BLE001
        logger.warning("failed to record TOOL_CALL_STARTED for %s", tool_name, exc_info=True)


def record_tool_succeeded(
    tool_name: str,
    tool_call_id: str,
    output: str | None,
    arguments: Any = None,
    *,
    audit_id: str | None = None,
    user_id: int | str | None = None,
    confirmation_id: str | None = None,
    conversation_id: str | None = None,
) -> None:
    """记录 ``TOOL_CALL_SUCCEEDED``（输出摘要 + 可选输出原文）。"""
    try:
        _raw, input_digest, digested_action = _tool_digests(tool_name, arguments)
        record_event(
            AuditEventType.TOOL_CALL_SUCCEEDED,
            "SUCCEEDED",
            audit_id=_resolve_audit_id(audit_id),
            actor_type="AGENT",
            actor_id=_resolve_actor_id(user_id),
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            confirmation_id=confirmation_id,
            action_digest=digested_action,
            input_digest=input_digest,
            output_digest=sha256(output),
            event_data=_tool_output_data(output),
            conversation_id=conversation_id,
        )
    except Exception:  # noqa: BLE001
        logger.warning("failed to record TOOL_CALL_SUCCEEDED for %s", tool_name, exc_info=True)


def record_tool_failed(
    tool_name: str,
    tool_call_id: str,
    error: BaseException | str | None,
    arguments: Any = None,
    *,
    audit_id: str | None = None,
    user_id: int | str | None = None,
    confirmation_id: str | None = None,
    conversation_id: str | None = None,
) -> None:
    """记录 ``TOOL_CALL_FAILED``（error_code/error_message 对齐 Java）。"""
    try:
        _raw, input_digest, digested_action = _tool_digests(tool_name, arguments)
        if isinstance(error, BaseException):
            error_code = type(error).__name__
            error_message = str(error)
        elif error is not None:
            error_code = "Error"
            error_message = str(error)
        else:
            error_code = None
            error_message = None
        record_event(
            AuditEventType.TOOL_CALL_FAILED,
            "FAILED",
            audit_id=_resolve_audit_id(audit_id),
            actor_type="AGENT",
            actor_id=_resolve_actor_id(user_id),
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            confirmation_id=confirmation_id,
            action_digest=digested_action,
            input_digest=input_digest,
            error_code=error_code,
            error_message=error_message,
            conversation_id=conversation_id,
        )
    except Exception:  # noqa: BLE001
        logger.warning("failed to record TOOL_CALL_FAILED for %s", tool_name, exc_info=True)


# ---------------------------------------------------------------------------
# Agent 级事件（对齐 Java ``AuditAdvisor``）；chat-core 可选使用
# ---------------------------------------------------------------------------


def record_agent_started(
    agent_name: str = "chatClient",
    *,
    model_name: str | None = None,
    prompt: str | None = None,
    audit_id: str | None = None,
) -> None:
    record_event(
        AuditEventType.AGENT_STARTED,
        "STARTED",
        audit_id=_resolve_audit_id(audit_id),
        actor_type="AGENT",
        agent_name=agent_name,
        model_name=model_name,
        input_digest=sha256(prompt),
        event_data={"advisor": "auditAdvisor"},
    )


def record_agent_completed(
    agent_name: str = "chatClient",
    *,
    model_name: str | None = None,
    output: str | None = None,
    audit_id: str | None = None,
) -> None:
    record_event(
        AuditEventType.AGENT_COMPLETED,
        "SUCCEEDED",
        audit_id=_resolve_audit_id(audit_id),
        actor_type="AGENT",
        agent_name=agent_name,
        model_name=model_name,
        output_digest=sha256(output),
    )


def record_agent_failed(
    agent_name: str = "chatClient",
    *,
    model_name: str | None = None,
    error: BaseException | str | None = None,
    audit_id: str | None = None,
) -> None:
    if isinstance(error, BaseException):
        error_code, error_message = type(error).__name__, str(error)
    else:
        error_code, error_message = ("Error", str(error)) if error is not None else (None, None)
    record_event(
        AuditEventType.AGENT_FAILED,
        "FAILED",
        audit_id=_resolve_audit_id(audit_id),
        actor_type="AGENT",
        agent_name=agent_name,
        model_name=model_name,
        error_code=error_code,
        error_message=error_message,
    )


def record_agent_waiting_confirmation(
    tool_name: str,
    confirmation_id: str | None,
    *,
    agent_name: str = "chatClient",
    model_name: str | None = None,
    audit_id: str | None = None,
) -> None:
    record_event(
        AuditEventType.AGENT_WAITING_CONFIRMATION,
        "WAITING_CONFIRMATION",
        audit_id=_resolve_audit_id(audit_id),
        actor_type="AGENT",
        agent_name=agent_name,
        model_name=model_name,
        tool_name=tool_name,
        confirmation_id=confirmation_id,
    )


__all__ = [
    "ERROR_MESSAGE_LIMIT",
    "audit_enabled",
    "record_event",
    "record_tool_requested",
    "record_tool_started",
    "record_tool_succeeded",
    "record_tool_failed",
    "record_agent_started",
    "record_agent_completed",
    "record_agent_failed",
    "record_agent_waiting_confirmation",
    "session_scope",
]
