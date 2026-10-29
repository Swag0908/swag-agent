#!/usr/bin/env python3
"""在发布镜像内验证真实依赖与 HTTP 接口；不输出凭据或业务内容。

验收只临时创建一个认证 token，finally 删除；聊天不传 conversationId。
数据库备份是单独的 backup 子命令，恢复不自动执行，避免覆盖切换后的新数据。
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import timedelta


def request(base, path, token=None, expected=200, headers=None):
    values = dict(headers or {})
    if token:
        values['Authorization'] = 'Bearer ' + token
    req = urllib.request.Request(base.rstrip('/') + path, headers=values)
    try:
        response = urllib.request.urlopen(req, timeout=20)
    except urllib.error.HTTPError as exc:
        response = exc
    with response:
        if response.status != expected:
            raise RuntimeError('HTTP check failed: {} expected {}, received {}'.format(path, expected, response.status))
        data = response.read()
    print('OK HTTP', path.split('?')[0], expected, flush=True)
    return json.loads(data) if data and expected == 200 else None


def verify_stream(base, token, model, headers=None):
    query = urllib.parse.urlencode({'model': model, 'userInput': '请调用 getCurrentTime 获取当前时间，只回答时间。'})
    values = dict(headers or {}, Authorization='Bearer ' + token, Accept='text/event-stream')
    req = urllib.request.Request(base.rstrip('/') + '/test/chat/stream/events?' + query, headers=values)
    names, text_chars = set(), 0
    started = time.monotonic()
    with urllib.request.urlopen(req, timeout=120) as response:
        if response.status != 200 or 'text/event-stream' not in response.headers.get('Content-Type', ''):
            raise RuntimeError('SSE content type/status invalid')
        event = ''
        for raw in response:
            line = raw.decode('utf-8').strip()
            if line.startswith('event:'):
                event = line[6:].strip()
                names.add(event)
                if event == 'error':
                    raise RuntimeError('SSE emitted error for model {}'.format(model))
            if line.startswith('data:'):
                payload = json.loads(line[5:].strip())
                payload = payload.get('data', payload)
                if event == 'content':
                    text_chars += len(payload.get('text', ''))
            if time.monotonic() - started > 150:
                raise RuntimeError('SSE deadline exceeded')
    if not {'ready', 'content', 'done', 'tool_call'} <= names or not text_chars:
        raise RuntimeError('SSE incomplete for model {}'.format(model))
    print('OK SSE model={} ready/tools/content/done'.format(model), flush=True)


def backup(directory):
    from app.config import settings
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    env = dict(os.environ, MYSQL_PWD=settings.mysql_password)
    command = ['mysqldump', '--single-transaction', '--quick', '--skip-lock-tables', '--hex-blob',
               '--no-tablespaces', '-h', settings.mysql_host, '-P', str(settings.mysql_port),
               '-u', settings.mysql_user, settings.mysql_db]
    temporary = target / 'mysql.sql.partial'
    with temporary.open('wb') as out:
        result = subprocess.run(command, env=env, stdout=out, stderr=subprocess.PIPE)
    if result.returncode or not temporary.stat().st_size:
        raise RuntimeError('MySQL backup failed; production has not been switched')
    temporary.rename(target / 'mysql.sql')
    print('OK consistent MySQL backup', flush=True)


def verify(base, chat=False, host=None, frontend=None):
    from sqlalchemy import delete, select, text
    from app.config import settings
    from app.core.timeutil import now, today
    from app.db.base import Base, SessionLocal, engine
    from app.db import models
    from app.db.pg import get_pg_engine
    from app.memory.long import embed_sync, vector_literal

    if not settings.deepseek_api_key or not settings.tavily_api_key:
        raise RuntimeError('Missing model/search credentials')
    if not settings.dual_write_chat_memory:
        raise RuntimeError('Java rollback requires DUAL_WRITE_CHAT_MEMORY=true')
    if not Path(settings.notes_root).is_dir() or not Path(settings.skills_external_root).is_dir():
        raise RuntimeError('Persistent data mounts missing')
    # SELECT 所有映射列，除了表存在还要确认线上字段与 Python 模型兼容。
    with engine.connect() as conn:
        for table in Base.metadata.sorted_tables:
            conn.execute(table.select().limit(0))
    print('OK MySQL schema/columns', flush=True)
    vector = embed_sync('deployment readiness check')
    if vector is None or len(vector) != settings.embedding_dimensions:
        raise RuntimeError('Ollama embedding unavailable or incorrect dimension')
    with get_pg_engine().connect() as conn:
        for table in ('vector_store', 'chat_user_memory_vec'):
            conn.execute(text('SELECT embedding <=> CAST(:v AS vector) FROM public.' + table + ' LIMIT 1'),
                         {'v': vector_literal(vector)})
    print('OK Ollama + pgvector similarity query', flush=True)
    headers = {'Host': host} if host else {}
    if request(base, '/actuator/health', headers=headers).get('status') != 'UP':
        raise RuntimeError('Database health is DOWN (HTTP 200 alone is insufficient)')
    if request(base, '/actuator/info', headers=headers).get('runtime') != 'python':
        raise RuntimeError('Nginx still points to Java')
    request(base, '/chat/conversations', expected=401, headers=headers)
    token = str(uuid.uuid4())
    with SessionLocal() as db:
        user = db.scalar(select(models.AppUser).where(models.AppUser.role == 'ADMIN').limit(1))
        if user is None:
            raise RuntimeError('No existing administrator for migration verification')
        user_id = user.id
        # 先核对旧登录态：Java 已颁发的有效 token 必须能在 Python 中继续使用。
        old_token = db.scalar(select(models.AuthToken.token).where(
            models.AuthToken.user_id == user_id, models.AuthToken.expires_at > now()).limit(1))
        conversation_id = db.scalar(select(models.ChatConversation.id).where(
            models.ChatConversation.user_id == user_id).limit(1))
        db.add(models.AuthToken(token=token, user_id=user_id, created_at=now(),
                                expires_at=now() + timedelta(minutes=15)))
        db.commit()
    try:
        if old_token:
            request(base, '/auth/me', old_token, headers=headers)
            print('OK existing login token', flush=True)
        me = request(base, '/auth/me', token, headers=headers)
        if me.get('userId') != user_id or me.get('role') != 'ADMIN':
            raise RuntimeError('Admin identity mismatch')
        date = today().isoformat()
        paths = ['/chat/conversations', '/chat/user-memory', '/bookmarks',
                 '/todo?from=' + date + '&to=' + date, '/todo/stats/daily',
                 '/notes/tree', '/notes/import/config', '/auth/admin/skills',
                 '/audit/chains?limit=1']
        if conversation_id:
            paths.append('/chat/conversations/{}/messages'.format(conversation_id))
        for path in paths:
            request(base, path, token, headers=headers)
        request(base, '/auth/zipkin-access', expected=204,
                headers=dict(headers, Cookie=settings.zipkin_cookie_name + '=' + token))
        if chat:
            for model in (1, 2):
                verify_stream(base, token, model, headers)
        if frontend:
            origin = base.rsplit('/api', 1)[0]
            req = urllib.request.Request(origin + '/', headers=headers)
            with urllib.request.urlopen(req, timeout=15) as response:
                index = response.read()
            if hashlib.sha256(index).hexdigest() != frontend:
                raise RuntimeError('Nginx is not serving this release frontend')
            # Vue history 模式路由和真实构建资源一起检查。
            import re
            for path in ['/login', '/notes', '/sites', '/traces'] + re.findall(
                    r'(?:src|href)="(/assets/[^"]+)"', index.decode()):
                req = urllib.request.Request(origin + path, headers=headers)
                with urllib.request.urlopen(req, timeout=15) as response:
                    if response.status != 200:
                        raise RuntimeError('Frontend route/asset unavailable')
            print('OK frontend index hash/routes/assets', flush=True)
    finally:
        with SessionLocal() as db:
            db.execute(delete(models.AuthToken).where(models.AuthToken.token == token))
            db.commit()
        print('OK temporary verification token removed', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['verify', 'backup'])
    parser.add_argument('--base-url', default='http://127.0.0.1:18081')
    parser.add_argument('--chat', action='store_true')
    parser.add_argument('--host')
    parser.add_argument('--frontend-sha256')
    parser.add_argument('--directory', default='/backup')
    args = parser.parse_args()
    try:
        if args.action == 'backup':
            backup(args.directory)
        else:
            verify(args.base_url, args.chat, args.host, args.frontend_sha256)
    except Exception as exc:
        # SQL/HTTP 异常可能携带连接信息或 prompt；只报告异常类型，详细检查在服务器执行。
        message = str(exc) if type(exc) is RuntimeError else type(exc).__name__
        print('FAILED migration verification:', message, flush=True)
        raise SystemExit(1)
