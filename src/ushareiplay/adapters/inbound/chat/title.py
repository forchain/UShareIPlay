import traceback
import shlex

from ushareiplay.core.base_command import BaseCommand


class TitleCommand(BaseCommand):
    """`:title` —— 薄适配器，逻辑全在 `RoomProfileManager`（ADR-0001）。"""

    handler_attr = 'soul_handler'
    error_message = 'Failed to process title command: {error}'

    def change_title(self, title: str):
        """Change room title with cooldown check."""
        if not self.handler.key_actions.switch_to_app():
            return {'error': 'Failed to switch to Soul app'}
        self.handler.logger.info("Switched to Soul app")
        return self.room_profile_manager.set_title(title)

    async def do_process(self, message_info, parameters):
        """Process title command.

        Parameters:
            - 1 parameter: title only
            - 2 parameters: title and theme
        """
        if not parameters:
            return {'error': 'Missing title parameter'}

        try:
            params = shlex.split(' '.join(parameters))
        except ValueError as e:
            self.handler.log_error(f"Error parsing parameters: {str(e)}")
            return {'error': 'Invalid parameter format. Use quotes for titles with spaces.'}

        if not params:
            return {'error': 'Missing title parameter'}

        new_title = params[0]
        new_theme = params[1] if len(params) >= 2 else None

        if new_theme:
            self.handler.logger.info(f"Theme will be updated to: {new_theme}")

        title_result = self.room_profile_manager.set_title(new_title, theme=new_theme)

        if new_theme and 'error' not in title_result:
            return {'title': f"主题: {new_theme}\n{title_result.get('title', '')}"}
        return title_result

    def update(self):
        """Check and update title periodically with simple retry logic."""
        try:
            # 兜底接地：进程重启时人已经坐在房里，`join_party` 那条线一次都不会走，
            # 房名就永远读不回来（`:theme` 只能报「当前标题: 未设置」）。这一句是
            # 只读且有守卫的：已经接地就立刻返回，一个 UI 调用都不发生。
            self.room_profile_manager.ensure_synced_on_return()

            result = self.room_profile_manager.update_title()
            if not result.get('ui_updated'):
                return

            self.handler.logger.info(f'标题更新成功: {self.room_profile_manager.get_current_title()}')
            self.message_dispatch.send_screen_message(
                f"标题已更新为: {self.room_profile_manager.get_current_title()}"
            )
        except Exception:
            self.handler.log_error(f"Error in title update: {traceback.format_exc()}")
