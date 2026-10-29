#!/usr/bin/env bash
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export UV_CACHE_DIR="${UV_CACHE_DIR:-$ROOT/ops/.cache/uv}"
OUT="$ROOT/release"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
BACKEND="$ROOT/swag_agent_backend_py"
PYTHON="$BACKEND/.venv/bin/python"
command -v uv >/dev/null
command -v pnpm >/dev/null
[ -x "$PYTHON" ] || { echo '缺少后端 .venv，请先安装 Python 3.12 与开发依赖' >&2; exit 1; }
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s "$ROOT/ops/tests" -v
node --experimental-vm-modules --test "$ROOT/ops/tests/chat.test.mjs"
(cd "$BACKEND" && "$PYTHON" -m pytest -q)
(cd "$ROOT/swag_agent_web" && pnpm install --frozen-lockfile && pnpm build)
uv build --wheel "$BACKEND" --out-dir "$STAGE"
rm -f "$STAGE/.gitignore"
cp "$BACKEND/requirements.lock" "$STAGE/requirements.lock"
cp "$ROOT/ops/"{Dockerfile,start_backend.sh,verify.py,remote.py} "$STAGE/"
COPYFILE_DISABLE=1 tar -czf "$STAGE/web.tar.gz" -C "$ROOT/swag_agent_web/dist" .
"$PYTHON" - "$ROOT" "$STAGE" <<'PY'
import hashlib, json, pathlib, subprocess, sys, zipfile
from datetime import datetime, timezone
root, stage = map(pathlib.Path, sys.argv[1:])
wheel, = stage.glob('*.whl')
with zipfile.ZipFile(wheel) as z:
    assert 'app/main.py' in z.namelist()
    assert not any('/.env' in n or n.startswith('tests/') for n in z.namelist())
sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
diff = subprocess.check_output(['git', 'diff', 'HEAD', '--', 'ops', 'swag_agent_backend_py', 'swag_agent_web'], cwd=root)
digest = hashlib.sha256(diff + b''.join(p.name.encode()+p.read_bytes() for p in sorted(stage.iterdir()))).hexdigest()[:12]
manifest = {'release_id': sha[:12] + '-' + digest, 'source_commit': sha,
            'working_tree_diff_sha256': hashlib.sha256(diff).hexdigest(),
            'built_at': datetime.now(timezone.utc).isoformat(), 'python': '3.12',
            'frontend_index_sha256': hashlib.sha256((root/'swag_agent_web/dist/index.html').read_bytes()).hexdigest(),
            'verification': 'pytest + pnpm frozen install/build; production checks run on deployment',
            'known_gap': 'Python does not export new traces to Zipkin yet; audit endpoints remain available'}
(stage/'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
files = sorted(p for p in stage.iterdir() if p.is_file())
(stage/'SHA256SUMS').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n' for p in files))
import importlib.util
spec = importlib.util.spec_from_file_location('release_check', stage/'remote.py')
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)
assert checker.verify_bundle(stage)['release_id'] == manifest['release_id']
print('Release:', manifest['release_id'])
PY
mkdir -p "$OUT"
# 只有完整构建成功后才替换仓库内的发布文件。
find "$OUT" -maxdepth 1 -type f ! -name README.md -delete
cp "$STAGE/"* "$OUT/"
echo "发布包已准备：$OUT"
