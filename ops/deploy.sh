#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ACTION="${1:-check}"
case "$ACTION" in
  check|stage|deploy|rollback|status|start|restart) ;;
  *) echo '用法: ops/deploy.sh check|stage|deploy|rollback|status|start|restart' >&2; exit 2 ;;
esac
# 复用本机已有配置；这些文件被 gitignore 忽略，绝不进入发布包。
if [ -f "$ROOT/deploy/config.env" ]; then source "$ROOT/deploy/config.env"; fi
if [ -f "$ROOT/ops/local.env" ]; then source "$ROOT/ops/local.env"; fi
: "${SERVER_HOST:?请配置 deploy/config.env 或 ops/local.env}"
SSH_USER="${SSH_USER:-root}"
SSH_PORT="${SSH_PORT:-22}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/id_ed25519}"
REMOTE_ROOT="${PY_REMOTE_ROOT:-/opt/swag_agent/python-deploy}"
NGINX_CONFIG="${PY_NGINX_CONFIG:-/etc/nginx/conf.d/swag-agent.conf}"
JAVA_SERVICE="${BACKEND_SERVICE:-swag-agent}"
SITE_HOST="${PY_SITE_HOST:-$(python3 - "${WEB_SMOKE_URL:-http://$SERVER_HOST}" <<'PY'
from urllib.parse import urlparse
import sys
print(urlparse(sys.argv[1]).hostname)
PY
)}"
for value in "$REMOTE_ROOT" "$NGINX_CONFIG"; do
  [[ "$value" =~ ^/[a-zA-Z0-9_./-]+$ ]] || { echo '远端路径必须是无空格的绝对路径' >&2; exit 2; }
done
CONFIG="$(python3 - "$REMOTE_ROOT" "$NGINX_CONFIG" "$JAVA_SERVICE" "$SITE_HOST" <<'PY'
import json, sys
print(json.dumps(dict(zip(['remote_root','nginx_config','java_service','site_host'], sys.argv[1:]))))
PY
)"
SSH_ARGS=(-o BatchMode=yes -o ConnectTimeout=15 -o StrictHostKeyChecking=accept-new -p "$SSH_PORT")
SCP_ARGS=(-o BatchMode=yes -o ConnectTimeout=15 -o StrictHostKeyChecking=accept-new -P "$SSH_PORT")
if [ -n "${SSH_PASSWORD:-}" ]; then
  command -v sshpass >/dev/null
  export SSHPASS="$SSH_PASSWORD"
  SSH_ARGS=(-o ConnectTimeout=15 -o StrictHostKeyChecking=accept-new -p "$SSH_PORT")
  SCP_ARGS=(-o ConnectTimeout=15 -o StrictHostKeyChecking=accept-new -P "$SSH_PORT")
else
  [ -f "$SSH_KEY" ] || { echo 'SSH 私钥不存在' >&2; exit 1; }
  SSH_ARGS+=(-i "$SSH_KEY")
  SCP_ARGS+=(-i "$SSH_KEY")
fi
TARGET="$SSH_USER@$SERVER_HOST"
transport() {
  if [ -n "${SSH_PASSWORD:-}" ]; then sshpass -e "$@"; else "$@"; fi
}
remote() { transport ssh "${SSH_ARGS[@]}" "$TARGET" "$1"; }
execute() {
  local command
  printf -v command 'python3 - %q %q %q' "$1" "$CONFIG" "${2:-}"
  remote "$command" < "$ROOT/ops/remote.py"
}
if [ "$ACTION" != deploy ] && [ "$ACTION" != stage ]; then
  execute "$ACTION"
  exit
fi
execute check
RELEASE_ID="$(python3 - "$ROOT" <<'PY'
import importlib.util, pathlib, sys
root = pathlib.Path(sys.argv[1])
spec = importlib.util.spec_from_file_location('remote', root/'ops/remote.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
print(module.verify_bundle(root/'release')['release_id'])
PY
)"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
COPYFILE_DISABLE=1 tar -czf "$STAGE/release.tar.gz" -C "$ROOT/release" .
remote "umask 077; mkdir -p '$REMOTE_ROOT/incoming/$RELEASE_ID'"
transport scp "${SCP_ARGS[@]}" "$STAGE/release.tar.gz" "$TARGET:$REMOTE_ROOT/incoming/$RELEASE_ID.tar.gz"
remote "tar -xzf '$REMOTE_ROOT/incoming/$RELEASE_ID.tar.gz' -C '$REMOTE_ROOT/incoming/$RELEASE_ID'"
execute "$ACTION" "$REMOTE_ROOT/incoming/$RELEASE_ID"
