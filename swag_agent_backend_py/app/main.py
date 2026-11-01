"""FastAPI 应用装配。

路由模块采用“存在即加载”的方式，便于各业务模块并行开发、逐个接入。
所有对外路径与 Java 后端保持一致（不带 /api 前缀；/api 由 nginx/Vite 剥离）。
"""

from __future__ import annotations

import importlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.core.errors import install_error_handlers
from app.core.middleware import AuthMiddleware

logger = logging.getLogger(__name__)

# 按模块接入顺序；不存在的模块会被跳过（开发期友好，生产期应全部存在）
ROUTER_MODULES = [
    "app.api.health",
    "app.api.auth",
    "app.api.admin",
    "app.api.zipkin",
    "app.api.conversations",
    "app.api.user_memory",
    "app.api.todo",
    "app.api.bookmarks",
    "app.api.notes",
    "app.api.skills",
    "app.api.audit",
    "app.api.chat",
    "app.api.legacy_chat",
]


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """应用的开机与关机流程：按配置启动定时任务、补齐初始数据，退出时停止任务。

    yield 前在启动时执行，yield 后在关闭时执行；初始化失败只记日志，服务仍可启动。
    """
    # lifespan 是服务进程的生命周期，不是每次聊天都执行一遍。
    scheduler = None
    if settings.scheduler_enabled:
        try:
            from app.jobs.scheduler import start_scheduler

            scheduler = start_scheduler()
        except Exception:  # noqa: BLE001
            logger.warning("scheduler start failed", exc_info=True)
    if settings.bootstrap_on_startup:
        from starlette.concurrency import run_in_threadpool

        from app.bootstrap import bootstrap

        try:
            # 当前数据库驱动是同步的：交给工作线程，异步主循环可以继续调度其他任务。
            await run_in_threadpool(bootstrap)
        except Exception:  # noqa: BLE001
            logger.warning("bootstrap failed (DB unavailable?); app will still start", exc_info=True)
    yield  # 到这里应用开始接收请求；关闭服务时从这一行后面继续。
    if scheduler is not None:
        from app.jobs.scheduler import stop_scheduler

        stop_scheduler()


def create_app() -> FastAPI:
    """组装 HTTP 服务：安装错误处理器和中间件，再挂载各业务路由。

    返回 FastAPI 实例；模块末尾的 app 会被 Uvicorn 作为请求入口加载。
    """
    logging.basicConfig(level=settings.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s %(message)s")
    app = FastAPI(
        title="swag_agent",
        version="0.1.0",
        docs_url="/docs" if settings.enable_docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.enable_docs else None,
        redirect_slashes=False,
        lifespan=lifespan,
    )
    install_error_handlers(app)

    # 顺序：先加审计（内层），再加鉴权（外层）→ 鉴权先执行
    try:
        from app.audit.middleware import AuditMiddleware

        app.add_middleware(AuditMiddleware)
    except ModuleNotFoundError:
        logger.info("audit middleware not available yet")
    app.add_middleware(AuthMiddleware)

    # 每个 api 模块把自己的地址登记在 router 中；include_router 汇总这些地址。
    for module_name in ROUTER_MODULES:
        try:
            module = importlib.import_module(module_name)
        except ModuleNotFoundError as exc:
            if exc.name == module_name:
                logger.info("router %s not available yet", module_name)
                continue
            raise
        router = getattr(module, "router", None)
        if router is not None:
            app.include_router(router)

    return app


# Uvicorn 的 "app.main:app"：冒号前是模块位置，冒号后是这里的应用对象。
app = create_app()
