import traceback
from ..core.base_command import BaseCommand

def create_command(controller):
    end_command = EndCommand(controller)
    controller.end_command = end_command
    return end_command

command = None

class EndCommand(BaseCommand):
    def __init__(self, controller):
        super().__init__(controller)
        self.handler = self.soul_handler
        self.handler.logger.info("EndCommand initialized")
        
        # 初始化派对管理器
        from ..managers.party_manager import PartyManager
        self.party_manager = PartyManager.instance()
        self.party_manager.initialize()

    async def process(self, message_info, parameters):
        """Process end command to close party"""
        try:
            # Check if user level >= 3
            from ..dal.user_dao import UserDAO
            user = await UserDAO.get_or_create(message_info.nickname)
            if user.level < 3:
                self.handler.logger.warning(f"User {message_info.nickname} level {user.level} < 3, cannot end party")
                return {'error': '必须群主关注的人才能关闭房间'}
                
            # 委托给PartyManager处理
            return self.party_manager.end_party()
        except Exception as e:
            self.handler.log_error(f"Error processing end command: {traceback.format_exc()}")
            return {'error': 'Failed to end party'} 

    def update(self):
        """委托给PartyManager处理派对管理逻辑"""
        try:
            # 将派对管理逻辑委托给PartyManager
            self.party_manager.update()
        except Exception as e:
            self.handler.log_error(f"Error in party management update: {traceback.format_exc()}")

