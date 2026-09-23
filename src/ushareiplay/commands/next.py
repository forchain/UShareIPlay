from ushareiplay.core.base_command import BaseCommand


class NextCommand(BaseCommand):
    """点歌到「下一首播放」。

    :next 只把歌曲追加到队列，不会打断当前音频流，因此不参与
    PlaybackMuting 的闭麦生命周期（见 Ticket #319）。
    """

    async def do_process(self, message_info, parameters):
        query = ' '.join(parameters)
        info = self.play_next(query)
        return info

    def play_next(self, query):
        info = self.music_handler.play_next(query)
        return info
