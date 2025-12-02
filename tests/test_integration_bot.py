import pytest
from unittest.mock import MagicMock, patch
from handlers.media_handler import MediaHandler
from handlers.command_handler import CommandHandler

@pytest.fixture
def fake_bot():
    bot = MagicMock()
    bot.send_message = MagicMock()
    bot.get_file = MagicMock()
    bot.download_file = MagicMock()
    return bot

@pytest.fixture
def fake_user_message():
    user = MagicMock()
    user.first_name = "Tester"
    chat = MagicMock()
    chat.id = 111
    msg = MagicMock()
    msg.from_user = user
    msg.chat = chat
    msg.content_type = "photo"
    msg.photo = [MagicMock(file_id="123456")]
    msg.message_id = 9
    return msg

def test_bot_photo_upload_flow(fake_bot, fake_user_message):
    mock_media_service = MagicMock()
    mock_media_service.process_media.return_value = "Файл photo успешно обработан."
    handler = MediaHandler(media_service=mock_media_service)
    handler.bot = fake_bot
    with patch("utils.media_service.save_media_file") as save_media:
        save_media.return_value = ("somefile.jpg", None)
        file_info = MagicMock()
        file_info.file_path = "photos/photo.jpg"
        file_info.file_size = 1024
        fake_bot.get_file.return_value = file_info
        fake_bot.download_file.return_value = b"fake_data"
        handler.handle_media(fake_user_message)
        calls = [call.args[1] for call in fake_bot.send_message.call_args_list]
        assert any("✅ Photo загружен как" in msg for msg in calls)

def test_bot_command_start(fake_bot):
    handler = CommandHandler()
    handler.bot = fake_bot
    msg = MagicMock()
    msg.chat.id = 222
    msg.from_user.first_name = "Dean"
    handler.start_callback(msg)
    calls = [call.args[1] for call in fake_bot.send_message.call_args_list]
    assert any("Привет, Dean!" in msg for msg in calls)


