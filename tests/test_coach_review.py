import json
import re
import shutil
import sqlite3
import subprocess
import sys

import pytest

from coach.migration import migrate
from coach.store import CoachStore, FIELDS, dataset_record, export_records
from jobs.job_model import JobStatus
from tests.conftest import sign_in
from webapp import main


@pytest.fixture
def completed(app_state):
    job = main.job_manager.create_job(user_id=1, owner_user_id=1, file_path='data/uploads/private.mp4', analysis_language='ru')
    original = {k: 'Исходный ' + k for k in FIELDS}
    paths = [f'/frames/{job.id}/frame_{i:02}.jpg' for i in range(1, 16)]
    main.job_manager.update_job(job.id, status=JobStatus.DONE, analysis_result=original, extracted_frame_paths=paths)
    return main.job_manager.get_job(job.id)


@pytest.fixture
def reviewer(client, app_state):
    with app_state[0].database.connect(write=True) as db:
        db.execute("UPDATE users SET role='admin' WHERE username='alice'")
    return client


def payload(**changes):
    result = {'revision': 0, 'status': 'saved', 'corrections': {k: None for k in FIELDS},
              'general_comment': 'Общий комментарий', 'frame_notes': [{'frame_index': 8, 'note': 'Поворот намеренный'}]}
    result.update(changes)
    return result


def endpoint(job):
    return '/api/coach-reviews/' + job.id


@pytest.mark.parametrize('role', ['admin', 'coach'])
def test_authorized_review_create_update_snapshot_and_restart(reviewer, app_state, completed, role):
    with app_state[0].database.connect(write=True) as db:
        db.execute('UPDATE users SET role=? WHERE id=1', (role,))
    before = main.job_manager.get_job(completed.id).to_dict()
    data = payload()
    data['corrections']['main_issue'] = 'Исправлено'
    response = reviewer.post(endpoint(completed), json=data)
    assert response.status_code == 200
    first = response.json()['review']
    assert first['original_analysis'] == completed.analysis_result
    assert first['analysis_language'] == 'ru'
    assert first['revision'] == 1
    assert main.job_manager.get_job(completed.id).to_dict() == before
    # A restarted service reads the same durable data.
    store = CoachStore(app_state[0].database.path)
    assert store.get(completed.id, 1) == first
    # Subsequent AI changes cannot silently replace the immutable first snapshot.
    main.job_manager.update_job(completed.id, analysis_result={k: 'new AI' for k in FIELDS})
    data.update(revision=1, frame_notes=[{'frame_index': 8, 'note': 'Обновлено'}])
    second = reviewer.post(endpoint(completed), json=data).json()['review']
    assert second['id'] == first['id'] and second['revision'] == 2
    assert second['original_analysis'] == first['original_analysis']
    assert second['created_at'] == first['created_at']
    assert second['frame_notes'] == data['frame_notes']
    data.update(revision=2, frame_notes=[])
    assert reviewer.post(endpoint(completed), json=data).json()['review']['frame_notes'] == []
    with app_state[0].database.connect() as db:
        assert db.execute('SELECT count(*) FROM coach_reviews').fetchone()[0] == 1
        assert not db.execute('PRAGMA foreign_key_check').fetchall()


def test_normal_guest_and_cross_owner_rejected(client, guest, app_state, completed):
    assert client.get(endpoint(completed)).status_code == 403
    assert client.post(endpoint(completed), json=payload()).status_code == 403
    assert 'coach-review-form' not in client.get('/result/' + completed.id).text
    client.post('/logout')
    client.headers.pop('X-CSRF-Token')
    assert guest.get(endpoint(completed)).status_code == 401
    assert guest.post(endpoint(completed), json=payload()).status_code == 401
    with app_state[0].database.connect(write=True) as db:
        db.execute("UPDATE users SET role='coach' WHERE username='bob'")
    sign_in(client, 'bob')
    assert client.get('/result/' + completed.id).status_code == 404
    assert client.get(endpoint(completed)).status_code == 404
    assert client.post(endpoint(completed), json=payload()).status_code == 404


def test_csrf_origin_and_inactive_reviewer(reviewer, completed, app_state):
    assert reviewer.post(endpoint(completed), json=payload(), headers={'Origin': 'https://evil.example'}).status_code == 403
    reviewer.headers.pop('X-CSRF-Token')
    assert reviewer.post(endpoint(completed), json=payload()).status_code == 403
    with app_state[0].database.connect(write=True) as db:
        db.execute('UPDATE users SET is_active=0 WHERE id=1')
    assert reviewer.get(endpoint(completed)).status_code == 401


@pytest.mark.parametrize('notes', [[{'frame_index': 0, 'note': 'bad'}], [{'frame_index': 16, 'note': 'bad'}],
                                 [{'frame_index': True, 'note': 'bad'}], [{'frame_index': 8, 'note': 'x'}]*2,
                                 [{'frame_index': 8, 'note': 'x'*4001}]])
