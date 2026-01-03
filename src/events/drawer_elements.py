"""
抽屉式弹窗事件 - 处理各种抽屉式弹窗界面

监控以下元素：
- input_drawer: 输入抽屉
- 其他抽屉式弹窗元素

当检测到这些元素时，自动点击特定位置关闭，避免界面被遮挡。
参考 handle_drawer_elements 的实现逻辑。
"""

__event__ = "DrawerElementsEvent"
__elements__ = [
    "input_drawer",
    # 可以根据需要添加其他抽屉式弹窗元素
    # 'party_restore_drawer',
    # 'bottom_drawer_1',
    # 'online_drawer',
]

from ..core.base_event import BaseEvent


class DrawerElementsEvent(BaseEvent):
    """抽屉式弹窗事件处理器"""

    def handle(self, key: str, element_wrapper):
        """
        处理抽屉式弹窗事件

        找到控件并点击特定位置关闭，使用 click_element_at 点击抽屉上方区域

        Args:
            key: 触发事件的元素 key
            element_wrapper: ElementWrapper 实例，包装了抽屉元素

        Returns:
            bool: 如果点击成功返回 True，否则 False
        """
        try:
            # 使用 wait_for 获取可点击的元素（因为 page_source 中已确认存在）
            element = self.handler.wait_for_element_clickable_plus(key)
            if not element:
                self.logger.warning(
                    f"Drawer element {key} found in page_source but not clickable"
                )
                return False

            # 点击抽屉上方区域来关闭（参考 handle_drawer_elements 的实现）
            click_success = self.handler.click_element_at(
                element, x_ratio=0.3, y_ratio=0, y_offset=-200
            )
            if not click_success:
                self.logger.warning(f"Failed to click drawer: {key}")
                return False

            # 等待 room_id 元素出现，确认界面已恢复正常（弹窗已关闭）
            room_id_element = self.handler.wait_for_element_plus("room_id")
            if room_id_element:
                self.logger.info(f"Closed drawer: {key}, room_id confirmed")
            else:
                self.handler.press_back()
                self.logger.warning(f"Closed drawer: {key}, but room_id not found")
            return True

        except Exception as e:
            self.logger.error(f"Error processing drawer element {key}: {str(e)}")
            return False
