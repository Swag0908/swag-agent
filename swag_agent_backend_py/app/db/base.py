"""SQLAlchemy 基类与 session。"""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    """所有数据库模型的共同基类，汇总表结构映射；定义模型本身不会创建业务表。"""
    pass


# engine 管理连接池，像一组可重复借用的数据库通道；不是一条业务记录。
engine = create_engine(
    settings.mysql_url,
    pool_pre_ping=True,
    pool_recycle=3600,
    pool_size=10,
    max_overflow=20,
    future=True,
    connect_args={"init_command": "SET time_zone = '+08:00'"},
)

# SessionLocal 是“制造会话的工厂”；每次调用才得到一份独立的读写事务上下文。
# autoflush=False：必要时显式 flush；commit 才正式提交，close 不会替你提交。
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """为请求提供一个数据库会话，并在请求结束时关闭；提交事务由业务函数负责。

    yield 把 db 暂借给路由，finally 确保发生异常时也能归还连接。
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
