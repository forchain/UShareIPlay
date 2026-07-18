from ushareiplay.core.base_command import BaseCommand


class NextCommand(BaseCommand):
    requires_mic = True

    async def do_process(self, message_info, parameters):
        query = ' '.join(parameters)
        info = self.play_next(query)
        return info

    def play_next(self, query):
        info = self.music_handler.play_next(query)
        return info
