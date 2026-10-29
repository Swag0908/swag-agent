# swag_agent Python 后端（FastAPI）

Java 后端（`../swag_agent_backend/`）的契约兼容重写版。目标：前端、数据库、nginx 均不改，
只把后端运行时从 Spring Boot 换成 FastAPI。**Java 服务保持运行**，本目录只是新实现。

## 当前状态

**65 个端点全部实现，251 个测试通过**；真实 MySQL 读接口与真实 DeepSeek SSE 聊天已验证。
Java 后端保持运行、未被修改；切换到 Python 由用户验收后自行执行。

| 模块 | 状态 |
| --- | --- |
| 基础设施（配置/错误/鉴权中间件/DB 模型/health） | ✅ |
| 认证 / 管理员 / Zipkin Cookie | ✅ |
| Agent 核心 + SSE 聊天 + 三层记忆 | ✅ |
| 会话管理 / 用户记忆 / 技能包 | ✅ |
| 待办 / 常用网站 | ✅ |
| Markdown 笔记 | ✅ |
| 审计 / 危险操作确认 / 调用链 | ✅ |

详细验证记录与已知差异见 [`../docs/python-migration/04-implementation-status.md`](../docs/python-migration/04-implementation-status.md)。

## 运行

要求 Python 3.12（系统默认 3.9 不适用）。本目录已带 `.venv/`：

```bash
cd swag_agent_backend_py
cp .env.example .env      # 填入 MySQL / DeepSeek / Tavily 等配置；.env 已被 gitignore
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8081
```

- 健康检查：`GET http://127.0.0.1:8081/actuator/health`
- Java 后端仍在 `8080`；前端 Vite 代理默认指向 8080。要预览 Python 版，把
  `swag_agent_web/vite.config.js` 的 target 临时改成 `http://localhost:8081`（不要提交）。
- 数据库：与 Java 共用同一个 MySQL 库；**不建表、不迁移结构**。PG/pgvector 用于向量记忆，
  PG 不可用时聊天与用户记忆会自动降级。

## 测试

```bash
.venv/bin/python -m pytest -q
```

单元测试使用 SQLite / 临时目录 / fake LLM，不写真实 MySQL，也不调用真实 DeepSeek。
需要真实库的验证请单独跑只读脚本（见 `scripts/`）。

## 关键文档

- [迁移总方案](../docs/python-migration/00-python-migration-plan.md)
- [接口契约](../docs/python-migration/01-api-contract.md)
- [数据模型](../docs/python-migration/02-data-model.md)
- [AI 核心映射](../docs/python-migration/03-ai-core-mapping.md)
- [协作契约（模块接口/文件所有权）](CONTRACTS.md)

## 目录

```text
app/
  main.py config.py bootstrap.py
  core/       errors / security / timeutil / middleware
  db/         base / pg / models
  api/        auth admin zipkin health conversations user_memory todo bookmarks notes skills audit chat legacy_chat
  agent/      llm / prompt / runner / stream / tools
  memory/     short / long / user_memory / rebuild
  audit/      context / middleware / recorder / digest / confirmation
  domains/    auth chat todo sites notes
  skills/     registry / markdown / assembler / installer
  jobs/       scheduler
tests/
schema/mysql_schema.sql   # 线上库只读快照（建表 DDL 的事实来源）
deploy/                   # systemd unit + 发布脚本（不含密钥）
```

## 安全

- 所有密钥走环境变量 / `.env`；`.env` 不入库。
- 旧 Java 的 `application-dev.properties` 含真实 key，迁移完成后建议轮换 DeepSeek/Tavily/DB 口令。
- 日志不打印 prompt、token、工具入参原文（审计默认只存 digest）。