def test_invalid_frame_notes_atomic(reviewer, app_state, completed, notes):
    assert reviewer.post(endpoint(completed), json=payload(frame_notes=notes)).status_code == 400
    with app_state[0].database.connect() as db:
        assert db.execute('SELECT count(*) FROM coach_reviews').fetchone()[0] == 0


def test_stale_revision_frame_changes_and_unfinished(reviewer, completed):
    assert reviewer.post(endpoint(completed), json=payload()).status_code == 200
    assert reviewer.post(endpoint(completed), json=payload()).status_code == 409
    main.job_manager.update_job(completed.id, extracted_frame_paths=list(reversed(completed.extracted_frame_paths)))
    assert reviewer.post(endpoint(completed), json=payload(revision=1)).status_code == 409
    main.job_manager.update_job(completed.id, status=JobStatus.PROCESSING)
    assert reviewer.post(endpoint(completed), json=payload(revision=1)).status_code == 400


def test_snapshot_trigger_and_delete_cascade(reviewer, app_state, completed):
    reviewer.post(endpoint(completed), json=payload())
    with pytest.raises(sqlite3.IntegrityError), app_state[0].database.connect(write=True) as db:
        db.execute("UPDATE coach_reviews SET original_analysis_snapshot='{}'")
    with app_state[0].database.connect(write=True) as db:
        db.execute('DELETE FROM jobs WHERE id=?', (completed.id,))
    with app_state[0].database.connect() as db:
        assert not db.execute('SELECT * FROM coach_reviews').fetchall()
        assert not db.execute('SELECT * FROM coach_frame_notes').fetchall()
        assert not db.execute('PRAGMA foreign_key_check').fetchall()


def test_migration_repeatable_preserves_existing_tables(app_state, completed):
    database = app_state[0].database
    with database.connect(write=True) as db:
        for statement in ('DROP TRIGGER coach_review_snapshot_immutable', 'DROP TABLE coach_frame_notes', 'DROP TABLE coach_reviews', "DELETE FROM metadata WHERE key='coach_schema_version'"):
            db.execute(statement)
    def snapshot():
        with database.connect() as db:
            return {t: [tuple(row) for row in db.execute('SELECT * FROM '+t)] for t in ('users','sessions','invites','jobs','auth_attempts')}
    before = snapshot()
    migrate(database)
    migrate(database)
    assert snapshot() == before
    with database.connect() as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert db.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()[0] == '1'


def test_dataset_deterministic_utf8_and_empty_export(reviewer, app_state, completed, tmp_path):
    database = app_state[0].database
    command = [sys.executable, '-m', 'coach.cli', '--database', str(database.path), 'export-coach-dataset', '--output']
    empty = tmp_path / 'empty.jsonl'
    subprocess.run(command + [str(empty)], check=True, capture_output=True)
    assert empty.read_bytes() == b''
    data = payload(status='draft')
    reviewer.post(endpoint(completed), json=data)
    assert list(export_records(database)) == []
    data.update(status='saved', revision=1)
    data['corrections']['level'] = 'Исправленный уровень'
    review = reviewer.post(endpoint(completed), json=data).json()['review']
    record = dataset_record(review)
    assert record['schema_version'] == 1
    assert record['original_analysis'] == completed.analysis_result
    assert record['coach_correction']['level'] == data['corrections']['level']
    assert record['coach_correction']['drill'] == completed.analysis_result['drill']
    assert record['changed_fields']['level'] and not record['changed_fields']['drill']
    assert record['frame_notes'] == data['frame_notes']
    assert [f['frame_index'] for f in record['frames']] == list(range(1,16))
    assert record['analysis_language'] == 'ru'
    output = tmp_path / 'dataset.jsonl'
    subprocess.run(command + [str(output)], check=True, capture_output=True)
    encoded = output.read_bytes()
    assert json.loads(encoded.decode('utf-8')) == record
    assert 'Исправленный'.encode() in encoded
    again = tmp_path / 'again.jsonl'
    subprocess.run(command + [str(again)], check=True, capture_output=True)
    assert again.read_bytes() == encoded
    assert subprocess.run(command + [str(output)], capture_output=True).returncode == 1
    for key in ('password', 'password_hash', 'session', 'invite', 'api_key', 'username', 'file_path', 'original_filename'):
        assert key not in json.dumps(record)


