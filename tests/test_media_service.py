# tests/test_media_service.py

import os
import pytest
from unittest.mock import MagicMock
from utils.media_service import save_media_file
from config import settings

@pytest.fixture
def fake_bot():
    bot = MagicMock()
    bot.download_file.return_value = b"fake_data"
    return bot

@pytest.fixture
def fake_message():
    user = MagicMock()
    user.first_name = "TestUser"

    msg = MagicMock()
    msg.from_user = user
    msg.message_id = 123
    return msg

def test_save_photo_success(tmp_path, fake_bot, fake_message):
    settings.DOWNLOAD_FOLDER = str(tmp_path)

    file_info = MagicMock()
    file_info.file_path = "photos/test.jpg"
    file_info.file_size = 1024 * 1024  # 1 MB

    filename, error = save_media_file(fake_bot, fake_message, file_info, "photo")
    assert error is None
    assert filename is not None
    assert os.path.exists(os.path.join(tmp_path, filename))

def test_save_file_too_large(tmp_path, fake_bot, fake_message):
    settings.DOWNLOAD_FOLDER = str(tmp_path)
    file_info = MagicMock()
    file_info.file_path = "photos/big.jpg"
    file_info.file_size = settings.MAX_FILE_SIZE + 1

    filename, error = save_media_file(fake_bot, fake_message, file_info, "photo")
    assert filename is None
    assert error == "❌ Файл слишком большой! Лимит: 50 МБ."


def test_save_file_invalid_path(tmp_path, fake_bot, fake_message):
    settings.DOWNLOAD_FOLDER = str(tmp_path)
    file_info = MagicMock()
    file_info.file_path = ""  # Пустой путь
    file_info.file_size = 1024

    filename, error = save_media_file(fake_bot, fake_message, file_info, "photo")

    assert filename is None
    assert error == "❌ Не указан путь к файлу."


