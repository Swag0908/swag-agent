"""待办模块单测：日期宽容解析、统计口径、rollover、REST 语义、工具 schema。

只用 SQLite 内存库（见 tests/conftest.py），不连真实 MySQL。
"""

from __future__ import annotations

from contextlib import nullcontext
from datetime import date, timedelta

import pytest

from app.core import timeutil
from app.core.errors import BadRequest, NotFound
from app.db.models import TodoDailyStat, TodoDeferLog
from app.domains.todo import repository, rollover, service, views


# ---------------------------------------------------------------------------
# 日期/时间宽容解析
# ---------------------------------------------------------------------------


def test_parse_date_accepts_chinese_words_and_iso():
    today = timeutil.today()
    assert service.parse_date("today", None) == today
    assert service.parse_date("今天", None) == today
    assert service.parse_date("tomorrow", None) == today + timedelta(days=1)
    assert service.parse_date("明天", None) == today + timedelta(days=1)
    assert service.parse_date("2026-08-30", None) == date(2026, 8, 30)
    assert service.parse_date("2026/08/30", None) is None
    assert service.parse_date("  ", date(2026, 1, 1)) == date(2026, 1, 1)


def test_parse_time_accepts_hh_mm_and_seconds():
    assert service.parse_time("09:30").strftime("%H:%M") == "09:30"
    assert service.parse_time("20:30:15").second == 15
    assert service.parse_time("bad") is None
    assert service.parse_time("9:30") is None  # Java LocalTime.parse 要求补零
    assert service.parse_time(None) is None


def test_java_time_text_omits_zero_seconds():
    from datetime import time

    assert views.java_time_text(time(9, 30)) == "09:30"
    assert views.java_time_text(time(9, 30, 5)) == "09:30:05"


# ---------------------------------------------------------------------------
# 统计口径
# ---------------------------------------------------------------------------


def _create(db, user_id=1, title="写周报", due_date=None, due_time=None, source="MANUAL"):
    return service.create(
        db, user_id, title, None, due_date or timeutil.today(), due_time, source
    )


def _stat(db, user_id, day):
    return db.get(TodoDailyStat, {"stat_date": day, "user_id": user_id})


def test_create_trims_title_and_defaults(sqlite_session):
    item = service.create(sqlite_session, 1, "  看电影  ", "  ", None, None, "MANUAL")
    assert item.title == "看电影"
    assert item.note is None
    assert item.due_date == timeutil.today()
    assert item.status == "TODO"
    assert item.source == "MANUAL"
    assert item.id == 1


def test_create_requires_title(sqlite_session):
    with pytest.raises(BadRequest) as exc:
        service.create(sqlite_session, 1, "  ", None, None, None, "MANUAL")
    assert exc.value.message == "待办标题不能为空"


def test_complete_refreshes_statistics(sqlite_session):
    day = timeutil.today()
    item = _create(sqlite_session, due_date=day)
    completed = service.complete(sqlite_session, 1, str(item.id))
    assert completed.status == "DONE"
    assert completed.completed_at is not None
    stat = _stat(sqlite_session, 1, day)
    assert (stat.created_count, stat.completed_count, stat.pending_count) == (1, 1, 0)
    assert float(stat.completion_rate) == 100.0


def test_statistics_completion_rate_is_half_up_two_decimals(sqlite_session):
    day = date(2026, 8, 30)
    # created_count 只统计 created_at 落在当天，不受 due_date 影响
    for title in ("a", "b", "c", "d"):
        _create(sqlite_session, due_date=day, title=title)
    service.complete(sqlite_session, 1, "1")
    service.complete(sqlite_session, 1, "2")
    service.defer(sqlite_session, 1, "3", day + timedelta(days=2))
    stat = service.refresh_daily_stat(sqlite_session, 1, day)
    assert stat.completed_count == 2
    assert stat.pending_count == 1
    assert stat.deferred_count == 1
    assert float(stat.completion_rate) == 50.0


def test_update_refreshes_old_and_new_due_dates(sqlite_session):
    old = timeutil.today()
    new = old + timedelta(days=3)
    item = _create(sqlite_session, due_date=old)
    updated = service.update(sqlite_session, 1, str(item.id), "新标题", "新备注", new, None)
    assert updated.title == "新标题"
    assert updated.due_date == new
    old_stat = _stat(sqlite_session, 1, old)
    new_stat = _stat(sqlite_session, 1, new)
    assert (old_stat.pending_count, new_stat.pending_count) == (0, 1)


