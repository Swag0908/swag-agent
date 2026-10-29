"""待办模块的对外视图（REST JSON 字段名与 Java Record 完全一致）。"""

from __future__ import annotations

from app.core import timeutil
from app.db.models import TodoDailyStat, TodoItem


def item_to_dict(item: TodoItem) -> dict:
    """对应 Java `TodoController.ItemResponse`（无 updatedAt 字段）。"""
    return {
        "id": item.id,
        "title": item.title,
        "note": item.note,
        "dueDate": timeutil.local_date_str(item.due_date),
        "dueTime": timeutil.local_time_str(item.due_time),
        "status": item.status,
        "source": item.source,
        "createdAt": timeutil.local_datetime_json(item.created_at),
        "completedAt": timeutil.local_datetime_json(item.completed_at),
    }


def stat_to_dict(stat: TodoDailyStat) -> dict:
    """对应 Java `TodoController.StatResponse`；BigDecimal completionRate → JSON number。"""
    return {
        "statDate": timeutil.local_date_str(stat.stat_date),
        "createdCount": stat.created_count,
        "completedCount": stat.completed_count,
        "pendingCount": stat.pending_count,
        "deferredCount": stat.deferred_count,
        "completionRate": None if stat.completion_rate is None else float(stat.completion_rate),
    }


def java_time_text(value) -> str:  # noqa: ANN001  datetime.time
    """Java LocalTime.toString()：秒为 0 时省略秒。"""
    if value.second == 0 and value.microsecond == 0:
        return value.strftime("%H:%M")
    return value.isoformat(timespec="seconds")
