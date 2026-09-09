from pathlib import Path

import cv2
import numpy as np
import pytest
from jobs.job_model import JobStatus
from webapp import main


@pytest.fixture
def video_bytes(tmp_path):
    path = tmp_path / "ride.avi"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10, (64, 64))
    assert writer.isOpened()
    for index in range(30):
        writer.write(np.full((64, 64, 3), index * 7, dtype=np.uint8))
    writer.release()
    return path.read_bytes()


def test_readable_upload_creates_queued_job(client, video_bytes):
    response = client.post("/upload", files={"file": ("ride.avi", video_bytes, "video/x-msvideo")})
    assert response.status_code == 303
    job = main.job_manager.list_jobs()[0]
    assert job.status == JobStatus.QUEUED
    assert job.original_filename == "ride.avi"
    assert Path(job.file_path).read_bytes() == video_bytes
    assert response.headers["location"] == f"/processing/{job.id}"
    assert "Video uploaded successfully" in client.get(response.headers["location"]).text


@pytest.mark.parametrize("extension,mime", [(ext, mime) for ext, mimes in main.VIDEO_MIME_TYPES.items() for mime in mimes])
def test_supported_type_metadata(client, monkeypatch, extension, mime):
    monkeypatch.setattr(main, "readable_thumbnail", lambda path: True)
    response = client.post("/upload", files={"file": ("ride" + extension.upper(), b"video", mime)})
    assert response.status_code == 303


@pytest.mark.parametrize("name,mime", [("ride.exe", "video/mp4"), ("ride.mp4", "text/plain"), ("ride.mp4", "video/webm"), ("ride", "video/mp4")])
def test_unsupported_upload_rejected(client, name, mime):
    response = client.post("/upload", files={"file": (name, b"bad", mime)})
    assert response.status_code == 400
    assert "Unsupported video format" in response.text
    assert "Choose another video" in response.text
    assert not main.job_manager.list_jobs()
    assert not list(main.UPLOAD_DIR.iterdir())


@pytest.mark.parametrize("mime", ["application/octet-stream", ""])
def test_generic_mime_requires_readable_video(client, video_bytes, mime):
    assert client.post("/upload", files={"file": ("ride.avi", video_bytes, mime)}).status_code == 303


def test_oversized_upload(client, monkeypatch):
    monkeypatch.setattr(main.settings, "MAX_FILE_SIZE", 10)
    response = client.post("/upload", files={"file": ("ride.mp4", b"x" * 11, "video/mp4")})
    assert response.status_code == 413
    assert "Video is too large" in response.text
    assert not main.job_manager.list_jobs()
    assert not list(main.UPLOAD_DIR.iterdir())


def test_multipart_body_bounded_without_content_length(client, monkeypatch):
    monkeypatch.setattr(main.settings, "MAX_FILE_SIZE", 10)
    def body():
        yield b'--demo\r\nContent-Disposition: form-data; name="file"; filename="ride.mp4"\r\nContent-Type: video/mp4\r\n\r\n'
        yield b"x" * (1024 * 1024 + 100)
        yield b"\r\n--demo--\r\n"
    response = client.post("/upload", content=body(), headers={"Content-Type": "multipart/form-data; boundary=demo"})
    assert response.status_code == 413
    assert "Video is too large" in response.text
    assert not main.job_manager.list_jobs()


@pytest.mark.parametrize("content,message", [(b"", "empty"), (b"not a video", "Video could not be read")])
def test_empty_and_unreadable_upload(client, content, message):
    response = client.post("/upload", files={"file": ("ride.mp4", content, "video/mp4")})
    assert response.status_code == 400
    assert message in response.text
    assert not main.job_manager.list_jobs()
    assert not list(main.UPLOAD_DIR.iterdir())


def test_missing_and_invalid_form(client):
    for kwargs in ({}, {"data": {"file": "not a file"}}, {"content": b"bad", "headers": {"Content-Type": "multipart/form-data"}}):
        response = client.post("/upload", **kwargs)
        assert response.status_code == 400
        assert "Choose another video" in response.text
        assert "traceback" not in response.text.lower()


def test_result_keeps_fifteen_frames_and_viewer(client):
    job = main.job_manager.create_job(user_id=1, owner_user_id=1, file_path="ride.mp4")
    main.job_manager.update_job(job.id, status=JobStatus.DONE,
        analysis_result={"level": "Intermediate", "coach_note": "Keep practicing"},
        extracted_frame_paths=[f"/frames/{job.id}/frame_{n:02}.jpg" for n in range(1, 16)],
        result_path="private/server/path.mp4")
    response = client.get(f"/result/{job.id}")
    assert response.status_code == 200
    assert response.text.count('data-frame-index="') == 15
    for text in ('id="frame-viewer"', 'data-frame-viewer-close', 'SurfAnalyzeFrameViewer', 'Keep practicing', 'Analyze Another Video'):
        assert text in response.text
    status = client.get(f"/api/jobs/{job.id}")
    assert "private/server" not in status.text


def test_failed_job_has_safe_retry_without_polling(client):
    job = main.job_manager.create_job(user_id=1, owner_user_id=1, file_path="ride.mp4")
    main.job_manager.update_job(job.id, status=JobStatus.FAILED, error_message="SECRET /server/private Traceback")
    response = client.get(f"/result/{job.id}", follow_redirects=True)
    assert response.status_code == 200
    assert "Try Another Video" in response.text
    assert "SECRET" not in response.text
    assert "}poll();" not in response.text
    assert "SECRET" not in client.get(f"/api/jobs/{job.id}").text
    assert "Try Another Video" in client.get("/dashboard").text


