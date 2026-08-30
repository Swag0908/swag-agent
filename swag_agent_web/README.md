# SWAG Agent Web（测试版）

一个用 **Vite + Vue 3** 构建的智能体前端，包含聊天、用户认证、待办和统计页面。

## 技术栈

- Vue 3（`<script setup>` 组合式 API）
- Vite 6
- marked + DOMPurify（Markdown 渲染 / XSS 消毒）
- 原生 CSS（深色为主，可切换浅色，无 UI 框架）

## 目录结构

```
swag_agent_web/
├── index.html
├── vite.config.js          # /api 代理 → http://localhost:8080
├── package.json
└── src/
    ├── main.js
    ├── router.js
    ├── auth.js
    ├── styles.css          # 设计令牌 + 全局样式
    ├── App.vue
    ├── api/                # 聊天、认证和待办接口
    ├── composables/useChat.js
    └── components/
        ├── ChatMessage.vue   # 消息气泡（Markdown）
        ├── ChatInput.vue     # 输入框
        ├── ModelSelector.vue # 模型选择
        ├── EmptyState.vue    # 欢迎/空状态
        └── TodoPanel.vue     # 待办面板
```

## 运行

### 1. 启动后端（`swag_agent_backend` 目录）

```bash
cd ../swag_agent_backend
# 需配置环境变量：DEEPSEEK_API_KEY、MYSQL_PASSWORD
./mvnw spring-boot:run
```

后端默认监听 `http://localhost:8080`，新增的流式接口为：

```
GET /test/chat/stream?model=1&userInput=你好
```

> 返回 `text/plain` 纯文本流（逐字输出）。旧的 `GET /test/chat` 仍可用（整段返回）。

### 2. 启动前端（本目录）

```bash
pnpm install   # 或 npm install
pnpm dev       # 或 npm run dev
```

浏览器打开 **http://localhost:5173**。

前端通过 Vite 代理把 `/api/*` 转发到 `http://localhost:8080`，因此**无需在后端配置 CORS**。

### 3. 生产构建（可选）

```bash
pnpm build
pnpm preview
```

## 说明与已知限制（测试版）

- **无多轮上下文记忆**：后端接口是单轮无状态调用，前端仅本地展示历史消息，智能体不记得之前的对话。
- **仅模型 1 可用**：后端 `SelectModelTool` 目前只支持 `model=1`（DeepSeek V4 Pro）。
- 主题偏好、会话均只保存在浏览器本地（`localStorage` / 内存），刷新后消息清空。

## 后续可扩展

- 后端：增加会话上下文（把历史消息一起传入）、更多模型、SSE `ServerSentEvent` 标准帧。
- 前端：会话列表持久化、代码高亮、语音输入、停止后继续补全。
