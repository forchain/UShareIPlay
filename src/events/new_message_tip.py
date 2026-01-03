"""
新消息提示事件 - 监控新消息提示元素

当检测到新消息提示时触发，自动点击滚动到最新消息。
"""

from ..core.base_event import BaseEvent


class NewMessageTipEvent(BaseEvent):
    """新消息提示事件处理器"""

    def handle(self, key: str, element_wrapper):
        """
        处理新消息提示事件
        
        Args:
            key: 触发事件的元素 key，这里是 'new_message_tip'
            element_wrapper: ElementWrapper 实例，包装了新消息提示元素
            
        Returns:
            bool: 默认返回 False，不中断后续处理
        """
        element_id = element_wrapper.get_attribute('resource-id') if element_wrapper else 'Unknown'
        # self.logger.info(f"NewMessageTipEvent: key={key}, id={element_id}")
        
        # 点击新消息提示，滚动到最新消息
        # 注意：实际点击操作需要获取真实的 WebElement
        # element_wrapper.click()
        
        return False

