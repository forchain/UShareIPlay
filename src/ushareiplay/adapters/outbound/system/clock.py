"""系统时钟：`Clock` 端口的生产实现。"""

import asyncio
from datetime import datetime

from ushareiplay.modules.shared.ports import Clock


class SystemClock(Clock):
    def now(self) -> datetime:
        return datetime.now()

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)
