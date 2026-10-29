#!/usr/bin/env sh
set -eu
# 镜像内启动入口；单 worker 避免重复定时任务与进程内 SSE 事件丢失。
exec python -m uvicorn app.main:app \
  --host "${UVICORN_HOST:-127.0.0.1}" --port "${UVICORN_PORT:-8081}" \
  --workers 1 --proxy-headers --forwarded-allow-ips=127.0.0.1
