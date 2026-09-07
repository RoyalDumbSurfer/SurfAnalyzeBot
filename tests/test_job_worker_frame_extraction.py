from pathlib import Path

import pytest

from jobs import job_worker


class FakeVideoCapture:
    def __init__(self, frame_count: int, unreadable_indices: set[int] | None = None):
        self.frame_count = frame_count
        self.unreadable_indices = unreadable_indices or set()
        self.current_index = 0
        self.requested_indices: list[int] = []
        self.released = False

    def isOpened(self) -> bool:
        return True

    def get(self, _property: int) -> int:
        return self.frame_count

    def set(self, _property: int, frame_index: int) -> None:
        self.current_index = frame_index
        self.requested_indices.append(frame_index)

    def read(self) -> tuple[bool, int | None]:
        if self.current_index in self.unreadable_indices:
            return False, None
        return True, self.current_index

    def release(self) -> None:
        self.released = True


def _extract_frames(
    monkeypatch,
    tmp_path: Path,
    frame_count: int,
    *,
    unreadable_indices: set[int] | None = None,
):
    capture = FakeVideoCapture(frame_count, unreadable_indices)
    written_frames: list[int] = []
    monkeypatch.setattr(job_worker, "EXTRACTED_FRAMES_DIR", tmp_path / "frames")
    monkeypatch.setattr(job_worker.cv2, "VideoCapture", lambda _path: capture)
    monkeypatch.setattr(
        job_worker.cv2,
        "imwrite",
        lambda _path, frame: written_frames.append(frame) is None,
    )

    paths = job_worker.extract_representative_frames(Path("ride.mp4"), "job-123")
    return paths, capture, written_frames


def test_extracts_default_target_number_of_chronological_frames(monkeypatch, tmp_path: Path):
    paths, capture, written_frames = _extract_frames(monkeypatch, tmp_path, frame_count=30)

    assert len(paths) == job_worker.DEFAULT_FRAME_SAMPLE_TARGET
    assert capture.requested_indices == sorted(capture.requested_indices)
    assert written_frames == capture.requested_indices
    assert paths == [f"/frames/job-123/frame_{index:02d}.jpg" for index in range(1, 16)]
    assert capture.released is True


def test_short_video_returns_fewer_available_frames_without_failure(monkeypatch, tmp_path: Path):
    paths, capture, written_frames = _extract_frames(monkeypatch, tmp_path, frame_count=3)

    assert capture.requested_indices == [0, 1, 2]
    assert written_frames == [0, 1, 2]
    assert paths == [
        "/frames/job-123/frame_01.jpg",
        "/frames/job-123/frame_02.jpg",
        "/frames/job-123/frame_03.jpg",
    ]


def test_zero_reported_frame_count_still_keeps_a_readable_first_frame(monkeypatch, tmp_path: Path):
    paths, capture, written_frames = _extract_frames(monkeypatch, tmp_path, frame_count=0)

    assert capture.requested_indices == [0]
    assert written_frames == [0]
    assert paths == ["/frames/job-123/frame_01.jpg"]


def test_unreadable_sampled_frame_does_not_discard_remaining_frames(monkeypatch, tmp_path: Path):
    paths, capture, written_frames = _extract_frames(
        monkeypatch,
        tmp_path,
        frame_count=5,
        unreadable_indices={2},
    )

    assert capture.requested_indices == [0, 1, 2, 3, 4]
    assert written_frames == [0, 1, 3, 4]
    assert paths == [
        "/frames/job-123/frame_01.jpg",
        "/frames/job-123/frame_02.jpg",
        "/frames/job-123/frame_03.jpg",
        "/frames/job-123/frame_04.jpg",
    ]


def test_raises_clear_error_when_no_usable_frames_can_be_extracted(monkeypatch, tmp_path: Path):
    capture = FakeVideoCapture(frame_count=3, unreadable_indices={0, 1, 2})
    monkeypatch.setattr(job_worker, "EXTRACTED_FRAMES_DIR", tmp_path / "frames")
    monkeypatch.setattr(job_worker.cv2, "VideoCapture", lambda _path: capture)

    with pytest.raises(RuntimeError, match="no usable frames could be extracted"):
        job_worker.extract_representative_frames(Path("ride.mp4"), "job-123")

    assert capture.released is True


def test_representative_frame_indices_are_distinct_and_chronological():
    indices = job_worker.representative_frame_indices(frame_count=31)

    assert len(indices) == job_worker.DEFAULT_FRAME_SAMPLE_TARGET
    assert indices == sorted(indices)
    assert len(indices) == len(set(indices))
    assert indices[0] == 0
    assert indices[-1] == 30
