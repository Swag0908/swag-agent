#!/usr/bin/env bash
# ============================================================
# swag_agent_backend 一键：本地打包 jar -> 上传服务器 -> 安装并启动 -> 健康检查
# 在 Mac 上执行，一条命令搞定。
#
# 用法：
#   先把下面 SERVER 改成你的服务器，然后：
#     ./publish_swag_backend.sh
#   或临时指定：
#     SERVER=root@1.2.3.4 ./publish_swag_backend.sh
#
# 前提：本机可 ssh/scp 登录服务器（配了密钥最佳；没配会提示输密码）。
# 若以 root 登录且服务器没装 sudo，把脚本里的两处 sudo 删掉即可。
# ============================================================
set -euo pipefail

SERVER="${SERVER:-root@<服务器IP>}"          # ← 改成你的服务器 IP
BACKEND_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # = swag_agent_backend/
DEPLOY_DIR="${BACKEND_DIR}/deploy"
JAR_NAME="swag_agent-0.0.1-SNAPSHOT.jar"
REMOTE_BASE="/opt/swag-agent/backend"
JAVA_HOME_21="$HOME/Library/Java/JavaVirtualMachines/corretto-21.0.7/Contents/Home"

# 复用同一 ssh 连接，避免多次输密码
SSHOPTS=(-o ControlMaster=auto -o ControlPath=/tmp/ssh-swag-%r@%h:%p -o ControlPersist=300)

echo "==> 目标服务器：${SERVER}"

# 判断远端是不是 root，决定要不要 sudo
if ssh "${SSHOPTS[@]}" "${SERVER}" 'id -u' 2>/dev/null | grep -q '^0$'; then
    SUDO=""
else
    SUDO="sudo"
fi

# 1) 本地打包（JDK 21，跳过测试）
echo "==> [1/4] 本地打包 jar ..."
(cd "${BACKEND_DIR}" && JAVA_HOME="${JAVA_HOME_21}" ./mvnw -DskipTests clean package)

# 2) 上传 jar
echo "==> [2/4] 上传 jar 到 ${SERVER}:${REMOTE_BASE}/ ..."
ssh "${SSHOPTS[@]}" "${SERVER}" "mkdir -p ${REMOTE_BASE}"
scp "${SSHOPTS[@]}" "${BACKEND_DIR}/target/${JAR_NAME}" "${SERVER}:${REMOTE_BASE}/${JAR_NAME}"

# 3) 上传部署文件（unit + env + 重启脚本）
echo "==> [3/4] 上传部署文件 ..."
ssh "${SSHOPTS[@]}" "${SERVER}" "mkdir -p /root/swag-deploy"
scp "${SSHOPTS[@]}" \
    "${DEPLOY_DIR}/swag-agent-backend.service" \
    "${DEPLOY_DIR}/swag-agent-backend.env" \
    "${DEPLOY_DIR}/restart_swag_backend.sh" \
    "${SERVER}:/root/swag-deploy/"

# 4) 服务器上：装密钥（不存在才装）+ 启动服务
echo "==> [4/4] 服务器上安装服务并启动 ..."
ssh "${SSHOPTS[@]}" "${SERVER}" "${SUDO} bash -c '
set -e
if [ ! -f /etc/swag-agent-backend.env ]; then
    install -m 600 /root/swag-deploy/swag-agent-backend.env /etc/swag-agent-backend.env
fi
bash /root/swag-deploy/restart_swag_backend.sh
'"

ssh "${SSHOPTS[@]}" -O exit "${SERVER}" 2>/dev/null || true
echo "✔ 打包、上传、启动全部完成"
