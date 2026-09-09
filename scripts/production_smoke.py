"""Operator-run acceptance check; creates data and performs a paid analysis.

See docs/production-smoke.md. Password is entered only in a real TTY.
"""
import io
import argparse
import json
import os
from pathlib import Path
import re
import secrets
import sys
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--app-dir', type=Path, required=True)
parser.add_argument('--base-url', required=True)
parser.add_argument('--owner', required=True)
parser.add_argument('--report', type=Path, required=True)
parser.add_argument('--passwordless', action='store_true', help='Run with a generated test account; skip owner authentication checks.')
args = parser.parse_args()
if sys.flags.optimize:
    parser.error('Assertions must be enabled; do not use python -O.')
if not args.base_url.startswith('https://'):
    parser.error('--base-url must use HTTPS')
args.base_url = args.base_url.rstrip('/')
REPORT = args.report.resolve()
if REPORT.exists() or not REPORT.parent.is_dir():
    parser.error('--report must be a new file in an existing directory')
os.umask(0o077)
REPORT.touch(mode=0o600, exist_ok=False)
os.chdir(args.app_dir)
sys.path.insert(0, os.getcwd())
import httpx
from accounts.cli import read_secret
from accounts.store import AccountStore
from config import settings
from jobs.job_manager import JobManager
from jobs.job_model import JobStatus

report = {}
def mark(name, value=True):
    report[name] = value
    REPORT.write_text(json.dumps(report, indent=2))
    print(name + ': ' + str(value), flush=True)

def csrf(client, path='/login'):
    response = client.get(path)
    assert response.status_code == 200
    return re.search(r'name="csrf" value="([^"]+)"', response.text).group(1)

def post(client, path, data=None, **kwargs):
    values = {'csrf': csrf(client, '/login' if path in {'/login', '/register'} else '/')}
    values.update(data or {})
    return client.post(path, data=values, headers={'Origin': args.base_url}, **kwargs)

def available(client, url, expected):
    with client.stream('GET', url) as response:
        assert response.status_code == expected, 'Unexpected resource status'

