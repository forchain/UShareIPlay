import traceback
from ..core.base_command import BaseCommand
import shlex
from collections import defaultdict
from typing import List, Tuple

def create_command(controller):
    hello_command = HelloCommand(controller)
    controller.hello_command = hello_command
    return hello_command

command = None

class HelloCommand(BaseCommand):
    def __init__(self, controller):
        super().__init__(controller)
        self.handler = self.soul_handler
        # username -> List[(sender, message, song)]
        self.pending_hellos = self.controller.db_helper.get_pending_hellos()

    async def process(self, message_info, parameters):
        """Process hello command
        Args:
            message_info: MessageInfo object
            parameters: List of parameters (username, message, song)
        Returns:
            dict: Result with success or error
        """
        try:
            # Parse parameters using shlex to handle quoted strings
            try:
                params = shlex.split(' '.join(parameters))
            except ValueError as e:
                return {'error': 'Invalid parameters format. Please check quotes.'}

            if len(params) < 3:
                return {'error': 'Missing parameters. Usage: :hello username "message" "song"'}

            username = params[0]
            message = params[1]
            song = params[2]

            # Add hello message to list
            self.pending_hellos[username].append((message_info.nickname, message, song))
            self.controller.db_helper.add_pending_hello(username, message_info.nickname, song, message)
            
            # Get position in queue
            queue_position = len(self.pending_hellos[username])
            
            return {
                'success': f'Will greet {username} when s/he (#{queue_position} in queue)'
            }

        except Exception as e:
            self.handler.log_error(f"Error processing hello command: {traceback.format_exc()}")
            return {'error': 'Failed to process hello command'}

    async def user_enter(self, username: str):
        """Called when a user enters the party"""
        try:
            # Check if we have pending hellos for this user
            if username in self.pending_hellos and self.pending_hellos[username]:
                # Get the first hello message
                sender, message, song = self.pending_hellos[username][0]
                
                # Send greeting message
                greeting = f"@{username}，{sender} 给你点了一首 {song}，TA想对你说：{message}"
                self.handler.send_message(greeting)
                self.handler.logger.info(f"Sent greeting to {username} from {sender}")
                
                # Play the song
                self.controller.play_command.play_song(song)
                self.handler.logger.info(f"Playing song: {song}")
                
                # Remove this hello from the list
                self.pending_hellos[username].pop(0)
                if not self.pending_hellos[username]:  # Clean up if empty
                    del self.pending_hellos[username]
                
                # Remove this hello from database
                self.controller.db_helper.delete_one_hello(username, sender, song, message)

        except Exception as e:
            self.handler.log_error(f"Error in hello user_enter: {traceback.format_exc()}") 