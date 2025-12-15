from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional, Any, Dict


class JobStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"


@dataclass
class Job:
    id: str
    user_id: int
    file_path: str
    status: JobStatus
    created_at: datetime
    updated_at: datetime

    # NEW: чтобы знать, куда отправлять результат
    chat_id: Optional[int] = None

    result_path: Optional[str] = None
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "chat_id": self.chat_id,
            "file_path": self.file_path,
            "status": self.status.value if isinstance(self.status, JobStatus) else self.status,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "result_path": self.result_path,
            "error_message": self.error_message,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Job":
        return cls(
            id=data["id"],
            user_id=int(data["user_id"]),
            chat_id=data.get("chat_id"),
            file_path=data["file_path"],
            status=JobStatus(data["status"]),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            result_path=data.get("result_path"),
            error_message=data.get("error_message"),
        )
