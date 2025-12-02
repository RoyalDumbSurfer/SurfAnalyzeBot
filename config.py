# config.py

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
import os

class Settings(BaseSettings):
    API_TOKEN: str = Field(..., min_length=10, description="Telegram Bot API Token")
    MAX_FILE_SIZE: int = Field(default=50 * 1024 * 1024, description="Maximum file size in bytes")

    PROJECT_DIR: str = Field(
        default_factory=lambda: os.path.dirname(os.path.abspath(__file__)),
        description="Project root directory"
    )
    DOWNLOAD_FOLDER: str = Field(
        default_factory=lambda: os.path.join(os.path.dirname(os.path.abspath(__file__)), 'downloads'),
        description="Folder for downloaded files"
    )
    LOG_FOLDER: str = Field(
        default_factory=lambda: os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs'),
        description="Folder for log files"
    )
    LOG_FILE: str = Field(
        default_factory=lambda: os.path.join(
            os.path.dirname(os.path.abspath(__file__)), 'logs', 'surfanalyze_bot.log'
        ),
        description="Path to log file"
    )

    VERSION: str = Field(default="1.0.0", description="App version")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore"
    )

    @field_validator("API_TOKEN")
    @classmethod
    def validate_token(cls, v: str) -> str:
        if not v or len(v) < 10:
            raise ValueError("API_TOKEN must be a valid token with at least 10 characters")
        return v

    @field_validator("VERSION")
    @classmethod
    def validate_version(cls, v: str) -> str:
        if not isinstance(v, str) or not v.count(".") == 2:
            raise ValueError("VERSION must be in format x.y.z")
        return v

    def ensure_directories(self) -> None:
        for directory in [self.DOWNLOAD_FOLDER, self.LOG_FOLDER]:
            if not os.path.exists(directory):
                os.makedirs(directory)
            if not os.access(directory, os.W_OK):
                raise PermissionError(f"No write permission for directory: {directory}")

settings = Settings()
settings.ensure_directories()

