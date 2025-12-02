# handlers/media_handler.py

from telebot import TeleBot
from telebot.apihelper import ApiTelegramException
from config import settings
from utils.logger import log_error, log_info, logger_message
from handlers.base_handler import BaseHandler
from services.media_service import MediaService
from utils.media_service import save_media_file  # пока используем его

class MediaHandler(BaseHandler):
    def __init__(self, media_service):
        self.media_service = media_service
        self.bot = None

    def register(self, bot: TeleBot):
        self.bot = bot
        @bot.message_handler(content_types=['photo', 'video'])
        @logger_message
        def handle_media(message):
            self.handle_media(message)

    @logger_message
    def handle_media(self, message):
        bot = self.bot
        file_type = 'unknown'
        try:
            if message.content_type == 'photo':
                file_info = bot.get_file(message.photo[-1].file_id)
                file_type = 'photo'
            elif message.content_type == 'video':
                file_info = bot.get_file(message.video.file_id)
                file_type = 'video'
            else:
                return

            filename, error = save_media_file(bot, message, file_info, file_type)
            if error:
                bot.send_message(message.chat.id, error)
                log_error("Ошибка сохранения", file_type=file_type, user=message.from_user.first_name, reason=error)
                return

            result = self.media_service.process_media(file_info.file_path)
            bot.send_message(message.chat.id, f"✅ {file_type.capitalize()} загружен как {filename}.")
            log_info("Медиафайл загружен", file=filename, user=message.from_user.first_name, service_result=result)

        except ApiTelegramException as e:
            msg = str(e)
            if "file is too big" in msg:
                bot.send_message(message.chat.id, "❌ Файл слишком большой для Telegram.")
                log_error("Файл слишком большой", file_type=file_type, user=message.from_user.first_name)
            else:
                bot.send_message(message.chat.id, "❌ Ошибка Telegram API.")
                log_error("Telegram API ошибка", error=msg)

        except Exception as e:
            bot.send_message(message.chat.id, "❌ Произошла ошибка при загрузке.")
            log_error("Ошибка в media_handler", error=str(e))

