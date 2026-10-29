# Python 后端协作契约（实现前必读）

> 目标：把 Java 后端 65 个端点 1:1 迁移到 `swag_agent_backend_py/`，前端零改动。
> 接口/字段/SSE 语义以 `docs/python-migration/01-api-contract.md` 为准；
> AI 核心映射以 `03-ai-core-mapping.md` 为准；数据层以 `02-data-model.md` 为准。
>
> **硬规则**
> 1. 不改 `swag_agent_backend/`（Java）和 `swag_agent_web/` 任何文件；不改现有数据库结构。
> 2. 只写自己任务写作用域内的文件；不要编辑别人的文件；需要新接口先在群里发消息。
> 3. 不把真实密钥写进任何文件/日志；本地 `.env` 已存在且被 gitignore。
> 4. 对外 REST 字段名保持 camelCase（Java record 原名）；SSE 的 data 保持 snake_case。
> 5. 所有时间用 `app.core.timeutil`，不要 `datetime.now()`；DATETIME(0) 表写前截断微秒。
> 6. 数据库访问用 SQLAlchemy 2.0（`Session` + `select()`），不要手拼 SQL 除非向量查询。
> 7. 完成标准：`app.main` 能 import、自己的路由能在 TestClient 里 200/4xx 正确、核心逻辑有 pytest。

## 运行环境

```bash
cd swag_agent_backend_py
.venv/bin/python -m pytest            # 测试
.venv/bin/python -m app.main          # 语法/导入检查（不会启动服务）
.venv/bin/python -m uvicorn app.main:app --port 8081
```

基础配置 `app/config.py` 已接好；MySQL 指向 Java 同一个库（只读/受限测试时注意不要污染真实数据）。

## 现有基础模块（Lead 已实现，可直接用）

| 模块 | 内容 |
| --- | --- |
| `app/config.py` | `settings`（pydantic-settings，读 `.env`）；`settings.mysql_url/pg_url` 等 |
| `app/core/timeutil.py` | `now()/today()/epoch_ms()/iso_instant()/parse_due_date()/parse_due_time()/title_from_text()` |
| `app/core/errors.py` | `AppError/Unauthorized/Forbidden/NotFound/BadRequest/ConfirmationRequired/ConfirmationInvalid`；全局处理器已装 |
| `app/core/security.py` | `hash_password/verify_password/new_token/new_id` |
| `app/core/middleware.py` | `AuthMiddleware`：校验 Bearer、写 `request.state.user_id/role/auth_token`、公开路径 401 固定 body |
| `app/db/base.py` | `Base`、`engine`、`SessionLocal`、`get_db()` |
| `app/db/pg.py` | `pg_connection()`（psycopg + pgvector 已注册）；PG 不可用要 try/except 降级 |
| `app/db/models.py` | 18 张业务表 + `SpringAiChatMemory` 的 ORM 模型（全部列已按真实 schema 定义） |
| `app/api/deps.py` | `current_user(request) -> AuthUser`、`require_admin`、`get_db` |
| `app/domains/auth/service.py` | 用户/令牌/注册闸门，`resolve_token(db, token)`、`require_admin(db, user_id)` 等 |
| `app/api/auth.py` / `admin.py` / `zipkin.py` / `health.py` | 已实现，Lead 维护 |

数据库模型对应关系：`app/db/models.py` 的类名即表名 camel 形式（如 `ChatConversation` → `chat_conversation`）。
`SpringAiChatMemory` 是短期记忆兼容表；`AuditEvent/AuditConfirmation` 的列已完整定义。

## 模块依赖接口（跨模块只通过这些名字）

### 1) Tool 注册表（chat-core 提供，domain 模块使用）

```python
# app/agent/tools/registry.py
@dataclass(frozen=True)
class ToolCtx:
    user_id: int
    audit_id: str | None = None
    conversation_id: int | None = None
    confirmation_id: str | None = None

@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict          # OpenAI function.parameters（required 与 Java 一致，全部必填）
    handler: Callable[..., Awaitable[str]]
    needs_user: bool = True
    side_effect: str = "read" # none/read/write/delete/external

def tool(name: str, description: str, parameters: dict, *, needs_user: bool = True,
         side_effect: str = "read"): ...
REGISTRY: dict[str, ToolSpec]
def openai_tools() -> list[dict]
async def dispatch(name: str, arguments: str | dict, ctx: ToolCtx) -> tuple[bool, str]
```

- domain 模块写 `app/domains/<x>/tools.py`，用 `@tool(...)` 注册，`handler` 形如
  `async def xxx(title: str, ..., ctx: ToolCtx) -> str`，**业务失败返回中文文案，不抛异常**。
- `app/agent/tools/__init__.py` 会按如下顺序 import（不存在则跳过）：
  `datetime_tool`、`web_search`、`app.domains.todo.tools`、`app.domains.sites.tools`、
  `app.domains.notes.tools`、`app.memory.tools`。

