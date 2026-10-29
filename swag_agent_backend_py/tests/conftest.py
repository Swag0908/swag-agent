"""pytest 公共 fixture：SQLite 内存库 + 最小测试 app。

原则：单元测试不连真实 MySQL/PG；集成测试（需要真实库）由 Lead 手动执行。
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.errors import install_error_handlers
import app.db.models  # noqa: F401  (注册所有表到 Base.metadata)
from app.db.base import Base, get_db


@pytest.fixture()
def sqlite_session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    db = TestingSession()
    try:
        yield db
    finally:
        db.close()


class _UserMiddleware:
    """测试用：从 X-Test-User-Id / X-Test-Role 注入 request.state，替代鉴权中间件。"""

    def __init__(self, app):  # noqa: ANN001
        self.app = app

    async def __call__(self, scope, receive, send):  # noqa: ANN001
        if scope["type"] == "http":
            headers = dict(scope.get("headers") or [])
            state = scope.setdefault("state", {})
            user_id = headers.get(b"x-test-user-id", b"1")
            role = headers.get(b"x-test-role", b"USER")
            state["user_id"] = int(user_id) if user_id else None
            state["role"] = role.decode()
        await self.app(scope, receive, send)


@pytest.fixture()
def make_test_app():
    def _make(router, db: Session) -> FastAPI:  # noqa: ANN001
        app = FastAPI()
        install_error_handlers(app)
        app.add_middleware(_UserMiddleware)
        app.include_router(router)
        app.dependency_overrides[get_db] = lambda: db
        return app

    return _make


@pytest.fixture()
def client_factory(make_test_app):
    def _factory(router, db: Session) -> TestClient:
        return TestClient(make_test_app(router, db))

    return _factory
