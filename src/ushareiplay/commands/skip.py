from ushareiplay.core.base_command import BaseCommand


class SkipCommand(BaseCommand):
    async def do_process(self, message_info, parameters):
        result = self.music_handler.skip_song()
        return result
