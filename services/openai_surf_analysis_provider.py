from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Sequence, cast

from openai import OpenAI, OpenAIError

if TYPE_CHECKING:
    from .surf_analysis_service import SurfAnalysisResult


class SurfAnalysisProviderError(RuntimeError):
    """Raised when a surf analysis provider cannot produce a valid result."""


SURF_ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "level": {"type": "string"},
        "main_issue": {"type": "string"},
        "why_it_matters": {"type": "string"},
        "how_to_fix": {"type": "string"},
        "drill": {"type": "string"},
        "coach_note": {"type": "string"},
    },
    "required": [
        "level",
        "main_issue",
        "why_it_matters",
        "how_to_fix",
        "drill",
        "coach_note",
    ],
    "additionalProperties": False,
}

COACHING_INSTRUCTIONS = """Act as an experienced professional surf coach analyzing chronological visual samples from one ride.

Evaluate only what can reasonably be observed in the supplied frames: stance, compression and extension, balance, weight distribution and transfer, upper/lower body coordination, rotation, timing, line choice, speed generation, and visible technical mistakes.

Do not invent information that is not visible. Do not infer unseen events between frames. If something cannot be determined reliably from the frames, do not claim it as fact. Prioritize the single most important actionable technical issue rather than listing every possible problem. Keep feedback practical and understandable by a surfer, not generic. Do not provide medical or injury advice."""

RESULT_FIELDS = {
    "level",
    "main_issue",
    "why_it_matters",
    "how_to_fix",
    "drill",
    "coach_note",
}


class OpenAISurfAnalysisProvider:
    def __init__(self, api_key: str | None, model: str, client: Any | None = None) -> None:
        self.api_key = api_key
        self.model = model
        self.client = client

    def analyze(
        self,
        frame_paths: Sequence[Path],
        *,
        original_filename: str | None = None,
        job_id: str | None = None,
        language: str | None = None,
    ) -> "SurfAnalysisResult":
        if not self.api_key:
            raise SurfAnalysisProviderError("OpenAI analysis is unavailable: OPENAI_API_KEY is not configured.")
        if not frame_paths:
            raise SurfAnalysisProviderError("OpenAI analysis requires at least one extracted frame.")

        content: list[dict[str, str]] = [
            {
                "type": "input_text",
                "text": self._sequence_prompt(len(frame_paths), original_filename, job_id),
            }
        ]
        for index, frame_path in enumerate(frame_paths, start=1):
            content.append(self._image_content(frame_path, index))

        client = self.client or OpenAI(api_key=self.api_key)
        try:
            response = client.responses.create(
                model=self.model,
                instructions=COACHING_INSTRUCTIONS + (
                    "\nWrite all six result values in " + {"ru": "Russian", "en": "English"}[language]
                    + ". Keep the JSON field names unchanged." if language in {"ru", "en"} else ""
                ),
                input=[{"role": "user", "content": content}],
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "surf_analysis_result",
                        "strict": True,
                        "schema": SURF_ANALYSIS_SCHEMA,
                    }
                },
            )
        except OpenAIError as error:
            raise SurfAnalysisProviderError(f"OpenAI surf analysis request failed: {error}") from error

        return self._parse_result(self._output_text(response))

    @staticmethod
    def _image_content(frame_path: Path, index: int) -> dict[str, str]:
        if not frame_path.is_file():
            raise SurfAnalysisProviderError(f"OpenAI analysis frame {index} is missing: {frame_path}")

        try:
            encoded_frame = base64.b64encode(frame_path.read_bytes()).decode("ascii")
        except OSError as error:
            raise SurfAnalysisProviderError(
                f"OpenAI analysis could not read frame {index}: {frame_path}"
            ) from error

        return {
            "type": "input_image",
            "image_url": f"data:image/jpeg;base64,{encoded_frame}",
            "detail": "high",
        }

    @staticmethod
    def _sequence_prompt(frame_count: int, original_filename: str | None, job_id: str | None) -> str:
        filename = original_filename or "an uploaded surf video"
        job_context = f" Job ID: {job_id}." if job_id else ""
        frame_labels = "\n".join(
            f"Frame {index} = {'earliest' if index == 1 else 'latest' if index == frame_count else 'chronological sample'}"
            for index in range(1, frame_count + 1)
        )
        return (
            f"Analyze {frame_count} chronological JPEG samples from the same surf ride in {filename}.{job_context}\n"
            f"{frame_labels}\n"
            "Treat their order as the ride sequence."
        )

    @staticmethod
    def _output_text(response: Any) -> str | None:
        """Extract output text while preserving a useful refusal error."""
        output = getattr(response, "output", None) or []
        for item in output:
            content_items = getattr(item, "content", None)
            if content_items is None and isinstance(item, dict):
                content_items = item.get("content", [])
            for content in content_items or []:
                content_type = getattr(content, "type", None)
                if content_type is None and isinstance(content, dict):
                    content_type = content.get("type")
                if content_type == "refusal":
                    raise SurfAnalysisProviderError("OpenAI analysis request was refused.")

        return getattr(response, "output_text", None)

    @staticmethod
    def _parse_result(output_text: str | None) -> "SurfAnalysisResult":
        if not output_text:
            raise SurfAnalysisProviderError("OpenAI analysis returned no structured result.")

        try:
            result = json.loads(output_text)
        except json.JSONDecodeError as error:
            raise SurfAnalysisProviderError("OpenAI analysis returned invalid structured JSON.") from error

        if not isinstance(result, dict) or set(result) != RESULT_FIELDS:
            raise SurfAnalysisProviderError("OpenAI analysis returned an invalid result schema.")
        if not all(isinstance(value, str) for value in result.values()):
            raise SurfAnalysisProviderError("OpenAI analysis result fields must all be strings.")

        return cast("SurfAnalysisResult", result)
