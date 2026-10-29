"""每日结算（供 APScheduler 调用）：对齐 Java `TodoRolloverService`。

Java 的定时任务在 Asia/Shanghai 每天 00:00 执行，结算「昨天」。`app/jobs/scheduler.py`
在 00:00 传 `today()` 进来，因此 `rollover_all_users(db, on_date)` 结算的是 `on_date - 1 天`；
若需要结算指定日期本身（测试/补跑），直接调用 `settle_all(db, day)`。
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.core import timeutil
from app.domains.todo import repository, service


def settle(db: Session, user_id: int, day: date) -> bool:
    """结算某用户某天；已有统计行则跳过（与 Java `hasDailyStat` 一致）。返回是否写入。"""
    if repository.has_daily_stat(db, user_id, day):
        return False
    service.refresh_daily_stat(db, user_id, day)
    db.commit()
    return True


def settle_all(db: Session, day: date) -> int:
    """结算全部活跃用户（有 todo_item 的用户）的指定日期，返回处理的用户数。"""
    user_ids = repository.list_active_user_ids(db)
    for user_id in user_ids:
        settle(db, user_id, day)
    return len(user_ids)


def ensure_settled(db: Session, user_id: int) -> bool:
    """访问今日清单/统计时的惰性兜底：确保昨天已结算。"""
    return settle(db, user_id, timeutil.today() - timedelta(days=1))


def rollover_all_users(db: Session, on_date: date) -> int:
    """APScheduler 入口：以 `on_date` 为“今天”，结算前一天；返回处理用户数。"""
    return settle_all(db, on_date - timedelta(days=1))


__all__ = ["settle", "settle_all", "ensure_settled", "rollover_all_users"]
