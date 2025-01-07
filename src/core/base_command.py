from abc import ABC, abstractmethod

class BaseCommand(ABC):
    def __init__(self):
        pass
    
    @abstractmethod
    def process(self, message_info, parameters):
        """Process the command
        Args:
            message_info: MessageInfo object containing message details
            parameters: list of command parameters
        Returns:
            str: Response message
        """
        pass 