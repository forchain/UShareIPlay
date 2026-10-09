"""在线用户列表关闭方式的回归测试。

新版 Soul 的在线用户列表带专门的关闭按钮 ivClose，不再暴露抽屉遮罩
touch_close。旧实现把在线列表当抽屉关：先等 online_drawer (touch_close)
可点击 → 等满 10 秒超时 → 再等 room_id 又等满 10 秒 → 最后 press_back 兜底，
一次关闭白白耗掉 20 秒还伴随两条 warning。这里锁定"用关闭按钮关列表"。
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from ushareiplay.managers.recovery_manager import RecoveryManager


@pytest.fixture(autouse=True)
def reset_recovery_manager_singleton():
    RecoveryManager.reset_instance()
    yield
    RecoveryManager.reset_instance()


class OnlineListCloseHandler:
    """模拟新版 Soul：在线列表开着时只有 ivClose 按钮，没有 touch_close 遮罩。

    记录关键动作，用来断言关闭走的是"点关闭按钮"而不是"点窗口上沿 + press_back"。
    """

    CLOSE_KEYS = ("online_users_close", "close_button")
    # 旧实现在遮罩缺失时耗时等待的两个元素
    SLOW_KEYS = ("online_drawer", "room_id")

    def __init__(self):
        self.logger = MagicMock()
        self.list_open = True
        self.close_button = SimpleNamespace(
            click=self._click_close_button, is_displayed=lambda: True
        )
        self.close_button_keys_clicked = []
        self.drawer_mask_clicks = 0
        self.slow_wait_seconds = 0.0
        self.press_back = MagicMock()
        self.room_element = SimpleNamespace(is_displayed=lambda: True)

        self.element_finder = SimpleNamespace(
            wait_for_element_clickable=self._wait_for_element_clickable,
            try_find_element=self._try_find_element,
            wait_for_element=self._wait_for_element,
            wait_for_element_disappear=self._wait_for_element_disappear,
        )
        self.key_actions = SimpleNamespace(press_back=self.press_back)
        self.gesture_handler = SimpleNamespace(click_element_at=self._click_element_at)

    def _click_close_button(self):
        self.close_button_keys_clicked.append("online_users_close")
        self.list_open = False

    def _click_element_at(self, element, x_ratio=0.5, y_ratio=0.5, x_offset=0, y_offset=0):
        # 点在窗口上沿（y_ratio=0 / y_offset=-200）是旧抽屉式关法
        self.drawer_mask_clicks += 1
        return True

    def _wait_for_element_clickable(self, key, timeout=10):
        if key in self.CLOSE_KEYS and self.list_open:
            return self.close_button
        # online_drawer (touch_close) 在新版里根本不存在
        self._charge_timeout(key, timeout)
        return None

    def _try_find_element(self, key, log=False):
        if key in self.CLOSE_KEYS and self.list_open:
            return self.close_button
        return None

    def _wait_for_element(self, key, timeout=10):
        if key == "room_id" and not self.list_open:
            return self.room_element
        self._charge_timeout(key, timeout)
        return None

    def _charge_timeout(self, key, timeout):
        """只有真的等满超时才算成本；立刻命中不计费。"""
        if key in self.SLOW_KEYS:
            self.slow_wait_seconds += timeout

    def _wait_for_element_disappear(self, key, timeout=3.0, poll_frequency=0.1):
        return key in self.CLOSE_KEYS and not self.list_open


def test_close_online_drawer_uses_close_button_instead_of_drawer_mask():
    """在线列表用 ivClose 关闭：不点窗口上沿，也不靠 press_back 兜底。"""
    handler = OnlineListCloseHandler()
    manager = RecoveryManager.initialize(handler)

    assert manager.close_drawer("online_drawer") is True

    assert handler.close_button_keys_clicked == ["online_users_close"], (
        "在线用户列表应通过 ivClose 关闭按钮关闭"
    )
    assert handler.drawer_mask_clicks == 0, "不应再把在线列表当抽屉点击窗口上沿"
    handler.press_back.assert_not_called()


def test_close_online_drawer_does_not_stall_on_missing_mask_and_room_id():
    """遮罩与 room_id 都找不到时，不得各等满 10 秒（旧实现的 20 秒空转）。"""
    handler = OnlineListCloseHandler()
    manager = RecoveryManager.initialize(handler)

    manager.close_drawer("online_drawer")

    assert handler.slow_wait_seconds == 0, (
        f"不应在 online_drawer / room_id 上累计等待 {handler.slow_wait_seconds} 秒"
    )
