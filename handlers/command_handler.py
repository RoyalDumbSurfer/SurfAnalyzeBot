from telebot.types import Message
from telebot import types
from utils.logger import logger_message
from handlers.base_handler import BaseHandler


class CommandHandler(BaseHandler):
    def register(self, bot):
        self.bot = bot
        bot.register_message_handler(self.start_callback, commands=["start"])
        bot.register_message_handler(self.webapp_callback, commands=["webapp"])
        bot.register_message_handler(self.text_callback, content_types=["text"])

    @logger_message
    def start_callback(self, message: Message):
        user_name = message.from_user.first_name

        # Кнопки
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        btn1 = types.KeyboardButton("📤 Загрузить медиа")
        btn2 = types.KeyboardButton("🌐 Открыть web-app")
        markup.add(btn1, btn2)

        # Приветственное сообщение с кнопками
        self.bot.send_message(
            message.chat.id,
            f"Привет, {user_name}! 👋\nОтправь фото или видео для разбора серфинга или выбери действие ниже:",
            reply_markup=markup
        )

    @logger_message
    def webapp_callback(self, message: Message):
        url = "https://fb59e86ef756.ngrok-free.app/"
        self.bot.send_message(message.chat.id, f"🌐 Открой SurfAnalyze web-app:\n{url}")

    @logger_message
    def text_callback(self, message: Message):
        if message.text == "📤 Загрузить медиа":
            self.bot.send_message(message.chat.id, "Отправь фото или видео сюда 👇")
        elif message.text == "🌐 Открыть web-app":
            url = "https://fb59e86ef756.ngrok-free.app/"
            self.bot.send_message(message.chat.id, f"🌐 Открой SurfAnalyze web-app:\n{url}")


