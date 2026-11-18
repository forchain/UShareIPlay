"""Soul App 房间档案适配器：抽屉、派对设置面板与只读判定读。

端口在 `modules/room/ports.py`，这里只做 Appium 映射。元素查询保持即用
即查：每次调用都重新定位，绝不缓存 WebElement。
"""

import time
from typing import Optional

from ushareiplay.modules.room.ports import (
    DEFAULT_MAX_SWIPES,
    DIALOG_KEYS,
    PARTY_SETTING_BUTTON_KEY,
    PARTY_SETTING_CLOSE_KEY,
    PARTY_SETTING_TITLE_KEY,
    RECOMMENDATION_OPTION_KEYS,
    RECOMMENDATION_STATUS_KEY,
    ROOM_INFO_CLOSE_KEYS,
    PartySettingsDriverPort,
    RoomProfileDrawerDriverPort,
    RoomProfileSurfacePort,
)


class SoulDrawerDriver(RoomProfileDrawerDriverPort):
    """驱动真实 Soul App 抽屉的生产适配器。

    Args:
        handler: 注入的 `SoulHandler`。`None` 时所有动作都以「App 不可用」的
            方式失败，而不是抛 AttributeError。
    """

    def __init__(self, handler=None):
        self._handler = handler

    def is_open(self) -> bool:
        handler = self._handler
        if handler is None:
            return False
        for key in DIALOG_KEYS:
            if handler.element_finder.try_find_element(key, log=False):
                return True
        return False

    def open_drawer(self, entry_key: str, *, error_message: str) -> dict:
        return self._require_handler().ui_actions.switch_and_click(
            entry_key, error_message=error_message
        )

    def close_drawer(self) -> bool:
        """关闭房间信息抽屉：点击专门的关闭按钮 (iv_close)，不点击窗口上方。"""
        handler = self._handler
        if handler is None:
            return False
        finder = handler.element_finder

        for key in ROOM_INFO_CLOSE_KEYS:
            close_btn = None
            if hasattr(finder, "wait_for_element_clickable"):
                close_btn = finder.wait_for_element_clickable(key, timeout=2)
            if not close_btn and hasattr(finder, "wait_for_element"):
                close_btn = finder.wait_for_element(key, timeout=1)
            if not close_btn and hasattr(finder, "try_find_element"):
                close_btn = finder.try_find_element(key, log=False)

            if close_btn:
                close_btn.click()
                if hasattr(finder, "wait_for_element_disappear"):
                    finder.wait_for_element_disappear(
                        key, timeout=3.0, poll_frequency=0.1
                    )
                return True

        return False

    def press_back(self) -> None:
        self._require_handler().key_actions.press_back()

    def click_element(self, key: str, *, timeout: int = 10) -> bool:
        element = self._require_handler().element_finder.wait_for_element_clickable(
            key, timeout=timeout
        )
        if not element:
            return False
        # Selenium 的 WebElement.click() 返回 None，因此不能拿它的返回值当布尔。
        element.click()
        return True

    def click_element_at(self, key: str, *, y_ratio: float, timeout: int = 10) -> bool:
        """点元素内某个纵向比例的位置（房名编辑入口的 0.25 高度点击）。"""
        handler = self._require_handler()
        element = handler.element_finder.wait_for_element_clickable(key, timeout=timeout)
        if not element:
            return False
        return bool(handler.gesture_handler.click_element_at(element, y_ratio=y_ratio))

    def wait_for_any(self, keys, *, timeout: int = 10) -> Optional[str]:
        key, _element = self._require_handler().element_finder.wait_for_any_element(
            list(keys), timeout
        )
        return key

    def replace_text(self, key: str, text: str, *, timeout: int = 10) -> bool:
        element = self._require_handler().element_finder.wait_for_element_clickable(
            key, timeout=timeout
        )
        if not element:
            return False
        element.clear()
        element.send_keys(text)
        return True

    def _require_handler(self):
        if self._handler is None:
            raise RuntimeError("Soul handler is not available")
        return self._handler


