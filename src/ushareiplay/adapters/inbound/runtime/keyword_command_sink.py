"""关键字命令的队列适配器：把命令文本落成运行时队列认识的 MessageInfo。"""

from ushareiplay.modules.shared.message_info import MessageInfo
from ushareiplay.modules.command.ports import KeywordCommandQueue


class QueueKeywordCommandSink(KeywordCommandQueue):
    def __init__(self, queue):
        self._queue = queue

    async def enqueue(self, content: str, *, nickname: str, sleep_exempt: bool) -> None:
        await self._queue.put_message(
            MessageInfo(content=content, nickname=nickname, sleep_exempt=sleep_exempt)
        )
