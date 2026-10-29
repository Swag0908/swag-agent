"""审计上下文（替代 Java 的 ``AuditContextHolder`` ThreadLocal）。

Java 侧同步调用用 ThreadLocal，Reactor 流水线用 Micrometer Context Propagation。
Python 的 asyncio 任务天然隔离，且 ``contextvars`` 会被 ``anyio.to_thread`` /
``run_in_threadpool`` 复制到工作线程，因此这里只需要一个 ``ContextVar``。

对外契约（``CONTRACTS.md`` §4）：

- ``current_audit_id() -> str | None``
- ``current_user_id() -> int | None``
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Iterator


@dataclass(frozen=True)
class AuditContext:
    """一次 HTTP 请求的审计上下文（对齐 Java ``AuditRequestContext``）。

    audit_id / request_id / tenant_id / actor_id / session_id / confirmation_id /
    conversation_id 与 Java record 的 7 个字段一一对应。
    """

    audit_id: str
    request_id: str | None = None
    tenant_id: str = "default"
    actor_id: str | None = None
    session_id: str | None = None
    confirmation_id: str | None = None
    conversation_id: str | None = None


_CTX: ContextVar[AuditContext | None] = ContextVar("swag_audit_context", default=None)


def current_context() -> AuditContext | None:
    """当前请求的审计上下文；无（后台任务/测试）时为 None。"""
    return _CTX.get()


def current_audit_id() -> str | None:
    ctx = _CTX.get()
    return ctx.audit_id if ctx is not None else None


def current_user_id() -> int | None:
    """当前审计主体对应的用户 id；匿名/系统事件返回 None。"""
    ctx = _CTX.get()
    if ctx is None or ctx.actor_id is None:
        return None
    try:
        return int(ctx.actor_id)
    except (TypeError, ValueError):
        return None


def current_tenant_id() -> str:
    ctx = _CTX.get()
    return ctx.tenant_id if ctx is not None else "default"


def current_conversation_id() -> str | None:
    ctx = _CTX.get()
    return ctx.conversation_id if ctx is not None else None


def current_confirmation_id() -> str | None:
    ctx = _CTX.get()
    return ctx.confirmation_id if ctx is not None else None


def parse_uuid(value: str | None) -> str | None:
    """解析 UUID 并归一化为小写字符串；非法/空返回 None（对齐 Java ``parseUuid``）。"""
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return str(uuid.UUID(text))
    except (ValueError, AttributeError, TypeError):
        return None


@contextmanager
def audit_context(ctx: AuditContext) -> Iterator[AuditContext]:
    """在 with 块内激活审计上下文，退出时恢复上一层（对齐 ``AuditContextHolder.open``）。"""
    token: Token[AuditContext | None] = _CTX.set(ctx)
    try:
        yield ctx
    finally:
        _CTX.reset(token)
