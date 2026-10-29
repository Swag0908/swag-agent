"""待办业务逻辑：与 Java `TodoService` / `TodoStatisticsService` 逐条对齐。

约定：
- 时间统一走 `app.core.timeutil`（naive Asia/Shanghai），不直接 `datetime.now()`；
- 每次写操作都在本层提交事务（Java 是 `@Transactional`），失败由全局处理器输出 400/404；
- 统计口径：created = 当天创建数；completed = 当天到期且 DONE；pending = 当天到期且 TODO；
  deferred = 当天被延期的去重条目数；完成率 = completed / (completed + pending + deferred)。
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.orm import Session

from app.core import timeutil
from app.core.errors import BadRequest, NotFound
from app.db.models import TodoDailyStat, TodoDeferLog, TodoItem
from app.domains.todo import repository


def refresh_daily_stat(db: Session, user_id: int, day: date) -> TodoDailyStat | None:
    """等价 Java `TodoStatisticsService.refresh`（BigDecimal 2 位、HALF_UP）。"""
    created = repository.count_created(db, user_id, day)
    completed = repository.count_completed(db, user_id, day)
    pending = repository.count_pending(db, user_id, day)
    deferred = repository.count_deferred(db, user_id, day)

    settled = completed + pending + deferred
    completion_rate: Decimal | None = None
    if settled != 0:
        completion_rate = (Decimal(completed * 100) / Decimal(settled)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
    repository.upsert_daily_stat(
        db, user_id, day, created, completed, pending, deferred, completion_rate
    )
    return db.get(TodoDailyStat, {"stat_date": day, "user_id": user_id})


def create(
    db: Session,
    user_id: int,
    title: str | None,
    note: str | None,
    due_date: date | None,
    due_time,  # noqa: ANN001  datetime.time | None
    source: str | None,
) -> TodoItem:
    if title is None or not title.strip():
        raise BadRequest("待办标题不能为空")
    now = timeutil.now()
    item = TodoItem(
        user_id=user_id,
        title=title.strip(),
        note=None if note is None or not note.strip() else note.strip(),
        due_date=due_date or timeutil.today(),
        due_time=due_time,
        status="TODO",
        source=source or "CHAT",
        created_at=now,
        updated_at=now,
        completed_at=None,
    )
    repository.insert_item(db, item)
    refresh_daily_stat(db, user_id, item.due_date)
    db.commit()
    return item


def list_today(db: Session, user_id: int) -> list[TodoItem]:
    return repository.list_by_date(db, user_id, timeutil.today())


def list_by_date(db: Session, user_id: int, day: date) -> list[TodoItem]:
    return repository.list_by_date(db, user_id, day)


def list_by_date_range(db: Session, user_id: int, start: date | None, end: date | None) -> list[TodoItem]:
    if start is None or end is None or start > end:
        raise BadRequest("日期范围不正确")
    if _plus_one_year(start) < end:
        raise BadRequest("单次最多查询一年待办")
    return repository.list_by_date_range(db, user_id, start, end)


def update(
    db: Session,
    user_id: int,
    id_or_title: str | None,
    title: str | None,
    note: str | None,
    due_date: date | None,
    due_time,  # noqa: ANN001
) -> TodoItem:
    if title is None or not title.strip():
        raise BadRequest("待办标题不能为空")
    if due_date is None:
        raise BadRequest("请选择待办日期")
    item = resolve(db, user_id, id_or_title)
    previous_date = item.due_date
    item.title = title.strip()
    item.note = None if note is None or not note.strip() else note.strip()
    item.due_date = due_date
    item.due_time = due_time
    item.updated_at = timeutil.now()
    repository.update_item(db, item)
    _refresh_dates(db, user_id, previous_date, due_date)
    db.commit()
    return item


def complete(db: Session, user_id: int, id_or_title: str | None) -> TodoItem:
    item = resolve(db, user_id, id_or_title)
    now = timeutil.now()
    repository.complete_item(db, item, now, now)
    refresh_daily_stat(db, user_id, item.due_date)
    db.commit()
    return item


def defer(db: Session, user_id: int, id_or_title: str | None, new_date: date | None) -> TodoItem:
    if new_date is None:
        raise BadRequest("请提供延期目标日期")
    item = resolve(db, user_id, id_or_title)
    previous = item.due_date
    if not new_date > previous:
        raise BadRequest("延期日期必须晚于当前日期")
    now = timeutil.now()
    repository.update_due_date(db, item, new_date, now)
    repository.insert_defer_log(
        db,
        TodoDeferLog(
            item_id=item.id,
            user_id=user_id,
            from_date=previous,
            to_date=new_date,
            deferred_at=now,
        ),
    )
    _refresh_dates(db, user_id, previous, new_date)
    db.commit()
    return item


def delete(db: Session, user_id: int, id_or_title: str | None) -> TodoItem:
    item = resolve(db, user_id, id_or_title)
    due_date = item.due_date
    repository.delete_item(db, item)
    refresh_daily_stat(db, user_id, due_date)
    db.commit()
    return item


def stats(db: Session, user_id: int, start: date | None, end: date | None) -> list[TodoDailyStat]:
    if start is None or end is None or start > end:
        raise BadRequest("日期范围不正确")
    if _plus_one_year(start) < end:
        raise BadRequest("单次最多查询一年统计")
    today = timeutil.today()
    last_historical_day = end if end < today else today - timedelta(days=1)
    day = start
    while day <= last_historical_day:
        refresh_daily_stat(db, user_id, day)
        day += timedelta(days=1)
    db.commit()
    return repository.list_daily_stats(db, user_id, start, end)


def resolve(db: Session, user_id: int, id_or_title: str | None) -> TodoItem:
    """按 #id 或标题解析；标题模糊命中多条时要求改用 #id。"""
    ref = (id_or_title or "").strip()
    # Java 只认纯数字（"#12" 会被当标题）；工具描述/列表回显都用 #id，这里兼容 "#12"（超集，不影响端点行为）。
    digits = ref[1:] if ref.startswith("#") else ref
    if digits.isdigit():
        item = repository.find_item(db, int(digits))
        if item is None or item.user_id != user_id:
            raise NotFound(f"待办不存在：#{int(digits)}")
        return item

    all_items = repository.list_all(db, user_id)
    lowered = ref.lower()
    matches = [i for i in all_items if i.title is not None and lowered in i.title.lower()]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise NotFound(f"未找到待办：{ref}")
    exact = [i for i in matches if i.title.lower() == lowered]
    if len(exact) == 1:
        return exact[0]
    ids = "[" + ", ".join(f"#{i.id}" for i in matches) + "]"
    raise BadRequest(f"匹配到多条待办，请用 #id 指定：{ids}")


def _plus_one_year(value: date) -> date:
    """等价 Java `LocalDate.plusYears(1)`（2 月 29 日回落到 2 月 28 日）。"""
    try:
        return value.replace(year=value.year + 1)
    except ValueError:
        return value.replace(year=value.year + 1, day=28)


def parse_date(value: str | None, fallback: date | None) -> date | None:
    return timeutil.parse_due_date(value, fallback)


def parse_time(value: str | None):
    """Java `LocalTime.parse` 需要补零的 HH:mm / HH:mm:ss；非法静默为 None。"""
    if value is None or not value.strip():
        return None
    text = value.strip()
    if re.fullmatch(r"\d{2}:\d{2}(:\d{2})?", text) is None:
        return None
    return timeutil.parse_due_time(text)


def _refresh_dates(db: Session, user_id: int, first: date | None, second: date | None) -> None:
    if first is not None:
        refresh_daily_stat(db, user_id, first)
    if second is not None and second != first:
        refresh_daily_stat(db, user_id, second)


__all__ = [
    "refresh_daily_stat",
    "create",
    "list_today",
    "list_by_date",
    "list_by_date_range",
    "update",
    "complete",
    "defer",
    "delete",
    "stats",
    "resolve",
    "parse_date",
    "parse_time",
]
