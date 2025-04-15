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
            if not parameters:
                return {'error': 'Missing parameters. Use: :theme [mode] [title] or :theme mode [title] or :theme title'}

            # Check if first parameter is a mode (2 chars)
            mode = None
            title = None
            if len(parameters[0]) <= 2:
                mode = parameters[0]
                if len(parameters) > 1:
                    title = ' '.join(parameters[1:])
            else:
                title = ' '.join(parameters)

            return self.theme_manager.change_theme(mode, title)
        except Exception as e:
            self.handler.log_error(f"Error processing theme command: {str(e)}")
            return {'error': f'Failed to process theme command'}

    def update(self):
        """Check and update theme periodically"""
        self.theme_manager.update() 