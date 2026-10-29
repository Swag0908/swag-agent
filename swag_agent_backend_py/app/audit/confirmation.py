"""危险操作确认：5 状态机 + 一次性消费 + 过期（对齐 Java ``ConfirmationService``）。

状态流转::

    PENDING ──approve──> APPROVED ──consume──> CONSUMED
       │                    │
       ├──deny──> DENIED    └──(过期)──> EXPIRED
       └──(过期)──> EXPIRED

- 绑定 ``tenant_id`` / ``actor_id`` / ``tool_name`` / ``action_digest``：归属或动作不匹配 → 409
  ``CONFIRMATION_INVALID``。
- 消费走 ``SELECT ... FOR UPDATE`` + 条件 UPDATE（MySQL 行锁；SQLite 忽略 FOR UPDATE 但条件
  UPDATE 仍能保证一次性）。
- 需要确认但本次请求没有票据 → 抛 ``ConfirmationRequired``（全局处理器输出 409 包络）。
- 校验失败/过期抛 ``ConfirmationInvalid``。
- 校验失败时，已发生的状态变更（如置为 EXPIRED）要保留（Java ``noRollbackFor``），
  因此本模块在 session 正常退出（提交）之后再抛出异常。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterator, Literal
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.audit import recorder
from app.audit.context import AuditContext, current_context
from app.audit.events import AuditEventType
from app.config import settings
from app.core.errors import ConfirmationInvalid, ConfirmationRequired
from app.core.timeutil import iso_instant, now
from app.db.models import AuditConfirmation

logger = logging.getLogger(__name__)

Decision = Literal["APPROVED", "DENIED"]


class ConfirmationStatus:
    """Java ``ConfirmationStatus`` 的 1:1 字符串常量。"""

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"
    CONSUMED = "CONSUMED"

    VALUES = (PENDING, APPROVED, DENIED, EXPIRED, CONSUMED)


@dataclass(frozen=True)
class ConfirmationRecord:
    """确认票据的只读快照（对齐 Java ``ConfirmationRecord``）。"""

    confirmation_id: str
    audit_id: str
    tool_call_id: str | None
    tenant_id: str | None
    actor_id: str | None
    tool_name: str
    canonical_input: str
    action_digest: str | None
    status: str
    decision_reason: str | None
    requested_at: datetime
    decided_at: datetime | None
    expires_at: datetime
    consumed_at: datetime | None


#: 确认票据有效期（Java ``audit.confirmation-ttl=10m``）
def confirmation_ttl_seconds() -> int:
    return int(settings.audit_confirmation_ttl_seconds or 600)


def requires_confirmation(tool_name: str) -> bool:
    """该工具是否必须用户确认（配置为空集合 = 生产等价于没有硬闸门）。"""
    if not tool_name:
        return False
    return tool_name in settings.confirmation_required_tools


def parse_decision(value: str | None) -> str:
    """``decision`` 大小写不敏感；非法值抛 ``ConfirmationInvalid``（Java 行为）。"""
    if value is None:
        raise invalid_error("Decision must not be null")
    normalized = value.strip().upper()
    if normalized not in (ConfirmationStatus.APPROVED, ConfirmationStatus.DENIED):
        raise invalid_error("Decision must be APPROVED or DENIED")
    return normalized


def _require_context(context: AuditContext | None) -> AuditContext:
    ctx = context if context is not None else current_context()
    if ctx is None:
        raise RuntimeError("No audit context is active")
    return ctx


def _equals_nullable(left: str | None, right: str | None) -> bool:
    return left == right


def _to_record(row: AuditConfirmation) -> ConfirmationRecord:
    return ConfirmationRecord(
        confirmation_id=row.confirmation_id,
        audit_id=row.audit_id,
        tool_call_id=row.tool_call_id,
        tenant_id=row.tenant_id,
        actor_id=row.actor_id,
        tool_name=row.tool_name,
        canonical_input=row.canonical_input,
        action_digest=row.action_digest,
        status=row.status,
        decision_reason=row.decision_reason,
        requested_at=row.requested_at,
        decided_at=row.decided_at,
        expires_at=row.expires_at,
        consumed_at=row.consumed_at,
    )


def response_dict(record: ConfirmationRecord) -> dict:
    """``ConfirmationResponse`` JSON（Instant 全部 Z 结尾字符串）。"""
    return {
        "confirmationId": record.confirmation_id,
        "auditId": record.audit_id,
        "toolName": record.tool_name,
        "status": record.status,
        "requestedAt": iso_instant(record.requested_at),
        "decidedAt": iso_instant(record.decided_at),
        "expiresAt": iso_instant(record.expires_at),
        "consumedAt": iso_instant(record.consumed_at),
    }


def invalid_error(message: str) -> ConfirmationInvalid:
    """构造 409 ``CONFIRMATION_INVALID``，并补齐 Java 的固定包络字段。

    ``app/core/errors.py`` 里 ``ConfirmationInvalid`` 只设置了 ``self.code``，没有把
    ``code``/``timestamp`` 放进 ``extra``；全局处理器对 ``extra["code"]`` 命中时才输出
    固定包络，所以这里统一补齐（改动只在本模块，不动 Lead 的 core/errors.py）。
    """
    error = ConfirmationInvalid(message)
    error.extra.update(
        {
            "code": "CONFIRMATION_INVALID",
            "message": message,
            "timestamp": iso_instant(now()),
        }
    )
    return error


def _confirmation_required(
    confirmation_id: str,
    audit_id: str,
    tool_name: str,
    requested_at: datetime,
    expires_at: datetime,
) -> ConfirmationRequired:
    """构造 409 ``CONFIRMATION_REQUIRED``（校验 body 的时间为 Instant/Z 形态）。"""
    error = ConfirmationRequired(
        confirmation_id=confirmation_id,
        audit_id=audit_id,
        tool_name=tool_name,
        requested_at=requested_at,
        expires_at=expires_at,
        message=f"工具 {tool_name} 需要用户确认",
    )
    # app.core.errors.ConfirmationRequired 用 datetime.isoformat()，对 naive datetime 不带 Z；
    # 这里覆盖成 Java Instant 的 JSON 形态（UTC、Z 结尾、毫秒）。
    error.extra["requestedAt"] = iso_instant(requested_at)
    error.extra["expiresAt"] = iso_instant(expires_at)
    return error


def request_confirmation(
    tool_name: str,
    tool_call_id: str | None,
    canonical_input: str,
    action_digest: str | None,
    *,
    context: AuditContext | None = None,
    db: Session | None = None,
) -> ConfirmationRequired:
    """创建 PENDING 票据并返回待抛出的 ``ConfirmationRequired``（不直接 raise，对齐 Java）。"""
    ctx = _require_context(context)
    requested_at = now()
    expires_at = requested_at + timedelta(seconds=confirmation_ttl_seconds())
    confirmation_id = str(uuid4())

    with recorder.session_scope(db) as session:
        row = AuditConfirmation(
            confirmation_id=confirmation_id,
            audit_id=ctx.audit_id,
            tool_call_id=tool_call_id,
            tenant_id=ctx.tenant_id,
            actor_id=ctx.actor_id,
            tool_name=tool_name,
            canonical_input=canonical_input,
            action_digest=action_digest,
            status=ConfirmationStatus.PENDING,
            decision_reason=None,
            requested_at=requested_at,
            decided_at=None,
            expires_at=expires_at,
            consumed_at=None,
        )
        session.add(row)
        session.flush()
        recorder.record_event(
            AuditEventType.CONFIRMATION_REQUESTED,
            ConfirmationStatus.PENDING,
            db=session,
            audit_id=ctx.audit_id,
            actor_type="AGENT",
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            confirmation_id=confirmation_id,
            action_digest=action_digest,
            event_data={"expiresAt": iso_instant(expires_at)},
        )

    return _confirmation_required(
        confirmation_id=confirmation_id,
        audit_id=ctx.audit_id,
        tool_name=tool_name,
        requested_at=requested_at,
        expires_at=expires_at,
    )


def _verify_actor(row: AuditConfirmation, ctx: AuditContext) -> None:
    if not _equals_nullable(row.tenant_id, ctx.tenant_id) or not _equals_nullable(
        row.actor_id, ctx.actor_id
    ):
        raise invalid_error("Confirmation does not belong to the current user")


def _expire_if_necessary(session: Session, row: AuditConfirmation) -> None:
    """已过期则置 EXPIRED、记事件并抛 ``ConfirmationInvalid``（变更需提交后生效）。"""
    if row.expires_at is not None and row.expires_at > now():
        return
    expired_at = now()
    result = session.execute(
        update(AuditConfirmation)
        .where(
            AuditConfirmation.confirmation_id == row.confirmation_id,
            AuditConfirmation.status.in_(
                (ConfirmationStatus.PENDING, ConfirmationStatus.APPROVED)
            ),
        )
        .values(status=ConfirmationStatus.EXPIRED, decided_at=expired_at)
    )
    if result.rowcount == 1:
        recorder.record_event(
            AuditEventType.CONFIRMATION_EXPIRED,
            ConfirmationStatus.EXPIRED,
            db=session,
            audit_id=row.audit_id,
            actor_type="SYSTEM",
            tool_name=row.tool_name,
            tool_call_id=row.tool_call_id,
            confirmation_id=row.confirmation_id,
            action_digest=row.action_digest,
        )
    row.status = ConfirmationStatus.EXPIRED
    raise invalid_error("Confirmation has expired")


def _reload(session: Session, confirmation_id: str) -> AuditConfirmation:
    row = session.get(AuditConfirmation, confirmation_id)
    if row is not None:
        session.refresh(row)
    if row is None:  # pragma: no cover - 极端并发删除
        raise invalid_error("Confirmation not found")
    return row


def decide(
    confirmation_id: str,
    decision: str,
    reason: str | None = None,
    *,
    context: AuditContext | None = None,
    db: Session | None = None,
) -> ConfirmationRecord:
    """批准/拒绝一张 PENDING 票据；非法/过期/已决策 → ``ConfirmationInvalid``。"""
    if decision not in (ConfirmationStatus.APPROVED, ConfirmationStatus.DENIED):
        raise invalid_error("Decision must be APPROVED or DENIED")
    ctx = _require_context(context)

    validation_error: ConfirmationInvalid | None = None
    record: ConfirmationRecord | None = None
    with recorder.session_scope(db) as session:
        row = session.scalar(
            select(AuditConfirmation)
            .where(AuditConfirmation.confirmation_id == confirmation_id)
            .with_for_update()
        )
        try:
            if row is None:
                raise invalid_error("Confirmation not found")
            _verify_actor(row, ctx)
            _expire_if_necessary(session, row)
            if row.status != ConfirmationStatus.PENDING:
                raise invalid_error(f"Confirmation is not pending: {row.status}")

            decided_at = now()
            result = session.execute(
                update(AuditConfirmation)
                .where(
                    AuditConfirmation.confirmation_id == confirmation_id,
                    AuditConfirmation.status == ConfirmationStatus.PENDING,
                )
                .values(
                    status=decision,
                    decision_reason=reason,
                    decided_at=decided_at,
                )
            )
            if result.rowcount != 1:
                raise invalid_error("Confirmation state changed concurrently")

            recorder.record_event(
                (
                    AuditEventType.CONFIRMATION_APPROVED
                    if decision == ConfirmationStatus.APPROVED
                    else AuditEventType.CONFIRMATION_DENIED
                ),
                decision,
                db=session,
                audit_id=row.audit_id,
                actor_type="USER",
                actor_id=ctx.actor_id,
                tool_name=row.tool_name,
                tool_call_id=row.tool_call_id,
                confirmation_id=confirmation_id,
                action_digest=row.action_digest,
                event_data={"reason": reason} if reason and reason.strip() else {},
            )
            row = _reload(session, confirmation_id)
            record = _to_record(row)
        except ConfirmationInvalid as exc:
            # 与 Java 的 noRollbackFor 对齐：EXPIRED 等状态变更随事务提交，异常在提交后再抛。
            validation_error = exc

    if validation_error is not None:
        raise validation_error
    assert record is not None
    return record


def consume_approval(
    confirmation_id: str,
    tool_name: str,
    action_digest: str | None,
    *,
    context: AuditContext | None = None,
    db: Session | None = None,
) -> ConfirmationRecord:
    """执行工具前原子消费一次已批准确认；不匹配/过期/已消费 → ``ConfirmationInvalid``。"""
    ctx = _require_context(context)

    validation_error: ConfirmationInvalid | None = None
    record: ConfirmationRecord | None = None
    with recorder.session_scope(db) as session:
        row = session.scalar(
            select(AuditConfirmation)
            .where(AuditConfirmation.confirmation_id == confirmation_id)
            .with_for_update()
        )
        try:
            if row is None:
                raise invalid_error("Confirmation not found")
            _verify_actor(row, ctx)
            _expire_if_necessary(session, row)

            if row.status != ConfirmationStatus.APPROVED:
                raise invalid_error(f"Confirmation is not approved: {row.status}")
            if row.tool_name != tool_name or row.action_digest != action_digest:
                raise invalid_error(
                    "Confirmed action does not match the requested tool call"
                )

            consumed_at = now()
            result = session.execute(
                update(AuditConfirmation)
                .where(
                    AuditConfirmation.confirmation_id == confirmation_id,
                    AuditConfirmation.status == ConfirmationStatus.APPROVED,
                    AuditConfirmation.consumed_at.is_(None),
                )
                .values(status=ConfirmationStatus.CONSUMED, consumed_at=consumed_at)
            )
            if result.rowcount != 1:
                raise invalid_error("Confirmation has already been consumed")

            recorder.record_event(
                AuditEventType.CONFIRMATION_CONSUMED,
                ConfirmationStatus.CONSUMED,
                db=session,
                audit_id=row.audit_id,
                actor_type="SYSTEM",
                tool_name=tool_name,
                tool_call_id=row.tool_call_id,
                confirmation_id=confirmation_id,
                action_digest=action_digest,
            )
            row = _reload(session, confirmation_id)
            record = _to_record(row)
        except ConfirmationInvalid as exc:
            validation_error = exc

    if validation_error is not None:
        raise validation_error
    assert record is not None
    return record


def resolve_audit_id_for_retry(
    confirmation_id: str | None,
    *,
    tenant_id: str | None,
    actor_id: str | None,
    db: Session | None = None,
) -> str | None:
    """带 ``X-Confirmation-Id`` 重试时恢复最初的 ``audit_id``，保持同一条审计链。

    仅当票据 APPROVED、未过期且租户/用户匹配时复用；否则返回 None（新链）。
    """
    if not confirmation_id:
        return None
    with recorder.session_scope(db, commit=False) as session:
        row = session.get(AuditConfirmation, confirmation_id)
        if row is None:
            return None
        if row.status != ConfirmationStatus.APPROVED:
            return None
        if row.expires_at is None or row.expires_at <= now():
            return None
        if not _equals_nullable(row.tenant_id, tenant_id):
            return None
        if not _equals_nullable(row.actor_id, actor_id):
            return None
        return row.audit_id


def find(confirmation_id: str | None, *, db: Session | None = None) -> ConfirmationRecord | None:
    """按 id 读取票据（不存在返回 None；GET 端点由调用方转 409）。"""
    if not confirmation_id:
        return None
    with recorder.session_scope(db, commit=False) as session:
        row = session.get(AuditConfirmation, confirmation_id)
        return _to_record(row) if row is not None else None


def is_expired(record: ConfirmationRecord) -> bool:
    return record.expires_at is not None and record.expires_at <= now()


__all__ = [
    "Decision",
    "ConfirmationStatus",
    "ConfirmationRecord",
    "confirmation_ttl_seconds",
    "requires_confirmation",
    "parse_decision",
    "request_confirmation",
    "decide",
    "consume_approval",
    "resolve_audit_id_for_retry",
    "find",
    "response_dict",
    "is_expired",
]
