import base64
import json
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from accounts.invite_migration import migrate
from accounts.security import token_hash
from accounts.store import AccountStore, InviteError
from storage.database import Database, SCHEMA
from tests.conftest import PASSWORD, csrf
from tests.test_admin_invites import admin
from webapp import main

TOKEN = 'local-only-invite-management-token-123456'


def post_registration(client, name='tester', code=''):
    return client.post('/register', data={'username': name, 'password': PASSWORD,
                       'invite_code': code, 'csrf': csrf(client)})


def invite_row(store):
    with store.database.connect() as db:
        return dict(db.execute('SELECT * FROM invites ORDER BY id DESC').fetchone())


@pytest.mark.parametrize('expiry,days', [(None, 7), ('1', 1), ('30', 30), ('none', None)])
def test_creation_expiry_and_safe_list(admin, app_state, expiry, days):
    now = int(time.time())
    data = {'label': '<script>alert(1)</script>'}
    if expiry:
        data['expiry'] = expiry
    response = admin.post('/api/invites', data=data)
    assert response.status_code == 201
    token = parse_qs(urlsplit(response.json()['url']).query)['invite'][0]
    row = invite_row(app_state[0])
    assert row['code_hash'] == token_hash(token)
    assert row['max_uses'] == 1 and row['is_active'] == 1
    assert row['expires_at'] is None if days is None else now + days * 86400 <= row['expires_at'] <= int(time.time()) + days * 86400
    page = admin.get('/admin/invites')
    assert page.status_code == 200
    assert token not in page.text and row['code_hash'] not in page.text
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in page.text
    assert '<script>alert(1)</script>' not in page.text
    assert 'href="/admin"' in admin.get('/dashboard').text


@pytest.mark.parametrize('role', ['user', 'coach'])
def test_management_role_boundary(client, app_state, role):
    store = app_state[0]
    identity = store.create_invite(TOKEN)
    with store.database.connect(write=True) as db:
        db.execute("UPDATE users SET role=? WHERE username='alice'", (role,))
    for path in ['/admin', '/admin/invites', '/admin/invites?before=100']:
        assert client.get(path).status_code == 403
    assert client.post(f'/admin/invites/{identity}/disable', data={'confirmed': 'yes'}).status_code == 403
    assert 'href="/admin"' not in client.get('/dashboard').text
    assert invite_row(store)['is_active'] == 1


def test_management_guest_boundary(guest, app_state):
    identity = app_state[0].create_invite(TOKEN)
    assert guest.get('/admin/invites').headers['location'] == '/login'
    assert guest.post(f'/admin/invites/{identity}/disable', data={'confirmed': 'yes'}).headers['location'] == '/login'
    assert guest.post('/api/invites').status_code == 401
    assert invite_row(app_state[0])['is_active'] == 1


def test_disable_requires_confirmation_csrf_origin_and_preserves_history(admin, app_state):
    store = app_state[0]
    identity = store.create_invite(TOKEN)
    path = f'/admin/invites/{identity}/disable'
    assert admin.get(path).status_code == 405
    assert admin.post(path).status_code == 400
    assert admin.post(path, data={'confirmed': 'yes'}, headers={'Origin': 'https://evil.example'}).status_code == 403
    assert admin.post(path, data={'confirmed': 'yes'}, headers={'X-CSRF-Token': 'wrong'}).status_code == 403
    assert invite_row(store)['is_active'] == 1
    response = admin.post(path, data={'confirmed': 'yes'})
    assert response.status_code == 303 and response.headers['location'] == '/admin/invites'
    assert 'Disabled' in admin.get('/admin/invites').text
    assert invite_row(store)['is_active'] == 0
    with pytest.raises(InviteError, match='disabled'):
        store.register('tester', PASSWORD, TOKEN)
    assert len(store.list_invites()) == 1


@pytest.mark.parametrize('kind,message', [('invalid', 'not valid'), ('used', 'already been used'),
                                          ('expired', 'expired'), ('disabled', 'disabled')])
def test_friendly_get_and_post_errors_prg(guest, app_state, kind, message):
    store = app_state[0]
    if kind != 'invalid':
        identity = store.create_invite(TOKEN)
        with store.database.connect(write=True) as db:
            if kind == 'used':
                db.execute('UPDATE invites SET used_count=1 WHERE id=?', (identity,))
            elif kind == 'expired':
                db.execute('UPDATE invites SET expires_at=0 WHERE id=?', (identity,))
            else:
                db.execute('UPDATE invites SET is_active=0 WHERE id=?', (identity,))
    response = guest.get('/register', params={'invite': TOKEN})
    assert response.status_code == 303 and response.headers['location'] == '/register'
    page = guest.get('/register')
    assert message in page.text and TOKEN not in page.text
    for _ in range(2):
        rejected = post_registration(guest)
        assert rejected.status_code == 303 and rejected.headers['location'] == '/register'
        assert message in guest.get('/register').text
    with store.database.connect() as db:
        assert db.execute('SELECT count(*) FROM users').fetchone()[0] == 2


