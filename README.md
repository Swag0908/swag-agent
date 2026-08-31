# swag_agent

智能体项目（monorepo），前后端代码统一托管在**同一个仓库**中：

```
swag_agent/
├── README.md
├── swag_agent_backend/   # 后端：Spring Boot + Spring AI + DeepSeek（端口 8080）
└── swag_agent_web/       # 前端：Vite + Vue 3 流式聊天界面（端口 5173）
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

浏览器打开 **http://localhost:5173**。前端通过 Vite 代理把 `/api/*` 转发到后端
`http://localhost:8080`，无需在后端配置 CORS。

## Git 约定

仓库根目录（`swag_agent/`）是**唯一的 Git 工作区**。前后端目录不再分别维护独立的
`.git`，所有变更都从仓库根目录统一提交和推送。
