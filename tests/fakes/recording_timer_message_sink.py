"""`TimerMessageSink` 的记录替身：只记录被投递的到点消息。"""

from ushareiplay.modules.timer.ports import TimerMessageSink


class RecordingTimerMessageSink(TimerMessageSink):
    def __init__(self):
        self.messages: list[dict] = []

    async def enqueue(
        self, content: str, *, nickname: str = "Timer", sleep_exempt: bool = True
    ) -> None:
        self.messages.append(
            {
                "content": content,
                "nickname": nickname,
                "sleep_exempt": sleep_exempt,
            }
        )
