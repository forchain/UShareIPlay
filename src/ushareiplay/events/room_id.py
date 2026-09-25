"""房间ID事件 - 监控房间ID变化

把当前房间 ID 交给 PartyManager 核对（群主转让 / 被调入随机房间的判定都在那里），
本事件只负责从元素里取出文本并决定是否中断后续处理。
"""

from ushareiplay.core.base_event import BaseEvent
from ushareiplay.managers.party_manager import PartyManager


class RoomIdEvent(BaseEvent):
    """房间ID事件处理器"""

    async def handle(self, key: str, element_wrapper):
        """
        处理房间ID事件

        Args:
            key: 触发事件的元素 key，这里是 'room_id'
            element_wrapper: ElementWrapper 实例，包装了房间ID元素

        Returns:
            bool: 核对结果要求退房重建时返回 True（中断后续处理），否则 False
        """
        try:
            room_id_text = element_wrapper.text
            if not room_id_text:
                return False

            if not PartyManager.is_initialized():
                return False

            return await PartyManager.instance().verify_current_room(
                room_id_text.strip(), source="room_id_event"
            )
        except Exception as e:
            self.logger.error(f"Error processing room ID event: {str(e)}")
            return False
