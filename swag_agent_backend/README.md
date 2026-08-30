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
