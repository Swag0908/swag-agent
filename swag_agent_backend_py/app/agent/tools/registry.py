"""Agent 工具注册表（契约见 CONTRACTS.md §1）。

设计要点：
- 工具 handler 统一 `async def xxx(..., ctx: ToolCtx) -> str`；业务失败**返回中文文案**，不抛异常
  （与 Java `@Tool` 方法一致：模型要能读到失败原因并转述给用户）。
- `parameters` 直接就是 OpenAI `function.parameters`；**required 与 Java 保持一致（全部必填）**，
  因为 Spring AI 的 `@ToolParam.required()` 默认 true（字节码核实），"可为空"的参数模型会传 ""。
- 只在此处维护一份注册表，`app/agent/tools/__init__.py` 负责 import 各来源模块触发注册。
"""

from __future__ import annotations

import inspect
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from app.core.errors import ConfirmationRequired

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolCtx:
    """一次工具调用可用的请求上下文；不用全局变量，天然按请求隔离。"""

    user_id: int | None
    audit_id: str | None = None
    conversation_id: int | None = None
    confirmation_id: str | None = None


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[..., Awaitable[str]]
    needs_user: bool = True
    side_effect: str = "read"  # none/read/write/delete/external


REGISTRY: dict[str, ToolSpec] = {}


def tool(
    name: str,
    description: str,
    parameters: dict[str, Any],
    *,
    needs_user: bool = True,
    side_effect: str = "read",
) -> Callable[[Callable[..., Awaitable[str]]], Callable[..., Awaitable[str]]]:
    """注册一个工具。重复注册时后者覆盖（并行开发期宽松，日志留痕）。"""

    def decorator(handler: Callable[..., Awaitable[str]]) -> Callable[..., Awaitable[str]]:
        if name in REGISTRY:
            logger.warning("tool %s 重复注册，将被覆盖", name)
        REGISTRY[name] = ToolSpec(
            name=name,
            description=description,
            parameters=dict(parameters),
            handler=handler,
            needs_user=needs_user,
            side_effect=side_effect,
        )
        setattr(handler, "__tool_name__", name)
        return handler

    return decorator


def get_tool(name: str) -> ToolSpec | None:
    return REGISTRY.get(name)


def openai_tools() -> list[dict[str, Any]]:
    """转换成 OpenAI/DeepSeek `tools` 参数。"""
    return [
        {
            "type": "function",
            "function": {
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.parameters,
            },
        }
        for spec in REGISTRY.values()
    ]


def _missing_required(spec: ToolSpec, args: dict[str, Any]) -> list[str]:
    """按 signature 判断必填参数是否齐全（模型可能漏字段）。

    只看没有默认值的位置/关键字参数；`ctx` 由 dispatch 注入，不算必填。
    """
    try:
        params = inspect.signature(spec.handler).parameters
    except (TypeError, ValueError):  # pragma: no cover - 内置 handler 才会有
        return []
    missing: list[str] = []
    for name, param in params.items():
        if name in {"ctx", "self"}:
            continue
        if param.kind not in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY):
            continue
        if param.default is not inspect.Parameter.empty:
            continue
        if name not in args:
            missing.append(name)
    return missing


def _accepts_ctx(spec: ToolSpec) -> bool:
    try:
        return "ctx" in inspect.signature(spec.handler).parameters
    except (TypeError, ValueError):  # pragma: no cover
        return True


async def dispatch(name: str, arguments: str | dict[str, Any], ctx: ToolCtx) -> tuple[bool, str]:
    """执行一个工具调用。

    Returns:
        (ok, text)：`ok=False` 表示**工具层面失败**（未知工具/参数非法/抛异常），
        bridge 会把这次调用标记为 `FAILED`；业务失败由 handler 自己返回中文文案，
    此时 `ok=True`（与 Java 一致：业务失败不产生 FAILED 事件）。
    """
    spec = REGISTRY.get(name)
    if spec is None:
        available = "、".join(REGISTRY) or "（当前没有可用工具）"
        return False, f"未知工具：{name}，可用工具：{available}"

    if isinstance(arguments, str):
        raw = arguments.strip()
        if not raw:
            args: dict[str, Any] = {}
        else:
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                return False, f"工具参数不是合法 JSON：{raw[:200]}"
            if not isinstance(parsed, dict):
                return False, "工具参数必须是 JSON 对象"
            args = parsed
    elif isinstance(arguments, dict):
        args = dict(arguments)
    else:  # pragma: no cover - 正常链路不会到这
        return False, "工具参数格式不支持"

    if spec.needs_user and ctx.user_id is None:
        return False, "未登录，无法执行该操作。"

    missing = _missing_required(spec, args)
    if missing:
        return False, f"工具参数不正确，缺少：{'、'.join(missing)}"

    kwargs = {key: value for key, value in args.items()}
    if _accepts_ctx(spec):
        kwargs["ctx"] = ctx
    try:
        result = await spec.handler(**kwargs)
    except ConfirmationRequired:
        # 危险工具需要用户确认：由 API 层决定转 409 还是发 error 事件，不能吞掉。
        raise
    except Exception as exc:  # noqa: BLE001 - 工具失败不能炸流
        logger.warning("tool %s 执行失败: %s", name, exc, exc_info=True)
        message = str(exc).strip() or exc.__class__.__name__
        return False, f"工具执行失败：{message}"
    return True, "" if result is None else str(result)


__all__ = [
    "ToolCtx",
    "ToolSpec",
    "REGISTRY",
    "tool",
    "get_tool",
    "openai_tools",
    "dispatch",
]
