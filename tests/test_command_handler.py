# tests/test_command_handler.py

import pytest
from unittest.mock import MagicMock
from handlers.command_handler import CommandHandler

@pytest.fixture
def mock_bot():
    bot = MagicMock()
    bot.send_message = MagicMock()
    return bot

def test_start_command(mock_bot):
    handler = CommandHandler()
    handler.register(mock_bot)

    message = MagicMock()
    message.chat.id = 123
    message.from_user.first_name = "TestUser"

    handler.start_callback(message)

    mock_bot.send_message.assert_called_once_with(
        123,
        "Привет, TestUser! 👋\nОтправь фото или видео для разбора серфинга."
    )
