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
    # 其他抽屉式弹窗元素按需加入。注意：在线用户抽屉（'online_drawer'）**不要**加
    # 回来 —— 它的生命周期归 OnlineDrawerManager 管，事件层去「顺手关掉」它会和会话
    # 的归属规则打架（会话正在用它开着的抽屉读名单，见 online_drawer/manager.py）。
    # 其他 key 原来就注释在下面，需要时照旧打开。
]

from ushareiplay.core.base_event import BaseEvent


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
            from ushareiplay.managers.recovery_manager import RecoveryManager
            recovery_manager = RecoveryManager.instance()
            return recovery_manager.close_drawer(key)

        except Exception as e:
            self.logger.error(f"Error processing drawer element {key}: {str(e)}")
            return False
