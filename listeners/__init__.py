# File: Oppo/listeners/__init__.py
# Purpose: Initialize the listeners package

import logging

logger = logging.getLogger(__name__)
logger.info("Listeners package initialized.")

# Optionally expose main classes if they are stable enough
try:
    from .listener_manager import ListenerManager
    from .youtube_listener import YouTubeListener
    from .telegram_listener import TelegramListener
    __all__ = [
        "ListenerManager",
        "YouTubeListener",
        "TelegramListener"
    ]
except ImportError as e:
     logger.error(f"Could not import all listener components: {e}")
     __all__ = []

