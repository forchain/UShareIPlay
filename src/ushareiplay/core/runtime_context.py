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

    def is_ui_busy(self) -> bool:
        if self.ui_lock is None:
            return False
        return bool(self.ui_lock.locked())


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
