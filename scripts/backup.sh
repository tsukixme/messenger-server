#!/usr/bin/env bash
set -euo pipefail
set +x

task_project=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
exec python3 - "$task_project" <<'PY'
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
import fcntl
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile

project = Path(sys.argv[1]).resolve()
backups = Path('/home/tildes/backups')
os.umask(0o077)
if backups.is_symlink():
    raise SystemExit('Backup directory must not be a symlink')
backups.mkdir(mode=0o700, exist_ok=True)
if backups.stat().st_uid != os.getuid():
    raise SystemExit('Run backup as the owner of /home/tildes/backups, without sudo')
backups.chmod(0o700)
lock_fd = os.open(backups / '.backup.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
try:
    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    raise SystemExit('Another backup is already running')

for name in ('data', 'data-auth'):
    p = project / name
    if p.is_symlink() or not p.is_dir() or p.resolve().parent != project:
        raise SystemExit('Missing or unexpected data directory: ' + name)

def compose(*args):
    return subprocess.run(['docker', 'compose', *args], cwd=project, check=True,
                          capture_output=True, text=True).stdout

def interrupted(signum, frame):
    raise SystemExit(128 + signum)

signal.signal(signal.SIGTERM, interrupted)

running = []
image = None
for service in ('synapse', 'auth'):
    ids = compose('ps', '--all', '--quiet', service).split()
    if len(ids) != 1:
        raise SystemExit('Expected exactly one existing container for ' + service)
    item = json.loads(subprocess.check_output(['docker', 'inspect', ids[0]]))[0]
    state = item['State']['Status']
    if state not in ('running', 'exited', 'created') or item['State'].get('Paused'):
        raise SystemExit('Cannot back up container in state ' + state)
    if state == 'running':
        running.append(service)
    if service == 'synapse':
        image = item['Image']

# Estimate an uncompressed tar before stopping writers. The existing Synapse
# image can read root-owned data; bind mounts are read-only and no network is used.
estimate_archive = '''
from pathlib import Path
import io, os, sys, tarfile
source = Path(sys.argv[1])
size = 0
with tarfile.open(fileobj=io.BytesIO(), mode='w', dereference=False) as archive:
    def visit(path, name):
        global size
        if '.env' in Path(name).parts:
            return
        info = archive.gettarinfo(str(path), arcname=name)
        if info is None:
            return
        size += len(info.tobuf(archive.format, archive.encoding, archive.errors))
        if info.isreg():
            size += ((info.size + 511) // 512) * 512
        if info.isdir():
            with os.scandir(path) as children:
                names = sorted(child.name for child in children)
            for child in names:
                visit(path / child, name + '/' + child)
    for folder in ('data', 'data-auth'):
        visit(source / folder, folder)
print(((size + 1024 + 10239) // 10240) * 10240)
'''
estimated = int(subprocess.check_output([
    'docker', 'run', '--rm', '--pull=never', '--network=none', '--user', '0',
    '--entrypoint', 'python',
    '-v', str(project / 'data') + ':/source/data:ro',
    '-v', str(project / 'data-auth') + ':/source/data-auth:ro',
    image, '-c', estimate_archive, '/source'
]))
required = estimated + max(64 * 1024 * 1024, (estimated + 19) // 20)
available = shutil.disk_usage(backups).free
if available < required:
    os.close(lock_fd)
    raise SystemExit(f'Not enough free space for backup: need {required} bytes, '
                     f'available {available}; services were not stopped')

name = 'tildes-S3-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.tar.gz'
fd, tmp = tempfile.mkstemp(prefix='.partial-', suffix='.tar.gz', dir=backups)
os.close(fd)
partial = Path(tmp)
create_archive = '''
from pathlib import Path, PurePosixPath
import os, sys, tarfile
out = Path('/backups') / sys.argv[1]
os.umask(0o077)
def keep(member):
    return None if '.env' in PurePosixPath(member.name).parts else member
with tarfile.open(out, 'w:gz', dereference=False) as archive:
    for folder in ('data', 'data-auth'):
        archive.add('/source/' + folder, arcname=folder, filter=keep)
os.chown(out, int(sys.argv[2]), int(sys.argv[3]))
os.chmod(out, 0o600)
'''

try:
    try:
        if running:
            compose('stop', *running)
        if compose('ps', '--status', 'running', '--quiet', 'synapse', 'auth').strip():
            raise SystemExit('Database writers are still running; no archive published')
        subprocess.run([
            'docker', 'run', '--rm', '--pull=never', '--network=none', '--user', '0',
            '--entrypoint', 'python',
            '-v', str(project / 'data') + ':/source/data:ro',
            '-v', str(project / 'data-auth') + ':/source/data-auth:ro',
            '-v', str(backups) + ':/backups',
            image, '-c', create_archive, partial.name, str(os.getuid()), str(os.getgid())
        ], check=True)
    finally:
        if running:
            compose('start', *running)

    with tarfile.open(partial, 'r:gz') as archive:
        members = archive.getmembers()
        roots = set()
        for member in members:
            p = PurePosixPath(member.name)
            if p.is_absolute() or '..' in p.parts or '.env' in p.parts or not p.parts or p.parts[0] not in ('data', 'data-auth'):
                raise SystemExit('Archive validation failed; no archive published')
            roots.add(p.parts[0])
        if roots != {'data', 'data-auth'}:
            raise SystemExit('Archive does not contain both data directories')
    partial.replace(backups / name)
    pattern = re.compile(r'tildes-S3-\d{8}T\d{12}Z\.tar\.gz')
    own = sorted(p for p in backups.iterdir() if pattern.fullmatch(p.name) and p.is_file() and not p.is_symlink())
    for old in own[:-5]:
        old.unlink()
    print('Backup saved: ' + str(backups / name) + '; retained: ' + str(min(len(own), 5)))
finally:
    if partial.exists():
        partial.unlink()
    os.close(lock_fd)
PY
