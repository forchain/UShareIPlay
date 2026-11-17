"""可重入的 UI 独占会话租赁：一把锁、按 task 记账的重入深度、暂停闸门。

UI 独占锁原先由 `AppController` 与 `SeatPanelReader` 各记一份深度，读取方还要
隔着接缝探私有属性。本模块把这套语义收进一个可独立构造的对象：谁持有、嵌套了
几层、别人是否占着屏幕，都只问这里。
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Callable, Optional


class UISessionLease:
    """独占 UI 执行权的租赁器。

    Args:
        lock: 底层的 `asyncio.Lock`；缺省自建。
        is_paused: 暂停闸门；返回 True 时任何一次 `acquire()` 都直接抛
            `asyncio.CancelledError`（`!stop` 中断在途 UI 操作）。
        logger: 日志来源；每次获取/释放时按需调用，便于换 handler 后仍写对地方。
    """

    def __init__(
        self,
        lock: Optional[asyncio.Lock] = None,
        is_paused: Optional[Callable[[], bool]] = None,
        logger: Optional[Callable[[], logging.Logger]] = None,
    ):
        self._lock = lock or asyncio.Lock()
        self._is_paused = is_paused
        self._logger = logger
        self._depths: dict[asyncio.Task, int] = {}

    @property
    def lock(self) -> asyncio.Lock:
        return self._lock

    @lock.setter
    def lock(self, value: asyncio.Lock):
        # 换锁即作废旧租约：旧 task 的深度在新锁上没有意义，留着会释放一把没持有的锁。
        self._depths.clear()
        self._lock = value

    @property
    def holds_session(self) -> bool:
        """当前 task 是否持有本租赁。"""
        task = asyncio.current_task()
        return task is not None and self._depths.get(task, 0) > 0

    @property
    def busy_elsewhere(self) -> bool:
        """锁被并非当前 task 的其他流程持有。"""
        if not self._lock.locked():
            return False
        return not self.holds_session

    @asynccontextmanager
    async def acquire(self, reason: str = "", *, skip_if_busy: bool = False):
        """独占 UI 执行权；同 task 嵌套进入直通并计数。

        Yields:
            本次是否真的执行了动作：`skip_if_busy=True` 且别人占着屏幕时
            yield False，调用方据此跳过本轮而不排队等待。
        """
        if self._is_paused is not None and self._is_paused():
            raise asyncio.CancelledError(f"UI session '{reason}' blocked: runtime paused by !stop")

        task = asyncio.current_task()
        depth = self._depths.get(task, 0) if task is not None else 0
        if depth > 0:
            self._depths[task] = depth + 1
            try:
                yield True
            finally:
                new_depth = self._depths[task] - 1
                if new_depth <= 0:
                    self._depths.pop(task, None)
                else:
                    self._depths[task] = new_depth
            return

        if skip_if_busy and self.busy_elsewhere:
            yield False
            return

        await self._lock.acquire()
        if task is not None:
            self._depths[task] = 1
        logger = self._logger() if self._logger is not None else None
        try:
            if logger and reason:
                logger.debug(f"[ui_lock] acquired: {reason}")
            yield True
        finally:
            if task is not None:
                self._depths.pop(task, None)
            if logger and reason:
                logger.debug(f"[ui_lock] released: {reason}")
            self._lock.release()
