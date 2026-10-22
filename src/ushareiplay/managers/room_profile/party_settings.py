"""派对设置面板（Party Settings）的物理动作端口与生产适配器。

Soul App 把「推荐分发」从房间信息抽屉搬到了派对设置面板（#456）。抽屉端口
（`driver.py`）描述的是另一块屏幕，硬把设置面板的动作塞进去会让「抽屉是否开着」
与「设置面板是否开着」混成同一个状态位。因此这里单独给设置面板一个端口：

    RoomProfileManager          决策：什么时候开、读到的文案算什么状态、谁负责关
        └── PartySettingsDriverPort   物理动作：开面板、翻页找状态项、点选项、关面板
              ├── SoulPartySettingsDriver       生产：包装 SoulHandler 的 Appium 细节
              └── InMemoryPartySettingsDriver   测试：内存替身（tests/fakes/）

端口只建模物理动作，**不承载「读文本」**：与抽屉端口同一个约定，判定留在
`RoomProfileManager`。推荐状态那一行显示「所有人」还是「关闭推荐分发」，
由 manager 用 handler 的 element_finder 读一次再判定。
"""

from abc import ABC, abstractmethod

#: 打开设置面板的按钮（房间主界面右上角）。
PARTY_SETTING_BUTTON_KEY = 'party_setting_button'
#: 面板里「推荐分发」那一行右侧的状态文案（「所有人」/「关闭推荐分发」）。
RECOMMENDATION_STATUS_KEY = 'party_setting_recommendation_status'
#: 点开状态那一行之后，二级弹窗里的两个目标选项。
RECOMMENDATION_OPTION_KEYS = {
    True: 'party_recommendation_open',
    False: 'party_recommendation_close',
}
#: 关闭设置面板的 ivClose 按钮。
PARTY_SETTING_CLOSE_KEY = 'party_setting_close'
#: 面板开着的两个辅助证据：标题与可滚动容器。它们都只在设置面板里出现。
PARTY_SETTING_TITLE_KEY = 'party_setting_title'
PARTY_SETTING_CONTAINER_KEY = 'party_setting_container'
PANEL_MARKER_KEYS = (
    PARTY_SETTING_CLOSE_KEY,
    PARTY_SETTING_TITLE_KEY,
    PARTY_SETTING_CONTAINER_KEY,
)
#: 找推荐状态项时最多翻几页。超过就报错，绝不无限滑动。
DEFAULT_MAX_SWIPES = 5


class PartySettingsDriverPort(ABC):
    """把派对设置面板的物理动作关在接口之后。"""

    @abstractmethod
    def is_open(self) -> bool:
        """设置面板当前是否开着。"""

    @abstractmethod
    def open(self) -> bool:
        """点设置按钮并把面板打开；已经开着时直接返回 True。"""

    @abstractmethod
    def reveal_recommendation_status(self, *, max_swipes: int = DEFAULT_MAX_SWIPES) -> bool:
        """在面板里翻页查找推荐状态项，找到（或已经在屏幕上）返回 True。"""

    @abstractmethod
    def click_recommendation_status(self) -> bool:
        """点推荐状态那一行，呼出二级选项弹窗。"""

    @abstractmethod
    def click_recommendation_option(self, enabled: bool) -> bool:
        """在二级弹窗里点「所有人」（True）或「关闭推荐分发」（False）。"""

    @abstractmethod
    def close(self) -> None:
        """关闭设置面板：优先点 ivClose，关不掉时用返回键兜底。"""

    @abstractmethod
    def press_back(self) -> None:
        """按一次返回键（选项弹窗的兜底关闭）。"""