def test_update_requires_due_date(sqlite_session):
    item = _create(sqlite_session)
    with pytest.raises(BadRequest) as exc:
        service.update(sqlite_session, 1, str(item.id), "标题", None, None, None)
    assert exc.value.message == "请选择待办日期"


def test_defer_writes_log_and_moves_statistics(sqlite_session):
    old = timeutil.today()
    new = old + timedelta(days=2)
    item = _create(sqlite_session, due_date=old)
    deferred = service.defer(sqlite_session, 1, str(item.id), new)
    assert deferred.due_date == new
    log = sqlite_session.query(TodoDeferLog).one()
    assert (log.item_id, log.from_date, log.to_date) == (item.id, old, new)
    assert _stat(sqlite_session, 1, old).deferred_count == 1
    assert _stat(sqlite_session, 1, new).deferred_count == 0


def test_defer_rejects_past_or_same_date(sqlite_session):
    item = _create(sqlite_session, due_date=timeutil.today())
    with pytest.raises(BadRequest) as exc:
        service.defer(sqlite_session, 1, str(item.id), timeutil.today())
    assert exc.value.message == "延期日期必须晚于当前日期"
    with pytest.raises(BadRequest) as exc2:
        service.defer(sqlite_session, 1, str(item.id), None)
    assert exc2.value.message == "请提供延期目标日期"


def test_delete_refreshes_statistics_and_removes_row(sqlite_session):
    day = timeutil.today()
    item = _create(sqlite_session, due_date=day)
    service.delete(sqlite_session, 1, str(item.id))
    assert repository.find_item(sqlite_session, item.id) is None
    assert _stat(sqlite_session, 1, day).pending_count == 0


# ---------------------------------------------------------------------------
# #id / 标题双寻址
# ---------------------------------------------------------------------------


def test_resolve_by_id_and_title(sqlite_session):
    item = _create(sqlite_session, title="写文档")
    assert service.resolve(sqlite_session, 1, f"#{item.id}").id == item.id
    assert service.resolve(sqlite_session, 1, "写文").id == item.id
    with pytest.raises(NotFound) as exc:
        service.resolve(sqlite_session, 1, "999")
    assert exc.value.message == "待办不存在：#999"


def test_resolve_ambiguous_title_requires_id(sqlite_session):
    a = _create(sqlite_session, title="写文档")
    b = _create(sqlite_session, title="写文档")
    with pytest.raises(BadRequest) as exc:
        service.resolve(sqlite_session, 1, "写文档")
    assert exc.value.message == f"匹配到多条待办，请用 #id 指定：[#{a.id}, #{b.id}]"
    assert service.resolve(sqlite_session, 1, str(b.id)).id == b.id


def test_resolve_isolated_by_user(sqlite_session):
    item = _create(sqlite_session, user_id=2, title="别人的")
    with pytest.raises(NotFound):
        service.resolve(sqlite_session, 1, str(item.id))


# ---------------------------------------------------------------------------
# 区间 / 统计校验
# ---------------------------------------------------------------------------


def test_range_validation_messages(sqlite_session):
    with pytest.raises(BadRequest) as exc:
        service.list_by_date_range(sqlite_session, 1, date(2026, 5, 2), date(2026, 5, 1))
    assert exc.value.message == "日期范围不正确"
    with pytest.raises(BadRequest) as exc2:
        service.list_by_date_range(sqlite_session, 1, date(2025, 1, 1), date(2026, 2, 1))
    assert exc2.value.message == "单次最多查询一年待办"


def test_range_allows_exactly_one_calendar_year(sqlite_session):
    # Java 用 LocalDate.plusYears(1)，跨闰年时 12 个月整不应被误判为超限
    assert service.list_by_date_range(sqlite_session, 1, date(2024, 1, 1), date(2025, 1, 1)) == []
    assert service.stats(sqlite_session, 1, date(2024, 1, 1), date(2025, 1, 1)) == []


