"""
关注者消息事件 - 监控关注者进入房间的消息

当检测到关注者进入房间的消息时，记录到聊天日志并点击打招呼按钮。
"""

import re
import asyncio

from ..core.base_event import BaseEvent


class FollowerMessageEvent(BaseEvent):
    """关注者消息事件处理器"""

    # 类变量，维护上一次的 follower_message，避免重复处理
    last_follower_message = None

    def _parse_nickname(self, message_text: str) -> str:
        """
        从 follower_message 文本中解析用户名
        
        支持两种格式：
        1. "你关注的Outlier进入房间啦，打个招呼吧～" - 解析"你关注的"和"进入房间啦"之间的名字
        2. "你的兄弟 Outlier进来啦～" - 解析"你的XX "（XX是两位字符，后面有空格）和"进来啦"之间的名字
        
        Args:
            message_text: follower_message 文本
            
        Returns:
            str: 解析出的用户名，如果解析失败返回 None
        """
        # 格式1: 你关注的XXX进入房间啦
        match = re.search(r'你关注的(.+?)进入房间啦', message_text)
        if match:
            return match.group(1).strip()
        
        # 格式2: 你的XX XXX进来啦（XX是两位字符，后面有空格）
        match = re.search(r'你的.{2} (.+?)进来啦', message_text)
        if match:
            return match.group(1).strip()
        
        return None

    def handle(self, key: str, element_wrapper):
        """
        处理关注者消息事件
        
        如果 follower_message 更新了，在聊天日志里记录，解析用户名并创建用户记录，然后点击 greet_follower
        
        Args:
            key: 触发事件的元素 key，这里是 'follower_message'
            element_wrapper: ElementWrapper 实例，包装了关注者消息元素
            
        Returns:
            bool: 默认返回 False，不中断后续处理
        """
        try:
            # 获取消息文本
            message_text = element_wrapper.text
            if not message_text:
                return False

            # 检查消息是否更新
            if self.last_follower_message == message_text:
                return False

            # 更新 last_follower_message
            self.last_follower_message = message_text

            # 记录到聊天日志
            from ..managers.message_manager import get_chat_logger
            chat_logger = get_chat_logger(self.handler.config)
            chat_logger.critical(message_text)

            # 解析用户名
            nickname = self._parse_nickname(message_text)
            if nickname:
                # 创建用户记录（异步操作）
                try:
                    from ..dal.user_dao import UserDAO
                    # 在事件循环中创建任务
                    loop = asyncio.get_event_loop()
                    loop.create_task(UserDAO.get_or_create(nickname))
                    self.logger.info(f"Creating user record for: {nickname}")
                except Exception as e:
                    self.logger.error(f"Error creating user record: {str(e)}")
            else:
                self.logger.warning(f"Failed to parse nickname from message: {message_text}")

            # 等待并点击打招呼按钮
            greet_follower = self.handler.try_find_element_plus('greet_follower')
            if not greet_follower:
                self.logger.warning("Failed to find greet button")
                return False

            greet_follower.click()
            self.logger.info("Clicked greet button")

            # 等待并点击发送按钮
            send_button = self.handler.wait_for_element_clickable_plus('button_send', timeout=3)
            if not send_button:
                self.logger.warning("Failed to find send button, pressing back")
                self.handler.press_back()
                return False

            send_button.click()
            self.logger.info("Sent greeting message")

            # 点击操作成功，返回 True 以中断后续事件处理（因为 UI 可能已改变）
            return True

        except Exception as e:
            self.logger.error(f"Error processing follower message event: {str(e)}")
            # 出错时尝试按返回键退出
            try:
                self.handler.press_back()
            except Exception:
                pass
            return False

