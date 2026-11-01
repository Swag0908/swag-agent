"""待办模块的数据访问层（SQLAlchemy 2.0）。

对齐 Java `TodoRepository`：列名、排序、按用户隔离、按天统计的计数口径保持一致。
DATETIME(6) 表，写入不截断微秒。
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from sqlalchemy import delete as sa_delete
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db.models import TodoDailyStat, TodoDeferLog, TodoItem


def insert_item(db: Session, item: TodoItem) -> TodoItem:
    """插入并 flush 以取得待办编号；此处不提交，便于与统计更新组成同一事务。"""
    db.add(item)
    db.flush()
    return item


def find_item(db: Session, item_id: int) -> TodoItem | None:
    """按主键取待办；调用方还必须核对 user_id。"""
    return db.get(TodoItem, item_id)


def list_by_date(db: Session, user_id: int, due_date: date) -> list[TodoItem]:
    """按用户和到期日筛选，具体时间在前、无具体时间在后。"""
    stmt = (
        select(TodoItem)
        .where(TodoItem.user_id == user_id, TodoItem.due_date == due_date)
        .order_by(TodoItem.due_time.is_(None), TodoItem.due_time, TodoItem.id)
    )
    return list(db.scalars(stmt).all())


def list_by_date_range(db: Session, user_id: int, start: date, end: date) -> list[TodoItem]:
    """读取含起止两天的待办范围，按日期、时间和编号排序。"""
    stmt = (
        select(TodoItem)
        .where(TodoItem.user_id == user_id, TodoItem.due_date.between(start, end))
        .order_by(TodoItem.due_date, TodoItem.due_time.is_(None), TodoItem.due_time, TodoItem.id)
    )
    return list(db.scalars(stmt).all())


def list_all(db: Session, user_id: int) -> list[TodoItem]:
    """读取当前用户全部待办，供标题匹配使用。"""
    stmt = select(TodoItem).where(TodoItem.user_id == user_id).order_by(TodoItem.due_date, TodoItem.id)
    return list(db.scalars(stmt).all())


def update_item(db: Session, item: TodoItem) -> None:
    """把修改同步到事务中；flush 不等于 commit，最终提交由 service 决定。"""
    db.add(item)
    db.flush()


def complete_item(db: Session, item: TodoItem, completed_at: datetime, updated_at: datetime) -> None:
    """写入 DONE 状态和完成时间，同步到当前事务但不提交。"""
    item.status = "DONE"
    item.completed_at = completed_at
    item.updated_at = updated_at
    db.add(item)
    db.flush()


def update_due_date(db: Session, item: TodoItem, new_due_date: date, updated_at: datetime) -> None:
    """更新到期日期与修改时间，不在此处提交。"""
    item.due_date = new_due_date
    item.updated_at = updated_at
    db.add(item)
    db.flush()


def delete_item(db: Session, item: TodoItem) -> None:
    """在当前事务删除待办，提交由 service 统一负责。"""
    db.delete(item)
    db.flush()


def insert_defer_log(db: Session, log: TodoDeferLog) -> TodoDeferLog:
    """追加延期流水，不在此处提交。"""
    db.add(log)
    db.flush()
    return log


def count_created(db: Session, user_id: int, day: date) -> int:
    """等价 Java `DATE(created_at) = day`，改成半开区间以便走索引且跨库可移植。"""
    start = datetime.combine(day, time.min)
    end = start + timedelta(days=1)
    stmt = select(func.count()).select_from(TodoItem).where(
        TodoItem.user_id == user_id,
        TodoItem.created_at >= start,
        TodoItem.created_at < end,
    )
    return int(db.scalar(stmt) or 0)


def count_completed(db: Session, user_id: int, day: date) -> int:
    """统计指定到期日且状态为 DONE 的条目，并非按 completed_at 计数。"""
    stmt = select(func.count()).select_from(TodoItem).where(
        TodoItem.user_id == user_id,
        TodoItem.status == "DONE",
        TodoItem.due_date == day,
    )
    return int(db.scalar(stmt) or 0)


def count_pending(db: Session, user_id: int, day: date) -> int:
    """统计指定到期日仍为 TODO 的条目。"""
    stmt = select(func.count()).select_from(TodoItem).where(
        TodoItem.user_id == user_id,
        TodoItem.due_date == day,
        TodoItem.status == "TODO",
    )
    return int(db.scalar(stmt) or 0)


def count_deferred(db: Session, user_id: int, day: date) -> int:
    """统计从指定日期延出的不同待办数量，同一条重复延期不重复计数。"""
    stmt = select(func.count(TodoDeferLog.item_id.distinct())).where(
        TodoDeferLog.user_id == user_id,
        TodoDeferLog.from_date == day,
    )
    return int(db.scalar(stmt) or 0)


def has_daily_stat(db: Session, user_id: int, day: date) -> bool:
    return db.get(TodoDailyStat, {"stat_date": day, "user_id": user_id}) is not None


def upsert_daily_stat(
    db: Session,
    user_id: int,
    day: date,
    created: int,
    completed: int,
    pending: int,
    deferred: int,
    completion_rate,  # noqa: ANN001  Decimal | None
) -> None:
    """存在当天统计就更新，否则插入；只 flush，由上层提交。"""
    row = db.get(TodoDailyStat, {"stat_date": day, "user_id": user_id})
    if row is None:
        row = TodoDailyStat(
            stat_date=day,
            user_id=user_id,
            created_count=created,
            completed_count=completed,
            pending_count=pending,
            deferred_count=deferred,
            completion_rate=completion_rate,
        )
        db.add(row)
    else:
        row.created_count = created
        row.completed_count = completed
        row.pending_count = pending
        row.deferred_count = deferred
        row.completion_rate = completion_rate
    db.flush()


def list_daily_stats(db: Session, user_id: int, start: date, end: date) -> list[TodoDailyStat]:
    """返回日期范围内至少有一种计数非零的统计行，按日期排列。"""
    stmt = (
        select(TodoDailyStat)
        .where(
            TodoDailyStat.user_id == user_id,
            TodoDailyStat.stat_date.between(start, end),
            or_(
                TodoDailyStat.created_count > 0,
                TodoDailyStat.completed_count > 0,
                TodoDailyStat.pending_count > 0,
                TodoDailyStat.deferred_count > 0,
            ),
        )
        .order_by(TodoDailyStat.stat_date)
    )
    return list(db.scalars(stmt).all())


def list_active_user_ids(db: Session) -> list[int]:
    return [int(uid) for uid in db.scalars(select(TodoItem.user_id).distinct()).all()]


def delete_all_for_user(db: Session, user_id: int) -> None:  # pragma: no cover - 测试/清理辅助
    db.execute(sa_delete(TodoItem).where(TodoItem.user_id == user_id))
    db.flush()
