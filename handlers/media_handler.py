from __future__ import annotations

from pathlib import Path

from telebot import TeleBot
from telebot.apihelper import ApiTelegramException
from telebot.types import Message

from config import settings
from utils.logger import log_error, log_info, logger_message
from handlers.base_handler import BaseHandler
from services.media_service import MediaService
from utils.media_service import save_media_file
from jobs.job_manager import JobManager

job_manager = JobManager()


class MediaHandler(BaseHandler):
    def __init__(self, media_service: MediaService):
        self.media_service = media_service
        self.bot: TeleBot | None = None

    def register(self, bot: TeleBot):
        """
        Регистрирует обработчик фото/видео.
        """
        self.bot = bot

        @bot.message_handler(content_types=["photo", "video"])
        @logger_message
        def handle_media(message: Message):
            self.handle_media(message)

    # ---------------------------
    # Обработка медиа
    # ---------------------------
    @logger_message
    def handle_media(self, message: Message):
        bot = self.bot
        file_type = "unknown"

        if bot is None:
            log_error("MediaHandler: bot is None")
            return

        try:
            # 1. Определяем файл
            if message.content_type == "photo":
                file_info = bot.get_file(message.photo[-1].file_id)
                file_type = "photo"

            elif message.content_type == "video":
                file_info = bot.get_file(message.video.file_id)
                file_type = "video"

            else:
                return

            # 2. Сохраняем файл локально
            filename, error = save_media_file(
                bot,
                message,
                file_info,
                file_type,
            )

            if error:
                bot.send_message(message.chat.id, error)
                log_error(
                    "Ошибка сохранения",
                    file_type=file_type,
                    user=message.from_user.first_name,
                    reason=error,
                )
                return

            # 3. Создаём задачу в очереди
            original_filename = None
            if message.content_type == "video":
                original_filename = getattr(message.video, "file_name", None)
            original_filename = original_filename or Path(file_info.file_path).name or Path(filename).name
            file_path = Path(settings.DOWNLOAD_FOLDER) / filename

            job = job_manager.create_job(
                user_id=message.from_user.id,
                chat_id=message.chat.id,
                file_path=str(file_path),
                original_filename=original_filename,
            )

            # 4. Ответ пользователю
            bot.send_message(
                chat_id=message.chat.id,
                text=(
                    "📥 Файл получен\n\n"
                    f"• Тип: {file_type}\n"
                    f"• Локальное имя: `{filename}`\n\n"
                    "Задача добавлена в очередь:\n"
                    f"`ID: {job.id}`\n"
                    "`Статус: queued`\n\n"
                    "SurfAnalyze принял данные.\n"
                    "Как только анализ завершится — вернём результат сюда 🌊"
                ),
                parse_mode="Markdown",
            )

            # 5. Лог
            log_info(
                "Медиафайл принят и отправлен в очередь",
                file=filename,
                user=message.from_user.first_name,
                job_id=job.id,
            )

        except ApiTelegramException as e:
            msg = str(e)
            if "file is too big" in msg:
                bot.send_message(
                    message.chat.id,
                    "❌ Файл слишком большой для Telegram.",
                )
                log_error(
                    "Файл слишком большой",
                    file_type=file_type,
                    user=message.from_user.first_name,
                )
            else:
                bot.send_message(
                    message.chat.id,
                    "❌ Ошибка Telegram API. Попробуй позже.",
                )
                log_error("Telegram API ошибка", error=msg)

        except Exception as e:
            bot.send_message(
                message.chat.id,
                "❌ Ошибка при обработке файла. Попробуй ещё раз.",
            )
            log_error("Ошибка в media_handler", error=str(e))
