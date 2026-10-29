#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
# 统一发布前端和 Python 后端；先运行 check/stage，正式切换使用 deploy。
exec "$ROOT/ops/deploy.sh" "${1:-check}"
