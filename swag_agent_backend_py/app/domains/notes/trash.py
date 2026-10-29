"""回收站定时清理入口（供 `app/jobs/scheduler.py` 调用）。

Java 侧对应 `NotesTrashCleaner`（``@Scheduled(cron = "0 30 3 * * *")``）→
``NotesService.purgeAllExpired()``。读取回收站列表时也会顺带清理过期条目。
"""

from __future__ import annotations

from pathlib import Path

from app.domains.notes.service import NotesService, get_notes_service


def purge_expired_trash_all_users(db: object | None = None) -> int:
    """清理所有 ``user-*`` 目录回收站中超过保留期（默认 7 天）的条目。

    :param db: 兼容 scheduler 的 ``Session`` 参数；笔记存储不依赖数据库。
    :return: 实际删除的回收站条目数。
    """
    return get_notes_service().purge_all_expired(db)


def purge_expired_trash_for_home(home: str | Path, db: object | None = None) -> int:
    """清理单个用户目录（``<notes_root>/user-<id>``）的过期回收站条目。"""
    del db  # 仅签名兼容
    return NotesService().purge_trash_home(Path(home))
