from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class DriverRecoveryContext:
    reinitialize_driver: Callable[[], bool]
    obs: Any = None

    def emit(self, event: str, **kwargs) -> None:
        if self.obs is not None:
            self.obs.emit(event, **kwargs)


@dataclass(frozen=True)
class EventRuntimeContext:
    ui_lock: Any = None
    controller: Any = None

    def is_ui_busy(self) -> bool:
        if self.ui_lock is None:
            return False
        return bool(self.ui_lock.locked())

    def is_paused(self) -> bool:
        if self.controller is None:
            return False
        ri = getattr(self.controller, "runtime_input", None)
        return bool(ri and ri.paused)

    @asynccontextmanager
    async def ui_session(self, reason: str = ""):
        if self.controller and hasattr(self.controller, "ui_session"):
            async with self.controller.ui_session(reason):
                yield
        elif self.ui_lock:
            await self.ui_lock.acquire()
            try:
                yield
            finally:
                self.ui_lock.release()
        else:
            yield


@dataclass(frozen=True)
class CommandRuntimeContext:
    controller: Any

    @property
    def obs(self):
        return getattr(self.controller, "obs", None)

    @asynccontextmanager
    async def ui_session(self, reason: str):
        async with self.controller.ui_session(reason):
            yield

    def emit(self, event: str, **kwargs) -> None:
        if self.obs is not None:
            self.obs.emit(event, **kwargs)
