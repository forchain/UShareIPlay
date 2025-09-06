import traceback
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
    
    def change_topic(self, topic: str) -> dict:
        """
        修改房间话题
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
