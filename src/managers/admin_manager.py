from ..handlers.soul_handler import SoulHandler
from ..dal import UserDAO
from ..models import User
from ..core.singleton import Singleton
import logging

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
        # Check relation tag
        if not message_info.relation_tag:
            return {
                'error': 'Only friends of owner can apply administrators',
                'user': message_info.nickname,
            }

        # Check if user is a close friend and level >= 5
        user = await UserDAO.get_or_create(message_info.nickname)
        if not user or user.level < 5:
            return {
                'error': 'Only close friends with level >= 5 can apply administrators',
                'user': message_info.nickname,
            }


        # Click avatar to open profile
        avatar = message_info.avatar_element
        if avatar:
            try:
                avatar.click()
                self.logger.info("Clicked sender avatar")
            except Exception as e:
                self.logger.error('Avatar element is unavailable')
                return {
                    'error': 'Avatar element is unavailable',
                    'user': message_info.nickname,
                }
        else:
            return {
                'error': 'Avatar element not found',
                'user': message_info.nickname,
            }

        # Find manager invite button
        manager_invite = self.handler.wait_for_element_clickable_plus('manager_invite')
        if not manager_invite:
            return {'error': 'Failed to find manager invite button', 'user': message_info.nickname}

        # Check current status
        current_text = manager_invite.text
        if enable:
            if current_text == "解除管理":
                self.handler.press_back()
                return {'error': '你已经是管理员了', 'user': message_info.nickname}
        else:
            if current_text == "管理邀请":
                self.handler.press_back()
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

        return {'user': message_info.nickname,
                'action': action}