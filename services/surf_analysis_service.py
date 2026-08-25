from __future__ import annotations

from pathlib import Path
from typing import Sequence, TypedDict


class SurfAnalysisResult(TypedDict):
    level: str
    main_issue: str
    why_it_matters: str
    how_to_fix: str
    drill: str
    coach_note: str


def analyze_surf_frames(
    frame_paths: Sequence[Path],
    *,
    original_filename: str | None = None,
    job_id: str | None = None,
) -> SurfAnalysisResult:
    """Return a surf analysis for extracted video frames.

    The current implementation is a local mock. A future vision provider can
    replace this implementation while retaining the same worker-facing contract.
    """
    for frame_path in frame_paths:
        if not frame_path.is_file():
            raise ValueError(f"Analysis failed: extracted frame is missing: {frame_path}")

    return {
        "level": "Intermediate",
        "main_issue": "Your stance becomes too upright during turns.",
        "why_it_matters": "A lower, balanced stance helps you keep control and generate speed.",
        "how_to_fix": "Keep your knees bent and your weight centered over the board through each turn.",
        "drill": "Practice low, controlled bottom turns while focusing on bending at the knees.",
        "coach_note": "You have good wave awareness—focus on staying compact as you transition.",
    }
