from ushareiplay.core.base_command import BaseCommand


class AccompanimentCommand(BaseCommand):
    """`:acc 1|0` —— QQ音乐 K歌伴唱/伴奏模式开关，交给 `SetAccompaniment` 用例。"""

    handler_attr = "music_handler"

    async def do_process(self, message_info, parameters):
        if len(parameters) == 0:
            return {
                "error": "Missing parameter (on:1, off:0) for accompaniment command"
            }

        enable = parameters[0] == "1"
        return await self.controller.set_accompaniment.execute(enable)
