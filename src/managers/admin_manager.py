from ..core.singleton import Singleton


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

    async def manage_admin(self, enable: bool, target_nickname: str):
        """
        管理管理员状态：在在线列表中打开目标用户资料页，再执行邀请/解除管理。

        Args:
            enable: True 邀请为管理员，False 解除管理员
            target_nickname: 被操作的用户昵称（在在线列表中查找并打开其资料页）

        Returns:
            dict: 成功含 user/action，失败含 error/user
        """
        from ..managers.user_manager import UserManager
        user_manager = UserManager.instance()
        open_result = user_manager.open_user_profile_from_online_list(target_nickname)
        if 'error' in open_result:
            return open_result

        manager_invite = self.handler.wait_for_element_clickable_plus('manager_invite')
        if not manager_invite:
            return {'error': 'Failed to find manager invite button', 'user': target_nickname}

        from ..managers.recovery_manager import RecoveryManager
        recovery_manager = RecoveryManager.instance()
        current_text = manager_invite.text
        if enable:
            if current_text == "解除管理":
                self.handler.press_back()
                recovery_manager.close_drawer('online_drawer')
                return {'error': '你已经是管理员了', 'user': target_nickname}
        else:
            if current_text == "管理邀请":
                self.handler.press_back()
                recovery_manager.close_drawer('online_drawer')
                return {'error': '你还不是管理员', 'user': target_nickname}

        manager_invite.click()
        self.logger.info("Clicked manager invite button")

        if enable:
            confirm_button = self.handler.wait_for_element_clickable_plus('confirm_invite')
            action = "Invited"
        else:
            confirm_button = self.handler.wait_for_element_clickable_plus('confirm_dismiss')
            action = "Dismissed"

        if not confirm_button:
            self.logger.error(f"Failed to find {action} confirmation button for {target_nickname}")
            return {'error': f'Failed to find {action} confirmation button', 'user': target_nickname}

        confirm_button.click()
        self.logger.info(f"Clicked {action} confirmation button")

        recovery_manager.close_drawer('online_drawer')

        return {'user': target_nickname, 'action': action}
