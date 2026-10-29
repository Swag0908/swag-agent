#!/usr/bin/env bash
# 一键发布 Python 后端（在 Mac 本地运行）。
# 用法：
#   SERVER_HOST=1.2.3.4 SERVER_USER=root ./deploy/publish_backend_py.sh
#   DRY_RUN=1 ... 只打包不传输。
#
# 前置：服务器已安装 Python 3.12、已创建 /opt/swag_agent/backend_py、.env 已配置、
#       systemd 服务名默认 swag-agent-py（unit 见 swag-agent-py.service）。
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REMOTE_DIR="${REMOTE_DIR:-/opt/swag_agent/backend_py}"
SERVICE="${SERVICE:-swag-agent-py}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8081/actuator/health}"

: "${SERVER_HOST:?请设置 SERVER_HOST}"
SERVER_USER="${SERVER_USER:-root}"
SSH_PORT="${SSH_PORT:-22}"

step() { printf '\n==> %s\n' "$*"; }

step "本地检查"
cd "$APP_DIR"
[ -x .venv/bin/python ] || { echo "缺少 .venv（python3.12 -m venv .venv）"; exit 1; }
.venv/bin/python -m compileall -q app
.venv/bin/python -m pytest -q

step "同步代码（保留远端 .env 与 .venv）"
if [ "${DRY_RUN:-0}" = "1" ]; then
  echo "DRY_RUN：跳过 rsync/ssh"
  exit 0
fi
rsync -az --delete \
  --exclude '.venv' --exclude '.env' --exclude '__pycache__' --exclude 'notes-data' \
  --exclude 'skills-data' --exclude '.pytest_cache' --exclude 'schema' \
  -e "ssh -p ${SSH_PORT}" \
  "$APP_DIR/" "${SERVER_USER}@${SERVER_HOST}:${REMOTE_DIR}/"

step "重启服务"
ssh -p "${SSH_PORT}" "${SERVER_USER}@${SERVER_HOST}" "systemctl restart ${SERVICE}"

step "健康检查"
for _ in $(seq 1 30); do
  code="$(ssh -p "${SSH_PORT}" "${SERVER_USER}@${SERVER_HOST}" \
    "curl -m 3 -s -o /dev/null -w '%{http_code}' '${HEALTH_URL}' || echo 000")"
  if [ "$code" = "200" ]; then
    echo "发布成功 ✅ ${HEALTH_URL} = 200"
    exit 0
  fi
  sleep 2
done

echo "健康检查超时，最近日志："
ssh -p "${SSH_PORT}" "${SERVER_USER}@${SERVER_HOST}" "journalctl -u ${SERVICE} -n 60 --no-pager" || true
exit 1
