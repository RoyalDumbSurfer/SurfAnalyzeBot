# bot_initializer.py

from telebot import TeleBot
from config import settings
from utils.file_utils import ensure_download_folder, cleanup_old_logs
from utils.logger import log_info


def initialize_bot() -> TeleBot:
    bot = TeleBot(settings.API_TOKEN)
    ensure_download_folder()
    cleanup_old_logs(days=7)
    log_info("Бот успешно инициализирован.")
    return bot
