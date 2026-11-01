"""健康检查：兼容现有发布脚本的 /actuator/health。"""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from app.db.base import engine

router = APIRouter(tags=["health"])


@router.get("/actuator/health")
def health() -> dict:
    """执行 MySQL SELECT 1，失败时 body 标记 DOWN；此函数仍返回普通 200 响应。"""
    status = "UP"
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        status = "DOWN"
    return {"status": status}


@router.get("/actuator/info")
def info() -> dict:
    """返回应用名称和运行时标识，便于确认请求是否到达 Python 服务。"""
    return {"app": "swag_agent", "runtime": "python"}
