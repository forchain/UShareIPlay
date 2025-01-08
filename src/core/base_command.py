from abc import ABC, abstractmethod
import time

class BaseCommand(ABC):
    def __init__(self, controller):
        self.controller = controller
        self.soul_handler = controller.soul_handler
        self.music_handler = controller.music_handler
        self.last_update_time = time.time()

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

    def update(self):
        """Update method called every monitoring loop
        Can be overridden by commands that need timer functionality
        
        Returns:
            None
        """
        current_time = time.time()
        delta_time = current_time - self.last_update_time
        self.last_update_time = current_time
        
        # Override this method in commands that need updates
        pass 