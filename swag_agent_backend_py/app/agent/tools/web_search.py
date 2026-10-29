"""联网搜索工具：等价 Java `WebSearchTools#webSearch`（`J/tool/WebSearchTools.java:28-63`）。

行为对齐：
- 未配置 key → 返回固定中文提示（模型转述给用户），不抛异常；
- 请求 Tavily `/search`（`search_depth=basic`、`max_results=5`）；
- 输出格式逐字对齐 Java：`回答：…` + `• 标题 / 链接 / 摘要`；
- 任何异常 → `搜索失败：<message>`，不炸流。
"""

from __future__ import annotations

import logging

import httpx

from app.agent.tools.registry import ToolCtx, tool
from app.config import settings

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(20.0, connect=5.0)


@tool(
    "webSearch",
    "联网搜索互联网上的最新、实时或事实性信息，返回结果摘要与来源链接。"
    "当用户的问题需要上网查询、涉及时效性内容（新闻/天气/最新数据/最新政策），"
    "或模型对答案不确定时，先调用本工具再基于结果回答。",
    {
        "type": "object",
        "properties": {"query": {"type": "string", "description": "搜索关键词或完整问题"}},
        "required": ["query"],
    },
    needs_user=False,
    side_effect="external",
)
async def web_search(query: str, ctx: ToolCtx) -> str:  # noqa: ARG001 - 契约要求签名带 ctx
    if not settings.tavily_api_key:
        # 文案沿用 Java（模型/用户看到的是同一句提示），实际配置项名称为 TAVILY_API_KEY。
        return "未配置 Tavily API Key（web.search.tavily.api-key），无法联网搜索。"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.post(
                settings.tavily_url,
                json={
                    "api_key": settings.tavily_api_key,
                    "query": query,
                    "search_depth": "basic",
                    "max_results": 5,
                },
            )
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:  # noqa: BLE001 - 搜索失败交给模型转述
        logger.warning("tavily search failed: %s", exc)
        return f"搜索失败：{exc}"

    parts: list[str] = []
    answer = (payload or {}).get("answer")
    if isinstance(answer, str) and answer.strip():
        parts.append(f"回答：{answer}\n\n")
    for item in (payload or {}).get("results") or []:
        title = item.get("title") or ""
        url = item.get("url") or ""
        content = item.get("content") or ""
        parts.append(f"• {title}\n  链接：{url}\n  摘要：{content}\n\n")
    result = "".join(parts).strip()
    return result or "搜索无结果。"


__all__ = ["web_search"]
