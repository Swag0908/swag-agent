#!/usr/bin/env python3
"""远端发布事务。仅使用 CentOS 7 自带 Python 3.6 标准库，应用在 Docker/Python 3.12 内运行。"""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import time
from urllib.parse import urlparse
from urllib.request import urlopen
import zipfile


def run(*args, **kwargs):
    return subprocess.run(list(args), check=True, universal_newlines=True, **kwargs)


def output(*args):
    return subprocess.check_output(list(args), universal_newlines=True, stderr=subprocess.DEVNULL).strip()


def active(service):
    return subprocess.call(['systemctl', 'is-active', '--quiet', service]) == 0


def http_health(port):
    for _ in range(40):
        try:
            with urlopen('http://127.0.0.1:{}/actuator/health'.format(port), timeout=3) as response:
                if json.load(response).get('status') == 'UP':
                    return
        except Exception:
            pass
        time.sleep(2)
    raise RuntimeError('Restored backend did not become healthy')


def atomic_json(path, data):
    path = Path(path)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(data, indent=2) + '\n')
    os.replace(str(temp), str(path))


def properties(contents):
    result = {}
    for line in contents.splitlines():
        line = line.strip()
        if line and not line.startswith(('#', '!')):
            pair = re.split(r'\s*[=:]\s*', line, maxsplit=1)
            if len(pair) == 2:
                result[pair[0]] = pair[1]
    return result


def legacy_config(service):
    values = properties(output('systemctl', 'show', service, '-p', 'MainPID', '-p', 'WorkingDirectory'))
    pid = values.get('MainPID', '0')
    if pid == '0':
        raise RuntimeError('First migration requires the existing Java service running')
    proc = Path('/proc') / pid
    env = dict(item.split('=', 1) for item in (proc/'environ').read_bytes().decode().split('\0') if '=' in item)
    args = (proc/'cmdline').read_bytes().decode().split('\0')
    jar = args[args.index('-jar') + 1]
    workdir = Path(values['WorkingDirectory'])
    if not Path(jar).is_absolute():
        jar = str(workdir / jar)
    with zipfile.ZipFile(jar) as archive:
        def read(name):
            key = 'BOOT-INF/classes/' + name
            return properties(archive.read(key).decode()) if key in archive.namelist() else {}
        props = read('application.properties')
        profile = env.get('SPRING_PROFILES_ACTIVE', props.get('spring.profiles.active', 'dev'))
        for name in profile.split(','):
            props.update(read('application-' + name.strip() + '.properties'))
        # 当前线上 jar 无内置技能；未来有内置资源时必须先补入发布包，避免静默丢失。
        if any(n.startswith('BOOT-INF/classes/skills/') and not n.endswith('/') for n in archive.namelist()):
            raise RuntimeError('Java contains built-in skills; include them in Python release before migration')
    for name in ('application.properties', 'application-' + profile + '.properties'):
        for path in (workdir/name, workdir/'config'/name):
            if path.is_file():
                props.update(properties(path.read_text(encoding="utf-8")))
    for arg in args:
        if arg.startswith(('-D', '--')) and '=' in arg:
            key, value = arg[2:].split('=', 1)
            props[key] = value

    def get(key, default='', depth=0):
        if depth > 10:
            raise RuntimeError('Java property expansion cycle')
        value = env.get(re.sub(r'[.-]', '_', key).upper(), props.get(key, default))
        def replace(match):
            name, _, fallback = match.group(1).partition(':')
            if name in env:
                return env[name]
            if name in props:
                return get(name, fallback, depth + 1)
            if not fallback:
                raise RuntimeError('Unresolved Java configuration placeholder: ' + name)
            return fallback
        return re.sub(r'\$\{([^}]+)\}', replace, value)

    mysql = urlparse(re.sub(r'^jdbc:', '', get('spring.datasource.url')))
    pg = urlparse(re.sub(r'^jdbc:', '', get('app.pgvector.datasource.url')))
    if mysql.scheme != 'mysql' or pg.scheme != 'postgresql':
        raise RuntimeError('Unrecognized JDBC database URL')
    settings = {
        'MYSQL_HOST': mysql.hostname, 'MYSQL_PORT': str(mysql.port or 3306),
        'MYSQL_DB': mysql.path.lstrip('/'), 'MYSQL_USER': get('spring.datasource.username', 'root'),
        'MYSQL_PASSWORD': get('spring.datasource.password'),
        'PG_HOST': pg.hostname, 'PG_PORT': str(pg.port or 5432), 'PG_DB': pg.path.lstrip('/'),
        'PG_USER': get('app.pgvector.datasource.username', 'postgres'),
        'PG_PASSWORD': get('app.pgvector.datasource.password'),
        'DEEPSEEK_API_KEY': get('spring.ai.deepseek.api-key'),
        'TAVILY_API_KEY': get('web.search.tavily.api-key'),
        'OLLAMA_BASE_URL': get('spring.ai.ollama.base-url', 'http://127.0.0.1:11434'),
        'OLLAMA_EMBED_MODEL': get('spring.ai.ollama.embedding.model', 'nomic-embed-text'),
        'ZIPKIN_COOKIE_NAME': get('app.zipkin-access.cookie-name', 'swag_zipkin_token'),
        'ZIPKIN_COOKIE_SECURE': get('app.zipkin-access.cookie-secure', 'false'),
        'NOTES_ROOT': '/data/notes', 'SKILLS_EXTERNAL_ROOT': '/data/skills',
        'NOTES_IMPORT_ROOTS': '', 'BOOTSTRAP_ON_STARTUP': 'false', 'SCHEDULER_ENABLED': 'false',
        'DUAL_WRITE_CHAT_MEMORY': 'true', 'THINKING_MODE': 'disabled', 'ENV': 'production',
    }
    for key in ('DEEPSEEK_API_KEY', 'TAVILY_API_KEY', 'MYSQL_HOST', 'PG_HOST'):
        if not settings[key]:
            raise RuntimeError('Missing production configuration: ' + key)
    paths = {}
    for key, prop, default in [('notes_dir', 'app.notes.root', './notes-data'),
                               ('skills_dir', 'app.skills.external-root', './skills-data')]:
        path = Path(get(prop, default))
        paths[key] = str((path if path.is_absolute() else workdir/path).resolve())
    return settings, paths


