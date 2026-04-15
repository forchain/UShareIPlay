class CommandParser:
    def __init__(self, commands, lyrics_tags=None):
        self.commands = commands
        self.lyrics_tags = lyrics_tags

    def is_valid_command(self, message):
        """Check if message starts with any valid prefix"""
        if not message:
            return False
        msg = message.lower()
        return any(msg.startswith(str(cmd.get('prefix', '')).lower()) for cmd in self.commands)

    def parse_command(self, message):
        """Parse command and get the music query"""
        if not message:
            return None

        # Split message into command and parameters
        parts = message.split()
        if not parts:
            return None

        command = parts[0].lower()
        parameters = parts[1:]  # All elements after the command

        # Find matching command config
        matching_cmd = None
        for cmd in self.commands:
            if command == str(cmd.get('prefix', '')).lower():
                matching_cmd = cmd
                break

        if not matching_cmd:
            return None

        matching_cmd['parameters'] = parameters
        return matching_cmd