from ushareiplay.core.base_command import BaseCommand
from ushareiplay.modules.playback.domain import PLAY_MODE_INVALID_PARAMETER_ERROR


class ModeCommand(BaseCommand):
    """`:mode 0|1|-1` —— 顺序播放 / 单曲循环 / 随机播放，交给 `SetPlayMode` 用例。"""

    handler_attr = "music_handler"
    error_message = "Mode change failed: {error}"

    async def do_process(self, message_info, parameters):
        if len(parameters) == 0:
            return {"error": "Missing mode parameter"}
        mode, err = self.coerce_int(
            parameters[0], error=PLAY_MODE_INVALID_PARAMETER_ERROR
        )
        if err or mode not in [0, 1, -1]:
            return {"error": PLAY_MODE_INVALID_PARAMETER_ERROR}

        return await self.controller.set_play_mode.execute(mode)
