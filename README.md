# swag_agent

智能体项目（monorepo），前后端代码统一托管在**同一个仓库**中：

```
swag_agent/
├── README.md
├── swag_agent_backend/   # 后端：Spring Boot + Spring AI + DeepSeek（端口 8080）
├── swag_agent_backend_py/ # 后端：Python / FastAPI（端口 8081）
├── swag_agent_web/       # 前端：Vite + Vue 3 流式聊天界面（端口 5173）
├── ops/                 # 构建、旁路验收、统一部署和回滚
└── release/             # 已构建的 Python wheel 与前端静态发布包
```

远程仓库：`git@github.com:Swag0908/swag-agent.git`

## 子项目

| 目录 | 说明 |
| --- | --- |
| `swag_agent_backend` | 后端服务，提供 `/test/chat` 与 `/test/chat/stream` 接口，默认端口 8080 |
| `swag_agent_web` | 前端聊天页（Vite + Vue 3，深色为主可切换浅色），默认端口 5173 |

## 快速开始

```bash
# 1. 启动后端（需配置 DEEPSEEK_API_KEY / MYSQL_PASSWORD 等环境变量）
cd swag_agent_backend
./mvnw spring-boot:run

# 2. 启动前端（另开终端）
cd swag_agent_web
pnpm install
pnpm dev
```

浏览器打开 **http://localhost:5173**。当前 Vite 代理把 `/api/*` 转发到 Python 后端
`http://localhost:8081`；如运行上述 Java 示例，请把代理改为 `8080`。生产迁移与发布请使用
[统一部署说明](ops/README.md)，`./ops/deploy.sh check` 可先只读检查服务器。

## Git 约定

仓库根目录（`swag_agent/`）是**唯一的 Git 工作区**。前后端目录不再分别维护独立的
`.git`，所有变更都从仓库根目录统一提交和推送。
