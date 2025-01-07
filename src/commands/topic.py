
from core.base_command import BaseCommand

class TopicCommand(BaseCommand):
    def __init__(self):
        pass
    
    def process(self, message_info, parameters):
        return "topic"
    
command = TopicCommand()