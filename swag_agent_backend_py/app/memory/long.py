"""长期语义记忆：pgvector `public.vector_store`（768 维 / cosine / HNSW）。

等价 Java `VectorStoreChatMemoryAdvisor`（topK=5）+ `PgVectorStore`：
- 写入：每轮 user/assistant 消息各写一条文档，metadata 固定
  `{"conversationId": <memoryKey>, "messageType": "USER"|"ASSISTANT"}`；
  `id` 是随机 UUID，与 `chat_message.id` **没有映射**（Java 也是）。
- 召回：按 `conversationId` 过滤，`ORDER BY embedding <=> query LIMIT top_k`。
- 降级：Ollama / PG 任何不可用 → 返回空列表并只记日志，聊天主链路不失败。

嵌入模型固定本地 Ollama `nomic-embed-text`（768 维）——换模型等于语义与维度全变，
必须整表重建（见 `docs/python-migration/02-data-model.md` §6.6）。
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

import httpx
from sqlalchemy import text

from app.config import settings
from app.db.pg import pg_connection

logger = logging.getLogger(__name__)

TOP_K = 5
_TIMEOUT = httpx.Timeout(10.0, connect=3.0)

_INSERT_SQL = text(
    "INSERT INTO public.vector_store (id, content, metadata, embedding) "
    "VALUES (:id, :content, CAST(:metadata AS json), CAST(:embedding AS vector))"
)
_SEARCH_SQL = text(
    "SELECT content FROM public.vector_store "
    "WHERE metadata->>'conversationId' = :conversation_id "
    "ORDER BY embedding <=> CAST(:embedding AS vector) "
    "LIMIT :top_k"
)
_DELETE_SQL = text("DELETE FROM public.vector_store WHERE metadata->>'conversationId' = :conversation_id")


def vector_literal(vector: list[float]) -> str:
    """把 float 列表转成 pgvector 文本字面量 `[0.1,0.2,...]`（避免类型适配器依赖）。"""
    return "[" + ",".join(f"{value:.8f}" for value in vector) + "]"


def embed_sync(content: str) -> list[float] | None:
    """同步嵌入（供 prompt 组装等同步路径使用）；失败返回 None。"""
    if not content or not content.strip():
        return None
    try:
        response = httpx.post(
            f"{settings.ollama_base_url.rstrip('/')}/api/embeddings",
            json={"model": settings.ollama_embed_model, "prompt": content},
            timeout=_TIMEOUT,
        )
        response.raise_for_status()
        vector = response.json().get("embedding")
        if isinstance(vector, list) and vector:
            return [float(item) for item in vector]
    except Exception as exc:  # noqa: BLE001 - 嵌入失败只降级
        logger.warning("ollama embed failed: %s", exc)
    return None


async def embed_async(content: str) -> list[float] | None:
    """异步嵌入（供工具/异步链路使用）；失败返回 None。"""
    if not content or not content.strip():
        return None
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.post(
                f"{settings.ollama_base_url.rstrip('/')}/api/embeddings",
                json={"model": settings.ollama_embed_model, "prompt": content},
            )
            response.raise_for_status()
            vector = response.json().get("embedding")
            if isinstance(vector, list) and vector:
                return [float(item) for item in vector]
    except Exception as exc:  # noqa: BLE001
        logger.warning("ollama embed (async) failed: %s", exc)
    return None


def _metadata(conversation_key: str, message_type: str) -> str:
    return json.dumps(
        {"conversationId": str(conversation_key), "messageType": message_type.upper()},
        ensure_ascii=False,
    )


def store_message_vector(memory_key: str | int, content: str, message_type: str) -> bool:
    """写一条对话长期记忆（user/assistant 各一条）；返回是否写入成功。"""
    if not content or not content.strip():
        return False
    vector = embed_sync(content)
    if vector is None:
        return False
    try:
        with pg_connection() as conn:
            conn.execute(
                _INSERT_SQL,
                {
                    "id": str(uuid.uuid4()),
                    "content": content,
                    "metadata": _metadata(str(memory_key), message_type),
                    "embedding": vector_literal(vector),
                },
            )
            conn.commit()
        return True
    except Exception as exc:  # noqa: BLE001 - PG 不可用降级
        logger.warning("写入对话长期记忆失败（已降级）：%s", exc)
        return False


async def astore_message_vector(memory_key: str | int, content: str, message_type: str) -> bool:
    """异步版本；供需要避免阻塞事件循环的链路。"""
    if not content or not content.strip():
        return False
    vector = await embed_async(content)
    if vector is None:
        return False
    try:
        with pg_connection() as conn:
            conn.execute(
                _INSERT_SQL,
                {
                    "id": str(uuid.uuid4()),
                    "content": content,
                    "metadata": _metadata(str(memory_key), message_type),
                    "embedding": vector_literal(vector),
                },
            )
            conn.commit()
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("异步写入对话长期记忆失败（已降级）：%s", exc)
        return False


def store_turn_vectors(memory_key: str | int, user_text: str, assistant_text: str) -> None:
    """一轮问答写两条向量（等价 advisor 的 after 阶段）。尽力而为，不抛。"""
    for content, message_type in ((user_text, "USER"), (assistant_text, "ASSISTANT")):
        try:
            store_message_vector(memory_key, content, message_type)
        except Exception:  # noqa: BLE001
            logger.warning("写入对话向量失败（%s）", message_type, exc_info=True)


def recall_semantic(
    db: Any,  # noqa: ARG001 - 契约签名带 db（本实现直连 PG，不依赖 MySQL session）
    conversation_id: int | str | None,
    query: str,
    top_k: int = TOP_K,
) -> list[str]:
    """按语义召回该会话的历史片段；任何异常返回空列表。"""
    if conversation_id is None or not query or not query.strip():
        return []
    vector = embed_sync(query)
    if vector is None:
        return []
    try:
        with pg_connection() as conn:
            rows = conn.execute(
                _SEARCH_SQL,
                {
                    "conversation_id": str(conversation_id),
                    "embedding": vector_literal(vector),
                    "top_k": max(1, int(top_k)),
                },
            ).fetchall()
        return [row[0] for row in rows if isinstance(row[0], str) and row[0].strip()]
    except Exception as exc:  # noqa: BLE001 - PG 不可用降级
        logger.warning("对话向量召回失败（已降级）：%s", exc)
        return []


def delete_conversation_vectors(conversation_id: int | str | None) -> None:
    """按 metadata.conversationId 删除该会话全部向量文档（删会话/重建记忆前调用）。"""
    if conversation_id is None:
        return
    try:
        with pg_connection() as conn:
            conn.execute(_DELETE_SQL, {"conversation_id": str(conversation_id)})
            conn.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("删除对话向量失败（已降级）：%s", exc)


def rebuild_conversation_vectors(memory_key: str | int, messages: list[dict[str, str]]) -> None:
    """清空并重放该会话的向量副本（删消息/重建记忆时用）。"""
    delete_conversation_vectors(memory_key)
    for message in messages:
        role = message.get("role")
        content = message.get("content")
        if not content:
            continue
        message_type = "USER" if role == "user" else "ASSISTANT"
        store_message_vector(memory_key, content, message_type)


__all__ = [
    "TOP_K",
    "vector_literal",
    "embed_sync",
    "embed_async",
    "store_message_vector",
    "astore_message_vector",
    "store_turn_vectors",
    "recall_semantic",
    "delete_conversation_vectors",
    "rebuild_conversation_vectors",
]
