# utils/media_service.py

import os
import datetime
from telebot import TeleBot
from telebot.types import Message
from config import settings
from utils.logger import log_info, log_error

def save_media_file(bot: TeleBot, message: Message, file_info, media_type: str):
    """Сохраняет фото или видео в папку загрузок."""

    # Проверка: Путь не должен быть пустым
    if not file_info.file_path:
        return None, "❌ Не указан путь к файлу."

    # Проверка размера файла
    if file_info.file_size > settings.MAX_FILE_SIZE:
        return None, "❌ Файл слишком большой! Лимит: 50 МБ."

    # Генерация имени файла
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    extension = os.path.splitext(file_info.file_path)[-1]
    user = getattr(message.from_user, "first_name", "user")
    filename = f"{user}_{media_type}_{message.message_id}_{timestamp}{extension}"
    file_path = os.path.join(settings.DOWNLOAD_FOLDER, filename)

    try:
        downloaded_file = bot.download_file(file_info.file_path)
        with open(file_path, 'wb') as new_file:
            new_file.write(downloaded_file)
        log_info(f"✅ {media_type.capitalize()} сохранено: {filename}")
        return filename, None
    except Exception as e:
        log_error("❌ Не удалось сохранить файл", error=str(e))
        return None, f"❌ Не удалось сохранить файл: {str(e)}"
