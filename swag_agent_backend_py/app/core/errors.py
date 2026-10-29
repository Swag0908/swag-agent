"""统一错误模型：尽量复刻 Spring 的响应包络，前端零改动兼容。

- 过滤器层未登录：固定 {"code":"UNAUTHORIZED","message":"请先登录"}
- 业务异常：{timestamp,status,error,path,message}
- 危险工具需确认：409 {"code":"CONFIRMATION_REQUIRED",...}
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


_STATUS_TEXT = {
    400: "Bad Request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not Found",
    405: "Method Not Allowed",
    409: "Conflict",
    413: "Payload Too Large",
    415: "Unsupported Media Type",
    500: "Internal Server Error",
    504: "Gateway Timeout",
}


def _now_iso() -> str:
    return datetime.now(ZoneInfo("UTC")).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class AppError(Exception):
    def __init__(self, status_code: int, message: str, *, code: str | None = None, extra: dict[str, Any] | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.code = code
        self.extra = extra or {}


class Unauthorized(AppError):
    def __init__(self, message: str = "请先登录"):
        super().__init__(401, message, code="UNAUTHORIZED", extra={"code": "UNAUTHORIZED", "message": message})


class Forbidden(AppError):
    def __init__(self, message: str = "无权执行该操作"):
        super().__init__(403, message)


class NotFound(AppError):
    def __init__(self, message: str = "资源不存在"):
        super().__init__(404, message)


class BadRequest(AppError):
    def __init__(self, message: str = "请求参数不正确"):
        super().__init__(400, message)


class ConfirmationRequired(AppError):
    """工具执行前需要用户确认；由 audit 模块抛出，全局处理器输出 409。"""

    def __init__(
        self,
        *,
        confirmation_id: UUID | str,
        audit_id: UUID | str,
        tool_name: str,
        requested_at: datetime,
        expires_at: datetime,
        message: str = "该操作需要确认",
        next_step: str = "请调用 POST /audit/confirmations/{confirmationId}/decision 审批后重试原请求",
    ):
        super().__init__(409, message, code="CONFIRMATION_REQUIRED")
        self.extra = {
            "code": "CONFIRMATION_REQUIRED",
            "message": message,
            "auditId": str(audit_id),
            "confirmationId": str(confirmation_id),
            "toolName": tool_name,
            "requestedAt": requested_at.isoformat(timespec="milliseconds"),
            "expiresAt": expires_at.isoformat(timespec="milliseconds"),
            "nextStep": next_step,
        }


class ConfirmationInvalid(AppError):
    def __init__(self, message: str = "确认票据无效或已过期"):
        super().__init__(409, message, code="CONFIRMATION_INVALID")
        self.extra = {"code": "CONFIRMATION_INVALID", "message": message, "timestamp": _now_iso()}


def _spring_body(request: Request, status: int, message: str) -> dict[str, Any]:
    return {
        "timestamp": _now_iso(),
        "status": status,
        "error": _STATUS_TEXT.get(status, "Error"),
        "path": request.url.path,
        "message": message,
    }


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError):  # noqa: ANN202
        if exc.extra.get("code") in {"UNAUTHORIZED", "CONFIRMATION_REQUIRED", "CONFIRMATION_INVALID"}:
            # 固定包络（Java 端这三种是显式构造的 body，不带 Spring 默认字段）
            return JSONResponse(status_code=exc.status_code, content=exc.extra)
        return JSONResponse(status_code=exc.status_code, content=_spring_body(request, exc.status_code, exc.message))

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException):  # noqa: ANN202
        detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        return JSONResponse(status_code=exc.status_code, content=_spring_body(request, exc.status_code, detail))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError):  # noqa: ANN202
        first = exc.errors()[0] if exc.errors() else {}
        loc = ".".join(str(x) for x in first.get("loc", []) if x != "body")
        message = f"{loc}: {first.get('msg', '参数不合法')}" if loc else first.get("msg", "参数不合法")
        return JSONResponse(status_code=400, content=_spring_body(request, 400, message))

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):  # noqa: ANN202
        # 不把堆栈暴露给客户端；由日志记录
        import logging

        logging.getLogger("swag_agent").exception("unhandled error: %s", exc)
        return JSONResponse(status_code=500, content=_spring_body(request, 500, "服务异常"))
