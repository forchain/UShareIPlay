"""生产适配器：把 `SoulHandler` 的 Appium 细节包成抽屉端口。

这里的每一步都对应 `room_info_window.py` 里原有的那一行 —— 本文件只搬家，
不改判定：入口点击仍是 `ui_actions.switch_and_click`，正规关窗仍是
`RecoveryManager.close_drawer('slide_drawer')`，保底仍是 `key_actions.press_back`。
编辑字段用到的三个元素级原语则逐字对应 `TopicManager._update_topic_ui` 里的
`wait_for_element_clickable` / `wait_for_any_element` / `clear()+send_keys()`。
"""

from typing import Optional, Sequence

from ushareiplay.managers.recovery_manager import RecoveryManager
from ushareiplay.managers.room_profile.driver import (
    DIALOG_KEYS,
    DRAWER_KEY,
    RoomProfileDrawerDriverPort,
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
        if not RecoveryManager.is_initialized():
            return False
        return bool(RecoveryManager.instance().close_drawer(DRAWER_KEY))

    def press_back(self) -> None:
        self._require_handler().key_actions.press_back()

    def click_element(self, key: str, *, timeout: int = 10) -> bool:
        element = self._require_handler().element_finder.wait_for_element_clickable(
            key, timeout=timeout
        )
        if not element:
            return False
        return bool(element.click())

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
