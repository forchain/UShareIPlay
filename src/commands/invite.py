import traceback
from ..core.base_command import BaseCommand


def create_command(controller):
    invite_command = InviteCommand(controller)
    controller.invite_command = invite_command
    return invite_command


command = None


class InviteCommand(BaseCommand):
    def __init__(self, controller):
        super().__init__(controller)
        self.handler = self.soul_handler

    async def process(self, message_info, parameters):
        """
        处理 invite 命令，邀请用户加入指定派对
        Args:
            message_info: 消息信息
            parameters: 命令参数，第一个参数应该是派对ID
        Returns:
            dict: 包含处理结果的字典
        """
        try:
            # 检查参数
            if len(parameters) == 0:
                return {
                    'error': 'Missing party ID parameter',
                    'party_id': 'unknown'
                }

            # 获取派对ID参数
            party_id = parameters[0]
            
            # 调用 soul_handler 的 invite_user 方法
            result = self.handler.invite_user(message_info, party_id)

            # 检查结果
            if 'error' in result:
                return {
                    'error': result['error'],
                    'party_id': result.get('party_id', party_id)
                }
            else:
                return {
                    'party_id': result.get('party_id', party_id),
                    'user': message_info.nickname
                }

        except Exception as e:
            self.handler.log_error(f"Error in invite command: {traceback.format_exc()}")
            return {
                'error': str(e),
                'party_id': parameters[0] if len(parameters) > 0 else 'unknown'
            }
