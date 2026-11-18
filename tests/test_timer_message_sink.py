"""队列出口适配器：定时器消息仍以原样的 MessageInfo 进入 MessageQueue。"""

import pytest

from ushareiplay.adapters.inbound.runtime.timer_message_sink import (
    QueueTimerMessageSink,
)
from ushareiplay.adapters.inbound.runtime.message_queue import MessageQueue


@pytest.mark.asyncio
async def test_queue_sink_preserves_the_timer_message_shape():
    queue = MessageQueue()
    sink = QueueTimerMessageSink(queue)

    await sink.enqueue(":say 晚安")

    messages = await queue.get_all_messages()
    assert len(messages) == 1
    fired = next(iter(messages.values()))
    assert fired.content == ":say 晚安"
    assert fired.nickname == "Timer"
    assert fired.sleep_exempt is True
