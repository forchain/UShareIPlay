from abc import ABC, abstractmethod
import time
import re

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

    def user_enter(self, username: str):
        """Called when a user enters the party
        Args:
            username: str, name of the user who entered
        Returns:
            None
        """
        # Override this method in commands that need to handle user entry
        pass

    @staticmethod
    def is_user_enter_message(message: str) -> tuple[bool, str]:
        """Check if message is a user enter notification
        Args:
            message: str, message to check
        Returns:
            tuple[bool, str]: (is_enter_message, username)
        """
        pattern = r"^(.+)进来陪你聊天啦(?: 来自派对提醒)?$"
        match = re.match(pattern, message)
        if match:
            return True, match.group(1)
        return False, "" 