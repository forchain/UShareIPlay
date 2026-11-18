from ushareiplay.adapters.inbound.chat.base_command import BaseCommand


class PauseCommand(BaseCommand):
    """`:pause [0|1]` —— 暂停/恢复播放，交给 `PauseResume` 用例。"""

    async def do_process(self, message_info, parameters):
        pause_state = None
        if len(parameters) > 0:
            pause_state = int(parameters[0])
            if pause_state not in [0, 1]:
                return {"error": "Invalid parameter, must be 0 or 1"}

        return await self.controller.pause_resume.execute(
            message_info.nickname,
            pause_state,
        )
