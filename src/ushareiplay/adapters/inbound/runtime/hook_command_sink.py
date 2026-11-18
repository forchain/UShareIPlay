"""用户事件钩子的入队出口：把命令作为普通消息交给运行时队列。"""

from ushareiplay.adapters.inbound.runtime.message_queue import MessageQueue
from ushareiplay.models.message_info import MessageInfo
from ushareiplay.modules.room.ports import HookCommandSink


class QueueHookCommandSink(HookCommandSink):
    def __init__(self, queue: MessageQueue):
        self._queue = queue

    async def enqueue(self, content: str, nickname: str) -> None:
        await self._queue.put_message(MessageInfo(content=content, nickname=nickname))
