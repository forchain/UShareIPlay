"""Appium driver lifecycle module.

Owns the Appium driver instance, the list of subscribers whose ``.driver``
attribute must follow the active driver, and the reentry-guarded recovery
path. ``AppController`` is the orchestration caller that composes this
module and exposes it through the composition root.

Public surface (small, deterministic):
- ``DriverLifecycle.initialize()`` -- build the driver once and start apps.
- ``DriverLifecycle.shutdown()`` -- release the driver without raising.
- ``DriverLifecycle.attach(component)`` -- track a component whose
  ``.driver`` attribute must be kept in sync.
- ``DriverLifecycle.reinitialize()`` -- quit the current driver and build a
  fresh one; guarded against re-entry so callers may invoke it from many
  decorators without stacking restarts.
- ``DriverLifecycle.driver`` -- the current driver (read-only view).

The factory callable and an optional ``on_reinit`` hook are supplied by the
composition root so production wiring stays in one place.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Iterable


class DriverLifecycle:
    """Deep Appium driver lifecycle."""

    def __init__(
        self,
        *,
        factory: Callable[[], Any],
        settings: dict | None = None,
        on_reinit: Callable[[Any], None] | None = None,
        obs: Any = None,
        sleep: Callable[[float], None] = time.sleep,
        recovery_delay: float = 1.0,
    ):
        self._factory = factory
        self._settings = settings or {}
        self._on_reinit = on_reinit
        self._obs = obs
        self._sleep = sleep
        self._recovery_delay = recovery_delay
        self._driver = None
        self._subscribers: list[Any] = []
        self._reentry = False

    @property
    def driver(self):
        return self._driver

    @property
    def subscribers(self) -> list[Any]:
        return list(self._subscribers)

    def initialize(self) -> Any:
        """Create the driver, apply settings, and propagate to existing subscribers."""
        if self._obs is not None:
            self._obs.emit("driver.init.start")
        self._driver = self._factory()
        if self._settings and self._driver is not None:
            self._driver.update_settings(self._settings)
        self._propagate(self._driver)
        if self._obs is not None:
            self._obs.emit("driver.init.ok")
        return self._driver

    def shutdown(self) -> None:
        """Quit the driver. Never raises."""
        if self._driver is None:
            return
        try:
            self._driver.quit()
        except Exception:
            pass
        self._driver = None

    def attach(self, component: Any) -> None:
        """Track a component whose ``.driver`` attribute must follow this lifecycle."""
        if component is None or not hasattr(component, "driver"):
            return
        if component in self._subscribers:
            return
        self._subscribers.append(component)
        if self._driver is not None:
            component.driver = self._driver

    def reinitialize(self) -> bool:
        """Quit, rebuild, and reattach. Reentry-guarded so call sites can
        decorate many methods without stacking driver restarts.
        """
        if self._reentry:
            return False
        self._reentry = True
        try:
            if self._obs is not None:
                self._obs.emit("driver.reinit.start")
            if self._driver is not None:
                try:
                    self._driver.quit()
                except Exception:
                    pass
            self._sleep(self._recovery_delay)
            self._driver = self._factory()
            if self._settings and self._driver is not None:
                self._driver.update_settings(self._settings)
            self._propagate(self._driver)
            if self._on_reinit is not None:
                try:
                    self._on_reinit(self._driver)
                except Exception:
                    pass
            if self._obs is not None:
                self._obs.emit("driver.reinit.ok")
            return True
        except Exception:
            if self._obs is not None:
                self._obs.emit(
                    "driver.reinit.error",
                    level="ERROR",
                    ctx={},
                )
            return False
        finally:
            self._reentry = False

    def _propagate(self, driver: Any) -> None:
        """Assign ``driver`` to every subscriber that follows this lifecycle."""
        for subscriber in list(self._subscribers):
            if hasattr(subscriber, "driver"):
                subscriber.driver = driver
