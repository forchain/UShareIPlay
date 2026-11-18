from ushareiplay.adapters.inbound.chat.base_command import BaseCommand


class RoomCommand(BaseCommand):
    error_message = '{error}'

    def __init__(self, controller):
        super().__init__(controller)
        self._party_service = controller.party_service

    def error_context(self, message_info, parameters):
        return {'party_id': parameters[0] if len(parameters) > 0 else 'unknown'}

    async def do_process(self, message_info, parameters):
        """
        处理 room 命令，邀请群主加入指定派对（切房）
        Args:
            message_info: 消息信息
            parameters: 命令参数，第一个参数为派对 ID
        Returns:
            dict: 包含 party_id、user 或 error、party_id
        """
        if len(parameters) == 0:
            return {
                'error': 'Missing party ID parameter',
                'party_id': 'unknown'
            }

        party_id = parameters[0]
        result = await self._party_service.invite_user(message_info.nickname, party_id)

        if 'error' in result:
            return {
                'error': result['error'],
                'party_id': result.get('party_id', party_id)
            }
        return {
            'party_id': result.get('party_id', party_id),
            'user': message_info.nickname
        }
