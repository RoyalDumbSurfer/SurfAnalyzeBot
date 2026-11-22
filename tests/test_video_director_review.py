"""Video Director coach corrections: ownership, revision conflicts and trusted source."""
from jobs.job_model import JobStatus
from webapp import main

ORIGINAL = {"version": 1, "frame_count": 2, "cues": [
    {"frame_number": 1, "title": "AI note", "note": "A draft observation.", "arrow": None}
]}
EDITED = [
    {"frame_number": 2, "title": "Proper line", "note": "Hold the high line.", "arrow": None}
]


def make_finished_job(app_state, owner_id=1):
    with app_state[0].database.connect(write=True) as db:
        db.execute("UPDATE users SET role='coach' WHERE username='alice'")
    job = main.job_manager.create_job(
        user_id=owner_id, owner_user_id=owner_id,
        file_path=str(main.UPLOAD_DIR / "dummy.mp4"), original_filename="dummy.mp4",
    )
    main.job_manager.update_job(job.id, status=JobStatus.DONE,
                                director_plan=ORIGINAL,
                                analysis_result={"level": "Intermediate", "main_issue": "issue",
                                                 "why_it_matters": "reason", "how_to_fix": "fix",
                                                 "drill": "drill", "coach_note": "note"})
    return job


def test_save_review_and_reject_stale_revisions(client, app_state):
    job = make_finished_job(app_state)
    url = f"/api/video-director/{job.id}/review"
    saved = client.post(url, json={"revision": 0, "cues": EDITED})
    assert saved.status_code == 200, saved.text
    assert saved.json()["review"]["revision"] == 1
    assert saved.json()["review"]["plan"]["cues"] == EDITED
    assert main.job_manager.get_job(job.id).director_plan == ORIGINAL
    assert main.job_manager.get_job(job.id).director_review["plan"]["cues"] == EDITED

    stale = client.post(url, json={"revision": 0, "cues": []})
    assert stale.status_code == 409
    assert main.job_manager.get_job(job.id).director_review["revision"] == 1

    page = client.get(f"/result/{job.id}")
    assert page.status_code == 200
    assert 'director-existing-review' in page.text
    assert "Save reviewed timeline" in page.text


def test_invalid_review_cues_fail_closed(client, app_state):
    job = make_finished_job(app_state)
    url = f"/api/video-director/{job.id}/review"
    for payload in [
        {"revision": 0, "cues": [{"frame_number": 9, "title": "Off", "note": "bad", "arrow": None}]},
        {"revision": True, "cues": EDITED},
        {"revision": 0, "cues": [{"frame_number": 2, "title": "<script>bad</script>", "note": "", "arrow": None}]},
        {"revision": 0, "cues": "not an array"},
        {"revision": 0, "cues": EDITED, "extra": 1},
    ]:
        assert client.post(url, json=payload).status_code == 400
    assert main.job_manager.get_job(job.id).director_review is None


def test_review_requires_owner_role_csrf(client, app_state):
    other = make_finished_job(app_state, owner_id=2)
    assert client.post(f"/api/video-director/{other.id}/review",
                       json={"revision": 0, "cues": []}).status_code == 404
    mine = make_finished_job(app_state)
    url = f"/api/video-director/{mine.id}/review"
    token = client.headers.pop("X-CSRF-Token")
    assert client.post(url, json={"revision": 0, "cues": EDITED}).status_code == 403
    client.headers["X-CSRF-Token"] = token
    with app_state[0].database.connect(write=True) as db:
        db.execute("UPDATE users SET role='user' WHERE username='alice'")
    assert client.post(url, json={"revision": 0, "cues": EDITED}).status_code == 403
