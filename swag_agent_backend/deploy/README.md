# swag-agent-backend 服务器部署（systemd）

针对 **Linux 云服务器** 的部署文件，服务以 root 运行、jar 位于
`/opt/swag-agent/backend/swag_agent-0.0.1-SNAPSHOT.jar`。

## 文件清单

| 文件 | 作用 |
| --- | --- |
| `swag-agent-backend.service` | systemd 服务单元（即之前那份 `[Unit]…` 的标准写法） |
| `swag-agent-backend.env.example` | 密钥/环境变量模板 → 服务器 `/etc/swag-agent-backend.env` |
| `restart_swag_backend.sh` | 一键重启脚本（含首次安装） |

## 首次部署（在服务器上）

```bash
# 1. 把整个 deploy 目录传到服务器（或至少传这三个文件）
#    本地执行：
#    scp -r swag_agent_backend/deploy root@<服务器IP>:/root/swag-deploy

# 2. 上传打包好的 jar（先在本地重新打包，保证代码最新）
#    本地执行（仓库根目录）：
#    cd swag_agent_backend && ./mvnw -DskipTests package
#    scp target/swag_agent-0.0.1-SNAPSHOT.jar root@<服务器IP>:/opt/swag-agent/backend/

# 3. 服务器上：创建部署目录并准备密钥文件
sudo mkdir -p /opt/swag-agent/backend
sudo cp /root/swag-deploy/swag-agent-backend.env.example /etc/swag-agent-backend.env
sudo chmod 600 /etc/swag-agent-backend.env
sudo vim /etc/swag-agent-backend.env     # 填入 DEEPSEEK_API_KEY / MYSQL_PASSWORD / TAVILY_API_KEY

# 4. 一键重启（首次会自动安装 unit 并 enable）
sudo bash /root/swag-deploy/restart_swag_backend.sh
```

> 若 jar 是在服务器上 `git clone` 后打包的：`application-dev.properties` 被 git
> 忽略不会进仓库，此时 jar 内没有数据库地址，务必在 env 文件里打开
> `SPRING_DATASOURCE_URL` / `SPRING_DATASOURCE_USERNAME` 两行。
> 若 jar 是在本地（含 application-dev.properties）打包后传上去的，则可不配。

## 日常重启

```bash
sudo bash /root/swag-deploy/restart_swag_backend.sh   # 重启 + 健康检查
# 等价于：
# sudo systemctl restart swag-agent-backend
```

## 常用命令

```bash
sudo systemctl status swag-agent-backend     # 状态
journalctl -u swag-agent-backend -f          # 实时日志
journalctl -u swag-agent-backend -n 100      # 最近 100 行
sudo systemctl stop swag-agent-backend       # 停止
sudo systemctl disable --now swag-agent-backend   # 停止并取消开机自启
curl http://127.0.0.1:8080/actuator/health   # 健康检查
```

## 更新后端代码后

```bash
# 本地：重新打包并上传
cd swag_agent_backend && ./mvnw -DskipTests package
scp target/swag_agent-0.0.1-SNAPSHOT.jar root@<服务器IP>:/opt/swag-agent/backend/

# 服务器：重启即可
sudo bash /root/swag-deploy/restart_swag_backend.sh
```
