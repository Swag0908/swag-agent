# 前端与 Python 后端发布

本目录是可提交的部署代码；服务器地址、SSH 私钥、模型与数据库密码不入库。
当前电脑优先读取已有的 `deploy/config.env`，必要时用 `ops/local.env` 覆盖配置。
新电脑可从 `ops/local.env.example` 创建本地配置。

## 用户发出部署指令时

在仓库根目录执行：

```bash
./ops/deploy.sh check       # 只读检查 Docker、Nginx、线上配置与数据路径
./ops/deploy.sh deploy      # 上传已有发布包，验收通过后切换前端与 Python 后端
./ops/deploy.sh status
```

用户可以直接说：“星期五，部署前端和 Python 后端”。准备阶段使用 `stage`，只构建镜像并旁路验收，
不改 Nginx、不停止 Java、不替换现网前端。正式切换等待用户的部署指令。

代码有变化时先运行 `./ops/package.sh`，并将源码改动与生成的 `release/` 一起审核提交。
脚本自动运行 Python 测试、部署安全测试、SSE 兼容测试，按前端锁文件安装依赖并构建，
再生成 wheel、前端压缩包、版本清单和 SHA-256 校验文件。只在全部成功后更新发布包。

## 发布产物

`release/` 包含 Python wheel、带版本和哈希的生产依赖锁、Dockerfile、启动与验收脚本、
前端 `web.tar.gz`。这些文件直接上传 GitHub，服务器无需从源码仓库临时构建前端。

Python wheel 是可安装的构建产物，包含跨平台 Python 模块；不把 Mac 虚拟环境或 Mac 生成的
`.pyc` 当成 Linux 程序上传。Docker 镜像内使用 Python 3.12 安装 wheel 并编译字节码。
目前服务器为 CentOS 7 / glibc 2.17，使用已安装的 Docker 提供运行环境。

依赖版本及包哈希已固定；首次构建仍需能访问 Docker 镜像仓库、Debian 软件源和 PyPI。
Debian 和 PyPI 默认使用清华 HTTPS 镜像，软件源保留 Debian 签名校验，Python 包保留锁文件哈希校验；
构建参数可覆盖镜像地址。
构建成功后服务器保留镜像，后续相同发布包直接复用。基础镜像标签是 `python:3.12-slim-bookworm`；
正式发布记录中同时保存实际镜像 ID。

## 迁移与验收

1. 校验完整发布包，构建镜像；这一阶段现网继续由原后端处理。
2. 首次迁移从**正在运行的 Java 进程环境与 jar 配置**读取真实 MySQL、PG、DeepSeek、Tavily、
   Ollama 和笔记/技能路径。配置写入服务器 `backend.env`，权限 `600`，之后不自动覆盖。
   不上传本机开发 `.env`，不打印密钥。当前 jar 无内置技能；未来若出现内置技能，脚本会拒绝
   静默跳过，要求先把它们纳入 Python 发布包。
3. 正式切换前对 MySQL 做 `--single-transaction` 备份，备份笔记、技能与 Nginx 配置。
   备份目录只允许 root 访问；普通部署不建表、不迁移表结构。
4. Python 候选容器监听回环地址 `18081`，关闭 bootstrap、scheduler 和审计写入。
   检查真实表和字段、Ollama embedding、pgvector 相似度查询、现有登录 token、管理员身份、
   会话/消息、记忆、待办/统计、书签、笔记、技能、审计链、Zipkin 访问鉴权。
   Flash 和 Pro 各执行一次真实 SSE 工具调用，必须包含 ready、工具、正文和 done，不能有 error。
5. 通过后停止 Java 和旧 Python 实例，启动正式 Python 容器 `8081`，开启单实例定时任务。
   新前端放入独立版本目录；旧静态资源保留，避免已打开的页面请求旧资源时 404。
   同一次 Nginx reload 切换静态目录、API 和 Zipkin 鉴权代理，保留 SSE 配置，上传上限设为 100MB。
6. 通过 Nginx 再跑真实 API、两种模型 SSE、前端首页哈希、页面路由和 JS/CSS 资源检查。
   全部通过才记录发布成功、关闭 Java 开机启动。Docker `unless-stopped` 负责 Python 容器重启。
   Python 启用 Spring AI 短期记忆双写，便于回滚 Java。

验收会创建一个 15 分钟有效的临时管理员 token，结束时删除；不传 conversationId，因此不创建
业务会话。部分 GET 接口与正常页面访问一样，会补齐昨日统计、初始化默认笔记目录或清理失效技能状态。
正式服务的正常审计事件会保留。真实 SSE 和 embedding 验收会调用已配置的模型服务。

## 启动、状态与回滚

```bash
./ops/deploy.sh start       # 启动已部署的 Python 容器
./ops/deploy.sh restart
./ops/deploy.sh status
./ops/deploy.sh rollback    # 恢复上一版后端、前端与 Nginx
```

镜像内启动入口是 `ops/start_backend.sh`：只运行一个 Uvicorn worker，绑定回环地址。
此流程不安装旧的 `swag-agent-py.service`，也不使用旧 Java 发布脚本。

切换阶段任何检查失败会尝试自动恢复原容器或 Java、原前端与 Nginx。回滚失败会明确返回非零状态，
不能宣称成功。发布状态、实际镜像 ID 和备份位置保存在 `PY_REMOTE_ROOT` 下。
手动回滚只恢复服务与路由，**不自动还原数据库**，避免覆盖切换后产生的新数据。
`rollback` 只支持回到最近一次发布前的状态，完成后将回滚记录归档，防止重复删除容器。

## 验证边界

`check` 是预检通过，`stage` 是旁路验收通过，只有 `deploy` 的全部检查通过才是生产迁移完成。
网络、镜像源、模型账号或实际数据结构有问题时会停止，不能提前保证未执行的切换成功。
目前 Python 仍不向 Zipkin 上报新 trace；审计接口、旧 trace 查询与管理员鉴权可用。
浏览器视觉与复杂业务写入流程仍需部署后人工验收，脚本不以只读检查替代这些体验验证。

实现依据：[uv 构建文档](https://docs.astral.sh/uv/guides/package/)、
[Docker host 网络](https://docs.docker.com/engine/network/drivers/host/)、
[Docker HEALTHCHECK](https://docs.docker.com/reference/dockerfile/#healthcheck)。
