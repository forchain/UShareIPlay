"""派对设置面板（Party Settings）的物理动作端口与生产适配器。

Soul App 把「推荐分发」从房间信息抽屉搬到了派对设置面板（#456）。
端口只建模物理动作，不承载「读文本」：判定留在 RoomProfileManager。

面板这块屏幕有两层，物理形状完全不一样：

- **原生设置面板**：`ScrollView` 列表，推荐分发那一行是 `tvRightHint`（显示
  「所有人」或「关闭推荐分发」）。列表要往下滑才看得见推荐那一行。
- **二级弹窗**（点状态行叫出来的「设置房间状态」）：RN 页面，选项文案本身
  `clickable=false`，能点的是它上面那层 `ViewGroup`（`content-desc` 由 RN 把
  子文案拼出来）。弹窗开着的时候原生面板整块被替换 —— 「派对设置」标题不在
  树里，所以弹窗必须自己按掉，否则设置按钮点不动、面板也关不掉。
"""

from abc import ABC, abstractmethod
import time

PARTY_SETTING_BUTTON_KEY = 'party_setting_button'
RECOMMENDATION_STATUS_KEY = 'party_setting_recommendation_status'
RECOMMENDATION_OPTION_KEYS = {
    True: 'party_recommendation_open',
    False: 'party_recommendation_close',
}
RECOMMENDATION_SHEET_KEY = 'party_recommendation_sheet'
PARTY_SETTING_CLOSE_KEY = 'party_setting_close'
PARTY_SETTING_TITLE_KEY = 'party_setting_title'
PARTY_SETTING_CONTAINER_KEY = 'party_setting_container'

DEFAULT_MAX_SWIPES = 5

# 面板是 ScrollView：翻页找状态项的那一滑还带着惯性时，状态行会继续往上飘，
# 这时候点下去会被滚动容器吃掉 —— 弹窗不开，选项也就永远找不到。
# 所以点之前先等行停稳，点完再确认弹窗真的开了，没开就再点一次。
SETTLE_POLL_SECONDS = 0.4
SETTLE_TIMEOUT_SECONDS = 3.0
STATUS_CLICK_ATTEMPTS = 3
SHEET_OPEN_TIMEOUT_SECONDS = 3.0
SHEET_CLOSE_TIMEOUT_SECONDS = 5.0


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

    @abstractmethod
    def dismiss_option_sheet(self) -> bool:
        """二级选项弹窗开着时按掉它；没开着返回 False。"""


class SoulPartySettingsDriver(PartySettingsDriverPort):
    """驱动真实 Soul App 派对设置面板的生产适配器。"""

    def __init__(self, handler):
        self._handler = handler

    def is_open(self) -> bool:
        element = self._handler.element_finder.try_find_element(
            PARTY_SETTING_TITLE_KEY, log=False
        )
        return bool(element and getattr(element, 'is_displayed', lambda: True)())

    def is_option_sheet_open(self) -> bool:
        """二级选项弹窗（RN 页面）当前是否开着。"""
        element = self._handler.element_finder.try_find_element(
            RECOMMENDATION_SHEET_KEY, log=False
        )
        return bool(element and getattr(element, 'is_displayed', lambda: True)())

    def open(self) -> bool:
        if self.is_open():
            return True
        # 上一次没点成留下的弹窗会把设置按钮整个盖住，先按掉它。
        self.dismiss_option_sheet()
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
        self.dismiss_option_sheet()
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

    def dismiss_option_sheet(self) -> bool:
        """按掉二级选项弹窗。

        弹窗是 RN 页面：它开着的时候原生设置面板整块被替换，「派对设置」标题不在
        树里 —— 不按掉它，设置按钮点不动、面板也关不掉，下一条命令就只能吃闭门羹。
        """
        if not self.is_option_sheet_open():
            return False
        self.press_back()
        return True

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
        )
        return element is not None

    def click_recommendation_status(self) -> bool:
        """点推荐状态那一行，把二级弹窗叫出来。

        翻页找状态项的那一滑还带着惯性时，状态行会继续往上飘，这时候点下去
        会被 ScrollView 吃掉 —— 弹窗不开，选项也就永远找不到（真机上就是这个
        症状：`:recommend off` 报「未找到推荐选项」）。
        所以点之前等行停稳，点完确认弹窗真的开了，没开就再点一次。
        """
        for _ in range(STATUS_CLICK_ATTEMPTS):
            element = self._handler.element_finder.wait_for_element_clickable(
                RECOMMENDATION_STATUS_KEY, timeout=5
            )
            if not element:
                return False
            self._wait_until_row_stops_moving(element)
            element.click()
            sheet = self._handler.element_finder.wait_for_element(
                RECOMMENDATION_SHEET_KEY, timeout=SHEET_OPEN_TIMEOUT_SECONDS
            )
            if sheet:
                return True
        return False

    def click_recommendation_option(self, enabled: bool) -> bool:
        key = RECOMMENDATION_OPTION_KEYS[bool(enabled)]
        element = self._handler.element_finder.wait_for_element_clickable(
            key, timeout=5
        )
        if not element:
            return False
        element.click()
        # 选项点完弹窗自己收起；等它收完，面板那一行才会露出新的状态文案。
        self._handler.element_finder.wait_for_element_disappear(
            RECOMMENDATION_SHEET_KEY, timeout=SHEET_CLOSE_TIMEOUT_SECONDS
        )
        return True

    def _wait_until_row_stops_moving(self, element) -> None:
        """等状态行停稳。

        面板还在惯性滑动时行会一直飘，这会儿点下去只会被滚动容器吃掉。
        连续两次读到同一个位置就算停稳。
        """
        deadline = time.time() + SETTLE_TIMEOUT_SECONDS
        try:
            previous = element.rect
        except Exception:
            return
        while time.time() < deadline:
            time.sleep(SETTLE_POLL_SECONDS)
            try:
                current = element.rect
            except Exception:
                return
            if current == previous:
                return
            previous = current