def test_two_devices_open_then_one_registers_session_rotates_and_replay_fails(guest, app_state):
    store = app_state[0]
    store.create_invite(TOKEN)
    with TestClient(main.app, base_url='https://testserver', follow_redirects=False) as other:
        other.cookies.set('surfanalyze_language', 'en')
        for device in (guest, other):
            device.get('/register', params={'invite': TOKEN})
            assert 'applied automatically' in device.get('/register').text
        old = guest.cookies.get('surfanalyze_account')
        response = post_registration(guest)
        assert response.status_code == 303 and response.headers['location'] == '/dashboard'
        for _ in range(2):
            assert guest.get('/dashboard').status_code == 200
        assert guest.get('/register').headers['location'] == '/dashboard'
        current = guest.cookies.get('surfanalyze_account')
        assert current != old
        session = json.loads(base64.b64decode(current.split('.')[0]))
        assert 'registration_invite' not in session
        identity = guest.get('/api/me').json()
        row = invite_row(store)
        assert row['used_by_user_id'] == identity['id'] and row['used_at']
        response = post_registration(other, 'another')
        assert response.headers['location'] == '/register'
        assert 'already been used' in other.get('/register').text
        other.cookies.set('surfanalyze_account', old, domain='testserver.local', path='/')
        assert other.get('/api/me').status_code == 401
        with store.database.connect() as db:
            assert db.execute('SELECT count(*) FROM users').fetchone()[0] == 3
        assert row['used_count'] == 1


def test_concurrent_http_activation_exactly_one_wins(app_state):
    store = app_state[0]
    store.create_invite(TOKEN)
    barrier = threading.Barrier(2)
    def submit(name):
        with TestClient(main.app, base_url='https://testserver', follow_redirects=False) as device:
            device.get('/register', params={'invite': TOKEN})
            token = csrf(device)
            barrier.wait(timeout=10)
            response = device.post('/register', data={'username': name, 'password': PASSWORD, 'csrf': token})
            return response.status_code, response.headers['location'], device.get('/api/me').status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit, ['race-one', 'race-two']))
    assert sorted(results) == [(303, '/dashboard', 200), (303, '/register', 401)]
    row = invite_row(store)
    assert row['used_count'] == 1 and row['used_by_user_id'] and row['used_at']
    with store.database.connect() as db:
        assert db.execute('SELECT count(*) FROM users').fetchone()[0] == 3


@pytest.mark.parametrize('iteration', range(4))
def test_concurrent_disable_activation_is_safe(app_state, monkeypatch, iteration):
    store = app_state[0]
    identity = store.create_invite(TOKEN)
    from accounts import store as module
    # Hashing is unrelated to SQLite locking; avoid spending time before the race.
    with store.database.connect() as db:
        encoded = db.execute('SELECT password_hash FROM users LIMIT 1').fetchone()[0]
    monkeypatch.setattr(module, 'hash_password', lambda _: encoded)
    barrier = threading.Barrier(2)
    def activate():
        barrier.wait(timeout=10)
        try:
            store.register('race-user', PASSWORD, TOKEN)
            return True
        except InviteError:
            return False
    def disable():
        barrier.wait(timeout=10)
        return store.disable_invite(identity)
    with ThreadPoolExecutor(max_workers=2) as pool:
        activated, disabled = pool.submit(activate), pool.submit(disable)
        activated, disabled = activated.result(timeout=20), disabled.result(timeout=20)
    assert activated != disabled
    row = invite_row(store)
    assert (row['used_count'], row['is_active']) == ((1, 1) if activated else (0, 0))
    with store.database.connect() as db:
        assert db.execute("SELECT count(*) FROM users WHERE username='race-user'").fetchone()[0] == int(activated)
    assert bool(row['used_by_user_id']) == bool(row['used_at']) == activated


def test_expiry_boundary_and_username_collision_rollback(app_state, monkeypatch):
    store = app_state[0]
    store.create_invite(TOKEN)
    with pytest.raises(ValueError):
        store.register('ALICE', PASSWORD, TOKEN)
    row = invite_row(store)
    assert row['used_count'] == 0 and row['used_at'] is None and row['used_by_user_id'] is None
    monkeypatch.setattr('accounts.store.time.time', lambda: row['expires_at'])
    with pytest.raises(InviteError, match='expired'):
        store.register('tester', PASSWORD, TOKEN)
    monkeypatch.setattr('accounts.store.time.time', lambda: row['expires_at'] - 1)
    assert store.register('tester', PASSWORD, TOKEN).username == 'tester'


