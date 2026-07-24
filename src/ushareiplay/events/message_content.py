"""
Message content event -- thin ingress into Command Execution.

Collects the freshly scraped chat rows from the live Soul screen and
forwards them to ``CommandManager.process_live_batch``. All dedupe /
anchor / classification / routing / execution / missed-history logic
lives on the Command Execution seam; this event only knows how to
flatten ``ElementWrapper`` inputs into raw strings.
"""

__multiple__ = True

import traceback

from ushareiplay.core.base_event import BaseEvent
from ushareiplay.managers.command_manager import CommandManager


class MessageContentEvent(BaseEvent):
    """Message content event handler.

    Collects the visible chat rows from the ``message_content`` element
    and submits them to Command Execution. No classification, dedupe,
    routing, or recovery logic is owned by this event.
    """

    async def handle(self, key, element_wrapper):
        try:
            wrappers = (
                element_wrapper
                if isinstance(element_wrapper, list)
                else [element_wrapper]
            )
            rows = [
                wrapper.content
                for wrapper in wrappers
                if wrapper and wrapper.content
            ]

            if rows:
                await CommandManager.instance().process_live_batch(rows)

            return False
        except Exception:
            self.logger.error(
                f"Error processing message content event: {traceback.format_exc()}"
            )
            return False
