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
from typing import List, Optional, Sequence

from ushareiplay.core.event_elements import resolve_event_elements


class BaseEvent(ABC):
    """事件处理器基类"""

    # 元素列表在 soul 配置中的键名；None 表示该事件不支持配置覆盖
    config_key: Optional[str] = None
    # 配置缺省时的默认元素列表（事件模块的 __elements__）
    default_elements: Sequence[str] = ()

    def __init__(self, handler, runtime=None):
        """
        初始化事件处理器
        
        Args:
            handler: SoulHandler 实例，提供元素操作接口
        """
        self.handler = handler
        self.logger = handler.logger
        self.controller = handler.controller
        self.runtime = runtime

    @property
    def elements(self) -> List[str]:
        """
        当前生效的元素 key 列表

        配置优先（soul.<config_key>），配置缺省或未声明时回退模块默认列表。
        每次访问都实时读取 handler.config，运行时热加载后立即生效。
        """
        return resolve_event_elements(
            self.handler.config, self.config_key, self.default_elements
        )

    def is_ui_busy(self) -> bool:
        if self.runtime is None:
            return False
        return self.runtime.is_ui_busy()

    async def handle(self, key: str, element_wrapper):
        """
        处理事件（默认实现）
        
        Args:
            key: 触发事件的元素 key（来自 config.yaml 中的 elements）
            element_wrapper: ElementWrapper 实例，包装了从 page_source 解析出的元素
        
        Returns:
            bool: 如果返回 True，将中断后续事件处理，进入下一轮循环。默认返回 None/False。
        
        默认实现输出元素的 key 和 resource-id
        子类应该重写此方法以实现具体的事件处理逻辑
        """
        element_id = element_wrapper.get_attribute('resource-id') if element_wrapper else 'Unknown'
        self.logger.info(f"Event triggered: key={key}, id={element_id}")
        return False
