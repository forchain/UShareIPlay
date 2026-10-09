"""生产适配器：把 `SoulHandler` 的 Appium 细节包成抽屉端口。

这里的每一步都是抽屉 ritual 原有的那一行 —— 入口点击仍是 `ui_actions.switch_and_click`，
正规关窗仍是 `RecoveryManager.close_drawer('slide_drawer')`，保底仍是 `key_actions.press_back`。
编辑字段用到的三个元素级原语则逐字对应原 `TopicManager._update_topic_ui` 里的
`wait_for_element_clickable` / `wait_for_any_element` / `clear()+send_keys()`。

唯一的例外是房名编辑入口：它走 `click_element_at` 落到
`gesture_handler.click_element_at(element, y_ratio=0.25)`，与旧 `RoomNameManager`
逐字一致 —— 点在元素上缘而不是中心。那是随主题功能一起上线的既有手势，端口
第一次成形时没有坐标原语，于是被悄悄退化成了中心点击；这里把它复原。
"""

from typing import Any, Optional, Sequence, Tuple

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
        # Selenium 的 WebElement.click() 返回 None，因此不能拿它的返回值当布尔：
        # 那样「点成功」与「点失败」在生产里无法区分，调用方会把每一次成功的
        # 点击误判成「元素没找到」。点得到就报告成功。
        element.click()
        return True

    def click_element_at(self, key: str, *, y_ratio: float, timeout: int = 10) -> bool:
        """点元素内某个纵向比例的位置（房名编辑入口的 0.25 高度点击）。"""
        handler = self._require_handler()
        element = handler.element_finder.wait_for_element_clickable(key, timeout=timeout)
        if not element:
            return False
        # 坐标手势自己会回 False（手势都失败且回落也失败），这一次失败必须如实
        # 上报：把它当成点成功，调用方就会把一次空点记成「房名已写」。
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

    def scroll_container_until_element(
        self,
        element_key: str,
        container_key: str,
        direction: str = "up",
        attribute_name: Optional[str] = None,
        attribute_value: Optional[str] = None,
        max_swipes: int = 10,
    ) -> Tuple[Optional[str], Optional[Any], list]:
        handler = self._require_handler()
        return handler.gesture_handler.scroll_container_until_element(
            element_key,
            container_key,
            direction=direction,
            attribute_name=attribute_name,
            attribute_value=attribute_value,
            max_swipes=max_swipes,
        )

    def is_settings_open(self) -> bool:
        handler = self._handler
        if handler is None:
            return False
        elem = handler.element_finder.try_find_element("party_setting_container", log=False)
        if not elem:
            return False
        try:
            return bool(elem.is_displayed())
        except Exception:
            return True

    def _require_handler(self):
        if self._handler is None:
            raise RuntimeError("Soul handler is not available")
        return self._handler
