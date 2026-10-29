"""对外路由契约回归：65 个端点一个都不能少，路径/方法/静态段顺序要正确。

该测试只 import app.main 做路由表比对，不连接数据库。
"""

from __future__ import annotations

import re

from app.main import app

# (method, path)，与 docs/python-migration/01-api-contract.md §2 的 65 个端点一一对应
EXPECTED: list[tuple[str, str]] = [
    ("POST", "/auth/register"),
    ("POST", "/auth/login"),
    ("POST", "/auth/logout"),
    ("GET", "/auth/me"),
    ("GET", "/auth/zipkin-access"),
    ("GET", "/auth/admin/register-settings"),
    ("PUT", "/auth/admin/register-settings"),
    ("POST", "/auth/admin/register-settings/regenerate"),
    ("GET", "/auth/admin/users"),
    ("PUT", "/auth/admin/users/{id}/role"),
    ("GET", "/auth/admin/skills"),
    ("PUT", "/auth/admin/skills/{name}"),
    ("POST", "/auth/admin/skills/refresh"),
    ("POST", "/auth/admin/skills/install"),
    ("DELETE", "/auth/admin/skills/{name}"),
    ("GET", "/chat/conversations"),
    ("POST", "/chat/conversations"),
    ("GET", "/chat/conversations/{id}/messages"),
    ("DELETE", "/chat/conversations/{id}"),
    ("DELETE", "/chat/conversations"),
    ("PUT", "/chat/conversations/{id}/favorite"),
    ("PUT", "/chat/conversations/favorites/order"),
    ("DELETE", "/chat/conversations/{id}/messages/{messageId}"),
    ("GET", "/chat/user-memory"),
    ("PUT", "/chat/user-memory/settings"),
    ("DELETE", "/chat/user-memory/{id}"),
    ("GET", "/todo/today"),
    ("POST", "/todo"),
    ("GET", "/todo"),
    ("PATCH", "/todo/{id}"),
    ("PATCH", "/todo/{id}/complete"),
    ("PATCH", "/todo/{id}/defer"),
    ("DELETE", "/todo/{id}"),
    ("GET", "/todo/stats/daily"),
    ("GET", "/bookmarks"),
    ("POST", "/bookmarks/folders"),
    ("PATCH", "/bookmarks/folders/{id}"),
    ("DELETE", "/bookmarks/folders/{id}"),
    ("POST", "/bookmarks"),
    ("PATCH", "/bookmarks/{id}"),
    ("GET", "/bookmarks/{id}/icon"),
    ("DELETE", "/bookmarks/{id}"),
    ("GET", "/notes/tree"),
    ("GET", "/notes/file"),
    ("POST", "/notes/file"),
    ("PUT", "/notes/file"),
    ("GET", "/notes/import/config"),
    ("POST", "/notes/import/local"),
    ("POST", "/notes/import/upload"),
    ("GET", "/notes/resource"),
    ("DELETE", "/notes/file"),
    ("POST", "/notes/dir"),
    ("DELETE", "/notes/dir"),
    ("POST", "/notes/rename"),
    ("GET", "/notes/trash"),
    ("POST", "/notes/trash/{id}/restore"),
    ("DELETE", "/notes/trash/{id}"),
    ("DELETE", "/notes/trash"),
    ("GET", "/audit/events/{auditId}"),
    ("GET", "/audit/chains"),
    ("GET", "/audit/confirmations/{confirmationId}"),
    ("POST", "/audit/confirmations/{confirmationId}/decision"),
    ("GET", "/test/chat"),
    ("GET", "/test/chat/stream"),
    ("GET", "/test/chat/stream/events"),
]

_EXTRA_ALLOWED = {
    ("GET", "/actuator/health"),
    ("GET", "/actuator/info"),
}

_PARAM = re.compile(r"\{[^}]+\}")


def _norm(path: str) -> str:
    return _PARAM.sub("{}", path)


def _routes() -> list[tuple[str, str]]:
    # FastAPI 0.162 的 app.routes 是惰性 _IncludedRouter（没有 path/methods），
    # 因此用 OpenAPI 路由表做契约比对。
    result: list[tuple[str, str]] = []
    for path, operations in app.openapi().get("paths", {}).items():
        for method in operations:
            if method.upper() in {"HEAD", "OPTIONS"}:
                continue
            result.append((method.upper(), path))
    return result


def test_all_contract_routes_exist():
    actual = {(m, _norm(p)) for m, p in _routes()}
    missing = [(m, p) for m, p in EXPECTED if (m, _norm(p)) not in actual]
    assert not missing, f"缺少端点: {missing}"


def test_no_unexpected_business_routes():
    actual = {(m, _norm(p)) for m, p in _routes()}
    expected = {(m, _norm(p)) for m, p in EXPECTED}
    extra = sorted(actual - expected - {(_norm(m), _norm(p)) for m, p in _EXTRA_ALLOWED})
    assert not extra, f"出现契约外端点: {extra}"


def test_static_routes_declared_before_dynamic():
    """/chat/conversations/favorites/order 必须早于 /chat/conversations/{id}。"""
    from app.api import conversations

    paths = [route.path for route in conversations.router.routes]
    static = paths.index("/chat/conversations/favorites/order")
    dynamic = paths.index("/chat/conversations/{conversation_id}")
    assert static < dynamic
