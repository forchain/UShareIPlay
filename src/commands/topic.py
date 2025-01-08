from ..core.base_command import BaseCommand

class TopicCommand(BaseCommand):
    def __init__(self, controller):
        super().__init__(controller)

    def process(self, message_info, parameters):
        return {'topic': "City Pop"}

def create_command(controller):
    return TopicCommand(controller)

command = None
