"""
星球标签事件 - 处理首页（星球标签）检测

当检测到 planet_tab 元素时，说明当前在首页（非派对页面），
直接调用 RecoveryManager 的 handle_join_party 方法进入派对。
"""

from ..core.base_event import BaseEvent


class PlanetTabEvent(BaseEvent):
    """星球标签事件处理器"""

    async def handle(self, key: str, element_wrapper):
        """
        处理星球标签事件

        检测到 planet_tab 时，调用 RecoveryManager 的 handle_join_party 方法

        Args:
            key: 触发事件的元素 key，这里是 'planet_tab'
            element_wrapper: ElementWrapper 实例，包装了星球标签元素

        Returns:
            bool: 如果成功处理返回 True，否则 False
        """
        try:
            # 调用 RecoveryManager 的 handle_join_party 方法
            from ..managers.recovery_manager import RecoveryManager
            recovery_manager = RecoveryManager.instance()
            result = recovery_manager.handle_join_party()

            if result:
                self.logger.info("Successfully handled planet_tab event via handle_join_party")
                return True
            else:
                self.logger.debug("handle_join_party returned False (no action needed)")
                return False

        except Exception as e:
            self.logger.error(f"Error processing planet_tab event: {str(e)}")
            return False

