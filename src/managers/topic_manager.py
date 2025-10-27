import traceback
from datetime import datetime
from ..core.singleton import Singleton


class TopicManager(Singleton):
    """
    话题管理器 - 管理房间话题的设置
    单例模式，提供统一的话题管理服务
    """
    
    def __init__(self):
        # 延迟初始化 handler，避免循环依赖
        self._soul_handler = None
        self._logger = None
        
        # 话题状态管理
        self.last_update_time = None
        self.current_topic = None
        self.next_topic = None
        self.cooldown_minutes = 5
    
    @property
    def soul_handler(self):
        """延迟获取 SoulHandler 实例"""
        if self._soul_handler is None:
            from ..handlers.soul_handler import SoulHandler
            self._soul_handler = SoulHandler.instance()
        return self._soul_handler
    
    @property
    def logger(self):
        """延迟获取 logger 实例"""
        if self._logger is None:
            self._logger = self.soul_handler.logger
        return self._logger
    
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
        
        if self.next_topic and self.last_update_time:
            current_time = datetime.now()
            time_diff = current_time - self.last_update_time
            remaining_minutes = self.cooldown_minutes - (time_diff.total_seconds() / 60)
            if remaining_minutes > 0:
                result['remaining_time'] = int(remaining_minutes)
            else:
                result['remaining_time'] = 0
        elif self.next_topic:
            result['remaining_time'] = 0
        
        return result
    
    def change_topic(self, topic: str) -> dict:
        """
        安排话题变更
        Args:
            topic: 新话题
        Returns:
            dict: 操作结果
        """
        if not self.soul_handler.switch_to_app():
            return {'error': 'Failed to switch to Soul app'}
        
        self.logger.info("Switched to Soul app")
        
        # 清理话题文本
        new_topic = topic.split('|')[0].split('(')[0].strip()[:15]
        current_time = datetime.now()
        
        # 设置下一个话题
        self.next_topic = new_topic
        
        # 检查是否可以立即更新
        if not self.last_update_time:
            self.logger.info(f'Topic will be updated to {new_topic} soon')
            return {
                'topic': f'{new_topic}. Topic will update soon'
            }
        
        time_diff = current_time - self.last_update_time
        remaining_minutes = self.cooldown_minutes - (time_diff.total_seconds() / 60)
        
        if remaining_minutes < 0:
            self.logger.info(f'Topic will be updated to {new_topic} soon')
            return {
                'topic': f'{new_topic}. Topic will update soon'
            }
        
        self.logger.info(f'Topic will be updated to {new_topic} in {remaining_minutes} minutes')
        return {
            'topic': f'{new_topic}. Topic will update in {int(remaining_minutes)} minutes'
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
            # Click room topic
            room_topic = self.soul_handler.wait_for_element_clickable_plus('room_topic')
            if not room_topic:
                return {'error': 'Failed to find room topic'}
            room_topic.click()

            # Click edit entry
            edit_entry = self.soul_handler.wait_for_element_clickable_plus('edit_topic_entry')
            if not edit_entry:
                return {'error': 'Failed to find edit topic entry'}
            edit_entry.click()

            # Input new topic
            topic_input = self.soul_handler.wait_for_element_clickable_plus('edit_topic_input')
            if not topic_input:
                return {'error': 'Failed to find topic input'}
            topic_input.clear()
            topic_input.send_keys(topic)

            # Click confirm
            confirm = self.soul_handler.wait_for_element_clickable_plus('edit_topic_confirm')
            if not confirm:
                return {'error': 'Failed to find confirm button'}
            confirm.click()

            # Wait for completion
            import time
            time.sleep(1)

            # Check if update was successful
            key, element = self.soul_handler.wait_for_any_element_plus(['input_box_entry', 'edit_topic_confirm'])
            if key == 'edit_topic_confirm':
                self.soul_handler.press_back()
                self.soul_handler.press_back()
                self.soul_handler.press_back()
                self.logger.warning('Update topic too frequently, hide edit topic dialog')
                return {'error': 'update topic too frequently'}
            elif key == 'input_box_entry':
                self.logger.info(f'Topic updated successfully to: {topic}')
            else:
                self.logger.warning(f'Unknown key: {key}')

            return {'success': True, 'topic': topic}

        except Exception as e:
            self.logger.error(f"Error changing topic: {traceback.format_exc()}")
            return {'error': f'Failed to update topic: {topic}'}
    
    def update(self):
        """定期检查并更新话题"""
        try:
            if not self.next_topic:
                return
            
            current_time = datetime.now()
            
            # 检查是否到达更新时间
            if self.last_update_time:
                time_diff = current_time - self.last_update_time
                if time_diff.total_seconds() < self.cooldown_minutes * 60:
                    return  # 冷却时间未到，等待
            
            # 记录尝试时间
            self.logger.info(f'Attempting to update topic to {self.next_topic}')
            
            # 无论成功失败，都更新 last_update_time，避免反复重试
            self.last_update_time = current_time
            
            # 执行 UI 更新
            result = self._update_topic_ui(self.next_topic)
            
            # 处理结果
            if 'error' not in result:
                # 成功：清空 next_topic
                self.current_topic = self.next_topic
                self.next_topic = None
                self.logger.info(f'Topic updated successfully to {self.current_topic}')
                self.soul_handler.send_message(f"Updating topic to {self.current_topic}")
            else:
                # 失败：保留 next_topic，等待下次冷却时间后重试
                self.logger.warning(
                    f'Failed to update topic: {result.get("error")}. '
                    f'Will retry in {self.cooldown_minutes} minute(s).'
                )
        
        except Exception as e:
            self.logger.error(f"Error in topic update: {traceback.format_exc()}")
