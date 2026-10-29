"""审计事件类型与执行状态常量（对齐 Java ``AuditEventType`` / 落库字符串）。

Java 端 16 种事件类型固定，落库列 ``audit_event.event_type`` 直接存枚举名；
``execution_status`` 是自由字符串，常用取值集中在这里，避免各调用方拼错。
"""

from __future__ import annotations


class AuditEventType:
    """Java ``com.swag.audit.core.AuditEventType`` 的 1:1 字符串常量。"""

    REQUEST_RECEIVED = "REQUEST_RECEIVED"
    REQUEST_COMPLETED = "REQUEST_COMPLETED"
    REQUEST_FAILED = "REQUEST_FAILED"
    AGENT_STARTED = "AGENT_STARTED"
    AGENT_COMPLETED = "AGENT_COMPLETED"
    AGENT_FAILED = "AGENT_FAILED"
    AGENT_WAITING_CONFIRMATION = "AGENT_WAITING_CONFIRMATION"
    TOOL_CALL_REQUESTED = "TOOL_CALL_REQUESTED"
    TOOL_CALL_STARTED = "TOOL_CALL_STARTED"
    TOOL_CALL_SUCCEEDED = "TOOL_CALL_SUCCEEDED"
    TOOL_CALL_FAILED = "TOOL_CALL_FAILED"
    CONFIRMATION_REQUESTED = "CONFIRMATION_REQUESTED"
    CONFIRMATION_APPROVED = "CONFIRMATION_APPROVED"
    CONFIRMATION_DENIED = "CONFIRMATION_DENIED"
    CONFIRMATION_EXPIRED = "CONFIRMATION_EXPIRED"
    CONFIRMATION_CONSUMED = "CONFIRMATION_CONSUMED"


ALL_EVENT_TYPES: tuple[str, ...] = (
    AuditEventType.REQUEST_RECEIVED,
    AuditEventType.REQUEST_COMPLETED,
    AuditEventType.REQUEST_FAILED,
    AuditEventType.AGENT_STARTED,
    AuditEventType.AGENT_COMPLETED,
    AuditEventType.AGENT_FAILED,
    AuditEventType.AGENT_WAITING_CONFIRMATION,
    AuditEventType.TOOL_CALL_REQUESTED,
    AuditEventType.TOOL_CALL_STARTED,
    AuditEventType.TOOL_CALL_SUCCEEDED,
    AuditEventType.TOOL_CALL_FAILED,
    AuditEventType.CONFIRMATION_REQUESTED,
    AuditEventType.CONFIRMATION_APPROVED,
    AuditEventType.CONFIRMATION_DENIED,
    AuditEventType.CONFIRMATION_EXPIRED,
    AuditEventType.CONFIRMATION_CONSUMED,
)

# 请求级事件：调用链汇总（/audit/chains）只读这三类还原「谁、请求了什么、最终状态」。
REQUEST_EVENT_TYPES: tuple[str, ...] = (
    AuditEventType.REQUEST_RECEIVED,
    AuditEventType.REQUEST_COMPLETED,
    AuditEventType.REQUEST_FAILED,
)


class AuditExecutionStatus:
    """``audit_event.execution_status`` 常用取值（Java 也是字符串，不限制枚举）。"""

    RECEIVED = "RECEIVED"
    REQUESTED = "REQUESTED"
    STARTED = "STARTED"
    SUCCEEDED = "SUCCEEDED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"
    WAITING_CONFIRMATION = "WAITING_CONFIRMATION"
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"
    CONSUMED = "CONSUMED"
    IN_PROGRESS = "IN_PROGRESS"
    UNKNOWN = "UNKNOWN"


def event_type_name(event_type: str) -> str:
    """统一把事件类型规整成字符串（容忍传入常量外的自定义类型）。"""
    return str(event_type)


def execution_status_for_http(http_status: int) -> str:
    """HTTP 状态码 → ``execution_status``（逐字对齐 ``AuditContextFilter``）。"""
    if http_status == 409:
        return AuditExecutionStatus.WAITING_CONFIRMATION
    if http_status >= 500:
        return AuditExecutionStatus.FAILED
    if http_status >= 400:
        return AuditExecutionStatus.REJECTED
    return AuditExecutionStatus.SUCCEEDED


def event_type_for_http(http_status: int) -> str:
    """HTTP 状态码 → 请求结束事件类型（Java：>=500 记 REQUEST_FAILED，其余 COMPLETED）。"""
    if http_status >= 500:
        return AuditEventType.REQUEST_FAILED
    return AuditEventType.REQUEST_COMPLETED
