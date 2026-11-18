"""`Clock` 的内存替身：时间可读、可手动推进，sleep 立即返回。"""

from datetime import datetime, timedelta

from ushareiplay.modules.shared.ports import Clock


class FakeClock(Clock):
    def __init__(self, current: datetime | None = None):
        self.current = current or datetime(2026, 1, 1, 12, 0, 0)
        self.sleeps: list[float] = []

    def now(self) -> datetime:
        return self.current

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.advance(seconds)

    def advance(self, seconds: float) -> None:
        self.current += timedelta(seconds=seconds)
