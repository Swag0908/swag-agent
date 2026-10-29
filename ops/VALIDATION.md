# 发布准备验证记录

验证日期：2026-10-29（Asia/Shanghai）。
候选发布 ID：`7974db67e978-c5129ddb9c85`，对应仓库 `release/manifest.json`。

已实际完成：

- Python 单元/契约测试：251 passed。
- 部署安全与回滚测试：12 passed，覆盖坏包、危险归档、Nginx 布局变化、回滚失败及回滚后健康失败。
- 真实前端模块的 Python/Java SSE 格式与跨字节分块测试：通过。
- 前端冻结锁文件安装及 Vite 生产构建：通过。
- Python wheel 脱离源码目录独立导入：13 个模块、67 个 OpenAPI 操作全部加载。
- 发布文件 SHA-256、wheel 和前端归档内容检查：通过；未发现密钥格式匹配项。
- 真实服务器 Linux x86_64 / Docker / Python 3.12 镜像：构建成功。
- 候选容器真实 MySQL 表/字段、Ollama embedding、pgvector 相似度查询：通过。
- 现有管理员登录 token、无 token 的 401、会话/消息、记忆、书签、待办/统计、笔记、技能、
  审计链和 Zipkin Cookie 鉴权：通过。
- Flash、Pro 真实 SSE：均出现 ready、tool_call、content、done，无 error；临时 token 已删除。
- 镜像内 mysqldump 对生产库的一致性备份：成功；备份只保留在服务器私有目录。

本次只完成旁路准备，候选容器已删除。Java 服务继续运行且健康，Nginx 和现网前端未切换。
正式发布时 `ops/deploy.sh deploy` 会重新备份、复查候选与切换后的接口/静态资源，不能跳过。

尚未执行：生产切换、切换后的浏览器视觉/复杂写入验收、真实生产故障回滚演练。
已知差异：Python 尚未向 Zipkin 上报新 trace；审计接口和旧 trace 查询不代表这项功能已补齐。
