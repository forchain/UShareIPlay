from ..core.base_command import BaseCommand


class RecoveryCommand(BaseCommand):
    def __init__(self, controller):
        super().__init__(controller)
        self.handler = self.soul_handler

    async def process(self, message_info, parameters):
        """处理recovery命令"""
        try:
            if not parameters:
                # 显示恢复管理器状态
                status = self.recovery_manager.get_status_info()
                return {
                    'status': f"恢复管理器状态:\n"
                             f"- 正常状态: {'是' if status['is_normal_state'] else '否'}\n"
                             f"- 上次恢复时间: {status['last_recovery_time']:.1f}秒前\n"
                             f"- 恢复冷却时间: {status['recovery_cooldown']}秒\n"
                             f"- 风险元素: {', '.join(status['risk_elements'])}\n"
                             f"- 关闭按钮: {', '.join(status['close_buttons'])}\n"
                             f"- 抽屉元素: {', '.join(status['drawer_elements'])}"
                }
            
            action = parameters[0].lower()
            
            if action == 'force':
                # 强制执行恢复
                result = self.recovery_manager.force_recovery()
                return {
                    'status': f"强制恢复{'执行成功' if result else '无需执行'}"
                }
            elif action == 'status':
                # 显示详细状态
                status = self.recovery_manager.get_status_info()
                return {
                    'status': f"恢复管理器详细状态:\n"
                             f"- 正常状态: {'是' if status['is_normal_state'] else '否'}\n"
                             f"- 上次恢复时间: {status['last_recovery_time']:.1f}秒前\n"
                             f"- 恢复冷却时间: {status['recovery_cooldown']}秒"
                }
            else:
                return {
                    'error': f"未知操作: {action}。可用操作: force(强制恢复), status(状态)"
                }
                
        except Exception as e:
            self.handler.log_error(f"处理recovery命令时出错: {str(e)}")
            return {'error': f'命令执行失败: {str(e)}'}

    def update(self):
        """定期更新，这里不需要特殊处理"""
        pass


def create_command(controller):
    return RecoveryCommand(controller) 