### 2) 记忆（chat-core 提供，conversations/user_memory 路由使用）

```python
# app/memory/short.py
def load_history(db, conversation_id: int, max_messages: int = 40) -> list[dict]  # [{"role","content"}]
def append_turn(db, conversation_id: int, user_id: int, user_text: str, assistant_text: str) -> None
def rebuild_from_chat_messages(db, conversation_id: int, user_id: int) -> None

# app/memory/long.py
async def recall_semantic(db, conversation_id: int | str, query: str, top_k: int = 5) -> list[str]
def delete_conversation_vectors(conversation_id: int | str) -> None

# app/memory/user_memory.py
def get_panel(db, user_id: int) -> dict          # {"enabled": bool, "items": [{"id","content","createdAtMs"}]}
def set_enabled(db, user_id: int, enabled: bool) -> None
def delete_memory(db, user_id: int, memory_id: int) -> None
def recall(db, user_id: int, query: str, top_k: int = 5) -> list[str]   # 向量失败降级最近 5 条
async def remember(db, user_id: int, content: str) -> str                # 工具用
def rebuild_memory(db, conversation_id: int, user_id: int) -> None       # 删消息/删会话后调用
```

### 3) 技能（api-modules 提供，chat-core 的 prompt 使用）

```python
# app/skills/assembler.py
def assemble_active_guide(db) -> str
# 返回 "" 或 "\n\n" + HEADER + 每个启用技能的 "\n## name（description）\n正文"
```

### 4) 审计（audit-builder 提供，chat-core/工具调用使用；模块不存在时调用方要能 no-op）

```python
# app/audit/context.py
def current_audit_id() -> str | None
def current_user_id() -> int | None

# app/audit/recorder.py
def record_event(event_type: str, execution_status: str | None = None, **fields) -> None
def record_tool_requested(tool_name: str, arguments: dict, audit_id: str | None,
                          user_id: int | None) -> str | None   # 返回 tool_call_id
async def check_tool_confirmation(tool_name: str, arguments: dict, ctx) -> str | None
# 如果需要确认且无有效票据：抛 ConfirmationRequired；返回已消费票据 id 或 None

# app/audit/middleware.py
class AuditMiddleware: ...   # 设置 contextvars、写请求事件、响应头 X-Audit-Id
```

`chat-core` 在每次工具执行前后尽力调用 recorder（用 try/except ImportError/Exception 包裹，审计失败不影响聊天）。

### 5) 会话/聊天使用的模型字段

见 `app/db/models.py`。会话列表排序、收藏、消息删除语义以 01 文档 §3.2 为准。
聊天落库：用户消息在调用模型前写；助手只写最终回答；标题 40 字见 `title_from_text()`。

### 6) 路由装配

`app/main.py` 动态加载：
`health, auth, admin, zipkin, conversations, user_memory, todo, bookmarks, notes, skills, audit, chat, legacy_chat`。
每个模块暴露 `router = APIRouter(...)`；protected 路由自己用 `Depends(current_user)`。
**路径不要带 `/api` 前缀**（由 Vite/nginx 剥离）。

## 文件所有权（禁止越界写）

| 负责人 | 写作用域 |
| --- | --- |
| Lead | `app/main.py`、`app/config.py`、`app/core/**`、`app/db/**`、`app/bootstrap.py`、`app/api/{auth,admin,zipkin,health}.py`、`tests/conftest.py`、`README.md`、`schema/**`、`deploy/**` |
| chat-core | `app/agent/**`、`app/memory/**`、`app/api/chat.py`、`app/api/legacy_chat.py` |
| api-modules | `app/api/conversations.py`、`app/domains/chat/**`、`app/api/user_memory.py`、`app/skills/**`、`app/api/skills.py` |
| domain-a | `app/domains/todo/**`、`app/api/todo.py`、`app/domains/sites/**`、`app/api/bookmarks.py` |
| notes-builder | `app/domains/notes/**`、`app/api/notes.py` |
| audit-builder | `app/audit/**`、`app/api/audit.py` |

测试文件按模块放在 `tests/` 下并用自己的名字前缀（如 `tests/test_notes.py`），避免抢文件。

## 参考源码（Java，只读）

- `swag_agent_backend/src/main/java/com/swag/<module>/`：精确行为以它为准。
- `docs/python-migration/01-api-contract.md`：端点/字段/错误/SSE。
- `docs/python-migration/02-data-model.md`：表/列/文件存储/记忆重建。
- `docs/python-migration/03-ai-core-mapping.md`：Agent/工具/审计/技能。
- 真实 schema 快照：`swag_agent_backend_py/schema/mysql_schema.sql`（已从线上库只读导出）。

## 完成时

`team_task_update` 置 complete，并 `send_message` 给 lead：
完成了哪些文件/端点/工具、如何自测（命令/结果）、未完成/待确认项、与其他模块的接口是否有偏差。
