import logging
from ushareiplay.core.singleton import Singleton

#: 抽屉本体 key → 该抽屉自带的关闭按钮 key（按优先级尝试）。
#:
#: 新版 Soul 的在线用户列表不再渲染 touch_close 遮罩，只有右上角的关闭按钮
#: ivClose。仍按"点窗口上沿"关的话，会先在遮罩上白等 10 秒、再在 room_id 上白等
#: 10 秒，最后只能 press_back 兜底 —— 一次关闭空转 20 秒还伴随两条告警。
#: 房间信息抽屉已有同样处理，见 room_profile/driver.py 的 ROOM_INFO_CLOSE_KEYS。
DRAWER_CLOSE_BUTTONS = {
    "online_drawer": ("online_users_close", "close_button"),
}


class RecoveryManager(Singleton):
    """异常检测和恢复管理器，用于检测和处理各种异常情况"""

    def __init__(self, handler=None):
        self.handler = handler
        self.logger = getattr(handler, "logger", None) or logging.getLogger("RecoveryManager")

    def close_drawer(
            self, drawer_key: str, wait_element: str = "room_id", max_attempts: int = 2
    ) -> bool:
        """
        关闭抽屉式弹窗

        优先使用抽屉自带的关闭按钮（见 DRAWER_CLOSE_BUTTONS）；没有关闭按钮的
        抽屉才退回「点击窗口上沿遮罩」的旧方式。

        Args:
            drawer_key: 抽屉元素的 key
            wait_element: 等待出现的界面元素，默认是 "room_id"
            max_attempts: 最多点击关闭次数，默认两次
            
        Returns:
            bool: 如果成功关闭返回 True，否则 False
        """
        try:
            if self._close_via_close_button(drawer_key):
                return True

            for attempt in range(1, max_attempts + 1):
                # 使用 wait_for 获取可点击的元素
                element = self.handler.element_finder.wait_for_element_clickable(drawer_key)
                if not element:
                    if not self._is_drawer_visible(drawer_key):
                        return self._confirm_drawer_closed(drawer_key, wait_element)
                    self.logger.warning(
                        f"Drawer element {drawer_key} found in page_source but not clickable"
                    )
                    return False

                # 点击抽屉上方区域来关闭
                click_success = self.handler.gesture_handler.click_element_at(
                    element, x_ratio=0.3, y_ratio=0, y_offset=-200
                )
                if not click_success:
                    self.logger.warning(f"Failed to click drawer: {drawer_key}")
                    return False

                # 使用 Appium/Selenium SDK 的 WebDriverWait + EC.invisibility 动态等待抽屉消失
                # poll_frequency=0.1s：抽屉一旦消失立即可返回，无需主观 sleep 固化延迟
                drawer_disappeared = False
                if hasattr(self.handler.element_finder, 'wait_for_element_disappear'):
                    drawer_disappeared = self.handler.element_finder.wait_for_element_disappear(
                        drawer_key, timeout=3.0, poll_frequency=0.1
                    )

                if drawer_disappeared or not self._is_drawer_visible(drawer_key):
                    return self._confirm_drawer_closed(drawer_key, wait_element)

                self.logger.warning(
                    f"Drawer {drawer_key} still visible after close attempt "
                    f"{attempt}/{max_attempts}"
                )

            self.logger.warning(f"Failed to close drawer after {max_attempts} attempts: {drawer_key}")
            return False

        except Exception as e:
            self.logger.error(f"Error closing drawer {drawer_key}: {str(e)}")
            return False

    def _close_via_close_button(self, drawer_key: str) -> bool:
        """优先点击抽屉自带的关闭按钮关闭，不点击窗口上沿。

        关闭按钮找不到时返回 False，交给调用方退回「点遮罩」的旧方式 —— 遮罩式
        抽屉（输入框等）本身就没有关闭按钮，这条路径不能因此失效。

        Args:
            drawer_key: 抽屉元素的 key

        Returns:
            bool: 找到并点击了关闭按钮返回 True，否则 False
        """
        close_keys = DRAWER_CLOSE_BUTTONS.get(drawer_key)
        if not close_keys:
            return False

        finder = self.handler.element_finder
        for key in close_keys:
            close_btn = None
            try:
                # 短超时：关闭按钮在弹窗打开时立即存在，等满默认 10 秒只会拖慢关窗
                close_btn = finder.wait_for_element_clickable(key, timeout=1.5)
                if not close_btn:
                    close_btn = finder.try_find_element(key, log=False)
            except Exception as e:
                self.logger.debug(f"Error looking for close button {key}: {e}")
                continue

            if not close_btn:
                continue

            try:
                close_btn.click()
                self.logger.info(f"Closed drawer {drawer_key} via close button: {key}")
                if hasattr(finder, 'wait_for_element_disappear'):
                    finder.wait_for_element_disappear(key, timeout=3.0, poll_frequency=0.1)
                return True
            except Exception as e:
                self.logger.warning(
                    f"Failed to close drawer {drawer_key} via close button {key}: {e}"
                )
                return False

        return False

    def _is_drawer_visible(self, drawer_key: str) -> bool:
        element = self.handler.element_finder.try_find_element(drawer_key, log=False)
        if not element:
            return False
        try:
            return element.is_displayed()
        except Exception:
            return True

    def _confirm_drawer_closed(self, drawer_key: str, wait_element: str) -> bool:
        # 等待指定元素出现，确认界面已恢复正常；成功条件仍以抽屉消失为准。
        target_element = self.handler.element_finder.wait_for_element(wait_element)
        if target_element:
            self.logger.info(f"Closed drawer: {drawer_key}, {wait_element} confirmed")
        else:
            self.handler.key_actions.press_back()
            self.logger.warning(f"Closed drawer: {drawer_key}, but {wait_element} not found")
        return not self._is_drawer_visible(drawer_key)

    def is_normal_state(self) -> bool:
        """
        检测是否处于正常状态
        最快速的方法就是检测输入框是否存在
        """
        try:
            # 从 InfoManager 获取房间ID
            from ushareiplay.managers.info_manager import InfoManager
            info_manager = InfoManager.instance()
            room_id_text = info_manager.room_id

            if room_id_text is None:
                return False

            if not room_id_text.startswith("FM"):
                self.logger.warning(f"Room ID:{room_id_text} does not start with FM, skip")
                return True

            party_id = self.handler.config.get('default_party_id')
            return room_id_text == party_id
        except Exception as e:
            self.logger.debug(f"检测正常状态时出错: {str(e)}")
            return False
