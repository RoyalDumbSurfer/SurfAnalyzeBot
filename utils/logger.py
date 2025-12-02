import structlog
import logging
import os
from functools import wraps
from telebot.types import Message
from config import settings

# Убедимся, что папка логов существует
os.makedirs(settings.LOG_FOLDER, exist_ok=True)

# Настраиваем стандартный logging
log_handlers = [
    logging.FileHandler(settings.LOG_FILE, encoding="utf-8"),
    logging.StreamHandler()  # ➕ Это то, что нужно для терминала
]

logging.basicConfig(
    format="%(message)s",
    handlers=log_handlers,
    level=logging.INFO
)

# Настраиваем structlog
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer()
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
)

logger = structlog.get_logger()

def log_info(message: str, **kwargs):
    logger.info(message, **kwargs)

def log_error(message: str, **kwargs):
    logger.error(message, **kwargs)

def logger_message(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        # Найдем объект message
        message = None
        # Если это bound method, первый аргумент — self, второй — message
        # Если функция, первый — message
        if len(args) == 1:
            message = args[0]
        elif len(args) >= 2:
            message = args[1]
        else:
            message = kwargs.get("message", None)

        user_name = getattr(getattr(message, "from_user", None), "first_name", "unknown")
        chat_id = getattr(getattr(message, "chat", None), "id", "unknown")
        msg_type = getattr(message, "content_type", "unknown")

        logger.info("Сообщение от пользователя", user=user_name, chat_id=chat_id, type=msg_type)
        return func(*args, **kwargs)
    return wrapper

