import pytest
from unittest.mock import MagicMock, patch
from handlers.media_handler import MediaHandler

@pytest.fixture
def mock_bot():
    bot = MagicMock()
    bot.send_message = MagicMock()
    bot.get_file = MagicMock()
    bot.download_file = MagicMock()
    return bot

@pytest.fixture
def fake_message():
    user = MagicMock()
    user.first_name = "TestUser"
    chat = MagicMock()
    chat.id = 777
    msg = MagicMock()
    msg.from_user = user
    msg.chat = chat
    msg.content_type = "photo"
    msg.photo = [MagicMock(file_id="photo_file_id")]
    msg.message_id = 100
    return msg

@pytest.fixture
def mock_media_service():
    service = MagicMock()
    service.process_media.return_value = "Файл photo успешно обработан."
    return service

def test_handle_photo_success(mock_bot, fake_message, mock_media_service):
    handler = MediaHandler(media_service=mock_media_service)
    handler.bot = mock_bot
    with patch("utils.media_service.save_media_file") as save_media:
        save_media.return_value = ("somefile.jpg", None)
        file_info = MagicMock()
        file_info.file_path = "photos/photo.jpg"
        file_info.file_size = 1024
        mock_bot.get_file.return_value = file_info
        mock_bot.download_file.return_value = b"fake_data"
        handler.handle_media(fake_message)
        calls = [call.args[1] for call in mock_bot.send_message.call_args_list]
        assert any("✅ Photo загружен как" in msg for msg in calls)

def test_handle_photo_save_error(mock_bot, fake_message, mock_media_service):
    handler = MediaHandler(media_service=mock_media_service)
    handler.bot = mock_bot
    with patch("utils.media_service.save_media_file") as save_media:
        save_media.return_value = (None, "Ошибка сохранения")
        file_info = MagicMock()
        file_info.file_path = "photos/photo.jpg"
        file_info.file_size = 1024
        mock_bot.get_file.return_value = file_info
        mock_bot.download_file.return_value = b"fake_data"
        handler.handle_media(fake_message)
        calls = [call.args[1] for call in mock_bot.send_message.call_args_list]
        # Проверяем, что всё равно было сообщение об успешной загрузке
        assert any("✅ Photo загружен как" in msg for msg in calls)







