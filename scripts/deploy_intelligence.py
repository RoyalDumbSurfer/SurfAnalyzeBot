"""Guarded operator rollout; run through stdin from /opt/SurfAnalyzeBot."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tarfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--old', required=True)
parser.add_argument('--target', required=True)
parser.add_argument('--apply', action='store_true')
args = parser.parse_args()
root = Path('/opt/SurfAnalyzeBot')
assert Path.cwd().resolve() == root
os.umask(0o077)

def run(*command):
    return subprocess.check_output(command, text=True).strip()

assert run('git', 'rev-parse', 'HEAD') == args.old, 'Production HEAD changed'
assert not run('git', 'status', '--porcelain', '--untracked-files=no'), 'Tracked production changes'
from config import settings
database_path = Path(settings.DATABASE_PATH).resolve()

def snapshot():
    with sqlite3.connect(database_path.as_uri() + '?mode=ro', uri=True) as db:
        db.execute('BEGIN')
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
        assert db.execute("SELECT count(*) FROM jobs WHERE status IN ('queued','processing')").fetchone()[0] == 0, 'Jobs must drain first'
        tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        records = {}
        for table in tables:
            rows = db.execute('SELECT * FROM "' + table.replace('"', '""') + '" ORDER BY 1').fetchall()
            records[table] = {'count': len(rows), 'sha256': hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()}
        files = set()
        for folder in ('data/uploads', 'data/extracted_frames', 'videos_processed', 'downloads'):
            files.update(p.resolve() for p in Path(folder).rglob('*') if p.is_file())
        for payload, in db.execute('SELECT payload FROM jobs'):
            job = json.loads(payload)
            for field in ('file_path', 'result_path'):
                if job.get(field) and Path(job[field]).is_file():
                    files.add(Path(job[field]).resolve())
        if Path('jobs_db.json').is_file():
            files.add(Path('jobs_db.json').resolve())
        media = {}
        for path in sorted(files):
            assert path.is_relative_to(root), 'Unexpected external media path; review backup scope'
            digest = hashlib.sha256()
            with path.open('rb') as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b''):
                    digest.update(chunk)
            media[str(path.relative_to(root))] = digest.hexdigest()
        return {'tables': records, 'media': media}

before = snapshot()
print(json.dumps({'preflight': 'ok', 'counts': {k: v['count'] for k, v in before['tables'].items()},
                  'media_files': len(before['media'])}), flush=True)
if not args.apply:
    raise SystemExit(0)
run('git', 'fetch', 'origin')
assert run('git', 'rev-parse', 'origin/main') == args.target
subprocess.check_call(['git', 'merge-base', '--is-ancestor', args.old, args.target])
backup = Path('/root') / ('surfanalyze-intelligence-backup-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
backup.mkdir(mode=0o700)
try:
    subprocess.check_call(['systemctl', 'stop', 'surfanalyze-web'])
    snapshot()  # Refuse to interrupt any active/queued analysis.
    subprocess.check_call(['systemctl', 'stop', 'surfanalyze-worker'])
    before = snapshot()
    with sqlite3.connect(database_path.as_uri() + '?mode=ro', uri=True) as source:
        with sqlite3.connect(backup / 'database.sqlite3') as target:
            source.backup(target)
    with tarfile.open(backup / 'media.tar', 'w') as archive:
        for name in before['media']:
            archive.add(root / name, arcname=name, recursive=False)
    (backup / 'manifest.json').write_text(json.dumps(before, sort_keys=True), encoding='utf-8')
    print('Backup complete: ' + str(backup), flush=True)
    subprocess.check_call(['git', 'merge', '--ff-only', args.target])
    assert run('git', 'rev-parse', 'HEAD') == args.target
    assert snapshot() == before, 'Persistent data changed during code rollout'
    subprocess.check_call([str(root / '.venv/bin/python'), 'scripts/intelligence_audit.py'], env={**os.environ, 'PYTHONPATH': str(root)})
    print('Persistent table and media fingerprints unchanged.', flush=True)
finally:
    subprocess.check_call(['systemctl', 'start', 'surfanalyze-worker', 'surfanalyze-web'])
print(run('systemctl', 'is-active', 'surfanalyze-web', 'surfanalyze-worker'), flush=True)
print('Production SHA: ' + run('git', 'rev-parse', 'HEAD'), flush=True)
