# handlers/command_handler.py

from telebot import TeleBot, types
from telebot.types import Message

from handlers.base_handler import BaseHandler
from utils.logger import logger_message

# Вынесем URL web-app в отдельную константу (потом можно перенести в settings)
WEBAPP_URL = "https://fb59e86ef756.ngrok-free.app/"


class CommandHandler(BaseHandler):
    def __init__(self):
        self.bot: TeleBot | None = None

    def register(self, bot: TeleBot):
        """
        Регистрирует обработчики команд и текстовых сообщений.
        """
        self.bot = bot

        bot.register_message_handler(self.start_callback, commands=["start"])
        bot.register_message_handler(self.webapp_callback, commands=["webapp"])
        bot.register_message_handler(self.text_callback, content_types=["text"])

    # ---------------------------
    # /start
    # ---------------------------
    @logger_message
    def start_callback(self, message: Message):
        user_name = message.from_user.first_name or "серфер"

        # Кнопки
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        btn_upload = types.KeyboardButton("📤 Загрузить медиа")
        btn_webapp = types.KeyboardButton("🌐 Открыть web-app")
        markup.add(btn_upload, btn_webapp)

        # Приветственное сообщение
        text = (
            f"Привет, {user_name}! 👋\n\n"
            "SurfAnalyze — сервис для разбора твоих серф-фото и видео.\n\n"
            "Просто отправь медиа сюда или выбери действие ниже 👇"
        )

        self.bot.send_message(
            chat_id=message.chat.id,
            text=text,
            reply_markup=markup,
        )

    # ---------------------------
    # /webapp
    # ---------------------------
    @logger_message
    def webapp_callback(self, message: Message):
        text = (
            "Открываю SurfAnalyze web-app. Если что-то пойдёт не так — "
            "просто обнови вкладку в браузере.\n\n"
            f"🌐 {WEBAPP_URL}"
        )
        self.bot.send_message(message.chat.id, text)

    # ---------------------------
    # Текстовые сообщения
    # ---------------------------
    @logger_message
    def text_callback(self, message: Message):
        text = message.text or ""

        if text == "📤 Загрузить медиа":
            self.bot.send_message(
                message.chat.id,
                "Отправь фото или видео сюда — SurfAnalyze поставит его в очередь на разбор 👇",
            )

        elif text == "🌐 Открыть web-app":
            self.bot.send_message(
                message.chat.id,
                f"🌐 Открой SurfAnalyze web-app:\n{WEBAPP_URL}"
            )

        else:
            # Небольшой мягкий дефолт
            self.bot.send_message(
                message.chat.id,
                "Я жду медиа для разбора или можешь нажать одну из кнопок снизу 👇",
            )
