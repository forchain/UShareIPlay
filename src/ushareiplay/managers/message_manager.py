"""
MessageManager -- thin chat transport adapter.

Cursor state (recent_chats / latest_chats), dedupe / anchor matching,
Chat Intake classification, command routing, and missed-history recovery
all live on the Command Execution seam (CommandManager). This module
keeps only what the transport layer actually owns: chat-logger setup,
the seat-manager handle for collapsing the seat panel, and the
``party_id`` lookup. ``process_new_messages`` is preserved as a
compatibility shim that delegates to Command Execution.
"""

import logging

from ushareiplay.core.log_formatter import ColoredFormatter
from ushareiplay.core.singleton import Singleton


# Global chat logger - will be initialized when needed
chat_logger = None


def get_chat_logger(config=None):
    """Get or create chat logger.

    Delegates to the RuntimeLogging module so the chat log inherits the
    same path / archive / handler / reset invariants as the app log.
    """
    global chat_logger
    if chat_logger is None:
        from ushareiplay.core.runtime_logging import get_runtime_logging

        chat_logger = get_runtime_logging().attach_chat_logger(config)
    return chat_logger


class MessageManager(Singleton):
    """Pure chat transport adapter.

    All command-execution, classification, dedupe, anchor, and
    missed-history logic has been moved to ``CommandManager`` (the
    Command Execution seam). This class keeps the transport-layer
    responsibilities that remain after the split: chat-logger setup,
    the seat-manager handle, and ``party_id`` lookup.
    """

    def __init__(self):
        self._handler = None
        self._chat_logger = None

    @property
    def handler(self):
        if self._handler is None:
            from ushareiplay.handlers.soul_handler import SoulHandler

            self._handler = SoulHandler.instance()
        return self._handler

    @property
    def chat_logger(self):
        if self._chat_logger is None:
            self._chat_logger = get_chat_logger(self.handler.config)
        return self._chat_logger

    def _get_seat_manager(self):
        from ushareiplay.managers.seat_manager import SeatManager

        return SeatManager.get_instance()

    def get_party_id(self):
        party_id = self.handler.party_id
        if not party_id:
            party_id = self.handler.config['default_party_id']
        return party_id

    async def process_new_messages(self):
        """Compatibility shim.

        Delegates to ``CommandManager`` so legacy callers (and the
        Soul-handler lookup) continue to work; new code should call
        ``CommandManager.process_live_batch(rows)`` directly.
        """
        from ushareiplay.managers.command_manager import CommandManager

        return await CommandManager.instance().execute_chat_scan([])
