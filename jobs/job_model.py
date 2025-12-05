from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any


class JobStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"


@dataclass
class Job:
    """
    Модель задачи на обработку видео/фото.
    Пока минимальная, но уже пригодна для Cocoon-интеграции.
    """
    id: str
    user_id: int
    file_path: str          # исходный файл, который загрузил пользователь
    status: JobStatus
    result_path: Optional[str] = None  # путь к результату (после анализа)
    created_at: datetime = datetime.utcnow()
    updated_at: datetime = datetime.utcnow()
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        # сериализуем datetime в ISO-строки, а статус в value
        data["status"] = self.status.value
        data["created_at"] = self.created_at.isoformat()
        data["updated_at"] = self.updated_at.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Job":
        return cls(
            id=data["id"],
            user_id=data["user_id"],
            file_path=data["file_path"],
            status=JobStatus(data["status"]),
            result_path=data.get("result_path"),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            error_message=data.get("error_message"),
        )
