"""关键字链路的记忆适配器：把 @ 群主发言记入双层用户记忆的短期聊天日志。"""

from ushareiplay.modules.command.ports import ChatLogRecorder


class UserMemoryChatLogRecorder(ChatLogRecorder):
    def __init__(self, memory):
        self._memory = memory

    async def record(self, username: str, content: str) -> None:
        await self._memory.record_chat(username, content)
