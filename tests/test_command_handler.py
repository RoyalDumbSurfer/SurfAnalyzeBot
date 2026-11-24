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

    mock_bot.send_message.assert_called_once()
    sent = mock_bot.send_message.call_args.kwargs
    assert sent['chat_id'] == 123
    assert 'TestUser' in sent['text'] and 'SurfAnalyze' in sent['text']
    assert sent['reply_markup'].keyboard
