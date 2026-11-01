"""APScheduler 定时任务：与 Java 的两个 @Scheduled 对齐。

- 待办跨天结算：每天 00:00 Asia/Shanghai
- 笔记回收站清理：每天 03:30 Asia/Shanghai

双跑期间必须保持 SCHEDULER_ENABLED=false，只允许一方执行，避免重复结算/清理。
"""

from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from starlette.concurrency import run_in_threadpool

from app.core.timeutil import today

logger = logging.getLogger(__name__)
_scheduler: AsyncIOScheduler | None = None


def _run_todo_rollover() -> None:
    """借用独立数据库会话，结算所有活跃用户前一天的待办统计。"""
    from app.db.base import SessionLocal
    from app.domains.todo.rollover import rollover_all_users

    with SessionLocal() as db:
        count = rollover_all_users(db, today())
    logger.info("todo rollover done for %s users", count)


def _run_notes_trash_cleanup() -> None:
    """清理所有用户过期笔记回收站；文件删除由笔记服务完成。"""
    from app.db.base import SessionLocal
    from app.domains.notes.trash import purge_expired_trash_all_users

    with SessionLocal() as db:
        count = purge_expired_trash_all_users(db)
    logger.info("notes trash cleanup removed %s entries", count)


async def _job_todo_rollover() -> None:
    await run_in_threadpool(_run_todo_rollover)


async def _job_notes_trash_cleanup() -> None:
    await run_in_threadpool(_run_notes_trash_cleanup)


def start_scheduler() -> AsyncIOScheduler:
    """启动进程内定时器：东八区零点结算待办、03:30 清理回收站；重复调用复用实例。"""
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
    scheduler.add_job(
        _job_todo_rollover,
        CronTrigger(hour=0, minute=0, timezone="Asia/Shanghai"),
        id="todo_rollover",
        replace_existing=True,
    )
    scheduler.add_job(
        _job_notes_trash_cleanup,
        CronTrigger(hour=3, minute=30, timezone="Asia/Shanghai"),
        id="notes_trash_cleanup",
        replace_existing=True,
    )
    scheduler.start()
    _scheduler = scheduler
    logger.info("scheduler started")
    return scheduler


def stop_scheduler() -> None:
    """停止并清除定时器实例，供应用关闭流程调用。"""
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
