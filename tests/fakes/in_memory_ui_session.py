"""`UISession` 的内存替身：单 task 重入计数、skip-if-busy。

shortcut: 并发争抢时不会排队等待（生产租赁会），需要测试排队语义时补上。
"""

import asyncio
from contextlib import asynccontextmanager

from ushareiplay.modules.shared.ports import UISession


class InMemoryUISession(UISession):
    def __init__(self):
        self.reasons: list[str] = []
        self._holder = None
        self._depth = 0

    @property
    def holds_session(self) -> bool:
        return self._holder is not None and self._holder is asyncio.current_task()

    @property
    def busy_elsewhere(self) -> bool:
        return self._holder is not None and not self.holds_session

    @asynccontextmanager
    async def acquire(self, reason: str = "", *, skip_if_busy: bool = False):
        if self.holds_session:
            self._depth += 1
            try:
                yield True
            finally:
                self._depth -= 1
            return

        if skip_if_busy and self.busy_elsewhere:
            yield False
            return

        self._holder = asyncio.current_task()
        self._depth = 1
        self.reasons.append(reason)
        try:
            yield True
        finally:
            self._holder = None
            self._depth = 0
