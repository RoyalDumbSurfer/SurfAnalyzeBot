from pathlib import Path

import pytest

from services.surf_analysis_service import analyze_surf_frames


def test_analyze_surf_frames_returns_expected_result(tmp_path: Path):
    frame_paths = []
    for index in range(5):
        frame_path = tmp_path / f"frame_{index:02d}.jpg"
        frame_path.write_bytes(b"frame")
        frame_paths.append(frame_path)

    result = analyze_surf_frames(
        frame_paths,
        original_filename="surf-session.mp4",
        job_id="job-123",
    )

    assert set(result) == {
        "level",
        "main_issue",
        "why_it_matters",
        "how_to_fix",
        "drill",
        "coach_note",
    }


def test_analyze_surf_frames_rejects_missing_frame(tmp_path: Path):
    missing_frame = tmp_path / "missing.jpg"

    with pytest.raises(ValueError, match="extracted frame is missing"):
        analyze_surf_frames([missing_frame])