def test_upload_copy_uses_configuration(client, monkeypatch):
    monkeypatch.setattr(main.settings, "MAX_FILE_SIZE", 25 * 1024 * 1024)
    page = client.get("/").text
    assert "25 MiB" in page
    assert "AVI, MKV, MOV, MP4, WEBM" in page
    assert "How it works" in page
    assert "10-30 second" in page


def test_upload_worker_result_flow(client, video_bytes, monkeypatch, tmp_path):
    from jobs import job_worker
    response = client.post("/upload", files={"file": ("ride.avi", video_bytes, "video/x-msvideo")})
    job = main.job_manager.list_jobs()[0]
    monkeypatch.setattr(job_worker, "JobManager", lambda: main.job_manager)
    monkeypatch.setattr(job_worker, "EXTRACTED_FRAMES_DIR", tmp_path / "frames")
    results = tmp_path / "results"
    results.mkdir(exist_ok=True)
    monkeypatch.setattr(job_worker, "RESULTS_DIR", results)
    def analyze(frames, **kwargs):
        assert len(frames) == 15
        assert all(path.is_file() for path in frames)
        return {"level": "Intermediate", "coach_note": "Test coaching feedback"}
    monkeypatch.setattr(job_worker, "analyze_surf_frames", analyze)
    def stop_worker(_):
        raise KeyboardInterrupt
    monkeypatch.setattr(job_worker.time, "sleep", stop_worker)
    job_worker.process_jobs()
    finished = main.job_manager.get_job(job.id)
    assert finished.status == JobStatus.DONE
    assert len(finished.extracted_frame_paths) == 15
    assert Path(finished.result_path).exists()
    assert "Test coaching feedback" in client.get(f"/result/{job.id}").text


def test_live_http_server(client):
    import socket
    import threading
    import time
    import httpx
    import uvicorn

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(main.app, log_level="error"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        try:
            for _ in range(100):
                if server.started:
                    break
                time.sleep(0.05)
            assert server.started
            headers = {"Cookie": "surfanalyze_account=" + client.cookies.get("surfanalyze_account"), "X-CSRF-Token": client.headers["X-CSRF-Token"]}
            response = httpx.get(f"http://127.0.0.1:{port}/", headers=headers, trust_env=False)
            assert response.status_code == 200
            assert "What to upload" in response.text
            response = httpx.post(f"http://127.0.0.1:{port}/upload", files={"file": ("bad.txt", b"bad", "text/plain")}, headers=headers, trust_env=False)
            assert response.status_code == 400
            assert "Choose another video" in response.text
        finally:
            server.should_exit = True
            thread.join(timeout=10)


def test_client_upload_interactions(client):
    import json
    import re
    import shutil
    import subprocess

    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required to exercise browser JavaScript without a browser")
    scripts = re.findall(r"<script>(.*?)</script>", client.get("/").text, re.S)
    script = next(script for script in scripts if "const videoTypes" in script)
    result = subprocess.run([node, "tests/private_demo_client.cjs"], input=json.dumps(script), text=True, capture_output=True)
    assert result.returncode == 0, result.stderr


def test_processing_javascript_stops_on_failure(client):
    import json
    import re
    import shutil
    import subprocess

    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for JavaScript checks")
    job = main.job_manager.create_job(user_id=1, owner_user_id=1, file_path="ride.mp4")
    scripts = re.findall(r"<script>(.*?)</script>", client.get(f"/processing/{job.id}").text, re.S)
    script = next(script for script in scripts if "async function poll" in script)
    harness = r'''
const vm = require('node:vm');
const assert = require('node:assert/strict');
const script = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
async function run(status, httpStatus = 200) {
    const elements = Object.fromEntries(['status', 'activity', 'retry'].map(id => [id, {textContent: '', classList: {add() {}, remove() {}}}]));
    let timers = 0;
    const window = {location: {href: ''}};
    vm.runInNewContext(script, {
        document: {getElementById: id => elements[id]}, window,
        setTimeout() { timers++; },
        fetch: async () => ({status: httpStatus, ok: httpStatus === 200, json: async () => ({ok: true, job: {status}})})
    });
    await new Promise(resolve => setImmediate(resolve));
    return {elements, timers, window};
}
(async () => {
    let result = await run('failed');
    assert.match(result.elements.status.textContent, /couldn't finish/);
    assert.equal(result.timers, 0);
    result = await run('done');
    assert.match(result.window.location.href, /^\/result\//);
    assert.equal(result.timers, 0);
    result = await run('queued');
    assert.match(result.elements.status.textContent, /queue/);
    assert.equal(result.timers, 1);
    result = await run('processing', 401);
    assert.equal(result.window.location.href, '/beta');
    assert.equal(result.timers, 0);
})().catch(error => { console.error(error); process.exitCode = 1; });
'''
    result = subprocess.run([node, "-e", harness], input=json.dumps(script), text=True, capture_output=True)
    assert result.returncode == 0, result.stderr


def test_exact_size_boundary_is_accepted(client, video_bytes, monkeypatch):
    monkeypatch.setattr(main.settings, "MAX_FILE_SIZE", len(video_bytes))
    assert client.post("/upload", files={"file": ("ride.avi", video_bytes, "video/x-msvideo")}).status_code == 303


def test_invalid_filename_never_reaches_filesystem(client):
    response = client.post("/upload", files={"file": ("ride.mp4\x00", b"bad", "video/mp4")})
    assert response.status_code == 400
    assert not main.job_manager.list_jobs()
    assert not list(main.UPLOAD_DIR.iterdir())
