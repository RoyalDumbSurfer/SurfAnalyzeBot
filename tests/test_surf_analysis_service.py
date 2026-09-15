from pathlib import Path
from unittest.mock import MagicMock

from services.surf_analysis_service import SurfAnalysisResult, analyze_surf_frames


def test_analyze_surf_frames_delegates_to_openai_provider(monkeypatch, tmp_path: Path):
    frame_path = tmp_path / "frame_01.jpg"
    frame_path.write_bytes(b"frame")
    expected_result: SurfAnalysisResult = {
        "level": "Intermediate",
        "main_issue": "Issue",
        "why_it_matters": "Why",
        "how_to_fix": "Fix",
        "drill": "Drill",
        "coach_note": "Note",
    }
    provider = MagicMock()
    provider.analyze.return_value = expected_result
    provider_class = MagicMock(return_value=provider)
    monkeypatch.setattr("services.surf_analysis_service.OpenAISurfAnalysisProvider", provider_class)

    result = analyze_surf_frames([frame_path], original_filename="ride.mp4", job_id="job-123")

    assert result == expected_result
    provider.analyze.assert_called_once_with(
        [frame_path],
        original_filename="ride.mp4",
        job_id="job-123",
    )


def test_service_forwards_provider_independent_coach_context(monkeypatch):
    provider = MagicMock()
    monkeypatch.setattr('services.surf_analysis_service.OpenAISurfAnalysisProvider', MagicMock(return_value=provider))
    analyze_surf_frames([], language='ru', coach_context='Expert context')
    assert provider.analyze.call_args.kwargs['coach_context'] == 'Expert context'
    assert provider.analyze.call_args.kwargs['language'] == 'ru'
