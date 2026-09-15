from __future__ import annotations

from pathlib import Path
from typing import Sequence, TypedDict

from config import settings

from .openai_surf_analysis_provider import OpenAISurfAnalysisProvider


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
    language: str | None = None,
    coach_context: str | None = None,
) -> SurfAnalysisResult:
    """Return a surf analysis while hiding the selected provider from the worker."""
    provider = OpenAISurfAnalysisProvider(
        api_key=settings.OPENAI_API_KEY,
        model=settings.OPENAI_VISION_MODEL,
    )
    return provider.analyze(
        frame_paths,
        original_filename=original_filename,
        job_id=job_id,
        **({"language": language} if language else {}),
        **({"coach_context": coach_context} if coach_context else {}),
    )
