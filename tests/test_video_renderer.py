import hashlib
import json
import shutil
import subprocess

import cv2
import pytest

from services import video_renderer as renderer
from tests.test_video_director_web import _completed_job
from webapp import main


@pytest.fixture
def render_job(client, app_state, monkeypatch, request):
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        pytest.skip('FFmpeg and FFprobe required')
    job = _completed_job(monkeypatch, app_state)
    size = getattr(request, 'param', '320x240')
    subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                    f'color=c=red:size={size}:rate=30:duration=3', '-c:v', 'libx264', job.file_path], check=True)
    paths = []
    capture = cv2.VideoCapture(job.file_path)
    try:
        for index in range(15):
            capture.set(cv2.CAP_PROP_POS_FRAMES, index*89//14)
            ok, frame = capture.read()
            assert ok
            name = f'frame_{index+1:02}.jpg'
            assert cv2.imwrite(str(main.EXTRACTED_FRAMES_DIR / job.id / name), frame)
            paths.append(f'/frames/{job.id}/{name}')
    finally:
        capture.release()
    plan = {'version': 1, 'frame_count': 15, 'cues': [
        {'frame_number': n, 'title': 'Тренер: взгляд вперёд',
         'note': "Keep line: 100% %{not_an_expression} 'quoted' [x]; "+'я'*160,
         'arrow': {'x1': 100, 'y1': 200, 'x2': 800, 'y2': 600}}
        for n in (1, 8, 15)]}
    main.job_manager.update_job(job.id, director_plan=plan, extracted_frame_paths=paths)
    review = main.job_manager.save_director_review(job.id, 1, 0, plan)
    return main.job_manager.get_job(job.id), review


@pytest.mark.parametrize('render_job', ['320x240', '240x320'], indirect=True)
def test_real_export_and_private_revision_download(client, render_job):
    job, review = render_job
    source_hash = hashlib.sha256(open(job.file_path, 'rb').read()).hexdigest()
    url = f'/api/video-director/{job.id}/render/1'
    response = client.post(url)
    assert response.status_code == 200, response.text
    download = response.json()['url']
    result = client.get(download)
    assert result.status_code == 200 and result.headers['content-type'] == 'video/mp4'
    path = main.app.state.results_dir / 'coaching' / job.id / (renderer.render_key(review)+'.mp4')
    metadata = json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(path)]))
    assert 13.8 <= float(metadata['format']['duration']) <= 14.5
    assert metadata['streams'][0]['codec_name'] == 'h264'
    assert metadata['streams'][0]['pix_fmt'] == 'yuv420p'
    assert len(metadata['streams']) == 1  # explicitly silent export
    video = cv2.VideoCapture(str(path))
    try:
        video.set(cv2.CAP_PROP_POS_MSEC, 500)
        ok, frame = video.read()
        assert ok
        # Cyan arrow and visible Unicode comment on the first pause.
        assert ((frame[:720,:,0] > 150) & (frame[:720,:,1] > 150) & (frame[:720,:,2] < 100)).sum() > 100
        assert (frame[740:].min(axis=2) > 150).sum() > 100
    finally:
        video.release()
    modified = path.stat().st_mtime_ns
    assert client.post(url).status_code == 200
    assert path.stat().st_mtime_ns == modified
    assert hashlib.sha256(open(job.file_path, 'rb').read()).hexdigest() == source_hash
    assert main.job_manager.get_job(job.id).director_plan == review['plan']
    main.job_manager.save_director_review(job.id, 1, 1, review['plan'])
    assert client.get(download).status_code == 404
    assert client.post(url).status_code == 409


def test_export_authorization_and_failure(client, render_job, app_state, monkeypatch):
    job, review = render_job
    url = f'/api/video-director/{job.id}/render/1'
    token = client.headers.pop('X-CSRF-Token')
    assert client.post(url).status_code == 403
    client.headers['X-CSRF-Token'] = token
    with app_state[0].database.connect(write=True) as db:
        db.execute("UPDATE users SET role='user' WHERE id=1")
    assert client.post(url).status_code == 403
    with app_state[0].database.connect(write=True) as db:
        db.execute("UPDATE users SET role='coach' WHERE id=1")
        db.execute('UPDATE jobs SET owner_user_id=2 WHERE id=?', (job.id,))
    assert client.post(url).status_code == 404
    assert client.get(f'/coaching-video/{job.id}/{renderer.render_key(review)}').status_code == 404
    with app_state[0].database.connect(write=True) as db:
        db.execute('UPDATE jobs SET owner_user_id=1 WHERE id=?', (job.id,))
    monkeypatch.setattr(main, 'render_video', lambda *a: (_ for _ in ()).throw(renderer.RenderBusy()))
    assert client.post(url).status_code == 429
    monkeypatch.setattr(main, 'render_video', lambda *a: (_ for _ in ()).throw(renderer.RenderError()))
    assert client.post(url).status_code == 503


def test_failed_render_cleans_partial_files_and_releases_slot(tmp_path, monkeypatch):
    monkeypatch.setattr(renderer, '_run', lambda *a: (_ for _ in ()).throw(renderer.RenderError()))
    review = {'plan': {'frame_count': 2, 'cues': []}}
    output = tmp_path / 'out.mp4'
    for _ in range(2):
        with pytest.raises(renderer.RenderError):
            renderer.render_video(tmp_path/'input.mp4', [tmp_path/'1.jpg', tmp_path/'2.jpg'], review, output)
        assert not output.exists()
        assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize('duration,count', [(181, 90), (float('nan'), 90), (3, 1)])
def test_probe_limits_fail_before_encoding(tmp_path, monkeypatch, duration, count):
    metadata = {'streams': [{'duration': duration, 'nb_read_frames': count}]}
    calls = []
    monkeypatch.setattr(renderer, '_run', lambda args, *a: calls.append(args) or json.dumps(metadata).encode())
    with pytest.raises(renderer.RenderError):
        renderer.render_video(tmp_path/'input.mp4', [tmp_path/'frame.jpg']*15,
                              {'plan': {'frame_count': 15, 'cues': []}}, tmp_path/'out.mp4')
    assert len(calls) == 1 and calls[0][0] == 'ffprobe'
    assert not (tmp_path/'out.mp4').exists()


def test_edit_during_export_is_not_returned_as_current(client, render_job, monkeypatch):
    job, review = render_job
    def concurrent_edit(*args):
        main.job_manager.save_director_review(job.id, 1, 1, review['plan'])
    monkeypatch.setattr(main, 'render_video', concurrent_edit)
    assert client.post(f'/api/video-director/{job.id}/render/1').status_code == 409


def test_export_requires_saved_review(client, app_state, monkeypatch):
    job = _completed_job(monkeypatch, app_state)
    assert client.post(f'/api/video-director/{job.id}/render/0').status_code == 409
