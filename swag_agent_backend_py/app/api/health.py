"""健康检查：兼容现有发布脚本的 /actuator/health。"""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from app.db.base import engine

router = APIRouter(tags=["health"])


@router.get("/actuator/health")
def health() -> dict:
    status = "UP"
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        status = "DOWN"
    return {"status": status}


@router.get("/actuator/info")
def info() -> dict:
    return {"app": "swag_agent", "runtime": "python"}
