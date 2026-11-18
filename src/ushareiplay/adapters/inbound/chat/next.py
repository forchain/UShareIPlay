from ushareiplay.adapters.inbound.chat.base_command import BaseCommand


class NextCommand(BaseCommand):
    """点歌到「下一首播放」，交给 `PlayNext` 用例。"""

    async def do_process(self, message_info, parameters):
        query = " ".join(parameters)
        return self.controller.play_next.execute(message_info.nickname, query)
