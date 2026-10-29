"""DeepSeek 客户端与模型路由。

对齐 Java：
- `SelectModelTool.java:19-29`：model=1 → flash、2 → pro，其它 400 `model must be 1 or 2`；
- `ChatClientConfig.java:87-88/103-104`：只有 model 是显式 options，其余走默认；
- `base_url=https://api.deepseek.com`（OpenAI 兼容），key 只从环境变量/`.env` 读。

与 Java 的差异（有意）：`thinking` 在 Java 侧无法显式开关（`DeepSeekChatOptions` 无该字段），
这里通过 `extra_body={"thinking": {"type": ...}}` 提供配置项，默认 None＝不传、跟随服务端默认。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from openai import AsyncOpenAI

from app.agent.tools import load_all
from app.agent.tools.registry import openai_tools
from app.config import settings
from app.core.errors import BadRequest

logger = logging.getLogger(__name__)

_FLASH = "deepseek-v4-flash"
_PRO = "deepseek-v4-pro"

_client: AsyncOpenAI | None = None


def model_for(model_id: int) -> str:
    """modelId → DeepSeek 模型名；非法值抛 400（文案与 Java 逐字一致）。"""
    if model_id == 1:
        return settings.deepseek_model_flash or _FLASH
    if model_id == 2:
        return settings.deepseek_model_pro or _PRO
    raise BadRequest("model must be 1 or 2")


def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            base_url=settings.deepseek_base_url,
            api_key=settings.deepseek_api_key,
            timeout=settings.llm_timeout_s,
            max_retries=0,  # 流式重试会重复吐字，交给上层处理
        )
    return _client


def reset_client() -> None:
    """测试用：丢弃已缓存客户端。"""
    global _client
    _client = None


def _request_kwargs(messages: list[dict[str, Any]], model: str) -> dict[str, Any]:
    load_all()
    tools = openai_tools()
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": True,
    }
    if tools:
        kwargs["tools"] = tools
    if settings.thinking_mode:
        kwargs["extra_body"] = {"thinking": {"type": settings.thinking_mode}}
    return kwargs


async def open_stream(messages: list[dict[str, Any]], model: str) -> AsyncIterator[Any]:
    """默认的流式来源：把 openai SDK 的 chunk 原样吐出来。

    bridge 只依赖 chunk 的形状（`choices[0].delta.{content,tool_calls}`），
    所以测试可以注入同形状的 fake 异步生成器，完全不触网。
    """
    load_all()
    stream = await get_client().chat.completions.create(**_request_kwargs(messages, model))
    async for chunk in stream:
        yield chunk


__all__ = ["model_for", "get_client", "reset_client", "open_stream"]
