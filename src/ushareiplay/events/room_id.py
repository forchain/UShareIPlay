"""
房间ID事件 - 监控房间ID变化

当检测到房间ID变化时，更新 InfoManager 中的房间ID。
"""

from ushareiplay.core.base_event import BaseEvent
from ushareiplay.state.room_state import RoomState


class RoomIdEvent(BaseEvent):
    """房间ID事件处理器"""

    async def handle(self, key: str, element_wrapper):
        """
        处理房间ID事件

        获取房间ID文本并更新到 RoomState

        Args:
            key: 触发事件的元素 key，这里是 'room_id'
            element_wrapper: ElementWrapper 实例，包装了房间ID元素

        Returns:
            bool: 默认返回 False，不中断后续处理
        """
        try:
            # 获取元素文本
            room_id_text = element_wrapper.text
            if not room_id_text:
                return False

            # 更新 RoomState 中的房间ID
            RoomState.instance().room_id = room_id_text

            return False

        except Exception as e:
            self.logger.error(f"Error processing room ID event: {str(e)}")
            return False

