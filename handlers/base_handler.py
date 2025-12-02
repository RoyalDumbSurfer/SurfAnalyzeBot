# handlers/base_handler.py

from abc import ABC, abstractmethod
from telebot import TeleBot

class BaseHandler(ABC):
    @abstractmethod
    def register(self, bot: TeleBot):
        """Метод для регистрации хендлера в боте"""
        pass
