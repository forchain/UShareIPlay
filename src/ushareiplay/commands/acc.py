from ushareiplay.core.base_command import BaseCommand


class AccompanimentCommand(BaseCommand):
    """`:acc 1|0` —— QQ音乐 K歌伴唱/伴奏模式开关。

    命令层只做参数校验并转交 `MusicManager.set_accompaniment()`：播放页怎么进、
    开关是页上直接点还是要进「更多」菜单里滚动着找，都是 UI 层的事（#427）。

    `:acc 1` 开伴唱（伴奏）、`:acc 0` 回到原唱；非 `1` 的参数按 `0` 处理，
    这条解析契约自迁移以来没有变过。
    """

    handler_attr = 'music_handler'

    async def do_process(self, message_info, parameters):
        # Get parameter
        if len(parameters) == 0:
            return {
                'error': 'Missing parameter (on:1, off:0) for accompaniment command'
            }

        enable = parameters[0] == '1'
        return await self.music_manager.set_accompaniment(enable)