@pytest.mark.parametrize('lang,label', [('ru','Разбор тренера'), ('en','Coach Review')])
def test_coach_ui_safe_localized_and_scripts(reviewer, completed, tmp_path, lang, label):
    attack = '</textarea><script>alert(1)</script>'
    data = payload(general_comment=attack, frame_notes=[{'frame_index':8,'note':attack}])
    data['corrections']['level'] = attack
    reviewer.post(endpoint(completed), json=data)
    reviewer.cookies.set('surfanalyze_language', lang)
    html = reviewer.get('/result/' + completed.id).text
    assert label in html and 'coach-review-form' in html
    assert attack not in html
    assert completed.analysis_result['level'] in html
    assert html.count('data-frame-index=') == 15
    node = shutil.which('node')
    assert node
    for i, script in enumerate(re.findall(r'<script>(.*?)</script>', html, re.S)):
        path = tmp_path / f'coach-{i}.js'
        path.write_text(script, encoding='utf-8')
        subprocess.run([node, '--check', str(path)], check=True, capture_output=True)


def test_invalid_payload_is_not_reflected_and_body_bounded(reviewer, completed):
    assert reviewer.post(endpoint(completed), content='{bad json').status_code == 400
    data = payload()
    data['password'] = 'do-not-reflect'
    response = reviewer.post(endpoint(completed), json=data)
    assert response.status_code == 400 and 'do-not-reflect' not in response.text
    assert reviewer.post(endpoint(completed), content=b'x'*(512*1024+1)).status_code == 413


def test_failed_note_write_rolls_back_entire_save(reviewer, app_state, completed):
    first = reviewer.post(endpoint(completed), json=payload()).json()['review']
    with app_state[0].database.connect(write=True) as db:
        db.execute("""CREATE TRIGGER reject_test_note BEFORE UPDATE ON coach_frame_notes
                      BEGIN SELECT RAISE(ABORT, 'test write failure'); END""")
    response = reviewer.post(endpoint(completed), json=payload(revision=1, general_comment='must roll back'))
    assert response.status_code == 503
    assert reviewer.get(endpoint(completed)).json()['review'] == first


def test_service_checks_ownership_and_role_inside_transaction(app_state, completed):
    store = CoachStore(app_state[0].database.path)
    with pytest.raises(PermissionError):
        store.save(completed.id, 1, payload())
    with app_state[0].database.connect(write=True) as db:
        db.execute("UPDATE users SET role='coach' WHERE id=2")
    with pytest.raises(LookupError):
        store.save(completed.id, 2, payload())


def test_unknown_migration_version_is_not_overwritten(app_state):
    database = app_state[0].database
    with database.connect(write=True) as db:
        db.execute("UPDATE metadata SET value='future' WHERE key='coach_schema_version'")
    with pytest.raises(RuntimeError):
        migrate(database)
    with database.connect() as db:
        assert db.execute("SELECT value FROM metadata WHERE key='coach_schema_version'").fetchone()[0] == 'future'


@pytest.mark.parametrize('language,label,count', [('en','Edit Coach Review','Frame notes: 2'), ('ru','Редактировать разбор тренера','Комментариев к кадрам: 2')])
@pytest.mark.parametrize('comment', ['', '<script>private feedback</script>'])
def test_saved_summary_without_field_corrections(reviewer, completed, language, label, count, comment):
    from bs4 import BeautifulSoup
    before = main.job_manager.get_job(completed.id).to_dict()
    data = payload(general_comment=comment, frame_notes=[{'frame_index': 8, 'note': 'one'}, {'frame_index': 12, 'note': 'two'}])
    assert all(value is None for value in data['corrections'].values())
    assert reviewer.post(endpoint(completed), json=data).status_code == 200
    reviewer.cookies.set('surfanalyze_language', language)
    page = BeautifulSoup(reviewer.get('/result/' + completed.id).text, 'html.parser')
    summary = page.select_one('#coach-review-summary')
    assert summary is not None and not summary.has_attr('hidden')
    assert not summary.find_parent('details')
    assert not summary.select('textarea, form, script')
    assert page.select_one('#coach-summary-comment-text').get_text() == comment
    assert page.select_one('#coach-summary-comment').has_attr('hidden') == (not comment)
    assert page.select_one('#coach-summary-notes').get_text() == count
    assert page.select_one('#coach-review-edit').get_text() == label
    assert not page.select_one('#coach-review-editor').has_attr('open')
    assert main.job_manager.get_job(completed.id).to_dict() == before


def test_summary_comment_only_and_draft_visibility(reviewer, completed):
    from bs4 import BeautifulSoup
    data = payload(frame_notes=[], general_comment='Comment without field corrections')
    assert reviewer.post(endpoint(completed), json=data).status_code == 200
    page = BeautifulSoup(reviewer.get('/result/' + completed.id).text, 'html.parser')
    assert not page.select_one('#coach-review-summary').has_attr('hidden')
    assert page.select_one('#coach-summary-comment-text').get_text() == data['general_comment']
    data.update(revision=1, status='draft')
    assert reviewer.post(endpoint(completed), json=data).status_code == 200
    page = BeautifulSoup(reviewer.get('/result/' + completed.id).text, 'html.parser')
    assert page.select_one('#coach-review-summary').has_attr('hidden')
    assert page.select_one('#coach-review-state').get_text() == 'Draft'
