"""待办工具（7 个）——schema 与 description 逐字对齐 Java `TodoTools`。

用户身份从 `ToolCtx.user_id` 取；业务失败返回中文文案，不抛异常给 Agent 循环。
"""

from __future__ import annotations

from datetime import date, timedelta

from starlette.concurrency import run_in_threadpool

from app.agent.tools.registry import ToolCtx, tool
from app.core import timeutil
from app.core.errors import AppError
from app.domains.todo import service as todo_service
from app.domains.todo.views import java_time_text

EMPTY_PARAMS = {"type": "object", "properties": {}, "required": []}

LIST_TODAY_DESC = (
    "查询当前用户今日的待办清单，返回每条的 #id、标题、状态，"
    "后续 completeTodo/deferTodo/deleteTodo 请按 #id 引用"
)
CREATE_DESC = (
    "新增一条待办。title 简短，note 放细节可为空；"
    "dueDate 格式 yyyy-MM-dd，默认今天，也支持「明天」；dueTime 格式 HH:mm 可为空"
)
UPDATE_DESC = (
    "修改已有待办的标题、备注、日期或时间。 dueDate 格式 yyyy-MM-dd；"
    "dueTime 格式 HH:mm，不需要具体时间时留空"
)
COMPLETE_DESC = "把一条待办标记为已完成。idOrTitle 传 #id 或标题"
DEFER_DESC = "把一条待办延期到新日期。newDate 格式 yyyy-MM-dd，也支持「明天」"
DELETE_DESC = "删除一条待办。idOrTitle 传 #id 或标题"
LIST_BY_DATE_DESC = "查询指定日期的待办。date 格式 yyyy-MM-dd"

ID_OR_TITLE = {"type": "string", "description": "待办的 #id 或标题"}


def _session():  # noqa: ANN202 - 便于测试 monkeypatch
    from app.db.base import SessionLocal

    return SessionLocal()


def _run(fn, *args):  # noqa: ANN001
    def call():
        with _session() as db:
            return fn(db, *args)

    return run_in_threadpool(call)


def _user_id(ctx: ToolCtx) -> int | None:
    value = getattr(ctx, "user_id", None)
    return int(value) if value is not None else None


def _format(items, header: str) -> str:  # noqa: ANN001
    if not items:
        return f"{header}：暂无。"
    lines = [f"{header}（共 {len(items)} 条）："]
    for item in items:
        prefix = "[已完成]" if item.status == "DONE" else "[待办]"
        line = f"#{item.id} {prefix} {item.title}"
        if item.due_time is not None:
            line += f"（截止 {java_time_text(item.due_time)}）"
        if item.note is not None:
            line += f" 备注：{item.note}"
        lines.append(line)
    return "\n".join(lines).strip()


def _list_today(db, user_id: int) -> str:  # noqa: ANN001
    return _format(todo_service.list_today(db, user_id), "今日待办")


def _create(db, user_id: int, title, note, dueDate, dueTime) -> str:  # noqa: ANN001
    item = todo_service.create(
        db,
        user_id,
        title,
        note,
        todo_service.parse_date(dueDate, timeutil.today()),
        todo_service.parse_time(dueTime),
        "CHAT",
    )
    return f"已记录待办 #{item.id} {item.title}"


def _update(db, user_id: int, idOrTitle, title, note, dueDate, dueTime) -> str:  # noqa: ANN001
    item = todo_service.update(
        db,
        user_id,
        idOrTitle,
        title,
        note,
        todo_service.parse_date(dueDate, None),
        todo_service.parse_time(dueTime),
    )
    suffix = f" {java_time_text(item.due_time)}" if item.due_time is not None else ""
    return f"已修改待办 #{item.id} {item.title} → {item.due_date.isoformat()}{suffix}"


def _complete(db, user_id: int, idOrTitle) -> str:  # noqa: ANN001
    item = todo_service.complete(db, user_id, idOrTitle)
    return f"已完成 #{item.id} {item.title}"


def _defer(db, user_id: int, idOrTitle, newDate) -> str:  # noqa: ANN001
    item = todo_service.defer(
        db,
        user_id,
        idOrTitle,
        todo_service.parse_date(newDate, timeutil.today() + timedelta(days=1)),
    )
    return f"已延期 #{item.id} {item.title} → {item.due_date.isoformat()}"


def _delete(db, user_id: int, idOrTitle) -> str:  # noqa: ANN001
    item = todo_service.delete(db, user_id, idOrTitle)
    return f"已删除 #{item.id} {item.title}"


def _list_by_date(db, user_id: int, raw_date) -> str:  # noqa: ANN001
    day: date = todo_service.parse_date(raw_date, timeutil.today())
    return _format(todo_service.list_by_date(db, user_id, day), f"{day.isoformat()} 待办")


