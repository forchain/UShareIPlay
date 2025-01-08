from abc import ABC, abstractmethod

class BaseCommand(ABC):
    def __init__(self, controller):
        self.controller = controller
        self.soul_handler  = controller.soul_handler
        self.music_handler  = controller.music_handler

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