store = AccountStore(settings.DATABASE_PATH, initialize=False)
manager = JobManager()
test_id = None
invite_id = None
test_name = None
try:
    with httpx.Client(base_url=args.base_url, timeout=120, follow_redirects=False, trust_env=False) as owner, httpx.Client(base_url=args.base_url, timeout=120, follow_redirects=False, trust_env=False) as other, httpx.Client(base_url=args.base_url, timeout=30, follow_redirects=False, trust_env=False) as guest:
        assert '<html lang="ru">' in owner.get('/login').text
        mark('https_and_russian_default')
        if not args.passwordless:
            password = read_secret('Owner password (hidden; used only for HTTPS login): ')
            response = post(owner, '/login', {'username': args.owner, 'password': password})
            password = None
            mark('owner_login_http_status', response.status_code)
            assert response.status_code == 303, 'Owner login failed'
            me = owner.get('/api/me').json()
            assert me['username'] == args.owner and me['role'] == 'admin'
            mark('owner_login')
        else:
            with store.database.connect() as db:
                me = dict(db.execute("SELECT id,username,role FROM users WHERE username=? AND is_active=1", (args.owner,)).fetchone())
            mark('owner_authentication_skipped')
        legacy = json.loads(Path('jobs_db.json').read_text())
        jobs = manager.list_jobs(owner_user_id=me['id'])
        assert {j['id'] for j in legacy}.issubset({j.id for j in jobs})
        if not args.passwordless:
            history = owner.get('/dashboard').text
            assert all('/result/' + j['id'] in history for j in legacy)
        mark('owner_legacy_history_count', len(legacy))
        invite = secrets.token_urlsafe(32)
        invite_id = store.create_invite(invite, max_uses=1, label='deployment-smoke')
        test_name = 'smoke-' + secrets.token_hex(6)
        test_password = secrets.token_urlsafe(32)
        response = post(other, '/register', {'username': test_name, 'password': test_password, 'invite_code': invite})
        assert response.status_code == 303
        test_id = other.get('/api/me').json()['id']
        assert not manager.list_jobs(owner_user_id=test_id)
        assert not any(j['id'] in other.get('/dashboard').text for j in legacy)
        mark('invite_registration_empty_history')
        for job in jobs:
            urls = [f'/result/{job.id}', f'/processing/{job.id}', f'/api/jobs/{job.id}', '/uploads/' + Path(job.file_path).name]
            urls += job.extracted_frame_paths or []
            if job.thumbnail:
                urls.append(job.thumbnail)
            if job.result_path:
                urls.append('/download/' + job.id)
            for url in urls:
                # Processing redirects to result only in the client; the endpoint still renders.
                if not args.passwordless:
                    available(owner, url, 200)
                forbidden = other.get(url)
                assert forbidden.status_code == 404 and forbidden.json() == {'detail': 'Not found'}
                available(guest, url, 401 if url.startswith('/api/') else 303)
        mark('legacy_resources_deny_other_and_guest' if args.passwordless else 'all_legacy_resource_isolation')
        for selected in ('en', 'ru'):
            assert post(other, '/language', {'selected': selected, 'return_to': '/dashboard'}).status_code == 303
            assert f'<html lang="{selected}">' in other.get('/dashboard').text
            assert f'<html lang="{selected}">' in other.get('/').text
        mark('ru_en_switch_persistence')
        invalid = post(other, '/upload', files={'file': ('bad.txt', b'not video', 'text/plain')})
        assert invalid.status_code == 400
        oversized = post(other, '/upload', files={'file': ('large.mp4', io.BytesIO(b'0' * (52428800 + 1)), 'video/mp4')})
        assert oversized.status_code == 413
        assert not manager.list_jobs(owner_user_id=test_id)
        mark('invalid_and_over_50_mib_rejected')
        # Reuse a backed-up real surf clip; never alter or move the original.
        candidates = [j for j in jobs if Path(j.file_path).is_file() and Path(j.file_path).suffix.lower() == '.mp4' and Path(j.file_path).stat().st_size <= 52428800]
        source = min(candidates, key=lambda j: Path(j.file_path).stat().st_size)
        with Path(source.file_path).open('rb') as video:
            response = post(other, '/upload', files={'file': ('deployment-surf-smoke.mp4', video, 'video/mp4')})
        assert response.status_code == 303
        job_id = response.headers['location'].rsplit('/', 1)[1]
        mark('new_smoke_job', job_id)
        deadline = time.monotonic() + 240
        while time.monotonic() < deadline:
            job = manager.get_job(job_id, owner_user_id=test_id)
            assert job.status != JobStatus.FAILED, 'Worker reported a failed job; inspect safely'
            if job.status == JobStatus.DONE:
                break
            time.sleep(3)
        assert job.status == JobStatus.DONE, 'Analysis timed out'
        assert len(job.extracted_frame_paths or []) == 15
        assert set(job.analysis_result or {}) == {'level', 'main_issue', 'why_it_matters', 'how_to_fix', 'drill', 'coach_note'}
        assert job.analysis_language == 'ru'
        assert any(re.search('[\u0400-\u04ff]', value) for value in job.analysis_result.values())
        result = other.get('/result/' + job_id)
        assert result.status_code == 200 and result.text.count('data-frame-index=') == 15
        assert 'frame-viewer' in result.text
        for url in ['/result/' + job_id, '/processing/' + job_id, '/api/jobs/' + job_id, '/uploads/' + Path(job.file_path).name, '/download/' + job_id] + job.extracted_frame_paths:
            available(other, url, 200)
            if not args.passwordless:
                available(owner, url, 404)
            available(guest, url, 401 if url.startswith('/api/') else 303)
        if not args.passwordless:
            assert job_id not in owner.get('/dashboard').text
        mark('real_upload_openai_russian_15_frames_result_and_guest_isolation' if args.passwordless else 'real_upload_openai_russian_15_frames_result_and_reverse_isolation')
        cookie = other.cookies.get('surfanalyze_account')
        assert post(other, '/logout').status_code == 303
        assert other.get('/api/me').status_code == 401
        available(other, '/result/' + job_id, 303)
        assert guest.get('/api/me', headers={'Cookie': 'surfanalyze_account=' + cookie}).status_code == 401
        assert post(other, '/login', {'username': test_name, 'password': test_password}).status_code == 303
        test_password = None
        assert post(other, '/logout').status_code == 303
        if not args.passwordless:
            assert post(owner, '/logout').status_code == 303
        mark('login_logout_replay')
        mark('passwordless_complete' if args.passwordless else 'complete')
except Exception as error:
    # Exception messages may contain HTTP context; never print raw exceptions.
    mark('failure_type', type(error).__name__)
    tb = error.__traceback__
    while tb.tb_next is not None:
        tb = tb.tb_next
    # Record only code location, never exception text, locals, bodies, or cookies.
    mark('failure_function', tb.tb_frame.f_code.co_name)
    mark('failure_line', tb.tb_lineno)
    sys.exit(1)
finally:
    with store.database.connect(write=True) as db:
        if test_id is None and test_name is not None:
            row = db.execute('SELECT id FROM users WHERE username=?', (test_name,)).fetchone()
            test_id = row[0] if row else None
        if test_id is not None:
            db.execute('UPDATE users SET is_active=0 WHERE id=?', (test_id,))
        if invite_id is not None:
            db.execute('UPDATE invites SET is_active=0 WHERE id=?', (invite_id,))
    mark('temporary_account_and_invite_disabled')
