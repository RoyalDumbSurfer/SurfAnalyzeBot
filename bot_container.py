# bot_container.py

from config import settings
from bot_initializer import initialize_bot
from handlers.command_handler import CommandHandler
from handlers.media_handler import MediaHandler
from services.media_service import MediaService

class BotContainer:
    def __init__(self):
        self.config = settings
        self.bot = initialize_bot()
        self.command_handler = CommandHandler()
        self.media_handler = MediaHandler()
        self.media_service = MediaService(config=self.config)

    def initialize(self):
        self.command_handler.register(self.bot)
        self.media_handler.register(self.bot)