def write_env(path, values):
    lines = []
    for key, value in sorted(values.items()):
        value = str(value)
        if '\n' in value or '\r' in value:
            raise RuntimeError('Multiline environment value unsupported: ' + key)
        lines.append(key + '=' + value)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(str(path), flags, 0o600)
    with os.fdopen(fd, 'w') as handle:
        handle.write('\n'.join(lines) + '\n')


def verify_bundle(bundle):
    names = set()
    for line in (bundle/'SHA256SUMS').read_text(encoding="utf-8").splitlines():
        digest, name = line.split('  ', 1)
        if Path(name).name != name or name in names:
            raise RuntimeError('Invalid bundle checksum path')
        names.add(name)
        if hashlib.sha256((bundle/name).read_bytes()).hexdigest() != digest:
            raise RuntimeError('Bundle checksum mismatch: ' + name)
    expected = {'Dockerfile', 'requirements.lock', 'start_backend.sh', 'verify.py',
                'remote.py', 'web.tar.gz', 'manifest.json'}
    if not expected <= names or len([n for n in names if n.endswith('.whl')]) != 1:
        raise RuntimeError('Incomplete release bundle')
    manifest = json.loads((bundle/'manifest.json').read_text(encoding="utf-8"))
    if not re.fullmatch(r'[a-f0-9]{12}-[a-f0-9]{12}', manifest['release_id']):
        raise RuntimeError('Invalid release id')
    return manifest


def extract_web(archive_path, destination):
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(str(archive_path), 'r:gz') as archive:
        for member in archive.getmembers():
            path = (destination / member.name).resolve()
            if os.path.commonpath([str(destination.resolve()), str(path)]) != str(destination.resolve()):
                raise RuntimeError('Unsafe frontend archive path')
            if not (member.isfile() or member.isdir()):
                raise RuntimeError('Unexpected frontend archive entry')
        archive.extractall(str(destination))
    if not (destination/'index.html').is_file():
        raise RuntimeError('Frontend index missing')


