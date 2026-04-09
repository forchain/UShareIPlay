"""
房名实时校验：
- 若房名不包含「｜」，认为审核未通过/系统随机命名，排队重设为「日推」
- 若已排队为「日推」且仍在冷却期，则忽略
"""

__elements__ = ["chat_room_title"]

import time

from ushareiplay.core.base_event import BaseEvent


class ChatRoomTitleEvent(BaseEvent):
    _min_interval_s = 30.0

    def __init__(self, handler):
        super().__init__(handler)
        self._last_check_ts = 0.0

    async def handle(self, key: str, element_wrapper):
        now = time.time()
        if now - self._last_check_ts < self._min_interval_s:
            return False
        self._last_check_ts = now

        try:
            from ushareiplay.core.app_controller import AppController

            controller = AppController.instance()
            if controller and controller.ui_lock and controller.ui_lock.locked():
                return False

            from ushareiplay.managers.title_manager import TitleManager

            title_manager = TitleManager.instance()
            room_title_text = title_manager.get_room_title_text_from_ui()
            if not room_title_text:
                return False

            if "｜" in room_title_text:
                return False

            if (
                title_manager.next_title == "日推"
                and title_manager.theme_manager
                and not title_manager.theme_manager.can_update_now()
            ):
                return False

            title_manager.set_next_title("日推")
            return False
        except Exception as e:
            self.logger.debug(f"ChatRoomTitleEvent skipped: {e}")
            return False

