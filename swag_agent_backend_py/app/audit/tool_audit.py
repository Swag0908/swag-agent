"""供 chat-core 调用的异步工具审计封装（对齐 Java ``AuditingToolCallback``）。

chat-core 在工具执行前后尽力调用这里（``CONTRACTS.md`` §4 要求的接口）：

- ``check_tool_confirmation(tool_name, arguments, ctx) -> str | None``
  需要确认且本次请求没有票据 → 抛 ``ConfirmationRequired``（全局处理器输出 409 包络）；
  有票据 → 原子消费并返回票据 id；不需要确认 → 返回 None。
- ``record_tool_requested(...)`` / ``record_tool_started(...)`` /
  ``record_tool_succeeded(...)`` / ``record_tool_failed(...)``：写 ``TOOL_CALL_*`` 事件。

约定：

- **审计写失败不能影响聊天**：recorder 内部已 try/except，本模块的 async 包装再兜一层，
  保证这些函数不会因为审计基础设施异常而抛错。
- 只有确认闸门（``ConfirmationRequired`` / ``ConfirmationInvalid``）会向上抛。
- ``ctx`` 接受 ``app.agent.tools.registry.ToolCtx``（或同名字段的 dict / 任意对象），
  字段：``user_id`` / ``audit_id`` / ``conversation_id`` / ``confirmation_id``。
- 线程模型：SQLAlchemy 是同步的，这里统一用 ``run_in_threadpool``；contextvars 会被
  anyio 复制到工作线程，所以审计上下文在子线程依然可见。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import partial
from typing import Any
from uuid import uuid4

from starlette.concurrency import run_in_threadpool

from app.audit import confirmation, recorder
from app.audit.context import AuditContext, current_context
from app.audit.digest import action_digest, canonicalize_json, raw_tool_input
from app.core.errors import ConfirmationInvalid

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _ToolCtxFields:
    user_id: int | str | None = None
    audit_id: str | None = None
    conversation_id: str | None = None
    confirmation_id: str | None = None


def _extract_ctx(ctx: Any) -> _ToolCtxFields:
    """从 chat-core 的 ``ToolCtx`` / dict / None 中提取审计相关字段。"""
    if ctx is None:
        return _ToolCtxFields()
    if isinstance(ctx, dict):
        return _ToolCtxFields(
            user_id=ctx.get("user_id"),
            audit_id=ctx.get("audit_id"),
            conversation_id=ctx.get("conversation_id"),
            confirmation_id=ctx.get("confirmation_id"),
        )
    return _ToolCtxFields(
        user_id=getattr(ctx, "user_id", None),
        audit_id=getattr(ctx, "audit_id", None),
        conversation_id=getattr(ctx, "conversation_id", None),
        confirmation_id=getattr(ctx, "confirmation_id", None),
    )


def _effective_context(fields: _ToolCtxFields) -> AuditContext:
    """优先使用请求级审计上下文；测试/后台任务退化为从 ToolCtx 拼一个。"""
    ctx = current_context()
    if ctx is not None:
        return AuditContext(
            audit_id=ctx.audit_id,
            request_id=ctx.request_id,
            tenant_id=ctx.tenant_id,
            actor_id=ctx.actor_id,
            session_id=ctx.session_id,
            confirmation_id=fields.confirmation_id or ctx.confirmation_id,
            conversation_id=fields.conversation_id or ctx.conversation_id,
        )
    actor_id = str(fields.user_id) if fields.user_id is not None else None
    return AuditContext(
        audit_id=fields.audit_id or str(uuid4()),
        request_id=None,
        tenant_id="default",
        actor_id=actor_id,
        session_id=None,
        confirmation_id=fields.confirmation_id,
        conversation_id=fields.conversation_id,
    )


async def check_tool_confirmation(
    tool_name: str,
    arguments: Any,
    ctx: Any = None,
    *,
    tool_call_id: str | None = None,
) -> str | None:
    """工具执行前的确认闸门。

    返回已消费的 ``confirmation_id``；不需要确认返回 None。
    需要确认但无票据 → ``ConfirmationRequired``；票据无效/过期/不匹配 → ``ConfirmationInvalid``。
    """
    if not confirmation.requires_confirmation(tool_name):
        return None

    fields = _extract_ctx(ctx)
    context = _effective_context(fields)
    raw = raw_tool_input(arguments)
    canonical_input = canonicalize_json(raw)
    digested_action = action_digest(tool_name, raw)
    confirmation_id = context.confirmation_id

    if not confirmation_id:
        error = await run_in_threadpool(
            partial(
                confirmation.request_confirmation,
                tool_name,
                tool_call_id or str(uuid4()),
                canonical_input,
                digested_action,
                context=context,
            )
        )
        raise error

    try:
        await run_in_threadpool(
            partial(
                confirmation.consume_approval,
                confirmation_id,
                tool_name,
                digested_action,
                context=context,
            )
        )
    except ConfirmationInvalid:
        raise
    except Exception as exc:  # noqa: BLE001  确认存储不可用：安全失败（不执行危险操作）
        logger.warning("consume confirmation failed", exc_info=True)
        raise confirmation.invalid_error("确认票据校验失败，请重新发起请求") from exc
    return confirmation_id


# ---------------------------------------------------------------------------
# TOOL_CALL_* 事件（审计失败不影响聊天）
# ---------------------------------------------------------------------------


async def record_tool_requested(
    tool_name: str,
    arguments: Any,
    audit_id: str | None = None,
    user_id: int | str | None = None,
    *,
    ctx: Any = None,
    tool_call_id: str | None = None,
    conversation_id: str | None = None,
) -> str | None:
    """记录 ``TOOL_CALL_REQUESTED``，返回 ``tool_call_id``（即使写库失败也返回）。"""
    fields = _extract_ctx(ctx)
    tool_call_id = tool_call_id or str(uuid4())
    try:
        return await run_in_threadpool(
            partial(
                recorder.record_tool_requested,
                tool_name,
                arguments,
                audit_id or fields.audit_id,
                user_id if user_id is not None else fields.user_id,
                tool_call_id=tool_call_id,
                conversation_id=conversation_id or fields.conversation_id,
            )
        )
    except Exception:  # noqa: BLE001
        logger.warning("failed to record TOOL_CALL_REQUESTED for %s", tool_name, exc_info=True)
        return tool_call_id


async def record_tool_started(
    tool_name: str,
    tool_call_id: str,
    arguments: Any = None,
    *,
    ctx: Any = None,
    audit_id: str | None = None,
    user_id: int | str | None = None,
    confirmation_id: str | None = None,
    conversation_id: str | None = None,
) -> None:
    """记录 ``TOOL_CALL_STARTED``。"""
    fields = _extract_ctx(ctx)
    try:
        await run_in_threadpool(
            partial(
                recorder.record_tool_started,
                tool_name,
                tool_call_id,
                arguments,
                audit_id=audit_id or fields.audit_id,
                user_id=user_id if user_id is not None else fields.user_id,
                confirmation_id=confirmation_id or fields.confirmation_id,
                conversation_id=conversation_id or fields.conversation_id,
            )
        )
    except Exception:  # noqa: BLE001
        logger.warning("failed to record TOOL_CALL_STARTED for %s", tool_name, exc_info=True)


async def record_tool_succeeded(
    tool_name: str,
    tool_call_id: str,
    output: str | None,
    arguments: Any = None,
    *,
    ctx: Any = None,
    audit_id: str | None = None,
    user_id: int | str | None = None,
    confirmation_id: str | None = None,
    conversation_id: str | None = None,
) -> None:
    """记录 ``TOOL_CALL_SUCCEEDED``（输出 SHA-256 + 可选原文）。"""
    fields = _extract_ctx(ctx)
    try:
        await run_in_threadpool(
            partial(
                recorder.record_tool_succeeded,
                tool_name,
                tool_call_id,
                output,
                arguments,
                audit_id=audit_id or fields.audit_id,
                user_id=user_id if user_id is not None else fields.user_id,
                confirmation_id=confirmation_id or fields.confirmation_id,
                conversation_id=conversation_id or fields.conversation_id,
            )
        )
    except Exception:  # noqa: BLE001
        logger.warning("failed to record TOOL_CALL_SUCCEEDED for %s", tool_name, exc_info=True)


async def record_tool_failed(
    tool_name: str,
    tool_call_id: str,
    error: BaseException | str | None,
    arguments: Any = None,
    *,
    ctx: Any = None,
    audit_id: str | None = None,
    user_id: int | str | None = None,
    confirmation_id: str | None = None,
    conversation_id: str | None = None,
) -> None:
    """记录 ``TOOL_CALL_FAILED``。"""
    fields = _extract_ctx(ctx)
    try:
        await run_in_threadpool(
            partial(
                recorder.record_tool_failed,
                tool_name,
                tool_call_id,
                error,
                arguments,
                audit_id=audit_id or fields.audit_id,
                user_id=user_id if user_id is not None else fields.user_id,
                confirmation_id=confirmation_id or fields.confirmation_id,
                conversation_id=conversation_id or fields.conversation_id,
            )
        )
    except Exception:  # noqa: BLE001
        logger.warning("failed to record TOOL_CALL_FAILED for %s", tool_name, exc_info=True)


# ---------------------------------------------------------------------------
# AGENT_* 事件（可选；chat-core 未实现 AuditAdvisor 等价逻辑时可直接用）
# ---------------------------------------------------------------------------


async def record_agent_started(
    agent_name: str = "chatClient",
    *,
    model_name: str | None = None,
    prompt: str | None = None,
    audit_id: str | None = None,
) -> None:
    try:
        await run_in_threadpool(
            partial(
                recorder.record_agent_started,
                agent_name,
                model_name=model_name,
                prompt=prompt,
                audit_id=audit_id,
            )
        )
    except Exception:  # noqa: BLE001
        logger.warning("failed to record AGENT_STARTED", exc_info=True)


async def record_agent_completed(
    agent_name: str = "chatClient",
    *,
    model_name: str | None = None,
    output: str | None = None,
    audit_id: str | None = None,
) -> None:
    try:
        await run_in_threadpool(
            partial(
                recorder.record_agent_completed,
                agent_name,
                model_name=model_name,
                output=output,
                audit_id=audit_id,
            )
        )
    except Exception:  # noqa: BLE001
        logger.warning("failed to record AGENT_COMPLETED", exc_info=True)


async def record_agent_failed(
    agent_name: str = "chatClient",
    *,
    model_name: str | None = None,
    error: BaseException | str | None = None,
    audit_id: str | None = None,
) -> None:
    try:
        await run_in_threadpool(
            partial(
                recorder.record_agent_failed,
                agent_name,
                model_name=model_name,
                error=error,
                audit_id=audit_id,
            )
        )
    except Exception:  # noqa: BLE001
        logger.warning("failed to record AGENT_FAILED", exc_info=True)


async def record_agent_waiting_confirmation(
    tool_name: str,
    confirmation_id: str | None,
    *,
    agent_name: str = "chatClient",
    model_name: str | None = None,
    audit_id: str | None = None,
) -> None:
    try:
        await run_in_threadpool(
            partial(
                recorder.record_agent_waiting_confirmation,
                tool_name,
                confirmation_id,
                agent_name=agent_name,
                model_name=model_name,
                audit_id=audit_id,
            )
        )
    except Exception:  # noqa: BLE001
        logger.warning("failed to record AGENT_WAITING_CONFIRMATION", exc_info=True)


__all__ = [
    "check_tool_confirmation",
    "record_tool_requested",
    "record_tool_started",
    "record_tool_succeeded",
    "record_tool_failed",
    "record_agent_started",
    "record_agent_completed",
    "record_agent_failed",
    "record_agent_waiting_confirmation",
]
