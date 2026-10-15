from ushareiplay.core.base_command import BaseCommand


class ModeCommand(BaseCommand):
    """`:mode 0|1|-1` —— 顺序播放 / 单曲循环 / 随机播放。

    命令层只做参数校验并转交 `MusicManager.set_play_mode()`：播放页怎么进、
    模式按钮怎么点、当前模式怎么读，都是 UI 层的事（#423）。
    """

    handler_attr = 'music_handler'
    error_message = 'Mode change failed: {error}'

    async def do_process(self, message_info, parameters):
        if len(parameters) == 0:
            return {
                'error': 'Missing mode parameter'
            }
        mode, err = self.coerce_int(parameters[0], error='Invalid mode parameter, must be 0, 1 or -1')
        if err or mode not in [0, 1, -1]:
            return {
                'error': 'Invalid mode parameter, must be 0, 1 or -1'
            }

        return await self.music_manager.set_play_mode(mode)
