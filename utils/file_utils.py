# utils/file_utils.py

import os
import time
from config import settings
from utils.logger import log_info, log_error


def ensure_download_folder():
    if not os.path.exists(settings.DOWNLOAD_FOLDER):
        os.makedirs(settings.DOWNLOAD_FOLDER)
        log_info(f"Создана папка загрузок: {settings.DOWNLOAD_FOLDER}")

def cleanup_old_logs(days=7):
    now = time.time()
    cutoff = now - (days * 86400)

    for filename in os.listdir(settings.LOG_FOLDER):
        if filename == os.path.basename(settings.LOG_FILE):
            continue

        file_path = os.path.join(settings.LOG_FOLDER, filename)
        if os.path.isfile(file_path):
            try:
                if os.path.getctime(file_path) < cutoff:
                    os.remove(file_path)
                    log_info(f"[CLEANUP] Удалён старый лог: {filename}")
            except Exception as e:
                log_error(f"[CLEANUP-ERROR] Не удалось удалить {filename}: {e}")
