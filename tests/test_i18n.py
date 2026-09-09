import json
import re
import shutil
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from tests.conftest import csrf, sign_in
from jobs.job_model import JobStatus
from services.openai_surf_analysis_provider import OpenAISurfAnalysisProvider, SURF_ANALYSIS_SCHEMA
from webapp import main
from webapp.i18n import CATALOGS


def test_default_language_and_cookie_survive_login_logout(guest):
    guest.cookies.clear()
    assert '<html lang="ru">' in guest.get('/login').text
    assert 'Создайте аккаунт' in guest.get('/register').text
    response = guest.post('/language', data={'selected': 'en', 'csrf': csrf(guest), 'return_to': '/login'})
    assert response.status_code == 303
    cookie = response.headers['set-cookie']
    assert all(flag in cookie for flag in ('HttpOnly', 'Secure', 'SameSite=lax'))
    sign_in(guest)
    assert '<html lang="en">' in guest.get('/dashboard').text
    assert guest.post('/logout', data={'csrf': csrf(guest, '/')}).status_code == 303
    assert '<html lang="en">' in guest.get('/login').text


def test_language_csrf_origin_redirect_and_invalid_cookie(guest):
    assert guest.post('/language', data={'selected': 'en'}).status_code == 403
    token = csrf(guest)
    data = {'selected': 'ru', 'csrf': token, 'return_to': '//evil.example'}
    assert guest.post('/language', data=data, headers={'Origin': 'https://evil.example'}).status_code == 403
    response = guest.post('/language', data=data)
    assert response.headers['location'] == '/'
    data['selected'] = 'unknown'
    assert guest.post('/language', data=data).status_code == 400
    guest.cookies.clear()
    guest.cookies.set('surfanalyze_language', 'unknown')
    assert '<html lang="ru">' in guest.get('/login').text


@pytest.mark.parametrize('selected', ['ru', 'en'])
def test_localized_core_flow_and_saved_job_language(client, monkeypatch, tmp_path, selected):
    client.cookies.set('surfanalyze_language', selected)
    monkeypatch.setattr(main, 'readable_thumbnail', lambda _: True)
    response = client.post('/upload', files={'file': ('ride.mp4', b'video', 'video/mp4')})
    assert response.status_code == 303
    job = main.job_manager.list_jobs()[0]
    assert job.analysis_language == selected
    pages = [client.get('/').text, client.get('/dashboard').text, client.get(response.headers['location']).text]
    main.job_manager.update_job(job.id, status=JobStatus.DONE,
                               analysis_result={key: 'Saved feedback' for key in SURF_ANALYSIS_SCHEMA['properties']},
                               extracted_frame_paths=[f'/frames/{job.id}/frame_{n:02}.jpg' for n in range(1, 16)])
    result = client.get(f'/result/{job.id}').text
    pages.append(result)
    assert result.count('data-frame-index=') == 15
    assert ('Закрыть просмотр кадров' if selected == 'ru' else 'Close frame viewer') in result
    assert ('Ключевые кадры' if selected == 'ru' else 'Representative Frames') in result
    assert 'Saved feedback' in result
    invalid = client.post('/upload', files={'file': ('bad.txt', b'bad', 'text/plain')})
    assert invalid.status_code == 400
    assert ('Неподдерживаемый формат' if selected == 'ru' else 'Unsupported video format') in invalid.text
    assert all(f'<html lang="{selected}">' in page for page in pages)
    node = shutil.which('node')
    assert node, 'Node is required to verify rendered JavaScript'
    for page_index, page in enumerate(pages):
        for index, script in enumerate(re.findall(r'<script>(.*?)</script>', page, re.S)):
            path = tmp_path / f'script-{page_index}-{index}.js'
            path.write_text(script, encoding='utf-8')
            subprocess.run([node, '--check', str(path)], check=True, capture_output=True)


@pytest.mark.parametrize('selected,expected', [('ru', 'Russian'), ('en', 'English')])
def test_provider_language_keeps_schema(tmp_path, selected, expected):
    frame = tmp_path / 'frame.jpg'
    frame.write_bytes(b'frame')
    client = MagicMock()
    client.responses.create.return_value.output_text = json.dumps({key: 'text' for key in SURF_ANALYSIS_SCHEMA['properties']})
    OpenAISurfAnalysisProvider('test-only', 'test-model', client).analyze([frame], language=selected)
    arguments = client.responses.create.call_args.kwargs
    assert f'values in {expected}' in arguments['instructions']
    assert arguments['text']['format']['schema'] == SURF_ANALYSIS_SCHEMA


def test_catalog_covers_all_template_messages():
    for path in Path('webapp/templates').glob('*.html'):
        for message in re.findall(r'\bt\("([^"\n]+)"', path.read_text(encoding='utf-8')):
            assert message in CATALOGS['ru'], (path, message)
