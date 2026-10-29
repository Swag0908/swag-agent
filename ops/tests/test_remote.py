import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('remote', Path(__file__).parents[1]/'remote.py')
remote = importlib.util.module_from_spec(spec)
spec.loader.exec_module(remote)

NGINX = '''server {
    listen 80;
    root /opt/swag_agent/web/dist;
    location = /_zipkin_auth { proxy_pass http://127.0.0.1:8080/auth/zipkin-access; }
    location /zipkin/ { proxy_pass http://127.0.0.1:9411; }
    location /api/ {
        proxy_pass http://127.0.0.1:8080/;
        proxy_buffering off;
        proxy_read_timeout 300s;
    }
}
'''


class ReleaseSafetyTests(unittest.TestCase):
    def setUp(self):
        health = patch.object(remote, 'http_health')
        self.health = health.start()
        self.addCleanup(health.stop)

    def test_nginx_switch_preserves_zipkin_and_sse(self):
        switched = remote.rewrite_nginx(NGINX, Path('/release/web'))
        self.assertIn('root /release/web;', switched)
        self.assertIn('8081/auth/zipkin-access', switched)
        self.assertIn('proxy_pass http://127.0.0.1:8081/;', switched)
        self.assertIn('proxy_pass http://127.0.0.1:9411;', switched)
        self.assertIn('client_max_body_size 100m;', switched)
        self.assertIn('proxy_buffering off;', switched)

    def test_changed_nginx_layout_stops_migration(self):
        for bad in [NGINX.replace('8080/', '9090/'), NGINX.replace('proxy_buffering off;', '')]:
            with self.assertRaises(RuntimeError):
                remote.rewrite_nginx(bad, Path('/release/web'))

    def test_property_parser_preserves_urls_and_password_delimiters(self):
        parsed = remote.properties('url=jdbc:mysql://localhost:3306/db?x=1\npassword=a:b=c#x\n#comment\n')
        self.assertEqual(parsed['url'], 'jdbc:mysql://localhost:3306/db?x=1')
        self.assertEqual(parsed['password'], 'a:b=c#x')

    def test_env_is_private_literal_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'backend.env'
            remote.write_env(path, {'PASSWORD': '$literal#value', 'EMPTY': ''})
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertIn('PASSWORD=$literal#value\n', path.read_text())
            with self.assertRaises(FileExistsError):
                remote.write_env(path, {'PASSWORD': 'new'})

    def test_multiline_secret_rejected_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'backend.env'
            with self.assertRaises(RuntimeError):
                remote.write_env(path, {'PASSWORD': 'secret\nINJECTED=true'})
            self.assertFalse(path.exists())

    def test_frontend_archive_rejects_traversal_and_symlinks(self):
        for name, kind in [('../outside', tarfile.REGTYPE), ('link', tarfile.SYMTYPE)]:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                with tarfile.open(root/'web.tar.gz', 'w:gz') as archive:
                    member = tarfile.TarInfo(name)
                    member.type = kind
                    member.linkname = '/etc/passwd' if kind == tarfile.SYMTYPE else ''
                    archive.addfile(member, io.BytesIO())
                with self.assertRaises(RuntimeError):
                    remote.extract_web(root/'web.tar.gz', root/'web')
                self.assertFalse((root/'outside').exists())

    def test_tampered_bundle_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            digest = hashlib.sha256(b'original').hexdigest()
            (root/'manifest.json').write_text('changed')
            (root/'SHA256SUMS').write_text(digest + '  manifest.json\n')
            with self.assertRaisesRegex(RuntimeError, 'checksum mismatch'):
                remote.verify_bundle(root)

    def make_deployment(self, root):
        config = {'remote_root': str(root), 'nginx_config': str(root/'nginx.conf'),
                  'java_service': 'legacy', 'site_host': 'example.test'}
        (root/'backup.conf').write_text(NGINX)
        (root/'nginx.conf').write_text('new config')
        return remote.Deployment(config), {'old_container': 'previous', 'java_active': False,
            'java_enabled': False, 'nginx_backup': str(root/'backup.conf')}

    def test_rollback_restores_old_container_and_nginx(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            deploy, state = self.make_deployment(root)
            with patch.object(deploy, 'exists', side_effect=lambda name: name in {'previous', deploy.name}), \
                    patch.object(remote, 'run') as run:
                deploy.restore(state)
            calls = [tuple(call.args) for call in run.call_args_list]
            self.assertIn(('docker', 'rm', '-f', deploy.name), calls)
            self.assertIn(('docker', 'rename', 'previous', deploy.name), calls)
            self.assertIn(('docker', 'start', deploy.name), calls)
            self.assertEqual((root/'nginx.conf').read_text(), NGINX)
            self.health.assert_called_once_with(8081)
            self.assertFalse(any('mysqldump' in call or 'mysql' in call for call in calls))

    def test_failed_rename_does_not_delete_original_container(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            deploy, state = self.make_deployment(root)
            with patch.object(deploy, 'exists', side_effect=lambda name: name == deploy.name), \
                    patch.object(remote, 'run') as run:
                deploy.restore(state)
            calls = [tuple(call.args) for call in run.call_args_list]
            self.assertNotIn(('docker', 'rm', '-f', deploy.name), calls)
            self.assertIn(('docker', 'start', deploy.name), calls)

    def test_first_migration_failure_restores_java(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            deploy, state = self.make_deployment(root)
            state.update(old_container=None, java_active=True, java_enabled=True)
            with patch.object(deploy, 'exists', side_effect=lambda name: name == deploy.name), \
                    patch.object(remote, 'run') as run:
                deploy.restore(state)
            calls = [tuple(call.args) for call in run.call_args_list]
            self.assertIn(('systemctl', 'start', 'legacy'), calls)
            self.assertIn(('systemctl', 'enable', 'legacy'), calls)
            self.health.assert_called_once_with(8080)

    def test_unhealthy_restored_backend_does_not_report_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            deploy, state = self.make_deployment(root)
            self.health.side_effect = RuntimeError('health failed')
            with patch.object(deploy, 'exists', return_value=False), patch.object(remote, 'run'):
                with self.assertRaisesRegex(RuntimeError, 'ROLLBACK INCOMPLETE'):
                    deploy.restore(state)

    def test_rollback_failure_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            deploy, state = self.make_deployment(root)
            with patch.object(deploy, 'exists', return_value=False), \
                    patch.object(remote, 'run', side_effect=OSError('failure')):
                with self.assertRaisesRegex(RuntimeError, 'ROLLBACK INCOMPLETE'):
                    deploy.restore(state)


if __name__ == '__main__':
    unittest.main()
