"""
关注者消息事件 - 监控关注者进入房间的消息

横幅文案的解析归 Chat Intake（`classify_banner_line`）；本事件只保留它独有的
UI 动作：写聊天日志、建用户记录、触发 return、点打招呼并发送。
"""

from ushareiplay.core.base_event import BaseEvent
from ushareiplay.core.chat_intake import ChatIntakeKind, classify_banner_line


class FollowerMessageEvent(BaseEvent):
    """关注者消息事件处理器"""

    # 类变量，维护上一次的 follower_message，避免重复处理
    last_follower_message = None

    async def handle(self, key: str, element_wrapper):
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
            from ushareiplay.managers.message_manager import get_chat_logger
            chat_logger = get_chat_logger(self.handler.config)
            chat_logger.critical(message_text)

            # 解析消息（横幅文法归 Chat Intake）
            banner = classify_banner_line(message_text)
            nickname = banner.nickname
            is_join = banner.kind == ChatIntakeKind.USER_RETURN
            if nickname:
                # 创建用户记录（异步操作）
                try:
                    from ushareiplay.dal.user_dao import UserDAO
                    # 在事件循环中创建任务
                    await UserDAO.get_or_create(nickname)
                    self.logger.info(f"Creating user record for: {nickname}")
                except Exception as e:
                    self.logger.error(f"Error creating user record: {str(e)}")
            else:
                self.logger.warning(f"Failed to parse nickname from message: {message_text}")
                return False

            # 如果不是进入房间消息，不处理打招呼
            if not is_join:
                return True # 已处理，拦截后续（因为文本已记录且用户已创建）

            # 触发用户返回事件（若符合 return 条件）
            try:
                from ushareiplay.state.presence_tracker import PresenceTracker
                from ushareiplay.managers.command_manager import CommandManager

                presence_tracker = PresenceTracker.instance()
                if presence_tracker.should_trigger_return(nickname):
                    presence_tracker.record_return(nickname)
                    self.logger.critical(f"User returned: {nickname}")
                    await CommandManager.instance().notify_user_return(nickname)
                else:
                    self.logger.info(
                        f"Follower banner for {nickname} skipped return event (not online or recently entered/returned)"
                    )
            except Exception as e:
                self.logger.error(f"Error notifying user return in follower message: {str(e)}")

            # 等待并点击打招呼按钮
            greet_follower = self.handler.element_finder.try_find_element('greet_follower')
            if not greet_follower:
                self.logger.warning("Failed to find greet button")
                return True

            greet_follower.click()
            self.logger.info("Clicked greet button")

            # 等待并点击发送按钮
            send_button = self.handler.element_finder.wait_for_element_clickable('button_send', timeout=3)
            if not send_button:
                self.logger.warning("Failed to find send button, pressing back")
                self.handler.key_actions.press_back()
                if hasattr(self.handler, "ensure_chat_window_closed"):
                    self.handler.ensure_chat_window_closed()
                return True

            send_button.click()
            self.logger.info("Sent greeting message")
            if hasattr(self.handler, "ensure_chat_window_closed"):
                self.handler.ensure_chat_window_closed()

            # 点击操作成功，返回 True 以中断后续事件处理（因为 UI 可能已改变）
            return True

        except Exception as e:
            self.logger.error(f"Error processing follower message event: {str(e)}")
            # 出错时尝试按返回键退出
            try:
                self.handler.key_actions.press_back()
            except Exception:
                pass
            return False

