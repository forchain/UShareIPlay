import traceback
from ushareiplay.core.singleton import Singleton
from ushareiplay.helpers.room_banner import TOPIC_MAX_LENGTH, clean_banner_text
from ushareiplay.managers.pending_write import PendingWrite


class TopicManager(Singleton):
    """
    话题管理器 - 管理房间话题的设置
    单例模式，提供统一的话题管理服务
    """
    
    def __init__(self):
        # 延迟初始化 handler，避免循环依赖
        self._soul_handler = None
        self._logger = None
        self._message_dispatch = None
        
        # 冷却时钟与待写入话题：计时机制由 PendingWrite 拥有
        self._write = PendingWrite(cooldown_minutes=self.COOLDOWN_MINUTES, label="topic")
        self.current_topic = None

    #: 话题冷却时长（分钟）
    COOLDOWN_MINUTES = 5

    @property
    def next_topic(self):
        return self._write.pending

    @next_topic.setter
    def next_topic(self, value):
        if value is None:
            self._write.clear()
        else:
            self._write.submit(value)

    @property
    def last_update_time(self):
        return self._write.last_attempt_at

    @last_update_time.setter
    def last_update_time(self, value):
        self._write.last_attempt_at = value

    @property
    def cooldown_minutes(self):
        return self._write.cooldown_minutes

    @cooldown_minutes.setter
    def cooldown_minutes(self, value):
        self._write.cooldown_minutes = value

    def can_update_now(self) -> bool:
        """是否可以立即写入话题（原先这份算术内联在 get_status/change_topic 里）。"""
        return self._write.can_apply_now()

    def get_remaining_cooldown_minutes(self) -> int:
        """距离可写入还有多少分钟。"""
        return self._write.remaining_minutes()
    
    @property
    def soul_handler(self):
        """延迟获取 SoulHandler 实例"""
        if self._soul_handler is None:
            from ushareiplay.handlers.soul_handler import SoulHandler
            self._soul_handler = SoulHandler.instance()
        return self._soul_handler
    
    @property
    def logger(self):
        """延迟获取 logger 实例"""
        if self._logger is None:
            self._logger = self.soul_handler.logger
        return self._logger

    @property
    def message_dispatch(self):
        if self._message_dispatch is None:
            from ushareiplay.core.message_dispatch import MessageDispatch

            self._message_dispatch = MessageDispatch.instance().bind_handler(self.soul_handler)
        return self._message_dispatch
    
    def get_status(self) -> dict:
        """
        获取当前话题状态
        Returns:
            dict: 包含当前话题、下一个话题和剩余时间的状态信息
        """
        result = {
            'current_topic': self.current_topic or 'None',
            'next_topic': self.next_topic or 'None',
            'remaining_time': None
        }
        
        if self.next_topic:
            result['remaining_time'] = self._write.remaining_minutes()
        
        return result
    
    def change_topic(self, topic: str) -> dict:
        """
        安排话题变更
        Args:
            topic: 新话题
        Returns:
            dict: 操作结果
        """
        if not self.soul_handler.key_actions.switch_to_app():
            return {'error': 'Failed to switch to Soul app'}
        
        self.logger.info("Switched to Soul app")
        
        # 清理话题文本: 支持半角和全角竖线及括号
        new_topic = clean_banner_text(topic, TOPIC_MAX_LENGTH)

        # 设置下一个话题
        self.next_topic = new_topic

        # 检查是否可以立即更新
        if self._write.can_apply_now():
            self.logger.info(f'Topic will be updated to {new_topic} soon')
            return {
                'topic': f'{new_topic}. Topic will update soon'
            }

        remaining_minutes = self._write.remaining_minutes()
        self.logger.info(f'Topic will be updated to {new_topic} in {remaining_minutes} minutes')
        return {
            'topic': f'{new_topic}. Topic will update in {remaining_minutes} minutes'
        }
    
    def _update_topic_ui(self, topic: str) -> dict:
        """
        通过 UI 修改房间话题
        Args:
            topic: 新话题
        Returns:
            dict: 操作结果
        """
        try:
            from ushareiplay.state.room_state import RoomState
            if RoomState.in_guest_room():
                self.logger.info("In guest room, skip topic UI update")
                return {'skipped': 'guest_room'}

            # Click room topic on blackboard
            room_topic = self.soul_handler.element_finder.wait_for_element_clickable('room_topic')
            if not room_topic:
                return {'error': 'Failed to find room topic'}
            room_topic.click()

            # Click edit entry (support edit_topic_entry or fallback edit_topic_bg_entry)
            key, edit_entry = self.soul_handler.element_finder.wait_for_any_element(
                ['edit_topic_entry', 'edit_topic_bg_entry'],
                timeout=5,
            )
            if not edit_entry:
                self.soul_handler.key_actions.press_back()
                return {'error': 'Failed to find edit topic entry'}
            edit_entry.click()

            # Input new topic
            topic_input = self.soul_handler.element_finder.wait_for_element_clickable('edit_topic_input')
            if not topic_input:
                self.soul_handler.key_actions.press_back()
                self.soul_handler.key_actions.press_back()
                return {'error': 'Failed to find topic input'}
            topic_input.clear()
            topic_input.send_keys(topic)

            # Click confirm
            confirm = self.soul_handler.element_finder.wait_for_element_clickable('edit_topic_confirm')
            if not confirm:
                self.soul_handler.key_actions.press_back()
                self.soul_handler.key_actions.press_back()
                return {'error': 'Failed to find confirm button'}
            confirm.click()

            # Wait for completion
            import time
            time.sleep(1)

            # Check if update was successful
            key, element = self.soul_handler.element_finder.wait_for_any_element(['input_box_entry', 'edit_topic_confirm'])
            if key == 'edit_topic_confirm':
                self.soul_handler.key_actions.press_back()
                self.soul_handler.key_actions.press_back()
                self.soul_handler.key_actions.press_back()
                self.logger.warning('Update topic too frequently, hide edit topic dialog')
                return {'error': 'update topic too frequently'}
            elif key == 'input_box_entry':
                self.logger.info(f'Topic updated successfully to: {topic}')
            else:
                self.logger.warning(f'Unknown key: {key}')
                self.soul_handler.key_actions.press_back()
                self.soul_handler.key_actions.press_back()

            return {'success': True, 'topic': topic}

        except Exception as e:
            self.logger.error(f"Error changing topic: {traceback.format_exc()}")
            return {'error': f'Failed to update topic: {topic}'}
    
    def update(self):
        """定期检查并更新话题"""
        try:
            if not self.next_topic:
                return

            # 检查是否到达更新时间
            if not self._write.can_apply_now():
                return  # 冷却时间未到，等待

            # 记录尝试时间
            self.logger.info(f'Attempting to update topic to {self.next_topic}')

            # 无论成功失败，都推进冷却时钟，避免反复重试
            self._write.mark_attempted()
            
            # 执行 UI 更新
            result = self._update_topic_ui(self.next_topic)
            
            # 处理结果
            if 'error' not in result:
                # 成功：清空 next_topic
                self.current_topic = self.next_topic
                self.next_topic = None
                self.logger.info(f'Topic updated successfully to {self.current_topic}')
                self.message_dispatch.send_screen_message(f"Updating topic to {self.current_topic}")
            else:
                # 失败：保留 next_topic，等待下次冷却时间后重试
                self.logger.warning(
                    f'Failed to update topic: {result.get("error")}. '
                    f'Will retry in {self.cooldown_minutes} minute(s).'
                )
        
        except Exception as e:
            self.logger.error(f"Error in topic update: {traceback.format_exc()}")
