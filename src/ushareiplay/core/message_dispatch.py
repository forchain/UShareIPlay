import traceback

from ushareiplay.core.command_silence import is_command_silent
from ushareiplay.core.singleton import Singleton


class MessageDispatch(Singleton):
    """Route outbound chat messages through one observable application seam."""

    def __init__(self):
        self._handler = None
        self._user_manager = None
        self._runtime = None

    def configure_runtime(self, runtime):
        self._runtime = runtime
        controller = getattr(runtime, "controller", None)
        handler = getattr(controller, "soul_handler", None)
        if handler is not None:
            self._handler = handler

    def bind_handler(self, handler):
        """Bind the active Soul handler for callers constructed outside runtime setup."""
        if handler is not None:
            self._handler = handler
        return self

    @property
    def handler(self):
        if self._handler is None:
            from ushareiplay.handlers.soul_handler import SoulHandler

            self._handler = SoulHandler.instance()
        return self._handler

    @property
    def user_manager(self):
        if self._user_manager is None:
            from ushareiplay.managers.user_manager import UserManager

            self._user_manager = UserManager.instance()
        return self._user_manager

    def _emit(self, event, ctx):
        if self._runtime is None:
            return
        try:
            self._runtime.emit(event, ctx=ctx)
        except Exception:
            pass

    def send_screen_message(self, message: str, silent: bool = False):
        """Send a room message unless the current command suppresses screen output."""
        if silent or is_command_silent():
            try:
                self.handler.logger.info(f"Silent command suppressed screen message: {message}")
            except Exception:
                pass
            self._emit(
                "message.dispatch.suppressed",
                {"channel": "screen", "message_len": len(message)},
            )
            return None

        try:
            result = self.handler.send_message(message)
        except Exception:
            self._emit(
                "message.dispatch.screen",
                {"message_len": len(message), "sent": False},
            )
            raise
        self._emit(
            "message.dispatch.screen",
            {"message_len": len(message), "sent": not isinstance(result, dict) or "error" not in result},
        )
        return result

    def send_private_message(self, nickname: str, message: str) -> bool:
        """Send a private reply and record its outcome without logging its contents."""
        try:
            sent = self.user_manager.send_private_message_to_user(nickname, message)
            if not sent:
                self.handler.logger.warning(f"Private reply dropped for {nickname}: send failed")
            self._emit(
                "message.dispatch.private",
                {"nickname": nickname, "message_len": len(message), "sent": bool(sent)},
            )
            return bool(sent)
        except Exception:
            try:
                self.handler.logger.error(
                    f"Private reply failed for {nickname}: {traceback.format_exc()}"
                )
            except Exception:
                pass
            self._emit(
                "message.dispatch.private",
                {"nickname": nickname, "message_len": len(message), "sent": False},
            )
            return False

    def send_for_message_info(self, message_info, response: str, silent: bool = False):
        """Route command output according to the requester's private-reply preference."""
        if not response:
            return None
        if getattr(message_info, "private_reply", False):
            return self.send_private_message(message_info.nickname, response)
        return self.send_screen_message(response, silent=silent)
