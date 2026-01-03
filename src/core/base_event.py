"""
事件基类 - 所有事件处理器的基类

使用方式：
1. 在 src/events/ 目录下创建事件文件，如 message_list.py
2. 创建继承 BaseEvent 的事件类，如 MessageListEvent
3. 实现 handle 方法处理事件逻辑

类名规则：
- 文件名转 PascalCase + Event（如 message_list.py -> MessageListEvent）
- 多个元素共用一个事件时，取第一个元素名（如 close_button,confirm.py -> CloseButtonEvent）
- 如果存在 __event__ 字段，使用该字段值作为类名
"""

from abc import ABC


class BaseEvent(ABC):
    """事件处理器基类"""

    def __init__(self, handler):
        """
        初始化事件处理器
        
        Args:
            handler: SoulHandler 实例，提供元素操作接口
        """
        self.handler = handler
        self.logger = handler.logger

    def handle(self, key: str, element_wrapper):
        """
        处理事件（默认实现）
        
        Args:
            key: 触发事件的元素 key（来自 config.yaml 中的 elements）
            element_wrapper: ElementWrapper 实例，包装了从 page_source 解析出的元素
        
        默认实现输出元素的 key 和 resource-id
        子类应该重写此方法以实现具体的事件处理逻辑
        """
        element_id = element_wrapper.get_attribute('resource-id') if element_wrapper else 'Unknown'
        self.logger.info(f"Event triggered: key={key}, id={element_id}")

