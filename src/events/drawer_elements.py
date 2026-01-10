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

    async def handle(self, key: str, element_wrapper):
        """
        处理抽屉式弹窗事件

        使用 RecoveryManager 的 close_drawer 方法关闭抽屉

        Args:
            key: 触发事件的元素 key
            element_wrapper: ElementWrapper 实例，包装了抽屉元素

        Returns:
            bool: 如果点击成功返回 True，否则 False
        """
        try:
            from ..managers.recovery_manager import RecoveryManager
            recovery_manager = RecoveryManager.instance()
            return recovery_manager.close_drawer(key)

        except Exception as e:
            self.logger.error(f"Error processing drawer element {key}: {str(e)}")
            return False
