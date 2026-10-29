"""记忆工具：`rememberUserMemory`（等价 Java `UserMemoryTools`
`J/memory/UserMemoryTools.java:34-48`）。

- 工具文案、参数 schema 与 Java 逐字一致；
- handler 是 async，但 MySQL 写入与 PG 写入都是同步驱动 → 用线程池执行，避免阻塞 SSE 事件循环；
- 业务失败返回中文文案（模型可转述），不抛异常。
"""

from __future__ import annotations

import logging

from starlette.concurrency import run_in_threadpool

from app.agent.tools.registry import ToolCtx, tool
from app.db.base import SessionLocal
from app.memory import user_memory

logger = logging.getLogger(__name__)

_DISABLED_TEXT = "长期记忆功能当前处于关闭状态，无法保存。请告知用户在「我的记忆」设置里开启后再试。"


def _remember_sync(user_id: int, content: str) -> tuple[str, str, int]:
    """写 MySQL 本体，返回 (状态文案前缀, 规范化内容, memory_id)。

    只做本体写入；向量副本在异步侧尽力补写（Java 也是「本体成功即成功」）。
    """
    from app.core.timeutil import now, truncate_to_second  # noqa: PLC0415
    from app.db.models import ChatUserMemory  # noqa: PLC0415

    normalized = user_memory.normalize_content(content)
    if not normalized:
        return "无法保存：记忆内容不能为空", "", 0
    with SessionLocal() as db:
        if not user_memory.is_enabled(db, user_id):
            return _DISABLED_TEXT, "", 0
        stamp = truncate_to_second(now())
        memory = ChatUserMemory(
            user_id=int(user_id),
            content=normalized,
            created_at=stamp,
            updated_at=stamp,
        )
        db.add(memory)
        db.commit()
        db.refresh(memory)
        return "已记住：", normalized, int(memory.id)


def _write_vector_sync(memory_id: int, user_id: int, content: str) -> None:
    from sqlalchemy import text  # noqa: PLC0415

    from app.db.pg import pg_connection  # noqa: PLC0415
    from app.memory import long as long_memory  # noqa: PLC0415

    try:
        embedding = long_memory.embed_sync(content)
        if embedding is None:
            return
        with pg_connection() as conn:
            conn.execute(
                text(
                    "INSERT INTO public.chat_user_memory_vec (memory_id, user_id, content, embedding) "
                    "VALUES (:memory_id, :user_id, :content, CAST(:embedding AS vector)) "
                    "ON CONFLICT (memory_id) DO UPDATE "
                    "SET content = EXCLUDED.content, embedding = EXCLUDED.embedding"
                ),
                {
                    "memory_id": memory_id,
                    "user_id": user_id,
                    "content": content,
                    "embedding": long_memory.vector_literal(embedding),
                },
            )
            conn.commit()
    except Exception as exc:  # noqa: BLE001 - 向量失败只降级
        logger.warning("用户 %s 记忆向量写入失败（已降级）：%s", user_id, exc)


@tool(
    "rememberUserMemory",
    (
        "当用户明确要求你「长期记住」某个偏好、身份或事实时调用，\n"
        "例如“记住我每周五下午开会”“以后都用表格回复我”“我的团队叫星火”。\n"
        "只保存用户主动要求记住的精炼一句话事实，不要自动归纳或保存一次性任务。\n"
        "记忆会跨会话生效，并可在「我的记忆」里查看或删除。"
    ),
    {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "要长期记住的一句精炼事实/偏好，写成陈述句，例如「用户偏好用 Markdown 表格回复」",
            }
        },
        "required": ["content"],
    },
    needs_user=True,
    side_effect="write",
)
async def remember_user_memory(content: str, ctx: ToolCtx) -> str:
    if ctx.user_id is None:
        return "未登录，无法保存记忆"
    user_id = int(ctx.user_id)
    prefix, saved, memory_id = await run_in_threadpool(_remember_sync, user_id, content)
    if memory_id:
        await run_in_threadpool(_write_vector_sync, memory_id, user_id, saved)
    return prefix + saved if saved else prefix


__all__ = ["remember_user_memory"]