@tool(name="listTodayTodos", description=LIST_TODAY_DESC, parameters=EMPTY_PARAMS, side_effect="read")
async def list_today_todos(ctx: ToolCtx) -> str:
    user_id = _user_id(ctx)
    if user_id is None:
        return "未登录，无法操作待办"
    try:
        return await _run(_list_today, user_id)
    except AppError as exc:
        return exc.message


@tool(
    name="createTodo",
    description=CREATE_DESC,
    parameters={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "待办标题"},
            "note": {"type": "string", "description": "备注/细节，可为空"},
            "dueDate": {"type": "string", "description": "目标日期 yyyy-MM-dd 或「明天」，可为空，默认今天"},
            "dueTime": {"type": "string", "description": "截止时间 HH:mm，可为空"},
        },
        "required": ["title", "note", "dueDate", "dueTime"],
    },
    side_effect="write",
)
async def create_todo(title: str, note: str, dueDate: str, dueTime: str, ctx: ToolCtx) -> str:
    user_id = _user_id(ctx)
    if user_id is None:
        return "未登录，无法操作待办"
    try:
        return await _run(_create, user_id, title, note, dueDate, dueTime)
    except AppError as exc:
        return exc.message


@tool(
    name="updateTodo",
    description=UPDATE_DESC,
    parameters={
        "type": "object",
        "properties": {
            "idOrTitle": ID_OR_TITLE,
            "title": {"type": "string", "description": "修改后的完整标题"},
            "note": {"type": "string", "description": "修改后的备注，可为空"},
            "dueDate": {"type": "string", "description": "修改后的日期 yyyy-MM-dd"},
            "dueTime": {"type": "string", "description": "修改后的时间 HH:mm，可为空"},
        },
        "required": ["idOrTitle", "title", "note", "dueDate", "dueTime"],
    },
    side_effect="write",
)
async def update_todo(
    idOrTitle: str, title: str, note: str, dueDate: str, dueTime: str, ctx: ToolCtx
) -> str:
    user_id = _user_id(ctx)
    if user_id is None:
        return "未登录，无法操作待办"
    try:
        return await _run(_update, user_id, idOrTitle, title, note, dueDate, dueTime)
    except AppError as exc:
        return exc.message


@tool(
    name="completeTodo",
    description=COMPLETE_DESC,
    parameters={
        "type": "object",
        "properties": {"idOrTitle": ID_OR_TITLE},
        "required": ["idOrTitle"],
    },
    side_effect="write",
)
async def complete_todo(idOrTitle: str, ctx: ToolCtx) -> str:
    user_id = _user_id(ctx)
    if user_id is None:
        return "未登录，无法操作待办"
    try:
        return await _run(_complete, user_id, idOrTitle)
    except AppError as exc:
        return exc.message


@tool(
    name="deferTodo",
    description=DEFER_DESC,
    parameters={
        "type": "object",
        "properties": {
            "idOrTitle": ID_OR_TITLE,
            "newDate": {"type": "string", "description": "目标日期 yyyy-MM-dd 或「明天」"},
        },
        "required": ["idOrTitle", "newDate"],
    },
    side_effect="write",
)
async def defer_todo(idOrTitle: str, newDate: str, ctx: ToolCtx) -> str:
    user_id = _user_id(ctx)
    if user_id is None:
        return "未登录，无法操作待办"
    try:
        return await _run(_defer, user_id, idOrTitle, newDate)
    except AppError as exc:
        return exc.message


@tool(
    name="deleteTodo",
    description=DELETE_DESC,
    parameters={
        "type": "object",
        "properties": {"idOrTitle": ID_OR_TITLE},
        "required": ["idOrTitle"],
    },
    side_effect="delete",
)
async def delete_todo(idOrTitle: str, ctx: ToolCtx) -> str:
    user_id = _user_id(ctx)
    if user_id is None:
        return "未登录，无法操作待办"
    try:
        return await _run(_delete, user_id, idOrTitle)
    except AppError as exc:
        return exc.message


@tool(
    name="listTodosByDate",
    description=LIST_BY_DATE_DESC,
    parameters={
        "type": "object",
        "properties": {"date": {"type": "string", "description": "日期 yyyy-MM-dd"}},
        "required": ["date"],
    },
    side_effect="read",
)
async def list_todos_by_date(date: str, ctx: ToolCtx) -> str:
    user_id = _user_id(ctx)
    if user_id is None:
        return "未登录，无法操作待办"
    try:
        return await _run(_list_by_date, user_id, date)
    except AppError as exc:
        return exc.message


__all__ = [
    "list_today_todos",
    "create_todo",
    "update_todo",
    "complete_todo",
    "defer_todo",
    "delete_todo",
    "list_todos_by_date",
]
