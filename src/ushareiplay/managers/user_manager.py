"""用户管理器：在在线列表中查找用户并打开其信息页等"""

from ushareiplay.core.singleton import Singleton

YELLOW_DUCK_NAME = "小黄鸭"  # 礼物列表兜底礼物，固定为列表首位，点击即送无需点赠送


class UserManager(Singleton):
    """在在线用户列表中查找指定用户并打开其资料页"""

    def __init__(self):
        self._handler = None
        self._logger = None

    @property
    def handler(self):
        if self._handler is None:
            from ushareiplay.handlers.soul_handler import SoulHandler
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
        user_count_elem = self.handler.wait_for_element('user_count')
        if not user_count_elem:
            self.logger.warning("未找到在线用户人数")
            return {
                'error': 'Failed to open online users list',
                'user': nickname,
            }

        user_count_elem.click()
        self.logger.info("Opened online users list")

        online_container = self.handler.wait_for_element('online_users')
        if not online_container:
            self.logger.warning("未找到在线用户列表")
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
            self.logger.warning(f"未找到用户 {nickname}")
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

        send_gift_btn = self.handler.wait_for_element_clickable('send_gift')
        if not send_gift_btn:
            self.logger.info("未找到送礼物按钮")
            return {'error': '未找到送礼物入口'}

        self.handler.click_element_at(send_gift_btn)
        self.logger.info("已点击送礼物")

        found_key, found_element = self.handler.wait_for_any_element(['give_gift', 'use_item'])
        if not found_element:
            self.logger.info("送礼界面未出现或超时")
            return {'error': '送礼界面未出现'}

        luck_item = self.handler.try_find_element('luck_item')
        if not luck_item:
            self.logger.warning('Failed to find gift')
            self.handler.press_back()
            return {'error': 'Failed to find gift'}

        gift_name = luck_item.text
        if (parts := gift_name.split('x')) and len(parts) > 1:
            gift_name = parts[0]

        soul_power = self.handler.try_find_element('soul_power')
        soul_points = soul_power.text if soul_power else '0'

        # 礼物列表兜底：背包为空时展示礼物列表，小黄鸭不会默认选中，直接点击即送出，无需点"赠送"
        if gift_name.strip() == YELLOW_DUCK_NAME:
            self.handler.click_element_at(luck_item)
            self.logger.info(f"已点击{YELLOW_DUCK_NAME}，送出后关闭在线列表")
            self._close_online_drawer()
            return {'success': f'{gift_name} 送你啦'}

        self.handler.click_element_at(found_element)
        self.logger.info(f"已点击赠送, gift_name: {gift_name} soul_points: {soul_points}")

        if found_key == 'use_item':
            confirm_use = self.handler.wait_for_element('confirm_use')
            if not confirm_use:
                self.handler.press_back()
                self.logger.warning("未找到确认使用按钮")
                return {'error': '未找到确认使用按钮'}

            confirm_use.click()
            self.logger.info("已点击确认使用")

        self._close_online_drawer()
        return {'success': f'{gift_name} 送你啦'}

    def send_private_message_to_user(self, nickname: str, message: str) -> bool:
        """
        向指定用户发送私聊消息。

        流程：
        1. 在线列表打开用户信息页
        2. 点击头像进入主页
        3. 点击私聊按钮进入私聊页
        4. 输入并发送消息
        5. 返回聊天室（优先 lottie_in_party，兜底 floating_entry）

        任意一步失败返回 False，不抛异常。
        """
        try:
            self.handler.switch_to_app()
            open_result = self.open_user_profile_from_online_list(nickname)
            if 'error' in open_result:
                self.logger.warning(f"打开用户资料页失败: {nickname}, error={open_result['error']}")
                return False

            avatar = self.handler.wait_for_element_clickable(
                'sender_avatar',
                timeout=5,
            )
            if not avatar:
                self.logger.warning(f"未找到头像入口: {nickname}")
                return False
            if not self.handler.click_element_at(avatar, y_ratio=0.7):
                self.logger.warning(f"点击头像入口失败: {nickname}")
                return False

            private_chat_btn = self.handler.wait_for_element_clickable(
                'private_chat_button',
                timeout=5,
            )
            if not private_chat_btn:
                self.logger.warning(f"未找到私聊按钮: {nickname}")
                return False
            private_chat_btn.click()

            input_box = self.handler.wait_for_element_clickable(
                'private_message_input',
                timeout=5,
            )
            if not input_box:
                self.logger.warning(f"未找到私聊输入框: {nickname}")
                return False
            input_box.send_keys(message)

            send_button = self.handler.wait_for_element_clickable(
                'private_message_send',
                timeout=5,
            )
            if not send_button:
                self.logger.warning(f"未找到私聊发送按钮: {nickname}")
                return False
            send_button.click()

            return self._return_to_room_after_private_chat(nickname)
        except Exception as e:
            self.logger.error(f"私聊发送失败: {nickname}, error={e}")
            return False

    def _return_to_room_after_private_chat(self, nickname: str) -> bool:
        """私聊发送后返回聊天室。"""
        try:
            _key, entry = self.handler.wait_for_any_element(
                ['private_room_entry', 'floating_entry', 'item_left_back'],
                timeout=3,
            )
            if entry:
                entry.click()
                if _key == 'item_left_back':
                    titlebar_back = self.handler.wait_for_element_clickable(
                        'titlebar_back_ivbtn',
                        timeout=3,
                    )
                    if titlebar_back:
                        titlebar_back.click()
                        return True

                    self.logger.warning(f"点击左侧返回后未找到用户主页返回按钮: {nickname}")
                    return False

                return True

            self.logger.warning(f"未找到返回聊天室入口: {nickname}")
            return False
        except Exception as e:
            self.logger.error(f"返回聊天室失败: {nickname}, error={e}")
            return False

    def _close_online_drawer(self):
        """关闭在线用户抽屉"""
        recovery_manager = self.handler.controller.recovery_manager
        recovery_manager.close_drawer('online_drawer')
