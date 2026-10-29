"""审计查询 / 危险操作确认端点（对齐 Java ``com.swag.audit.web`` 的 4 个接口）。

- ``GET  /audit/events/{auditId}``                登录即可：一条审计链的全部事件
- ``GET  /audit/chains?limit=30``                 仅 ADMIN：最近调用链列表（limit 钳制 1..200）
- ``GET  /audit/confirmations/{confirmationId}``  登录即可：确认票据状态；不存在 → 409
- ``POST /audit/confirmations/{confirmationId}/decision`` 登录即可：审批（APPROVED/DENIED）

返回字段严格保持 Java record 的 camelCase；Instant 一律 ``Z`` 结尾字符串；
``eventData`` 是“JSON 字符串”而非对象（与 Java 二次编码一致）。
错误包络由 ``app.core.errors.install_error_handlers`` 统一处理：

- 票据需确认：409 ``{"code":"CONFIRMATION_REQUIRED",...}``（由工具调用路径抛出）
- 票据非法/过期/不存在：409 ``{"code":"CONFIRMATION_INVALID","message":...}``
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import current_user, get_db, require_admin
from app.audit import confirmation, query
from app.audit.context import AuditContext, current_audit_id, parse_uuid
from app.core.errors import BadRequest
from app.domains.auth.service import AuthUser

router = APIRouter(tags=["audit"])


class ConfirmationDecisionRequest(BaseModel):
    """Java ``ConfirmationDecisionRequest(decision, reason)``。"""

    decision: str | None = None
    reason: str | None = None


def _request_context(request: Request, user: AuthUser) -> AuditContext:
    """从请求态拼审计上下文（中间件已写入 state；无中间件时退化为请求头/默认值）。"""
    state = request.state
    tenant_id = (
        getattr(state, "tenant_id", None)
        or request.headers.get("x-tenant-id")
        or "default"
    )
    return AuditContext(
        audit_id=getattr(state, "audit_id", None) or current_audit_id() or "",
        request_id=getattr(state, "request_id", None),
        tenant_id=tenant_id,
        actor_id=str(user.id),
        session_id=None,
        confirmation_id=getattr(state, "confirmation_id", None),
        conversation_id=getattr(state, "conversation_id", None),
    )


def _require_uuid(raw: str, field: str) -> str:
    normalized = parse_uuid(raw)
    if normalized is None:
        # Java 侧 @PathVariable UUID 解析失败 → 400
        raise BadRequest(f"{field} 不是合法的 UUID")
    return normalized


@router.get("/audit/events/{audit_id}")
def get_audit_events(
    audit_id: str,
    _user: AuthUser = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    """Java ``AuditQueryController.findByAuditId`` 返回 ``List<AuditEventResponse>``。"""
    normalized = _require_uuid(audit_id, "auditId")
    return query.event_responses(db, normalized)


@router.get("/audit/chains")
def get_audit_chains(
    limit: int = query.DEFAULT_LIMIT,
    _admin: AuthUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[dict]:
    """仅 ADMIN（Java ``AuditChainController.requireAdmin``，403 message 由 errors 统一）。"""
    return query.chain_views(db, limit)


@router.get("/audit/confirmations/{confirmation_id}")
def get_confirmation(
    confirmation_id: str,
    _user: AuthUser = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    normalized = _require_uuid(confirmation_id, "confirmationId")
    record = confirmation.find(normalized, db=db)
    if record is None:
        raise confirmation.invalid_error("Confirmation not found")
    return confirmation.response_dict(record)


@router.post("/audit/confirmations/{confirmation_id}/decision")
def decide_confirmation(
    confirmation_id: str,
    payload: ConfirmationDecisionRequest,
    request: Request,
    user: AuthUser = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    normalized = _require_uuid(confirmation_id, "confirmationId")
    decision = confirmation.parse_decision(payload.decision)
    context = _request_context(request, user)
    record = confirmation.decide(
        normalized,
        decision,
        payload.reason,
        context=context,
        db=db,
    )
    return confirmation.response_dict(record)


__all__ = ["router"]
