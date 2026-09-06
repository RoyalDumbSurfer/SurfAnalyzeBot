import base64
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from openai import OpenAIError

from services.openai_surf_analysis_provider import (
    OpenAISurfAnalysisProvider,
    SurfAnalysisProviderError,
)


EXPECTED_RESULT = {
    "level": "Intermediate",
    "main_issue": "Issue",
    "why_it_matters": "Why",
    "how_to_fix": "Fix",
    "drill": "Drill",
    "coach_note": "Note",
}


def _frame_paths(tmp_path: Path, count: int = 3) -> list[Path]:
    paths = []
    for index in range(1, count + 1):
        path = tmp_path / f"frame_{index:02d}.jpg"
        path.write_bytes(f"frame-{index}".encode())
        paths.append(path)
    return paths


def test_provider_sends_chronological_frames_in_one_request(tmp_path: Path):
    client = MagicMock()
    client.responses.create.return_value.output_text = json.dumps(EXPECTED_RESULT)
    frame_paths = _frame_paths(tmp_path)
    provider = OpenAISurfAnalysisProvider("test-key", "test-model", client=client)

    assert provider.analyze(frame_paths, original_filename="ride.mp4", job_id="job-123") == EXPECTED_RESULT

    client.responses.create.assert_called_once()
    request = client.responses.create.call_args.kwargs
    content = request["input"][0]["content"]
    images = content[1:]
    assert request["model"] == "test-model"
    assert len(images) == 3
    assert "Frame 1 = earliest" in content[0]["text"]
    assert "Frame 3 = latest" in content[0]["text"]
    assert [image["type"] for image in images] == ["input_image"] * 3
    assert [
        base64.b64decode(image["image_url"].split(",", 1)[1]) for image in images
    ] == [path.read_bytes() for path in frame_paths]
    output_format = request["text"]["format"]
    assert output_format["type"] == "json_schema"
    assert output_format["strict"] is True
    assert set(output_format["schema"]["properties"]) == set(EXPECTED_RESULT)
    assert output_format["schema"]["additionalProperties"] is False


def test_provider_rejects_missing_key(tmp_path: Path):
    provider = OpenAISurfAnalysisProvider(None, "test-model")

    with pytest.raises(SurfAnalysisProviderError, match="OPENAI_API_KEY"):
        provider.analyze(_frame_paths(tmp_path, count=1))


def test_provider_rejects_missing_frame(tmp_path: Path):
    provider = OpenAISurfAnalysisProvider("test-key", "test-model", client=MagicMock())
    missing_frame = tmp_path / "missing.jpg"

    with pytest.raises(SurfAnalysisProviderError, match="frame 1 is missing"):
        provider.analyze([missing_frame])


def test_provider_rejects_refused_response(tmp_path: Path):
    client = MagicMock()
    client.responses.create.return_value.output = [
        {"content": [{"type": "refusal", "refusal": "Cannot analyze this."}]}
    ]
    client.responses.create.return_value.output_text = None
    provider = OpenAISurfAnalysisProvider("test-key", "test-model", client=client)

    with pytest.raises(SurfAnalysisProviderError, match="was refused"):
        provider.analyze(_frame_paths(tmp_path, count=1))


def test_provider_rejects_invalid_structured_response(tmp_path: Path):
    client = MagicMock()
    client.responses.create.return_value.output_text = json.dumps({"level": "Intermediate"})
    provider = OpenAISurfAnalysisProvider("test-key", "test-model", client=client)

    with pytest.raises(SurfAnalysisProviderError, match="invalid result schema"):
        provider.analyze(_frame_paths(tmp_path, count=1))


def test_provider_wraps_openai_errors(tmp_path: Path):
    client = MagicMock()
    client.responses.create.side_effect = OpenAIError("connection lost")
    provider = OpenAISurfAnalysisProvider("test-key", "test-model", client=client)

    with pytest.raises(SurfAnalysisProviderError, match="OpenAI surf analysis request failed"):
        provider.analyze(_frame_paths(tmp_path, count=1))