def test_stats_validation_and_filters_empty_days(sqlite_session):
    today = timeutil.today()
    _create(sqlite_session, due_date=today)
    stats = service.stats(sqlite_session, 1, today - timedelta(days=2), today)
    # 今天不参与历史回填，但当天已有非零计数，因此仍在结果里；空白日期不出现
    assert [s.stat_date for s in stats] == [today]
    with pytest.raises(BadRequest) as exc:
        service.stats(sqlite_session, 1, date(2025, 1, 1), date(2026, 2, 1))
    assert exc.value.message == "单次最多查询一年统计"


def test_rollover_all_users_settles_previous_day(sqlite_session):
    yesterday = timeutil.today() - timedelta(days=1)
    _create(sqlite_session, due_date=yesterday, title="昨天的事")
    processed = rollover.rollover_all_users(sqlite_session, timeutil.today())
    assert processed == 1
    stat = _stat(sqlite_session, 1, yesterday)
    assert stat is not None and stat.pending_count == 1
    # 幂等：已结算的日期不会重复写
    rollover.rollover_all_users(sqlite_session, timeutil.today())
    again = _stat(sqlite_session, 1, yesterday)
    assert again.pending_count == 1


def test_settle_all_uses_exact_date(sqlite_session):
    day = date(2026, 8, 30)
    _create(sqlite_session, due_date=day)
    assert rollover.settle_all(sqlite_session, day) == 1
    assert _stat(sqlite_session, 1, day).pending_count == 1


# ---------------------------------------------------------------------------
# REST 端点（8 个）
# ---------------------------------------------------------------------------


@pytest.fixture()
def client(client_factory, sqlite_session):
    from app.api.todo import router

    return client_factory(router, sqlite_session)


def test_rest_create_and_today(client):
    body = client.post("/todo", json={"title": "买牛奶", "note": "低脂", "dueTime": "20:30"}).json()
    assert body["title"] == "买牛奶"
    assert body["note"] == "低脂"
    assert body["dueDate"] == timeutil.today().isoformat()
    assert body["dueTime"] == "20:30:00"
    assert body["status"] == "TODO"
    assert body["source"] == "MANUAL"
    assert body["completedAt"] is None
    today = client.get("/todo/today").json()
    assert [item["title"] for item in today] == ["买牛奶"]


def test_rest_create_requires_title(client):
    resp = client.post("/todo", json={})
    assert resp.status_code == 400
    assert resp.json()["message"] == "待办标题不能为空"


def test_rest_range_requires_both_dates(client):
    resp = client.get("/todo")
    assert resp.status_code == 400
    assert resp.json()["message"] == "请提供开始日期"
    resp = client.get("/todo", params={"from": "2026-08-01"})
    assert resp.status_code == 400
    assert resp.json()["message"] == "请提供结束日期"


def test_rest_range_and_bad_date(client):
    client.post("/todo", json={"title": "a", "dueDate": "2026-08-30"})
    ok = client.get("/todo", params={"from": "2026-08-01", "to": "2026-08-31"})
    assert ok.status_code == 200 and [i["title"] for i in ok.json()] == ["a"]
    bad = client.get("/todo", params={"from": "xxx", "to": "2026-08-31"})
    assert bad.status_code == 400 and bad.json()["message"] == "请提供开始日期"


def test_rest_update_complete_defer_delete(client):
    item = client.post("/todo", json={"title": "a"}).json()
    updated = client.patch(f"/todo/{item['id']}", json={"title": "b", "dueDate": "2026-12-01"})
    assert updated.status_code == 200
    assert updated.json()["title"] == "b"
    assert updated.json()["dueDate"] == "2026-12-01"

    completed = client.patch(f"/todo/{item['id']}/complete")
    assert completed.json()["status"] == "DONE"
    assert completed.json()["completedAt"] is not None

    deferred = client.patch(f"/todo/{item['id']}/defer", json={"newDate": "2026-12-05"})
    assert deferred.json()["dueDate"] == "2026-12-05"

    deleted = client.delete(f"/todo/{item['id']}")
    assert deleted.status_code == 200
    assert deleted.content == b""
    assert client.get("/todo/today").json() == []


