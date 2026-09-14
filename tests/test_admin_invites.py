import logging
import re
import shutil
import subprocess
from urllib.parse import parse_qs, urlsplit

import pytest

from accounts.security import token_hash
from tests.conftest import PASSWORD, csrf
from webapp import main


@pytest.fixture
def admin(client, app_state):
    with app_state[0].database.connect(write=True) as db:
        db.execute("UPDATE users SET role='admin' WHERE username='alice'")
    return client


def test_admin_creates_single_use_link_and_registration(admin, app_state, caplog):
    response = admin.post('/api/invites', headers={'Origin': 'https://testserver'})
    assert response.status_code == 201
    assert set(response.json()) == {'url'}
    assert response.headers['cache-control'] == 'no-store'
    url = urlsplit(response.json()['url'])
    assert url.scheme == 'https' and url.netloc == 'surfanalyze.com' and url.path == '/register'
    token = parse_qs(url.query)['invite'][0]
    assert re.fullmatch(r'[A-Za-z0-9_-]{43}', token)
    with app_state[0].database.connect() as db:
        row = db.execute('SELECT * FROM invites').fetchone()
        assert row['code_hash'] == token_hash(token)
        assert row['max_uses'] == 1 and row['used_count'] == 0 and row['is_active'] == 1
    assert token not in caplog.text and row['code_hash'] not in response.text
    admin.post('/logout')
    admin.headers.pop('X-CSRF-Token')
    # No code is copied into a form: the URL establishes a pending invitation.
    response = admin.get('/register?' + url.query)
    assert response.status_code == 303 and response.headers['location'] == '/register'
    assert response.headers['referrer-policy'] == 'no-referrer'
    assert 'httponly' in response.headers['set-cookie'].lower()
    page = admin.get('/register')
    assert page.headers['referrer-policy'] == 'same-origin'
    assert token not in page.text
    assert 'applied automatically' in page.text
    # The invitation survives changing language and a rejected registration.
    assert admin.post('/language', data={'csrf': csrf(admin), 'selected': 'en', 'return_to': '/register'}).status_code == 303
    data = {'username': 'alice', 'password': PASSWORD, 'csrf': csrf(admin)}
    rejected = admin.post('/register', data=data)
    assert rejected.status_code == 303 and rejected.headers['location'] == '/register'
    assert 'Unable to register' in admin.get('/register').text
    data['username'] = 'invited'
    assert admin.post('/register', data=data).status_code == 303
    assert admin.get('/api/me').json()['role'] == 'user'
    assert 'create-invite-form' not in admin.get('/dashboard').text
    with app_state[0].database.connect() as db:
        assert db.execute('SELECT used_count FROM invites').fetchone()[0] == 1
    admin.post('/logout', data={'csrf': csrf(admin, '/')})
    admin.get('/register?' + url.query)
    data.update(username='second', csrf=csrf(admin))
    rejected = admin.post('/register', data=data)
    assert rejected.status_code == 303 and rejected.headers['location'] == '/register'
    assert 'already been used' in admin.get('/register').text


@pytest.mark.parametrize('role', ['user', 'coach'])
def test_non_admin_cannot_create(client, app_state, role):
    with app_state[0].database.connect(write=True) as db:
        db.execute('UPDATE users SET role=? WHERE username=?', (role, 'alice'))
    assert 'create-invite-form' not in client.get('/').text
    assert client.post('/api/invites').status_code == 403
    with app_state[0].database.connect() as db:
        assert db.execute('SELECT count(*) FROM invites').fetchone()[0] == 0


def test_guest_cannot_create(guest):
    assert guest.post('/api/invites').status_code == 401
    assert 'create-invite-form' not in guest.get('/register').text


def test_admin_csrf_origin_and_post_only(admin, app_state):
    assert admin.get('/api/invites').status_code == 405
    assert admin.post('/api/invites', headers={'Origin': 'https://evil.example'}).status_code == 403
    admin.headers.pop('X-CSRF-Token')
    assert admin.post('/api/invites').status_code == 403
    assert admin.post('/api/invites', data={'csrf': 'wrong'}).status_code == 403
    with app_state[0].database.connect() as db:
        assert db.execute('SELECT count(*) FROM invites').fetchone()[0] == 0


@pytest.mark.parametrize('kind', ['invalid', 'disabled'])
def test_bad_link_rejected(guest, app_state, kind):
    token = 'invalid-test-invitation-token-123456789'
    if kind == 'disabled':
        invite_id = app_state[0].create_invite(token)
        with app_state[0].database.connect(write=True) as db:
            db.execute('UPDATE invites SET is_active=0 WHERE id=?', (invite_id,))
    guest.get('/register', params={'invite': token})
    rejected = guest.post('/register', data={'username': 'newuser', 'password': PASSWORD, 'csrf': csrf(guest)})
    assert rejected.status_code == 303 and rejected.headers['location'] == '/register'
    assert ('not valid' if kind == 'invalid' else 'disabled') in guest.get('/register').text
    assert guest.get('/api/me').status_code == 401


@pytest.mark.parametrize('language,create,copy', [('ru', 'Создать инвайт', 'Скопировать ссылку'), ('en', 'Create invite', 'Copy link')])
def test_admin_ui_localization_and_javascript(admin, language, create, copy, tmp_path):
    admin.cookies.set('surfanalyze_language', language)
    page = admin.get('/admin/invites').text
    assert create in page and copy in page
    node = shutil.which('node')
    assert node
    script = next(s for s in re.findall(r'<script>(.*?)</script>', page, re.S) if 'create-invite-form' in s)
    path = tmp_path / 'invite.js'
    path.write_text(script, encoding='utf-8')
    subprocess.run([node, '--check', str(path)], check=True, capture_output=True)
    subprocess.run([node, 'tests/admin_invite_client.cjs', str(path)], check=True, capture_output=True)


@pytest.mark.parametrize('path', ['/register', '/register/', '/%72egister'])
def test_access_log_redacts_invite(path):
    record = logging.LogRecord('uvicorn.access', logging.INFO, '', 0, '%s - "%s %s HTTP/%s" %d',
                               ('client', 'GET', path + '?invite=secret', '1.1', 303), None)
    main.InviteAccessLogFilter().filter(record)
    assert 'secret' not in record.getMessage() and '/register' in record.getMessage()


def test_creation_failure_is_safe(admin, monkeypatch):
    import sqlite3
    def fail(*args, **kwargs):
        raise sqlite3.OperationalError('private database context')
    monkeypatch.setattr(main.account_store, 'create_invite', fail)
    response = admin.post('/api/invites')
    assert response.status_code == 503
    assert response.json() == {'error': 'Invite creation failed'}


def test_inactive_admin_cannot_create(admin, app_state):
    with app_state[0].database.connect(write=True) as db:
        db.execute("UPDATE users SET is_active=0 WHERE username='alice'")
    assert admin.post('/api/invites').status_code == 401
