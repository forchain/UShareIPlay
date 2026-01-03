"""
消息列表事件 - 监控消息列表元素

这是一个示例事件，演示事件系统的基本用法。
当 page_source 中检测到 message_list 元素时触发。
"""

from ..core.base_event import BaseEvent


class MessageListEvent(BaseEvent):
    """消息列表事件处理器"""

    def handle(self, key: str, element_wrapper):
        """
        处理消息列表事件
        
        Args:
            key: 触发事件的元素 key，这里是 'message_list'
            element_wrapper: ElementWrapper 实例，包装了消息列表元素
            
        Returns:
            bool: 默认返回 False，不中断后续处理
        """
        # 默认实现：输出元素信息
        element_id = element_wrapper.get_attribute('resource-id') if element_wrapper else 'Unknown'
        # self.logger.debug(f"MessageListEvent: key={key}, id={element_id}")
        
        # 这里可以添加自定义逻辑，例如：
        # - 检查是否有新消息
        # - 获取消息内容
        # - 触发消息处理
        
        return False

