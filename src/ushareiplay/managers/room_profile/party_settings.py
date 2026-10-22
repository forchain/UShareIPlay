"""派对设置面板（Party Settings）的物理动作端口与生产适配器。

Soul App 把「推荐分发」从房间信息抽屉搬到了派对设置面板（#456）。
端口只建模物理动作，不承载「读文本」：判定留在 RoomProfileManager。
"""

from abc import ABC, abstractmethod

PARTY_SETTING_BUTTON_KEY = 'party_setting_button'
RECOMMENDATION_STATUS_KEY = 'party_setting_recommendation_status'
RECOMMENDATION_OPTION_KEYS = {
    True: 'party_recommendation_open',
    False: 'party_recommendation_close',
}
PARTY_SETTING_CLOSE_KEY = 'party_setting_close'
PARTY_SETTING_TITLE_KEY = 'party_setting_title'
PARTY_SETTING_CONTAINER_KEY = 'party_setting_container'

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
        """按一次返回键。"""


class SoulPartySettingsDriver(PartySettingsDriverPort):
    """驱动真实 Soul App 派对设置面板的生产适配器。"""

    def __init__(self, handler):
        self._handler = handler

    def is_open(self) -> bool:
        key, _element = self._handler.element_finder.wait_for_any_element(
            [PARTY_SETTING_TITLE_KEY, PARTY_SETTING_BUTTON_KEY]
        )
        if key == PARTY_SETTING_TITLE_KEY:
            return True
        return False

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
            duration_ms=500,
        )
        return element is not None

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