def test_list_statuses_used_identity_pagination_and_no_secret(admin, app_state):
    store = app_state[0]
    for status in ('Active', 'Used', 'Expired', 'Disabled'):
        identity = store.create_invite(TOKEN + status, label=status)
        if status == 'Used':
            store.register('invite-user', PASSWORD, TOKEN + status)
        elif status == 'Disabled':
            store.disable_invite(identity)
        elif status == 'Expired':
            with store.database.connect(write=True) as db:
                db.execute('UPDATE invites SET expires_at=0 WHERE id=?', (identity,))
    assert {r['label']: r['status'] for r in store.list_invites()} == {s: s for s in ('Active', 'Used', 'Expired', 'Disabled')}
    page = admin.get('/admin/invites').text
    assert 'invite-user' in page and 'Activated at' in page and TOKEN not in page
    used = next(r for r in store.list_invites() if r['status'] == 'Used')
    assert not store.disable_invite(used['id'])
    for i in range(48):
        store.create_invite(TOKEN + str(i))
    page = admin.get('/admin/invites').text
    assert 'before=' in page
    assert len(store.list_invites(before=3)) == 2


@pytest.mark.parametrize('language,text', [('en', 'This invite has expired.'), ('ru', 'Срок действия этого инвайта истёк.')])
def test_expired_localization(guest, app_state, language, text):
    app_state[0].create_invite(TOKEN)
    with app_state[0].database.connect(write=True) as db:
        db.execute('UPDATE invites SET expires_at=0')
    guest.cookies.set('surfanalyze_language', language)
    guest.get('/register', params={'invite': TOKEN})
    assert text in guest.get('/register').text


def test_registration_csrf_origin_validation_failures_all_prg(guest, app_state):
    app_state[0].create_invite(TOKEN)
    for data, headers in [({'csrf': 'wrong'}, {}), ({'csrf': csrf(guest)}, {'Origin': 'https://evil.example'}),
                          ({'csrf': csrf(guest), 'username': 'x' * 41}, {})]:
        response = guest.post('/register?next=https://evil.example', data={
            'username': 'tester', 'password': PASSWORD, 'invite_code': TOKEN, **data}, headers=headers)
        assert response.status_code == 303 and response.headers['location'] == '/register'
        page = guest.get('/register')
        assert page.status_code == 200 and 'role="alert"' in page.text
        assert PASSWORD not in page.text and TOKEN not in page.text
    assert invite_row(app_state[0])['used_count'] == 0
    assert guest.get('/api/me').status_code == 401


def test_admin_invalid_inputs_no_reflection(admin, app_state):
    for data in [{'expiry': 'bad'}, {'label': 'x' * 101}, {'expiry': '0'}]:
        assert admin.post('/api/invites', data=data).status_code == 400
    response = admin.post('/admin/invites/not-an-id/disable', data={'csrf': 'sensitive-token'})
    assert response.status_code == 400 and 'sensitive-token' not in response.text
    assert not app_state[0].list_invites()


def test_additive_migration_repeatable_preserves_old_rows(tmp_path):
    path = tmp_path / 'old.sqlite3'
    with sqlite3.connect(path) as db:
        db.executescript(SCHEMA)
        db.execute("INSERT INTO users VALUES (1,'owner','test-hash','admin','old',1)")
        db.execute("INSERT INTO invites VALUES (1,'test-hash',NULL,3,1,'old','legacy')")
        original = db.execute('SELECT * FROM invites').fetchall()
    database = Database(path, initialize=False)
    migrate(database)
    migrate(database)
    with database.connect() as db:
        assert [tuple(r) for r in db.execute('SELECT id,code_hash,max_uses,used_count,is_active,created_at,label FROM invites')] == original
        assert tuple(db.execute('SELECT expires_at,used_by_user_id,used_at FROM invites').fetchone()) == (None, None, None)
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert not db.execute('PRAGMA foreign_key_check').fetchall()


@pytest.mark.parametrize('language', ['ru', 'en'])
def test_all_management_messages_localized(admin, language):
    from webapp.i18n import CATALOGS
    admin.cookies.set('surfanalyze_language', language)
    page = admin.get('/admin/invites').text
    for key in ('Invites', 'Create invite', 'Copy link', 'Expires in', 'No expiry', 'Invite history'):
        assert (CATALOGS['ru'][key] if language == 'ru' else key) in page
    for key in ('Active', 'Used', 'Expired', 'Disabled', 'This invite is not valid.',
                'This invite has already been used.', 'This invite has expired.', 'This invite has been disabled.'):
        assert CATALOGS['ru'][key] != key
