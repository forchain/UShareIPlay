"""In-memory 派对设置面板驱动 —— 设置面板 UI 端口的离线替身（#456）。

真实面板这一层唯一的外部依赖是 Soul App 的屏幕，这里整块换掉：

| 真实依赖 | 替身 |
|---|---|
| 点 `party_setting_button` 打开面板 | `open()`：成功就把 `panel_open` 置上 |
| `gesture_handler.scroll_container_until_element` | `reveal_recommendation_status`：按 `visible_after_swipes` 模拟翻页 |
| 点状态项呼出二级弹窗 | `click_recommendation_status`：置 `popup_open` |
| 点「所有人」/「关闭推荐分发」 | `click_recommendation_option`：改写 `status_text` |
| 点 ivClose 关面板 | `close()`：按 `close_button_works` 决定是否走返回键兜底 |

屏幕状态由 `status_text`（那一行显示什么）、`visible_after_swipes`（翻几页才
找到）与一组 `fail_*` 开关描述。读文本本身不在这里 —— 与生产端口同一个约定，
判定读走 handler 的 element_finder。
"""

from ushareiplay.managers.room_profile.party_settings import (
    PARTY_SETTING_BUTTON_KEY,
    RECOMMENDATION_OPTION_KEYS,
    RECOMMENDATION_STATUS_KEY,
    PartySettingsDriverPort,
)

OPEN_TEXT = '所有人'
CLOSED_TEXT = '关闭推荐分发'


class InMemoryPartySettingsDriver(PartySettingsDriverPort):
    """把设置面板的开关、翻页与弹窗状态放在内存里的 UI 端口替身。

    Args:
        panel_open: 初始状态。True 表示「外层流程已经把面板打开了」。
        status_text: 推荐状态那一行当前显示的文案。
        visible_after_swipes: 需要翻几页才看到状态项。0 表示一开始就在屏幕上。
        fail_open: 点设置按钮打不开面板。
        fail_scroll: 翻页也找不到状态项。
        fail_status_click: 状态项点不动（弹窗不出现）。
        fail_option: 选项点不动（状态不变）。
        close_button_works: ivClose 能否关掉面板。False 时账户走返回键兜底。

    Attributes:
        open_attempts / opened: `open()` 的尝试次数与真正打开的次数。
        close_calls: `close()` 被调用的次数 —— 断言「谁打开谁关闭」。
        swipes: 实际翻页次数。
        swipe_limits: 每次 `reveal_recommendation_status` 收到的上限。
        clicks: 点过的 selector key，按顺序。
        option_clicks: 点过的目标状态（True/False），按顺序。
        back_presses: 返回键次数。
        popup_open: 二级选项弹窗当前是否开着。
    """

    def __init__(
        self,
        *,
        panel_open=False,
        status_text=OPEN_TEXT,
        visible_after_swipes=0,
        fail_open=False,
        fail_scroll=False,
        fail_status_click=False,
        fail_option=False,
        close_button_works=True,
    ):
        self.panel_open = bool(panel_open)
        self.status_text = status_text
        self.visible_after_swipes = max(0, int(visible_after_swipes))
        self.fail_open = fail_open
        self.fail_scroll = fail_scroll
        self.fail_status_click = fail_status_click
        self.fail_option = fail_option
        self.close_button_works = close_button_works

        self.status_visible = self.visible_after_swipes == 0
        self.popup_open = False

        self.open_attempts = 0
        self.opened = 0
        self.close_calls = 0
        self.swipes = 0
        self.swipe_limits = []
        self.clicks = []
        self.option_clicks = []
        self.back_presses = 0

    # ------------------------------------------------------------------
    # 面板开关
    # ------------------------------------------------------------------

    def is_open(self) -> bool:
        return self.panel_open

    def open(self) -> bool:
        self.open_attempts += 1
        if self.panel_open:
            return True
        if self.fail_open:
            return False
        self.panel_open = True
        self.opened += 1
        self.status_visible = self.visible_after_swipes == 0
        return True

    def close(self) -> None:
        self.close_calls += 1
        if not self.panel_open:
            return
        self.popup_open = False
        if self.close_button_works:
            self.panel_open = False
            return
        # ivClose 没生效：生产适配器会按返回键兜底。
        self.back_presses += 1
        self.panel_open = False

    def press_back(self) -> None:
        self.back_presses += 1
        self.popup_open = False
        self.panel_open = False

    def dismiss_option_sheet(self) -> bool:
        if not self.popup_open:
            return False
        self.back_presses += 1
        self.popup_open = False
        return True

    # ------------------------------------------------------------------
    # 推荐状态
    # ------------------------------------------------------------------

    def reveal_recommendation_status(self, *, max_swipes: int = 5) -> bool:
        self.swipe_limits.append(max_swipes)
        if self.status_visible:
            return True
        if self.fail_scroll:
            return False

        for _ in range(max(0, max_swipes)):
            self.swipes += 1
            if self.swipes >= self.visible_after_swipes:
                self.status_visible = True
                return True
        return False

    def click_recommendation_status(self) -> bool:
        self.clicks.append(RECOMMENDATION_STATUS_KEY)
        if not self.status_visible or self.fail_status_click:
            return False
        self.popup_open = True
        return True

    def click_recommendation_option(self, enabled: bool) -> bool:
        option_key = RECOMMENDATION_OPTION_KEYS[bool(enabled)]
        self.clicks.append(option_key)
        self.option_clicks.append(bool(enabled))
        if not self.popup_open or self.fail_option:
            return False

        self.status_text = OPEN_TEXT if enabled else CLOSED_TEXT
        self.popup_open = False
        return True

    # ------------------------------------------------------------------
    # 测试辅助
    # ------------------------------------------------------------------

    def click_setting_button(self) -> bool:
        """记录一次「点设置按钮」；真实动作由 `open()` 代表。"""
        self.clicks.append(PARTY_SETTING_BUTTON_KEY)
        return self.open()
