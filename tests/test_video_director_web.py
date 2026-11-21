"""Web video director: ownership, CSRF, persistence, and a read-only source video."""
from pathlib import Path

from jobs.job_model import JobStatus
from webapp import main


ANALYSIS = {
    "level": "Intermediate", "main_issue": "Look ahead",
    "why_it_matters": "Keeps the line", "how_to_fix": "Turn shoulders",
    "drill": "Practice", "coach_note": "Good wave",
}
PLAN = {"version": 1, "frame_count": 2, "cues": [
    {"frame_number": 2, "title": "Look ahead", "note": "Look at the shoulder", "arrow": None},
]}


def _completed_job(monkeypatch, app_state, owner=1):
    with app_state[0].database.connect(write=True) as db:
        db.execute("UPDATE users SET role='coach' WHERE username='alice'")
    uploaded = main.UPLOAD_DIR / "surfride.mp4"
    uploaded.write_bytes(b"test video placeholder")
    job = main.job_manager.create_job(
        user_id=owner, owner_user_id=owner,
        file_path=str(uploaded), original_filename="surfride.mp4")
    frames = main.EXTRACTED_FRAMES_DIR / job.id
    frames.mkdir(parents=True)
    paths = []
    for i in (1, 2):
        name = f"frame_{i:02d}.jpg"
        (frames / name).write_bytes(b"fake jpg used by mocked AI")
        paths.append(f"/frames/{job.id}/{name}")
    main.job_manager.update_job(
        job.id, status=JobStatus.DONE,
        analysis_result=ANALYSIS, extracted_frame_paths=paths)
    return job


def test_director_generates_only_once_and_renders_preview(client, app_state, monkeypatch):
    job = _completed_job(monkeypatch, app_state)
    calls = []
    def fake_plan(frames, analysis):
        calls.append((frames, analysis))
        return PLAN
    monkeypatch.setattr(main, "generate_video_plan", fake_plan)
    path = f"/api/video-director/{job.id}"
    response = client.post(path)
    assert response.status_code == 200
    assert response.json()["plan"] == PLAN
    assert calls[0][1] == ANALYSIS
    assert len(calls[0][0]) == 2
    assert main.job_manager.get_job(job.id).director_plan == PLAN
    assert client.post(path).status_code == 200
    assert len(calls) == 1  # saved plan prevents a second AI charge
    page = client.get(f"/result/{job.id}")
    assert page.status_code == 200
    assert "Video Coach Preview" in page.text
    assert "/uploads/surfride.mp4" in page.text
    assert Path(job.file_path).read_bytes() == b"test video placeholder"


def test_director_does_not_expose_other_users_jobs(client, app_state):
    job = _completed_job(None, app_state, owner=2)
    assert client.post(f"/api/video-director/{job.id}").status_code == 404


def test_director_requires_csrf_and_coach_role(client, app_state):
    job = _completed_job(None, app_state)
    token = client.headers.pop("X-CSRF-Token")
    assert client.post(f"/api/video-director/{job.id}").status_code == 403
    client.headers["X-CSRF-Token"] = token
    with app_state[0].database.connect(write=True) as db:
        db.execute("UPDATE users SET role='user' WHERE username='alice'")
    assert client.post(f"/api/video-director/{job.id}").status_code == 403