class SoulPartySettingsDriver(PartySettingsDriverPort):
    """驱动真实 Soul App 派对设置面板的生产适配器。

    Args:
        handler: 注入的 `SoulHandler`。`None` 时所有动作都以「不可用」的方式
            失败，而不是抛 AttributeError。
    """

    def __init__(self, handler=None):
        self._handler = handler

    # ------------------------------------------------------------------
    # 面板开关
    # ------------------------------------------------------------------

    def is_open(self) -> bool:
        handler = self._handler
        if handler is None:
            return False
        finder = getattr(handler, 'element_finder', None)
        if finder is None:
            return False
        for key in PANEL_MARKER_KEYS:
            element = finder.try_find_element(key, log=False)
            if element is None:
                continue
            try:
                if element.is_displayed():
                    return True
            except Exception:
                # 元素存在但读不到 is_displayed：按「开着」处理，宁可多关一次，
                # 也不要把面板留在屏幕上。
                return True
        return False

    def open(self) -> bool:
        if self.is_open():
            return True
        if self._handler is None:
            return False

        handler = self._handler
        finder = handler.element_finder
        element = finder.wait_for_element_clickable(PARTY_SETTING_BUTTON_KEY, timeout=5)
        if not element:
            element = finder.wait_for_element(PARTY_SETTING_BUTTON_KEY, timeout=5)
        if not element:
            return False

        if not self._click_element(element):
            return False

        if hasattr(finder, 'wait_for_any_element'):
            finder.wait_for_any_element(list(PANEL_MARKER_KEYS), timeout=5)
        return self.is_open()

    def close(self) -> None:
        if not self.is_open():
            return

        handler = self._require_handler()
        finder = handler.element_finder

        close_button = None
        if hasattr(finder, 'wait_for_element_clickable'):
            close_button = finder.wait_for_element_clickable(
                PARTY_SETTING_CLOSE_KEY, timeout=3
            )
        if not close_button and hasattr(finder, 'wait_for_element'):
            close_button = finder.wait_for_element(PARTY_SETTING_CLOSE_KEY, timeout=2)

        if close_button is not None:
            self._click_element(close_button)
            if hasattr(finder, 'wait_for_element_disappear'):
                finder.wait_for_element_disappear(
                    PARTY_SETTING_CLOSE_KEY, timeout=2.0, poll_frequency=0.1
                )

        # ivClose 没把面板收掉（或压根没找到）：用返回键兜底。第二次只在
        # 「确实还开着」时才按 —— 盲按会把用户退出派对房间。
        if self.is_open():
            self.press_back()
        if self.is_open():
            self.press_back()

    def press_back(self) -> None:
        if self._handler is None:
            return
        self._handler.key_actions.press_back()

    # ------------------------------------------------------------------
    # 推荐状态：翻页、点行、点选项
    # ------------------------------------------------------------------

    def reveal_recommendation_status(self, *, max_swipes: int = DEFAULT_MAX_SWIPES) -> bool:
        if self._handler is None:
            return False
        handler = self._handler
        finder = handler.element_finder

        if finder.try_find_element(RECOMMENDATION_STATUS_KEY, log=False):
            return True

        gesture = getattr(handler, 'gesture_handler', None)
        if gesture is not None and hasattr(gesture, 'scroll_container_until_element'):
            _key, element, _values = gesture.scroll_container_until_element(
                RECOMMENDATION_STATUS_KEY,
                PARTY_SETTING_CONTAINER_KEY,
                direction='up',
                max_swipes=max_swipes,
            )
            if element is not None:
                return True
            if finder.try_find_element(RECOMMENDATION_STATUS_KEY, log=False):
                return True

        # 容器选择器没配 / 翻页 helper 不可用时，退化为屏幕级上滑。
        return self._swipe_until_status(max_swipes)

    def click_recommendation_status(self) -> bool:
        return self._click_key(RECOMMENDATION_STATUS_KEY)

    def click_recommendation_option(self, enabled: bool) -> bool:
        return self._click_key(RECOMMENDATION_OPTION_KEYS[bool(enabled)])

    def _swipe_until_status(self, max_swipes: int) -> bool:
        handler = self._require_handler()
        gesture = getattr(handler, 'gesture_handler', None)
        driver = getattr(handler, 'driver', None)
        if gesture is None or driver is None:
            return False

        try:
            size = driver.get_window_size()
            width = int(size['width'])
            height = int(size['height'])
        except Exception:
            return False

        start_x = end_x = width // 2
        start_y = int(height * 0.75)
        end_y = int(height * 0.35)
        for _ in range(max(0, max_swipes)):
            if not gesture.swipe(start_x, start_y, end_x, end_y):
                return False
            if handler.element_finder.try_find_element(
                RECOMMENDATION_STATUS_KEY, log=False
            ):
                return True
        return False

    def _click_key(self, key: str) -> bool:
        if self._handler is None:
            return False
        handler = self._handler
        finder = handler.element_finder

        element = None
        if hasattr(finder, 'wait_for_element_clickable'):
            element = finder.wait_for_element_clickable(key, timeout=5)
        if not element and hasattr(finder, 'wait_for_element'):
            element = finder.wait_for_element(key, timeout=5)
        if not element:
            return False
        return self._click_element(element)

    def _click_element(self, element) -> bool:
        """点元素的中心。坐标手势优先 —— 设置面板里的行常常不可点击（TextView）。"""
        handler = self._require_handler()
        gesture = getattr(handler, 'gesture_handler', None)
        if gesture is not None and hasattr(gesture, 'click_element_at'):
            try:
                if gesture.click_element_at(element):
                    return True
            except Exception:
                pass
        try:
            element.click()
            return True
        except Exception:
            return False

    def _require_handler(self):
        if self._handler is None:
            raise RuntimeError("Soul handler is not available")
        return self._handler
