"""Run on Linux: python3 -m unittest discover -s tests -v.

Fixtures contain synthetic passwords only. Docker calls are isolated; no accounts
are created and no running server is stopped by these tests.
"""
import ast
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
BACKUP = (SCRIPTS / 'backup.sh').read_text().split("<<'PY'\n", 1)[1].rsplit('\nPY', 1)[0]


class PilotScripts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def run_registration(self, password, confirmation=None):
        call = self.root / 'docker-call.json'
        docker = self.root / 'docker'
        docker.write_text('#!/usr/bin/env python3\nimport json,os,sys\n'
                          'from pathlib import Path\n'
                          'Path(os.environ["TEST_CALL"]).write_text(json.dumps('
                          '{"args":sys.argv[1:],"password":sys.stdin.read()}))\n')
        docker.chmod(0o700)
        env = dict(os.environ, PATH=str(self.root) + ':' + os.environ['PATH'], TEST_CALL=str(call))
        result = subprocess.run(['bash', str(SCRIPTS / 'create-user.sh')],
            input='test_user\n' + password + '\n' + (confirmation if confirmation is not None else password) + '\n',
            text=True, capture_output=True, env=env)
        self.assertNotIn(password, result.stdout + result.stderr)
        return result, json.loads(call.read_text()) if call.exists() else None

    def test_eleven_characters_never_reach_registration(self):
        result, call = self.run_registration('TestOnly123')
        self.assertNotEqual(result.returncode, 0)
        self.assertIsNone(call)

    def test_twelve_characters_use_stdin_without_admin_rights(self):
        password = 'TestOnly1234'
        result, call = self.run_registration(password)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(call['password'], password)
        self.assertNotIn(password, ' '.join(call['args']))
        self.assertIn('--no-admin', call['args'])
        self.assertIn('/dev/stdin', call['args'])

    def test_mismatch_never_reaches_registration(self):
        result, call = self.run_registration('TestOnly1234', 'OtherOnly1234')
        self.assertNotEqual(result.returncode, 0)
        self.assertIsNone(call)

    def test_edge_whitespace_never_reaches_registration(self):
        result, call = self.run_registration(' TestOnly1234')
        self.assertNotEqual(result.returncode, 0)
        self.assertIsNone(call)

    def test_low_space_preserves_services_and_existing_backups(self):
        project = self.root / 'project'
        project.mkdir()
        for folder in ('data', 'data-auth'):
            (project / folder).mkdir()
        backups = self.root / 'backups'
        backups.mkdir()
        old = backups / 'tildes-S3-20260101T000000000000Z.tar.gz'
        old.write_bytes(b'previous-backup')
        calls = []
        real_path = Path

        def path(value):
            return backups if str(value) == '/home/tildes/backups' else real_path(value)

        def run(args, **kwargs):
            calls.append(args)
            if args[:3] == ['docker', 'compose', 'ps']:
                return subprocess.CompletedProcess(args, 0, stdout=args[-1] + '-id\n')
            if args[:3] in (['docker', 'compose', 'stop'], ['docker', 'compose', 'start']):
                raise AssertionError('Low space must not change service state')
            raise AssertionError('Unexpected Docker mutation during low-space preflight')

        def output(args, **kwargs):
            calls.append(args)
            if args[:2] == ['docker', 'inspect']:
                return json.dumps([{'State': {'Status': 'running', 'Paused': False}, 'Image': 'test-existing-image'}]).encode()
            if args[:2] == ['docker', 'run']:
                return b'10240\n'
            raise AssertionError('Unexpected external command')

        with mock.patch('pathlib.Path', side_effect=path), mock.patch('sys.argv', ['backup', str(project)]), \
                mock.patch('subprocess.run', side_effect=run), mock.patch('subprocess.check_output', side_effect=output), \
                mock.patch('shutil.disk_usage', return_value=shutil._ntuple_diskusage(100, 99, 1)), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaisesRegex(SystemExit, 'space'):
                exec(compile(BACKUP, str(SCRIPTS / 'backup.sh'), 'exec'), {})
        self.assertEqual(old.read_bytes(), b'previous-backup')
        self.assertEqual(sorted(p.name for p in backups.iterdir()), ['.backup.lock', old.name])

    def test_estimate_covers_tar_and_does_not_follow_links_or_include_env(self):
        tree = ast.parse(BACKUP)
        estimate = next((node.value.value for node in tree.body if isinstance(node, ast.Assign)
                         and any(isinstance(t, ast.Name) and t.id == 'estimate_archive' for t in node.targets)), None)
        self.assertIsNotNone(estimate, 'Backup must expose its container estimator as estimate_archive')
        for folder in ('data', 'data-auth'):
            (self.root / folder).mkdir()
        for size in (0, 1, 511, 512, 513):
            (self.root / 'data' / str(size)).write_bytes(b'x' * size)
        (self.root / 'data' / ('long-' + 'x' * 180)).write_bytes(b'x')
        (self.root / 'data-auth' / 'кириллица').write_bytes(b'x')
        (self.root / 'data' / '.env').write_bytes(b'x' * (1024 * 1024))
        os.symlink('/nonexistent-outside-target', self.root / 'data' / 'link')
        estimate_bytes = int(subprocess.check_output([sys.executable, '-c', estimate, str(self.root)]))
        contents = io.BytesIO()
        with tarfile.open(fileobj=contents, mode='w', dereference=False) as archive:
            for folder in ('data', 'data-auth'):
                archive.add(self.root / folder, arcname=folder,
                            filter=lambda item: None if '.env' in Path(item.name).parts else item)
        self.assertGreaterEqual(estimate_bytes, len(contents.getvalue()))
        self.assertLess(estimate_bytes, 1024 * 1024)

    def test_space_boundary_and_archive_failure_keep_old_copies_and_restart(self):
        # 10 KiB tar estimate + 64 MiB reserve = 67,119,104 bytes.
        cases = [(67119103, False, False), (67119104, True, False),
                 (67119105, True, False), (67119104, True, True)]
        for free, enough, fail_archive in cases:
            with self.subTest(free=free, fail_archive=fail_archive), tempfile.TemporaryDirectory(dir=self.root) as directory:
                project = Path(directory) / 'project'
                project.mkdir()
                for folder in ('data', 'data-auth'):
                    (project / folder).mkdir()
                backups = Path(directory) / 'backups'
                backups.mkdir()
                old = backups / 'tildes-S3-20260101T000000000000Z.tar.gz'
                old.write_bytes(b'previous-backup')
                changes = []
                real_path = Path

                def path(value):
                    return backups if str(value) == '/home/tildes/backups' else real_path(value)

                def run(args, **kwargs):
                    if args[:3] == ['docker', 'compose', 'ps']:
                        output = '' if '--status' in args else args[-1] + '-id\n'
                        return subprocess.CompletedProcess(args, 0, stdout=output)
                    if args[:3] in (['docker', 'compose', 'stop'], ['docker', 'compose', 'start']):
                        changes.append((args[2], args[3:]))
                        return subprocess.CompletedProcess(args, 0, stdout='')
                    if args[:2] == ['docker', 'run']:
                        if fail_archive:
                            raise subprocess.CalledProcessError(1, args)
                        partial = backups / args[args.index('-c') + 2]
                        with tarfile.open(partial, 'w:gz') as archive:
                            for folder in ('data', 'data-auth'):
                                item = tarfile.TarInfo(folder)
                                item.type = tarfile.DIRTYPE
                                archive.addfile(item)
                        return subprocess.CompletedProcess(args, 0)
                    raise AssertionError('Unexpected command')

                def output(args, **kwargs):
                    if args[:2] == ['docker', 'inspect']:
                        return json.dumps([{'State': {'Status': 'running', 'Paused': False}, 'Image': 'test-existing-image'}]).encode()
                    if args[:2] == ['docker', 'run']:
                        return b'10240\n'
                    raise AssertionError('Unexpected command')

                with mock.patch('pathlib.Path', side_effect=path), mock.patch('sys.argv', ['backup', str(project)]), \
                        mock.patch('subprocess.run', side_effect=run), mock.patch('subprocess.check_output', side_effect=output), \
                        mock.patch('shutil.disk_usage', return_value=shutil._ntuple_diskusage(100000000, 0, free)), \
                        contextlib.redirect_stdout(io.StringIO()):
                    if not enough:
                        with self.assertRaisesRegex(SystemExit, 'space'):
                            exec(compile(BACKUP, 'backup.sh', 'exec'), {})
                    elif fail_archive:
                        with self.assertRaises(subprocess.CalledProcessError):
                            exec(compile(BACKUP, 'backup.sh', 'exec'), {})
                    else:
                        exec(compile(BACKUP, 'backup.sh', 'exec'), {})
                self.assertEqual(changes, [('stop', ['synapse', 'auth']), ('start', ['synapse', 'auth'])] if enough else [])
                self.assertEqual(old.read_bytes(), b'previous-backup')
                self.assertFalse(list(backups.glob('.partial-*')))
                self.assertEqual(len(list(backups.glob('tildes-S3-*.tar.gz'))), 2 if enough and not fail_archive else 1)


if __name__ == '__main__':
    unittest.main()