class SoulPartySettingsDriver(PartySettingsDriverPort):
    """驱动真实 Soul App 派对设置面板的生产适配器。"""

    def __init__(self, handler):
        self._handler = handler

    def is_open(self) -> bool:
        key, _element = self._handler.element_finder.wait_for_any_element(
            [PARTY_SETTING_TITLE_KEY, PARTY_SETTING_BUTTON_KEY]
        )
        return key == PARTY_SETTING_TITLE_KEY

    def open(self) -> bool:
        if self.is_open():
            return True
        element = self._handler.element_finder.wait_for_element_clickable(
            PARTY_SETTING_BUTTON_KEY, timeout=5
        )
        if not element:
            return False
        element.click()
        return bool(
            self._handler.element_finder.wait_for_element(
                PARTY_SETTING_TITLE_KEY, timeout=5
            )
        )

    def close(self) -> None:
        if not self.is_open():
            return
        close_btn = self._handler.element_finder.wait_for_element_clickable(
            PARTY_SETTING_CLOSE_KEY, timeout=3
        )
        if close_btn:
            close_btn.click()
            if self._handler.element_finder.wait_for_element_disappear(
                    PARTY_SETTING_TITLE_KEY, timeout=3
            ):
                return
        if self.is_open():
            self.press_back()

    def press_back(self) -> None:
        self._handler.key_actions.press_back()

    def reveal_recommendation_status(self, *, max_swipes: int = DEFAULT_MAX_SWIPES) -> bool:
        if self._handler.element_finder.try_find_element(
                RECOMMENDATION_STATUS_KEY, log=False
        ):
            return True
        element = self._handler.gesture_handler.swipe_until_element(
            RECOMMENDATION_STATUS_KEY,
            direction='up',
            max_swipes=max_swipes,
            duration_ms=800,
        )
        if element is not None:
            time.sleep(1.0)
            return True
        return False

    def click_recommendation_status(self) -> bool:
        element = self._handler.element_finder.wait_for_element_clickable(
            RECOMMENDATION_STATUS_KEY, timeout=5
        )
        if not element:
            return False
        element.click()
        return True

    def click_recommendation_option(self, enabled: bool) -> bool:
        key = RECOMMENDATION_OPTION_KEYS[bool(enabled)]
        element = self._handler.element_finder.wait_for_element_clickable(
            key, timeout=5
        )
        if not element:
            return False
        element.click()
        return True


class SoulRoomProfileSurface(RoomProfileSurfacePort):
    """房间档案的只读判定读与前台切换。"""

    def __init__(self, handler):
        self._handler = handler

    def switch_to_app(self) -> bool:
        return bool(self._handler.key_actions.switch_to_app())

    def read_room_title(self) -> Optional[str]:
        handler = self._handler
        if handler is None:
            return None
        finder = handler.element_finder
        try:
            # 优先检查弹窗内部的房名 ID，等待动画/过渡完成。
            dialog_element = finder.wait_for_element('room_name_in_dialog', timeout=2)
            if dialog_element:
                text = finder.get_element_text(dialog_element)
                if isinstance(text, str) and text.strip():
                    return text.strip()

            # 若弹窗未打开，回退至主界面房名 ID。
            room_title_element = finder.try_find_element('chat_room_title', log=False)
            if not room_title_element:
                return None
            text = finder.get_element_text(room_title_element)
            if isinstance(text, str) and text.strip():
                return text.strip()
            return None
        except Exception:
            return None

    def read_notice_text(self) -> str:
        handler = self._handler
        if handler is None:
            return ""
        finder = handler.element_finder
        element = finder.try_find_element('chat_room_notice', log=False)
        if element:
            text = (finder.get_element_text(element) or "").strip()
            if text and text != "编辑":
                return text
        return ""

    def read_row_text(self, key: str, *, wait: bool = False) -> str:
        handler = self._handler
        if handler is None:
            return ""
        finder = handler.element_finder
        try:
            if wait:
                element = finder.wait_for_element(key)
            else:
                element = finder.try_find_element(key, log=False)
            if not element:
                return ""
            return (finder.get_element_text(element) or "").strip()
        except Exception:
            return ""
