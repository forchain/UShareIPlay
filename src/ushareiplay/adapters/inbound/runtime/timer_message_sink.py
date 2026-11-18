"""定时器消息的队列适配器：把领域消息落成运行时队列认识的 MessageInfo。"""

from ushareiplay.models.message_info import MessageInfo
from ushareiplay.modules.timer.ports import TimerMessageSink


class QueueTimerMessageSink(TimerMessageSink):
    def __init__(self, queue):
        self._queue = queue

    async def enqueue(
        self, content: str, *, nickname: str = "Timer", sleep_exempt: bool = True
    ) -> None:
        await self._queue.put_message(
            MessageInfo(
                content=content,
                nickname=nickname,
                # 定时器是房主事先排好的计划（夜间助眠歌单等），不是听众的临时
                # 请求，因此不受睡眠保护拦截。
                sleep_exempt=sleep_exempt,
            )
        )
