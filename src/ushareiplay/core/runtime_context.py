from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Callable

from ushareiplay.core.ui_session_lease import UISessionLease


@dataclass(frozen=True)
class DriverRecoveryContext:
    reinitialize_driver: Callable[[], bool]
    obs: Any = None

    def emit(self, event: str, **kwargs) -> None:
        if self.obs is not None:
            self.obs.emit(event, **kwargs)


@dataclass(frozen=True)
class EventRuntimeContext:
    lease: UISessionLease
    paused: Callable[[], bool] = lambda: False

    def is_ui_busy(self) -> bool:
        return bool(self.lease.lock.locked())

    def is_paused(self) -> bool:
        return bool(self.paused())

    @asynccontextmanager
    async def ui_session(self, reason: str = ""):
        async with self.lease.acquire(reason):
            yield


@dataclass(frozen=True)
class CommandRuntimeContext:
    lease: UISessionLease
    controller: Any = None

    @property
    def obs(self):
        return getattr(self.controller, "obs", None)

    @asynccontextmanager
    async def ui_session(self, reason: str):
        async with self.lease.acquire(reason):
            yield

    def emit(self, event: str, **kwargs) -> None:
        if self.obs is not None:
            self.obs.emit(event, **kwargs)