def test_rest_patch_validation_and_404(client):
    resp = client.patch("/todo/999", json={"title": "x", "dueDate": "2026-12-01"})
    assert resp.status_code == 404
    assert resp.json()["message"] == "待办不存在：#999"

    item = client.post("/todo", json={"title": "a"}).json()
    resp = client.patch(f"/todo/{item['id']}", json={"title": "a"})
    assert resp.status_code == 400
    assert resp.json()["message"] == "请选择待办日期"


def test_rest_stats_daily(client):
    item = client.post("/todo", json={"title": "a"}).json()
    client.patch(f"/todo/{item['id']}/complete")
    resp = client.get("/todo/stats/daily")
    assert resp.status_code == 200
    rows = resp.json()
    today = timeutil.today().isoformat()
    row = next(r for r in rows if r["statDate"] == today)
    assert row["completedCount"] == 1
    assert row["completionRate"] == 100.0
    assert set(row) == {
        "statDate",
        "createdCount",
        "completedCount",
        "pendingCount",
        "deferredCount",
        "completionRate",
    }


# ---------------------------------------------------------------------------
# 工具 schema（chat-core 的 registry 尚未落地时跳过）
# ---------------------------------------------------------------------------


def test_tool_schemas_match_java():
    pytest.importorskip("app.agent.tools.registry")
    import app.domains.todo.tools  # noqa: F401  触发 @tool 注册
    from app.agent.tools.registry import REGISTRY

    names = {
        "listTodayTodos",
        "createTodo",
        "updateTodo",
        "completeTodo",
        "deferTodo",
        "deleteTodo",
        "listTodosByDate",
    }
    assert names <= set(REGISTRY)
    create = REGISTRY["createTodo"]
    assert create.parameters["required"] == ["title", "note", "dueDate", "dueTime"]
    assert create.parameters["properties"]["title"]["description"] == "待办标题"
    assert create.description == (
        "新增一条待办。title 简短，note 放细节可为空；"
        "dueDate 格式 yyyy-MM-dd，默认今天，也支持「明天」；dueTime 格式 HH:mm 可为空"
    )
    assert REGISTRY["listTodayTodos"].parameters == {"type": "object", "properties": {}, "required": []}
    assert REGISTRY["deferTodo"].parameters["required"] == ["idOrTitle", "newDate"]
    assert REGISTRY["deleteTodo"].side_effect == "delete"


def test_tool_format_and_user_guard(sqlite_session, monkeypatch):
    pytest.importorskip("app.agent.tools.registry")
    from app.agent.tools.registry import ToolCtx

    from app.domains.todo import tools as todo_tools

    item = _create(sqlite_session, title="写周报")
    monkeypatch.setattr(todo_tools, "_session", lambda: nullcontext(sqlite_session))
    text = todo_tools._format([item], "今日待办")
    assert text == f"今日待办（共 1 条）：\n#{item.id} [待办] 写周报"

    # 未登录时返回文案而不是抛异常
    import asyncio

    result = asyncio.run(todo_tools.list_today_todos(ToolCtx(user_id=None)))
    assert result == "未登录，无法操作待办"


@pytest.mark.asyncio
async def test_dispatch_create_todo_via_registry(sqlite_session, monkeypatch):
    """与 chat-core 的 dispatch 联调：参数 schema → handler → 中文成功文案。"""
    pytest.importorskip("app.agent.tools.registry")
    from app.agent.tools import load_all
    from app.agent.tools.registry import ToolCtx, dispatch

    load_all()
    from app.domains.todo import tools as todo_tools

    monkeypatch.setattr(todo_tools, "_session", lambda: nullcontext(sqlite_session))
    ok, text = await dispatch(
        "createTodo",
        {"title": "写周报", "note": "", "dueDate": "明天", "dueTime": "09:30"},
        ToolCtx(user_id=1),
    )
    assert ok is True
    assert text.startswith("已记录待办 #")
    assert "写周报" in text
    item = repository.list_all(sqlite_session, 1)[0]
    assert item.source == "CHAT"
    assert item.due_date == timeutil.today() + timedelta(days=1)

    # 业务失败不产生 FAILED（ok=True，文案交给模型转述）
    ok, text = await dispatch(
        "createTodo", {"title": "", "note": "", "dueDate": "", "dueTime": ""}, ToolCtx(user_id=1)
    )
    assert ok is True and text == "待办标题不能为空"
