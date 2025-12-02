# utils/texts.py

from telebot import types

START_MESSAGE = (
    "Привет, серфер! 🏄‍♂️\n\n"
    "Это *SurfAnalyze* — бот, который поможет тебе улучшить технику катания.\n\n"
    "Выбери, что хочешь сделать 👇"
)

RESPONSES = {
    "upload_photo": "📸 Жду твоё фото для разбора!",
    "upload_video": "🎥 Жду твоё видео для разбора!",
    "example": "📂 Пока пример не загружен.",
    "about": "🌊 *SurfAnalyze* — это бот для серферов. Загружай фото или видео и получай обратную связь от коуча!"
}

def get_main_menu():
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("📸 Отправить фото", callback_data="upload_photo"),
        types.InlineKeyboardButton("🎥 Отправить видео", callback_data="upload_video"),
        types.InlineKeyboardButton("📂 Пример разбора", callback_data="example"),
        types.InlineKeyboardButton("🌊 О проекте", callback_data="about")
    )
    return markup
