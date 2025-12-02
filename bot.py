# bot.py

import os
import sys
from time import sleep
from container import Container
from utils.logger import log_error, log_info
from config import settings

LOCK_FILE = 'bot.lock'
print(f"Текущая версия приложения: {settings.VERSION}")

def main():
    if os.path.exists(LOCK_FILE):
        log_info("⚠️ Бот уже запущен. Выход.")
        sys.exit()

    with open(LOCK_FILE, 'w') as f:
        f.write("LOCKED")

    try:
        container = Container()
        bot = container.bot()
        container.command_handler().register(bot)
        container.media_handler().register(bot)

        log_info("🤖 Бот запущен.")

        while True:
            try:
                bot.polling(none_stop=True)
            except ConnectionError as e:
                log_error("Connection error", error=str(e))
                sleep(5)
            except Exception as e:
                log_error("Unexpected error", error=str(e))
                sleep(5)

    finally:
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)
            log_info("🔒 Lock-файл удалён.")

if __name__ == "__main__":
    main()
