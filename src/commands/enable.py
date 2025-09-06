import traceback
from ..core.base_command import BaseCommand


def create_command(controller):
    enable_command = EnableCommand(controller)
    controller.enable_command = enable_command
    return enable_command


command = None


class EnableCommand(BaseCommand):
    def __init__(self, controller):
        super().__init__(controller)
        self.handler = self.soul_handler

    async def process(self, message_info, parameters):
        """
        处理 enable 命令，控制 recovery manager 的启用/禁用
        Args:
            message_info: 消息信息
            parameters: 命令参数 ['1'] 或 ['0']
        Returns:
            dict: 包含处理结果的字典
        """
        try:
            # 检查参数
            if len(parameters) == 0:
                return {
                    'error': 'Missing parameter. Use: :enable [1|0]'
                }

            # 解析参数
            try:
                recovery_enabled = ''.join(parameters) == "1"
            except ValueError:
                return {
                    'error': 'Invalid parameter. Use: :enable [1|0]'
                }

            # 设置 recovery manager 的手动模式状态（与 recovery_enabled 相反）
            # recovery_enabled=True 表示启用自动恢复，manual_mode=False
            # recovery_enabled=False 表示禁用自动恢复，manual_mode=True（手动模式）
            if hasattr(self.controller, 'recovery_manager') and self.controller.recovery_manager:
                self.controller.recovery_manager.set_manual_mode(not recovery_enabled)
                status_msg = "enabled" if recovery_enabled else "disabled"
                self.handler.logger.info(f"Recovery manager {status_msg}")
            else:
                return {
                    'error': 'Recovery manager not available'
                }

            return {
                'recovery_enabled': recovery_enabled
            }

        except Exception as e:
            self.handler.log_error(f"Error in enable command: {traceback.format_exc()}")
            return {
                'error': str(e)
            }
