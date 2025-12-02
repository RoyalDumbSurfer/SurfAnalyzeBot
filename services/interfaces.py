# services/interfaces.py

from abc import ABC, abstractmethod

class IMediaService(ABC):
    @abstractmethod
    def process_media(self, file_id: str) -> str:
        pass
