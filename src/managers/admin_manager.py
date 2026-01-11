from ..core.singleton import Singleton
from ..dal import UserDAO


class AdminManager(Singleton):
    def __init__(self):
        # 延迟初始化 handler，避免循环依赖
        self._handler = None
        self._logger = None

    @property
    def handler(self):
        """延迟获取 SoulHandler 实例"""
        if self._handler is None:
            from ..handlers.soul_handler import SoulHandler
            self._handler = SoulHandler.instance()
        return self._handler

    @property
    def logger(self):
        """延迟获取 logger 实例"""
        if self._logger is None:
            self._logger = self.handler.logger
        return self._logger

    async def manage_admin(self, message_info, enable: bool):
        """
        Manage administrator status
        Args:
            message_info: MessageInfo object containing user information
            enable: bool, True to enable admin, False to disable
        Returns:
            dict: Result of operation with user info
        """
        # Check if user level >= 3
        user = await UserDAO.get_or_create(message_info.nickname)
        if user.level < 3:
            return {
                'error': 'Only close friends can apply administrators',
                'user': message_info.nickname,
            }

        # Check if user level >= 5 for admin operations
        if user.level < 5:
            return {
                'error': 'Only close friends with level >= 5 can apply administrators',
                'user': message_info.nickname,
            }

        # Open online users list to find and click the user
        user_count_elem = self.handler.wait_for_element_plus('user_count', log=False)
        if not user_count_elem:
            return {
                'error': 'Failed to open online users list',
                'user': message_info.nickname,
            }
        
        user_count_elem.click()
        self.logger.info("Opened online users list")
        
        # Wait for online users container
        online_container = self.handler.wait_for_element_plus('online_users')
        if not online_container:
            return {
                'error': 'Failed to find online users container',
                'user': message_info.nickname,
            }
        
        # Find the user in online users list
        key, user_elem, _ = self.handler.scroll_container_until_element(
            'online_user', 
            'online_users', 
            'up', 
            'text', 
            message_info.nickname
        )
        
        if not user_elem:
            # Close online users list
            bottom_drawer = self.handler.wait_for_element_plus('bottom_drawer')
            if bottom_drawer:
                self.handler.click_element_at(bottom_drawer, 0.5, -0.1)
            return {
                'error': 'User not found in online users list',
                'user': message_info.nickname,
            }
        
        # Click the user element to open profile
        try:
            user_elem.click()
            self.logger.info(f"Clicked user element for {message_info.nickname}")
        except Exception as e:
            self.logger.error(f'Failed to click user element: {str(e)}')
            # Close online users list
            bottom_drawer = self.handler.wait_for_element_plus('bottom_drawer')
            if bottom_drawer:
                self.handler.click_element_at(bottom_drawer, 0.5, -0.1)
            return {
                'error': 'Failed to click user element',
                'user': message_info.nickname,
            }

        # Find manager invite button
        manager_invite = self.handler.wait_for_element_clickable_plus('manager_invite')
        if not manager_invite:
            return {'error': 'Failed to find manager invite button', 'user': message_info.nickname}

        # 关闭在线用户抽屉
        from ..managers.recovery_manager import RecoveryManager
        recovery_manager = RecoveryManager.instance()
        # Check current status
        current_text = manager_invite.text
        if enable:
            if current_text == "解除管理":
                self.handler.press_back()
                recovery_manager.close_drawer('online_drawer')
                return {'error': '你已经是管理员了', 'user': message_info.nickname}
        else:
            if current_text == "管理邀请":
                self.handler.press_back()
                recovery_manager.close_drawer('online_drawer')
                return {'error': '你还不是管理员', 'user': message_info.nickname}

        # Click manager invite button
        manager_invite.click()
        self.logger.info("Clicked manager invite button")

        # Click confirm button
        if enable:
            confirm_button = self.handler.wait_for_element_clickable_plus('confirm_invite')
            action = "Invited"
        else:
            confirm_button = self.handler.wait_for_element_clickable_plus('confirm_dismiss')
            action = "Dismissed"

        if not confirm_button:
            self.logger.error(f"Failed to find {action} confirmation button by {message_info.nickname}")
            return {'error': f'Failed to find {action} confirmation button', 'user': message_info.nickname}

        confirm_button.click()
        self.logger.info(f"Clicked {action} confirmation button")

        # 关闭在线用户抽屉
        from ..managers.recovery_manager import RecoveryManager
        recovery_manager = RecoveryManager.instance()
        recovery_manager.close_drawer('online_drawer')

        return {'user': message_info.nickname,
                'action': action}
