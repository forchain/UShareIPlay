from ushareiplay.core.base_command import BaseCommand


class ThemeCommand(BaseCommand):
    handler_attr = 'soul_handler'
    error_message = '处理主题命令失败: {error}'

    def change_theme(self, theme: str):
        """Change room theme."""
        if not self.handler.key_actions.switch_to_app():
            return {'error': 'Failed to switch to Soul app'}
        self.handler.logger.info("Switched to Soul app")

        result = self.room_name_manager.set_theme(theme)
        if 'error' in result:
            return result

        verify_result = self.room_name_manager.verify_theme(theme)
        if 'error' in verify_result:
            return verify_result

        ui_result = self.room_name_manager.process_pending_update()

        response = {'theme': f'主题已更新为: {result["theme"]}'}
        if ui_result.get('ui_updated'):
            response['ui_update'] = '房间标题已更新'
        elif ui_result.get('cooldown'):
            response['ui_update'] = f'房间标题更新被冷却时间阻止，还需等待{ui_result["remaining_minutes"]}分钟'
        elif ui_result.get('error'):
            response['ui_update'] = '房间标题更新失败，将在下个周期重试'
        elif ui_result.get('skipped'):
            response['ui_update'] = '没有标题可以更新'
        return response

    async def do_process(self, message_info, parameters):
        """Process theme command"""
        if not parameters:
            current_theme = self.room_name_manager.get_current_theme()
            current_title = self.room_name_manager.get_current_title()
            next_title = self.room_name_manager.get_next_title()
            remaining_minutes = self.room_name_manager.get_remaining_cooldown_minutes()

            status_parts = [f'当前主题: {current_theme}']
            status_parts.append(f'当前标题: {current_title}' if current_title else '当前标题: 未设置')
            if next_title:
                status_parts.append(f'即将更新标题: {next_title}')
                status_parts.append(
                    f'剩余更新时间: {remaining_minutes}分钟' if remaining_minutes > 0 else '剩余更新时间: 可立即更新'
                )
            else:
                status_parts.append('即将更新标题: 无')

            return {'theme': '\n'.join(status_parts)}

        new_theme = ' '.join(parameters)
        return self.change_theme(new_theme)

    def update(self):
        """Update method for background tasks - handle theme UI synchronization"""
        try:
            if not self.room_name_manager.has_pending_ui_update():
                return
            self.room_name_manager.process_pending_update()
        except Exception as e:
            self.handler.log_error(f"Error in theme update: {str(e)}")
