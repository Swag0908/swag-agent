"""PostgreSQL / pgvector 连接。

业务上 MySQL 是事实来源，PG 只承载两份向量副本：
- public.vector_store（Spring AI 自动建，metadata json，768 维，hnsw/cosine）
- public.chat_user_memory_vec（业务表，无索引，768 维）
PG 不可用时聊天主链路必须降级，不能抛到流外。
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine

from app.config import settings

logger = logging.getLogger(__name__)

_pg_engine: Engine | None = None


def _create_engine() -> Engine:
    from pgvector.psycopg import register_vector

    engine = create_engine(
        settings.pg_url,
        pool_pre_ping=True,
        pool_recycle=3600,
        pool_size=5,
        max_overflow=10,
        future=True,
    )

    @event.listens_for(engine, "connect")
    def _register_vector(dbapi_connection, _connection_record):  # noqa: ANN001
        try:
            register_vector(dbapi_connection)
        except Exception:  # noqa: BLE001
            logger.warning("pgvector register_vector failed; vector operations will degrade", exc_info=True)

    return engine


def get_pg_engine() -> Engine:
    global _pg_engine
    if _pg_engine is None:
        _pg_engine = _create_engine()
    return _pg_engine


@contextmanager
def pg_connection() -> Iterator:
    conn = get_pg_engine().connect()
    try:
        yield conn
    finally:
        conn.close()