def rewrite_nginx(contents, web_dir):
    contents, roots = re.subn(r'(?m)^(\s*root\s+)[^;]+;', lambda m: m[1] + str(web_dir) + ';', contents)
    contents, proxies = re.subn(r'(proxy_pass\s+http://127\.0\.0\.1:)(?:8080|8081)(/)', r'\g<1>8081\2', contents)
    if roots != 1 or proxies != 2:
        raise RuntimeError('Nginx layout changed; expected one root and API/Zipkin auth upstreams')
    if 'proxy_buffering off;' not in contents or 'proxy_read_timeout' not in contents:
        raise RuntimeError('Nginx SSE settings missing')
    if not re.search(r'^\s*client_max_body_size\s', contents, re.M):
        contents = re.sub(r'(server\s*\{)', r'\1\n    client_max_body_size 100m;', contents, count=1)
    return contents


class Deployment:
    def __init__(self, config):
        self.config = config
        self.root = Path(config['remote_root'])
        self.nginx = Path(config['nginx_config'])
        self.env_file = self.root/'backend.env'
        self.name = 'swag-agent-py'
        self.candidate = 'swag-agent-py-candidate'
        self.java = config['java_service']

    def context(self):
        if self.env_file.exists() and (self.root/'runtime.json').exists():
            return None, json.loads((self.root/'runtime.json').read_text(encoding="utf-8"))
        return legacy_config(self.java)

    def check(self):
        if os.geteuid() != 0:
            raise RuntimeError('Deployment requires root for Docker, Nginx, and systemd')
        for command in ('docker', 'nginx', 'systemctl', 'tar'):
            if not shutil.which(command):
                raise RuntimeError('Missing server command: ' + command)
        output('docker', 'version', '--format', '{{.Server.Version}}')
        run('nginx', '-t')
        settings, paths = self.context()
        for key in ('notes_dir', 'skills_dir'):
            if not Path(paths[key]).is_dir():
                raise RuntimeError('Existing data directory missing: ' + key)
        rewrite_nginx(self.nginx.read_text(encoding="utf-8"), self.root/'releases'/'preflight'/'web')
        print('OK server Docker/Nginx/legacy configuration/data paths; no production changes', flush=True)
        print('Data directories:', paths['notes_dir'], paths['skills_dir'], flush=True)
        return settings, paths

    def exists(self, name):
        return subprocess.call(['docker', 'container', 'inspect', name],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0

    def start_container(self, name, image, paths, port, scheduler, candidate=False):
        run('docker', 'run', '-d', '--name', name, '--network', 'host',
            '--restart', 'unless-stopped', '--init', '--read-only', '--tmpfs', '/tmp:rw,size=128m',
            '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
            '--log-opt', 'max-size=10m', '--log-opt', 'max-file=3',
            '--env-file', str(self.env_file), '-e', 'UVICORN_PORT=' + str(port),
            '-e', 'SCHEDULER_ENABLED=' + str(scheduler).lower(),
            '-e', 'BOOTSTRAP_ON_STARTUP=false', '-e', 'DUAL_WRITE_CHAT_MEMORY=true',
            '-e', 'NOTES_ROOT=/data/notes', '-e', 'SKILLS_EXTERNAL_ROOT=/data/skills',
            '-e', 'AUDIT_ENABLED=' + ('false' if candidate else 'true'),
            '-v', paths['notes_dir'] + ':/data/notes', '-v', paths['skills_dir'] + ':/data/skills',
            image, stdout=subprocess.DEVNULL)

    def healthy(self, name):
        for _ in range(40):
            if output('docker', 'inspect', '-f', '{{.State.Running}}', name) != 'true':
                raise RuntimeError('Backend container exited')
            status = output('docker', 'inspect', '-f', '{{.State.Health.Status}}', name)
            if status == 'healthy':
                return
            time.sleep(2)
        raise RuntimeError('Backend database health did not become UP')

    def verify(self, name, base, manifest=None, chat=False):
        args = ['docker', 'exec', name, 'python', '/opt/release/verify.py', 'verify', '--base-url', base]
        if chat:
            args.append('--chat')
        if manifest:
            args += ['--host', self.config['site_host'], '--frontend-sha256', manifest['frontend_index_sha256']]
        run(*args)

    def restore(self, state):
        # 先准备旧后端，再恢复 Nginx；不恢复数据库，保留切换后的新消息和业务数据。
        errors = []
        def attempt(*args):
            try:
                run(*args, stdout=subprocess.DEVNULL)
            except Exception:
                errors.append(args[:3])
        old = state.get('old_container')
        if old and self.exists(old):
            if self.exists(self.name):
                attempt('docker', 'rm', '-f', self.name)
            attempt('docker', 'rename', old, self.name)
            attempt('docker', 'start', self.name)
        elif old and self.exists(self.name):
            # stop/rename 失败时这个名字仍是原容器，不能删除它。
            attempt('docker', 'start', self.name)
        elif not old and self.exists(self.name):
            attempt('docker', 'rm', '-f', self.name)
        if state['java_active']:
            attempt('systemctl', 'start', self.java)
        if state['java_enabled']:
            attempt('systemctl', 'enable', self.java)
        try:
            shutil.copy2(state['nginx_backup'], str(self.nginx))
        except Exception:
            errors.append(('nginx', 'restore'))
        attempt('nginx', '-t')
        attempt('systemctl', 'reload', 'nginx')
        if self.exists(self.candidate):
            attempt('docker', 'rm', '-f', self.candidate)
        if not errors:
            try:
                http_health(8080 if state['java_active'] else 8081)
            except Exception:
                errors.append(('backend', 'health'))
        if errors:
            raise RuntimeError('ROLLBACK INCOMPLETE: inspect server services and backup ' + state['nginx_backup'])
        print('OK previous backend/frontend/Nginx restored; database retained', flush=True)

    def prepare(self, bundle):
        settings, paths = self.check()
        manifest = verify_bundle(bundle)
        release_id = manifest['release_id']
        release = self.root/'releases'/release_id
        release.parent.mkdir(parents=True, exist_ok=True)
        self.root.chmod(0o755)
        release.parent.chmod(0o755)
        if release.exists():
            if verify_bundle(release) != manifest:
                raise RuntimeError('Existing staged release has different contents')
        else:
            shutil.copytree(str(bundle), str(release))
        release.chmod(0o755)
        extract_web(release/'web.tar.gz', release/'web')
        for directory, _, files in os.walk(str(release/'web')):
            Path(directory).chmod(0o755)
            for name in files:
                (Path(directory)/name).chmod(0o644)
        if hashlib.sha256((release/'web'/'index.html').read_bytes()).hexdigest() != manifest['frontend_index_sha256']:
            raise RuntimeError('Frontend manifest mismatch')
        original_nginx = self.nginx.read_text(encoding="utf-8")
        # 老页面可能在切换后继续请求旧 hash 资源，保留上一版本资源。
        old_root = Path(re.search(r'^\s*root\s+([^;]+);', original_nginx, re.M).group(1).strip())
        if (old_root/'assets').is_dir():
            for asset in (old_root/'assets').iterdir():
                destination = release/'web'/'assets'/asset.name
                if asset.is_file() and not destination.exists():
                    shutil.copy2(str(asset), str(destination))
        candidate_nginx = rewrite_nginx(original_nginx, release/'web')
        if not self.env_file.exists():
            write_env(self.env_file, settings)
            atomic_json(self.root/'runtime.json', paths)
        image = 'swag-agent-py:' + release_id
        if subprocess.call(['docker', 'image', 'inspect', image],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) != 0:
            print('Building Linux/Python 3.12 image; live traffic remains on existing backend', flush=True)
            run('docker', 'build', '--network', 'host', '--pull', '-t', image, str(release))
        return manifest, release, paths, candidate_nginx, image

    def verify_candidate(self, image, paths):
        if self.exists(self.candidate):
            raise RuntimeError('Another candidate container exists; inspect it before retrying')
        try:
            self.start_container(self.candidate, image, paths, 18081, False, candidate=True)
            self.healthy(self.candidate)
            self.verify(self.candidate, 'http://127.0.0.1:18081', chat=True)
        finally:
            if self.exists(self.candidate):
                run('docker', 'rm', '-f', self.candidate, stdout=subprocess.DEVNULL)

    def stage(self, bundle):
        manifest, release, paths, _, image = self.prepare(bundle)
        self.verify_candidate(image, paths)
        atomic_json(self.root/'staged.json', {'release_id': manifest['release_id'], 'image': image,
                                            'verified_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())})
        print('STAGED and verified; Nginx/Java/live frontend unchanged', manifest['release_id'], flush=True)

    def deploy(self, bundle):
        current = self.root/'current.json'
        manifest = verify_bundle(bundle)
        if current.exists() and json.loads(current.read_text(encoding="utf-8"))['release_id'] == manifest['release_id']:
            self.verify(self.name, 'http://127.0.0.1/api', manifest)
            print('OK this release is already deployed', flush=True)
            return
        manifest, release, paths, candidate_nginx, image = self.prepare(bundle)
        release_id = manifest['release_id']
        backup = self.root/'backups'/(release_id + '-' + time.strftime('%Y%m%d%H%M%S'))
        backup.mkdir(parents=True, mode=0o700)
        shutil.copy2(str(self.nginx), str(backup/'nginx.conf'))
        run('docker', 'run', '--rm', '--network', 'host', '--env-file', str(self.env_file),
            '-v', str(backup) + ':/backup', image, 'python', '/opt/release/verify.py', 'backup')
        for key in ('notes_dir', 'skills_dir'):
            source = Path(paths[key])
            run('tar', '-czf', str(backup/(key + '.tar.gz')), '-C', str(source.parent), source.name)
        self.verify_candidate(image, paths)
        old = self.name + '-previous-' + release_id if self.exists(self.name) else None
        state = {'release_id': release_id, 'nginx_backup': str(backup/'nginx.conf'),
                 'old_container': old, 'java_active': active(self.java),
                 'java_enabled': subprocess.call(['systemctl', 'is-enabled', '--quiet', self.java]) == 0}
        atomic_json(backup/'transaction.json', state)
        try:
            if old:
                run('docker', 'stop', '--time', '30', self.name, stdout=subprocess.DEVNULL)
                run('docker', 'rename', self.name, old)
            if state['java_active']:
                run('systemctl', 'stop', self.java)
            self.start_container(self.name, image, paths, 8081, True)
            self.healthy(self.name)
            self.nginx.write_text(candidate_nginx, encoding='utf-8')
            run('nginx', '-t')
            run('systemctl', 'reload', 'nginx')
            self.verify(self.name, 'http://127.0.0.1/api', manifest, chat=True)
            # 避免重启服务器后 Java 与 Python 的定时任务同时运行。
            run('systemctl', 'disable', self.java)
            atomic_json(self.root/'last-deployment.json', state)
            atomic_json(self.root/'current.json', {'release_id': release_id, 'image': image,
                                                   'image_id': output('docker', 'image', 'inspect', '-f', '{{.Id}}', image)})
        except BaseException:
            print('Deployment failed; restoring previous service and Nginx', flush=True)
            self.restore(state)
            raise
        print('DEPLOYED', release_id, 'backup:', str(backup), flush=True)

    def rollback(self):
        path = self.root/'last-deployment.json'
        if not path.is_file():
            raise RuntimeError('No completed deployment available to roll back')
        self.restore(json.loads(path.read_text(encoding="utf-8")))
        path.rename(self.root/'rolled-back.json')
        if (self.root/'current.json').exists():
            (self.root/'current.json').unlink()


def main():
    action, raw_config = sys.argv[1:3]
    config = json.loads(raw_config)
    deploy = Deployment(config)
    os.umask(0o077)
    if action == 'check':
        deploy.check()
        return
    if action == 'status':
        print('Java active:', active(deploy.java))
        run('docker', 'ps', '-a', '--filter', 'name=swag-agent-py', '--format', '{{.Names}} {{.Status}}')
        return
    deploy.root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (deploy.root/'.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if action in ('stage', 'deploy'):
            getattr(deploy, action)(Path(sys.argv[3]))
        elif action == 'rollback':
            deploy.rollback()
        elif action in ('start', 'restart'):
            run('docker', action, deploy.name)
            deploy.healthy(deploy.name)
        else:
            raise RuntimeError('Unknown action')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        message = str(exc) if type(exc) is RuntimeError else type(exc).__name__
        print('FAILED:', message, file=sys.stderr, flush=True)
        raise SystemExit(1)
