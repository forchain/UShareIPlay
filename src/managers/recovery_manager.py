from ..core.singleton import Singleton


class RecoveryManager(Singleton):
    """异常检测和恢复管理器，用于检测和处理各种异常情况"""

    def __init__(self):
        # 获取 SoulHandler 单例实例
        from ..handlers.soul_handler import SoulHandler
        self.handler = SoulHandler.instance()
        self.logger = self.handler.logger

    def close_drawer(self, drawer_key: str, wait_element: str = "room_id") -> bool:
        """
        关闭抽屉式弹窗
        
        Args:
            drawer_key: 抽屉元素的 key
            wait_element: 等待出现的界面元素，默认是 "room_id"
            
        Returns:
            bool: 如果成功关闭返回 True，否则 False
        """
        try:
            # 使用 wait_for 获取可点击的元素
            element = self.handler.wait_for_element_clickable_plus(drawer_key)
            if not element:
                self.logger.warning(
                    f"Drawer element {drawer_key} found in page_source but not clickable"
                )
                return False

            # 点击抽屉上方区域来关闭
            click_success = self.handler.click_element_at(
                element, x_ratio=0.3, y_ratio=0, y_offset=-200
            )
            if not click_success:
                self.logger.warning(f"Failed to click drawer: {drawer_key}")
                return False

            # 等待指定元素出现，确认界面已恢复正常（弹窗已关闭）
            target_element = self.handler.wait_for_element_plus(wait_element)
            if target_element:
                self.logger.info(f"Closed drawer: {drawer_key}, {wait_element} confirmed")
            else:
                self.handler.press_back()
                self.logger.warning(f"Closed drawer: {drawer_key}, but {wait_element} not found")
            return True

        except Exception as e:
            self.logger.error(f"Error closing drawer {drawer_key}: {str(e)}")
            return False

    def is_normal_state(self) -> bool:
        """
        检测是否处于正常状态
        最快速的方法就是检测输入框是否存在
        """
        try:
            # 从 InfoManager 获取房间ID
            from .info_manager import InfoManager
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
