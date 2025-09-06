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
            if not self.soul_handler.switch_to_app():
                return {'error': 'Failed to switch to Soul app'}
            
            self.logger.info(f"Attempting to change topic to: {topic}")
            
            # 点击话题编辑入口
            topic_edit_entry = self.soul_handler.try_find_element_plus('edit_topic_entry')
            if not topic_edit_entry:
                self.logger.warning("Topic edit entry not found")
                return {'error': 'Topic edit entry not found'}
            
            topic_edit_entry.click()
            self.logger.info("Clicked topic edit entry")
            
            # 等待输入框出现
            topic_input = self.soul_handler.wait_for_element_plus('edit_topic_input')
            if not topic_input:
                return {'error': 'Topic input field not found'}
            
            # 清空并输入新话题
            topic_input.clear()
            topic_input.send_keys(topic)
            self.logger.info(f"Entered topic: {topic}")
            
            # 点击确认按钮
            confirm_button = self.soul_handler.try_find_element_plus('edit_topic_confirm')
            if not confirm_button:
                return {'error': 'Topic confirm button not found'}
            
            confirm_button.click()
            self.logger.info("Clicked topic confirm button")
            
            return {'topic': topic}
            
        except Exception as e:
            self.logger.error(f"Error changing topic: {traceback.format_exc()}")
            return {'error': str(e)}
