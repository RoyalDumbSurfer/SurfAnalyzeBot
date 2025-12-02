# container.py

from dependency_injector import containers, providers
from config import settings
from bot_initializer import initialize_bot
from handlers.command_handler import CommandHandler
from handlers.media_handler import MediaHandler
from services.media_service import MediaService

class Container(containers.DeclarativeContainer):
    config = providers.Singleton(lambda: settings)

    bot = providers.Singleton(initialize_bot)

    media_service = providers.Singleton(
        MediaService,
        config=config
    )

    command_handler = providers.Singleton(
        CommandHandler
    )

    media_handler = providers.Singleton(
        MediaHandler,
        media_service=media_service
    )
