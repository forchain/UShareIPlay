from ushareiplay.core.base_command import BaseCommand
from ushareiplay.modules.playback.domain import PlaybackMode, PlaybackRequest


class RadioCommand(BaseCommand):
    """`:radio [channel]` —— 打开 QQ 音乐的电台频道。"""

    handler_attr = "music_handler"

    RADIO_CHANNELS = ("guess", "daily", "collection", "sleep", "radar")
    DEFAULT_CHANNEL = "collection"

    async def do_process(self, message_info, parameters):
        channel = str(parameters[0]).lower() if parameters else self.DEFAULT_CHANNEL
        if channel not in self.RADIO_CHANNELS:
            return {"error": f"Unsupported radio keyword: {channel}"}

        result = await self.controller.play_song.execute(
            PlaybackRequest(
                mode=PlaybackMode.RADIO,
                channel=channel,
                requester=message_info.nickname,
            )
        )
        return result.as_response()
