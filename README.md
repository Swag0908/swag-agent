# swag-agent

智能体项目，前后端合并在**同一个 GitHub 仓库**（monorepo）中托管：

```
swag-agent/
├── pom.xml / mvnw / src/   # 后端：Spring Boot + Spring AI (DeepSeek)，位于仓库根目录
└── web/                    # 前端：Vite + Vue 3 聊天界面
```

远程仓库：`git@github.com:Swag0908/swag-agent.git`

## 子项目

| 目录 | 说明 | 端口 |
| --- | --- | --- |
| 仓库根目录（`backend`） | 后端服务（含 `/test/chat` 与 `/test/chat/stream` 接口） | 8080 |
| `web/` | 前端聊天页（Vite + Vue 3，深色为主可切换浅色） | 5173 |

## 快速开始

```bash
# 1. 启动后端（需配置 DEEPSEEK_API_KEY / MYSQL_PASSWORD）
./mvnw spring-boot:run

# 2. 启动前端（另开终端）
cd web
pnpm install
pnpm dev
```

浏览器打开 **http://localhost:5173**。

## 结构说明

- **后端**代码位于仓库根目录（`src/main/java/com/swag/...`）。
- **前端**代码位于 `web/` 目录，通过 Vite 代理把 `/api/*` 转发到 `http://localhost:8080`，无需后端配置 CORS。
- 两端各自的 `.gitignore` 已配置：后端忽略 `target/`、`application-dev.properties`（含密钥）等；前端忽略 `node_modules/`、`dist/`、`.idea/` 等。
