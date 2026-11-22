"""No paid API calls: validate director plans and cue positioning contracts."""
import pytest

from services.video_director import VideoDirectorError, validate_plan


def test_valid_cues_sorted_and_frame_anchored():
    result = validate_plan({"cues": [
        {"frame_number": 10, "title": "Finish", "note": "Keep pressure on the rail.", "arrow": None},
        {"frame_number": 3, "title": "Start", "note": "Look along the shoulder.",
         "arrow": {"x1": 100, "y1": 200, "x2": 500, "y2": 300}},
    ]}, frame_count=15)
    assert result["version"] == 1
    assert result["frame_count"] == 15
    assert [c["frame_number"] for c in result["cues"]] == [3, 10]


def test_no_confident_annotations_is_allowed():
    assert validate_plan({"cues": []}, 15)["cues"] == []


@pytest.mark.parametrize("bad", [
    {"cues": [{"frame_number": 16, "title": "No", "note": "Wrong", "arrow": None}]},
    {"cues": [{"frame_number": True, "title": "No", "note": "Wrong", "arrow": None}]},
    {"cues": [{"frame_number": 1, "title": "No", "note": "Wrong", "arrow": None}] * 2},
    {"cues": [{"frame_number": 2, "title": "No", "note": "Wrong",
               "arrow": {"x1": -1, "y1": 0, "x2": 10, "y2": 10}}]},
    {"cues": [{"frame_number": 2, "title": "", "note": "Wrong", "arrow": None}]},
    {"cues": [{"frame_number": 2, "title": "No", "note": "Wrong",
               "arrow": {"x1": 10, "y1": 10, "x2": 10, "y2": 10}}]},
    {"cues": [{"frame_number": 2, "title": "No", "note": "Wrong", "arrow": None}] * 4},
    {"cues": {"frame_number": 2}},
])
def test_bad_cues_rejected(bad):
    with pytest.raises(VideoDirectorError):
        validate_plan(bad, 15)
