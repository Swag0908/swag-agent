# swag-agent

智能体项目，前后端统一托管在同一个 GitHub 仓库中。

## 项目结构

```text
swag-agent/
├── README.md
├── swag_agent_backend/   # Spring Boot + Spring AI
└── swag_agent_web/       # Vite + Vue 3
```

远程仓库：`git@github.com:Swag0908/swag-agent.git`

## 本地启动

启动后端（默认端口 `8080`）：

```bash
cd swag_agent_backend
./mvnw spring-boot:run
```

启动前端（默认端口 `5173`）：

```bash
cd swag_agent_web
pnpm install
pnpm dev
```

前端通过 Vite 代理访问后端 API。启动前请按需配置
`DEEPSEEK_API_KEY`、`MYSQL_PASSWORD` 等本地环境变量。

## Git 约定

仓库根目录是唯一的 Git 工作区。前后端目录不再分别维护独立的
`.git`，所有变更都从仓库根目录统一提交和推送。
