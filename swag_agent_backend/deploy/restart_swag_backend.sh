#!/usr/bin/env bash
# ============================================================
# swag-agent-backend 一键重启脚本（服务器上用 root 执行）
#
# 功能：
#   1. 校验 jar / env 文件是否存在
#   2. 首次运行自动安装并启用 systemd 服务
#   3. 之后每次运行 = 重启服务 + 等待健康检查 + 打印状态
#
# 用法：
#   sudo bash restart_swag_backend.sh
# 如需强制覆盖 /etc/systemd/system 里的 unit：
#   sudo FORCE_INSTALL=1 bash restart_swag_backend.sh
# ============================================================
set -euo pipefail

SERVICE=swag-agent-backend
UNIT=/etc/systemd/system/${SERVICE}.service
DEPLOY_DIR=/opt/swag-agent/backend
JAR=${DEPLOY_DIR}/swag_agent-0.0.1-SNAPSHOT.jar
ENV_FILE=/etc/swag-agent-backend.env
HEALTH_URL=http://127.0.0.1:8080/actuator/health

# 脚本所在目录（用于找到同目录的 .service 文件）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCAL_UNIT="${SCRIPT_DIR}/swag-agent-backend.service"

# ---------- 前置检查 ----------
if [[ $EUID -ne 0 ]]; then
    echo "✘ 请用 root 执行：sudo bash $0" >&2
    exit 1
fi
if [[ ! -f "${JAR}" ]]; then
    echo "✘ 找不到 ${JAR}" >&2
    echo "  请先把打包好的 jar 放到 ${DEPLOY_DIR}/ 下（文件名保持 swag_agent-0.0.1-SNAPSHOT.jar）" >&2
    echo "  例如：scp target/swag_agent-0.0.1-SNAPSHOT.jar root@<服务器IP>:${DEPLOY_DIR}/" >&2
    exit 1
fi
if [[ ! -f "${ENV_FILE}" ]]; then
    echo "✘ 找不到 ${ENV_FILE}" >&2
    echo "  请先创建（模板：${SCRIPT_DIR}/swag-agent-backend.env.example）并 chmod 600" >&2
    exit 1
fi
chmod 600 "${ENV_FILE}"

# ---------- 安装/更新 systemd unit ----------
mkdir -p "${DEPLOY_DIR}"
if [[ ! -f "${UNIT}" ]] || [[ "${FORCE_INSTALL:-0}" == "1" ]] \
   || { [[ -f "${LOCAL_UNIT}" ]] && ! cmp -s "${LOCAL_UNIT}" "${UNIT}"; }; then
    if [[ -f "${LOCAL_UNIT}" ]]; then
        echo "==> 安装/更新 unit 文件 -> ${UNIT}"
        install -m 644 "${LOCAL_UNIT}" "${UNIT}"
    else
        echo "⚠ 本目录没有 swag-agent-backend.service，假定 ${UNIT} 已存在且配置正确"
    fi
    systemctl daemon-reload
    systemctl enable "${SERVICE}"
fi

# ---------- 重启 ----------
echo "==> 重启 ${SERVICE} ..."
systemctl restart "${SERVICE}"

# ---------- 等待健康检查 ----------
echo "==> 等待健康检查：${HEALTH_URL}"
for i in $(seq 1 30); do
    if curl -fsS "${HEALTH_URL}" >/dev/null 2>&1; then
        echo "✔ 服务已就绪（第 ${i} 秒探测成功）"
        systemctl status "${SERVICE}" --no-pager -l | head -15
        echo
        echo "✔ 完成。查看实时日志：journalctl -u ${SERVICE} -f"
        exit 0
    fi
    sleep 1
done

echo "✘ 30 秒内未通过健康检查，最近的日志如下：" >&2
journalctl -u "${SERVICE}" -n 60 --no-pager >&2
systemctl status "${SERVICE}" --no-pager -l >&2
exit 1
