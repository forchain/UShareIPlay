import traceback
from ..core.base_command import BaseCommand
from ..managers.theme_manager import ThemeManager

def create_command(controller):
    theme_command = ThemeCommand(controller)
    controller.theme_command = theme_command
    return theme_command

class ThemeCommand(BaseCommand):
    def __init__(self, controller):
        super().__init__(controller)
        self.theme_manager = ThemeManager(controller.soul_handler)

    async def process(self, message_info, parameters):
        """Process theme command
        Format: :theme [mode] [title] or :theme mode [title] or :theme title
        """
        try:
            if not parameters or len(parameters) == 0:
                return {'error': 'Missing parameters. Use: :theme [title] [mode] or :theme title'}

            title = parameters[0]
            mode = None
            if len(parameters) > 1:
                mode = parameters[1]

            return self.theme_manager.change_theme(mode, title)
        except Exception as e:
            self.handler.log_error(f"Error processing theme command: {str(e)}")
            return {'error': f'Failed to process theme command'}

    def update(self):
        """Check and update theme periodically"""
        self.theme_manager.update() 