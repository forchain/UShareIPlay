import traceback
from ..core.base_command import BaseCommand
from datetime import datetime, timedelta
import time

def create_command(controller):
    help_command = HelpCommand(controller)
    controller.help_command = help_command
    return help_command

command = None

class HelpCommand(BaseCommand):
    def __init__(self, controller):
        super().__init__(controller)

    async def process(self, message_info, parameters):
        return {}
