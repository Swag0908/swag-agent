# SWAG Agent Backend

基于 Spring Boot、Spring AI 和 DeepSeek 的智能体后端服务。

## 运行

在当前目录配置 `DEEPSEEK_API_KEY`、`MYSQL_PASSWORD` 等本地环境变量后执行：

```bash
./mvnw spring-boot:run
```

服务默认监听 `http://localhost:8080`。

本地专用的 `src/main/resources/application-dev.properties` 已被 Git 忽略，
请勿提交密钥或数据库密码。

## 技能包（Skill）

技能 = 一个含 `SKILL.md` 的目录（frontmatter 写 `name`/`description`，正文是给模型的领域指南）。
网上公开的 agent skill 目录可直接拿来用，**不需要为它写 Java**：`SKILL.md` 正文会作为提示词注入
system prompt（见 `TestController.buildSystemPrompt`）；技能目录里的脚本/资源不会被自动执行。

两种来源，同名时外部覆盖内置：

| 来源 | 位置 | 说明 |
| --- | --- | --- |
| 内置 | `src/main/resources/skills/<name>/SKILL.md` | 随 jar 发布、团队共享 |
| 外部 | `app.skills.external-root`（默认 `./skills-data`） | 运行时安装/热插拔，已加入 `.gitignore` |

放置即生效：目录内容变化后无需重启，下一轮对话自动带上（`SkillRegistry` 按目录 mtime 重扫）。

管理端接口（仅 ADMIN，前缀 `/auth/admin/skills`）：

| 方法/路径 | 说明 |
| --- | --- |
| `GET /auth/admin/skills` | 列出全部技能（名称、描述、启停、来源、正文长度、文件路径） |
| `PUT /auth/admin/skills/{name}` | 启停某技能，body `{"enabled": false}` |
| `POST /auth/admin/skills/refresh` | 重新扫描目录（手工拷贝技能后可用） |
| `POST /auth/admin/skills/install` | 从 Git 仓库安装，body `{"repoUrl":"anthropics/skills","skillPath":"skills/webapp-testing"}` |
| `DELETE /auth/admin/skills/{name}` | 删除外部技能（内置技能不可删） |

配置项见 `application.properties` 中的 `app.skills.*`（外部目录、是否注入、正文注入上限、安装开关与超时）。

启停状态**落库**：表 `skill_state`（Flyway 迁移 `db/migration/V2__skill_state.sql`）。语义是「表里没有该技能
= 启用」，所以新装技能开箱即用、只有被显式停用过的才写入；重启、多实例部署后设置依然保持，技能被删除时
顺带清理其状态行。

前端入口：`/skills` 技能管理页（`swag_agent_web/src/views/SkillsView.vue`，`api/skills.js`）——管理员可从
聊天页侧栏、「更多」菜单或效率统计页顶栏进入，页面里可安装 / 启停 / 删除技能。

可选冒烟测试（默认跳过，需联网或显式指定目录）：

```bash
# 从 GitHub 真实安装一个公开技能到 ./skills-data
./mvnw test -Dtest=SkillInstallerNetworkTests -Dswag.skills.installTarget=skills-data \
  -Dswag.skills.installRepo=anthropics/skills -Dswag.skills.installSkillPath=skills/webapp-testing

# 校验磁盘上已有的技能目录能否被扫描解析
./mvnw test -Dtest=SkillExternalDirSmokeTests -Dswag.skills.demoRoot=skills-data
```

注意：技能是外部文本，注入时带安全护栏（与系统规则冲突时以系统规则为准）。需要"真正能执行的外部能力"
（浏览器、GitHub、数据库等）应接 MCP server 或写成 `@Tool`，不要依赖技能目录里的脚本。
