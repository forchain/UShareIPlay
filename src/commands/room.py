import traceback
from ..core.base_command import BaseCommand


def create_command(controller):
    room_command = RoomCommand(controller)
    controller.room_command = room_command
    return room_command


command = None


class RoomCommand(BaseCommand):
    def __init__(self, controller):
        super().__init__(controller)
        self._party_manager = None

    @property
    def party_manager(self):
        if self._party_manager is None:
            from ..managers.party_manager import PartyManager
            self._party_manager = PartyManager.instance()
        return self._party_manager

    async def process(self, message_info, parameters):
        """
        处理 room 命令，邀请群主加入指定派对（切房）
        Args:
            message_info: 消息信息
            parameters: 命令参数，第一个参数为派对 ID
        Returns:
            dict: 包含 party_id、user 或 error、party_id
        """
        try:
            if len(parameters) == 0:
                return {
                    'error': 'Missing party ID parameter',
                    'party_id': 'unknown'
                }

            party_id = parameters[0]
            result = await self.party_manager.invite_user(message_info, party_id)

            if 'error' in result:
                return {
                    'error': result['error'],
                    'party_id': result.get('party_id', party_id)
                }
            return {
                'party_id': result.get('party_id', party_id),
                'user': message_info.nickname
            }

        except Exception as e:
            self.soul_handler.log_error(f"Error in room command: {traceback.format_exc()}")
            return {
                'error': str(e),
                'party_id': parameters[0] if len(parameters) > 0 else 'unknown'
            }
