from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional, Any, Dict, List


class JobStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"


def safe_int(value: Any, default: int = 0) -> int:
    """
    Безопасно превращает user_id / chat_id в int.

    Старые jobs могли иметь:
    - "anonymous"
    - None
    - пустую строку

    Раньше из-за этого worker падал.
    Теперь такие значения превращаются в 0.
    """
    try:
        if value is None:
            return default

        if value == "":
            return default

        if value == "anonymous":
            return default

        return int(value)

    except (ValueError, TypeError):
        return default


@dataclass
class Job:
    id: str
    user_id: int
    file_path: str
    status: JobStatus
    created_at: datetime
    updated_at: datetime

    # Чтобы знать, куда отправлять результат
    chat_id: Optional[int] = None

    result_path: Optional[str] = None
    error_message: Optional[str] = None
    thumbnail: Optional[str] = None
    original_filename: Optional[str] = None
    analysis_result: Optional[Dict[str, str]] = None
    extracted_frame_paths: Optional[List[str]] = None

    @property
    def display_filename(self) -> str:
        return self.original_filename or Path(self.file_path).name or "Unknown file"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "chat_id": self.chat_id,
            "file_path": self.file_path,
            "original_filename": self.original_filename,
            "status": self.status.value if isinstance(self.status, JobStatus) else self.status,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "result_path": self.result_path,
            "error_message": self.error_message,
            "thumbnail": self.thumbnail,
            "analysis_result": self.analysis_result,
            "extracted_frame_paths": self.extracted_frame_paths,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Job":
        return cls(
            id=data["id"],
            user_id=safe_int(data.get("user_id"), default=0),
            chat_id=safe_int(data.get("chat_id"), default=0) if data.get("chat_id") is not None else None,
            file_path=data["file_path"],
            original_filename=data.get("original_filename"),
            status=JobStatus(data.get("status", JobStatus.QUEUED.value)),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            result_path=data.get("result_path"),
            error_message=data.get("error_message"),
            thumbnail=data.get("thumbnail"),
            analysis_result=data.get("analysis_result"),
            extracted_frame_paths=data.get("extracted_frame_paths"),
        )
