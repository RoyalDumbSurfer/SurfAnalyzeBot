# services/media_service.py

from config import Settings

class MediaService:
    def __init__(self, config: Settings):
        self.config = config

    def process_media(self, file_id: str) -> str:
        # Заглушка — сюда можно будет добавить OpenCV, AI и т.д.
        return f"Файл {file_id} успешно обработан."
