"""审计、危险操作确认与调用链（对齐 Java `com.swag.audit` 包）。

对外契约见 ``CONTRACTS.md`` §4；精确行为以 Java 源码为准：

- ``app.audit.context``      审计上下文（contextvars，替代 ThreadLocal/Reactor 传播）
- ``app.audit.middleware``   ASGI 审计入口（鉴权之后运行、写请求事件、回填 X-Audit-Id）
- ``app.audit.digest``       SHA-256 / canonical JSON / actionDigest（与 Java 逐字一致）
- ``app.audit.events``       16 种事件类型与执行状态常量
- ``app.audit.recorder``     审计事件唯一写入口（audit_event 35 列，失败降级不阻断业务）
- ``app.audit.confirmation`` 5 状态确认机（PENDING/APPROVED/DENIED/EXPIRED/CONSUMED）
- ``app.audit.tool_audit``   供 chat-core 调用的异步工具审计封装
- ``app.audit.query``        审计事件 / 调用链只读查询
"""

from __future__ import annotations

__all__ = [
    "context",
    "digest",
    "events",
    "middleware",
    "recorder",
    "confirmation",
    "tool_audit",
    "query",
]
