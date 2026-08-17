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
            clean_room_id = room_id_text.strip()
            room_state = RoomState.instance()

            # 校验当前房间是否与预期房间一致（防止被系统自动调入随机房间）
            expected_id = room_state.get_expected_party_id()
            if expected_id and clean_room_id != expected_id:
                self.logger.warning(
                    f"Room ID mismatch detected: current={clean_room_id}, expected={expected_id}. "
                    f"Possible unauthorized auto-redirect by system. Exiting room and recreating party..."
                )
                party_manager = getattr(self.controller, 'party_manager', None)
                if party_manager:
                    await party_manager.leave_and_recreate_party()
                    return True

            # 更新 RoomState 中的房间ID
            room_state.room_id = clean_room_id
            if self.handler:
                self.handler.party_id = clean_room_id

            return False

        except Exception as e:
            self.logger.error(f"Error processing room ID event: {str(e)}")
            return False

