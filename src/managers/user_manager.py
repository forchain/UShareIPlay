"""用户管理器：在在线列表中查找用户并打开其信息页等"""
from ..core.singleton import Singleton


class UserManager(Singleton):
    """在在线用户列表中查找指定用户并打开其资料页"""

    def __init__(self):
        self._handler = None
        self._logger = None

    @property
    def handler(self):
        if self._handler is None:
            from ..handlers.soul_handler import SoulHandler
            self._handler = SoulHandler.instance()
        return self._handler

    @property
    def logger(self):
        if self._logger is None:
            self._logger = self.handler.logger
        return self._logger

    def open_user_profile_from_online_list(self, nickname: str):
        """
        在在线用户列表中查找指定用户并打开其资料页。

        Args:
            nickname: 要查找的用户昵称。

        Returns:
            dict: 成功时返回 {}；失败时返回 {'error': str, 'user': nickname}。
        """
        user_count_elem = self.handler.wait_for_element_plus('user_count')
        if not user_count_elem:
            return {
                'error': 'Failed to open online users list',
                'user': nickname,
            }

        user_count_elem.click()
        self.logger.info("Opened online users list")

        online_container = self.handler.wait_for_element_plus('online_users')
        if not online_container:
            return {
                'error': 'Failed to find online users container',
                'user': nickname,
            }

        key, user_elem, _ = self.handler.scroll_container_until_element(
            'online_user',
            'online_users',
            'up',
            'text',
            nickname,
        )

        if not user_elem:
            self._close_online_drawer()
            return {
                'error': 'User not found in online users list',
                'user': nickname,
            }

        try:
            user_elem.click()
            self.logger.info(f"Clicked user element for {nickname}")
            return {}
        except Exception as e:
            self.logger.error(f"Failed to click user element: {e}")
            self._close_online_drawer()
            return {
                'error': 'Failed to click user element',
                'user': nickname,
            }

    def send_gift(self, nickname: str):
        """
        执行送礼流程：先在在线列表中打开目标用户资料页，再点击送礼物并执行赠送/使用/背包逻辑。

        Args:
            nickname: 要送礼的目标用户昵称。

        Returns:
            dict: 成功返回 {'success': str}；失败返回 {'error': str} 或 {'error': str, 'user': nickname}。
        """
        open_result = self.open_user_profile_from_online_list(nickname)
        if 'error' in open_result:
            return open_result

        send_gift_btn = self.handler.wait_for_element_clickable_plus('send_gift')
        if not send_gift_btn:
            self.logger.info("未找到送礼物按钮")
            return {'error': '未找到送礼物入口'}

        self.handler.click_element_at(send_gift_btn)
        self.logger.info("已点击送礼物")

        found_key, found_element = self.handler.wait_for_any_element_plus(['give_gift', 'use_item'])
        if not found_element:
            self.logger.info("送礼界面未出现或超时")
            return {'error': '送礼界面未出现'}

        recovery_manager = self.handler.controller.recovery_manager
        if found_key == 'use_item':
            self.handler.press_back()
            recovery_manager.close_drawer('online_drawer')
            self.logger.info("当前选中的是其他道具，已关闭界面")
            return {'error': '当前选中的不是礼物，请先选择礼物'}

        if found_key == 'give_gift':
            self.handler.click_element_at(found_element)
            soul_power = self.handler.try_find_element_plus('soul_power')
            if not soul_power:
                self.logger.warning('Failed to find gift')
                self.handler.press_back()

            # self.handler.press_back()
            recovery_manager.close_drawer('online_drawer')
            self.logger.info("已点击赠送，送礼完成")
            return {'success': '送礼成功'}

        return {'error': '未知界面状态'}

    def _close_online_drawer(self):
        """关闭在线用户抽屉"""
        bottom_drawer = self.handler.wait_for_element_plus('bottom_drawer')
        if bottom_drawer:
            self.handler.click_element_at(bottom_drawer, 0.5, -0.1)
