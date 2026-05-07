from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Iterable

from ushareiplay.core.singleton import Singleton


def _parse_hhmm(value: object) -> dt.time | None:
    if not isinstance(value, str):
        return None
    try:
        parts = value.strip().split(":")
        if len(parts) != 2:
            return None
        hour = int(parts[0])
        minute = int(parts[1])
        return dt.time(hour=hour, minute=minute)
    except (ValueError, TypeError):
        return None


def _parse_enabled(value: object, default: bool) -> bool:
    """
    Parse a config value into a boolean without Python's `bool(x)` pitfalls.

    Supported:
    - bool: returned as-is
    - int: 0 -> False, non-zero -> True
    - str: common true/false spellings (case-insensitive, surrounding whitespace ignored)
    """
    if value is None:
        return default

    # bool is a subclass of int; check it first.
    if isinstance(value, bool):
        return value

    if isinstance(value, int):
        return value != 0

    if isinstance(value, str):
        s = value.strip().lower()
        if s in {"true", "1", "yes", "y", "on"}:
            return True
        if s in {"false", "0", "no", "n", "off"}:
            return False
        return default

    return default


@dataclass(frozen=True)
class _Window:
    start: dt.time
    end: dt.time


class SleepManager(Singleton):
    """
    SleepManager (睡眠模式)

    - Reads config from a merged dict (config.yaml + config.local.yaml result).
    - Provides a guard window check and command blocking decision.
    """

    DEFAULT_ENABLED = True
    DEFAULT_WINDOW_START = dt.time(23, 0)
    DEFAULT_WINDOW_END = dt.time(6, 0)
    DEFAULT_BLOCKED_COMMANDS = (
        "play",
        "next",
        "fav",
        "singer",
        "album",
        "playlist",
        "radio",
    )

    def __init__(self, config: dict | None = None):
        self._config = config or {}

        sleep_cfg = self._config.get("sleep")
        if not isinstance(sleep_cfg, dict):
            sleep_cfg = {}

        self._enabled = _parse_enabled(sleep_cfg.get("enabled"), self.DEFAULT_ENABLED)
        self._override_enabled: bool | None = None

        # Spec prefers sleep.start/end. Keep sleep.window.start/end as a compatible fallback.
        window = sleep_cfg.get("window") or {}
        if not isinstance(window, dict):
            window = {}

        start_raw = sleep_cfg.get("start")
        if start_raw is None:
            start_raw = window.get("start")
        if start_raw is None:
            start_raw = self.DEFAULT_WINDOW_START.strftime("%H:%M")

        end_raw = sleep_cfg.get("end")
        if end_raw is None:
            end_raw = window.get("end")
        if end_raw is None:
            end_raw = self.DEFAULT_WINDOW_END.strftime("%H:%M")

        self._window_start_str = (
            start_raw if isinstance(start_raw, str) else self.DEFAULT_WINDOW_START.strftime("%H:%M")
        )
        self._window_end_str = end_raw if isinstance(end_raw, str) else self.DEFAULT_WINDOW_END.strftime("%H:%M")

        start = _parse_hhmm(start_raw)
        end = _parse_hhmm(end_raw)
        self._window: _Window | None = _Window(start, end) if start and end else None

        blocked = sleep_cfg.get("blocked_commands", self.DEFAULT_BLOCKED_COMMANDS)
        self._blocked_commands = self._normalize_commands(blocked)

    @staticmethod
    def _normalize_commands(value: object) -> set[str]:
        if value is None:
            return set()
        if isinstance(value, (list, tuple, set)):
            items: Iterable[object] = value
        elif isinstance(value, str):
            # Allow comma-separated strings defensively
            items = [s.strip() for s in value.split(",")]
        else:
            return set()

        out: set[str] = set()
        for item in items:
            if isinstance(item, str):
                s = item.strip().lower()
                if s:
                    out.add(s)
        return out

    @classmethod
    def reset_for_tests(cls) -> None:
        """
        Official singleton reset hook for tests.

        Do not use in production code.
        """
        if hasattr(cls, "_instance"):
            delattr(cls, "_instance")

    def set_override(self, enabled: bool | None) -> None:
        if enabled is None:
            self._override_enabled = None
        else:
            self._override_enabled = bool(enabled)

    def get_default_enabled(self) -> bool:
        return self._enabled

    def get_override(self) -> bool | None:
        return self._override_enabled

    @property
    def effective_enabled(self) -> bool:
        if self._override_enabled is not None:
            return self._override_enabled
        return self._enabled

    def _resolve_time(self, now: dt.time | dt.datetime | None) -> dt.time | None:
        if now is None:
            return dt.datetime.now().time()
        if isinstance(now, dt.datetime):
            return now.time()
        if isinstance(now, dt.time):
            return now
        return None

    def is_in_configured_window(self, now: dt.time | dt.datetime | None = None) -> bool:
        """
        Check whether `now` is inside the configured sleep window only.

        This method MUST NOT be affected by enabled/override; it answers purely
        "is the time within the configured window?"
        """
        if self._window is None:
            # Parse failure: safe default is "do not block"
            return False

        t = self._resolve_time(now)
        if t is None:
            return False

        start = self._window.start
        end = self._window.end

        # start == end means "all day"
        if start == end:
            return True

        # Non-cross-midnight window: start <= t < end
        if start < end:
            return start <= t < end

        # Cross-midnight window: [start, 24:00) U [00:00, end)
        return (t >= start) or (t < end)

    def is_in_sleep_window(self, now: dt.time | dt.datetime | None = None) -> bool:
        if not self.effective_enabled:
            return False
        return self.is_in_configured_window(now)

    # Backwards-compatible alias: older code/tests used "guard window".
    def is_in_guard_window(self, now: dt.time | dt.datetime | None = None) -> bool:
        return self.is_in_sleep_window(now)

    def get_window_start_str(self) -> str:
        return self._window_start_str

    def get_window_end_str(self) -> str:
        return self._window_end_str

    def get_window_display(self) -> str:
        return f"{self._window_start_str}-{self._window_end_str}"

    def is_blocked_command(self, command: str, now: dt.time | dt.datetime | None = None) -> bool:
        if not isinstance(command, str):
            return False
        cmd = command.strip().lower()
        if not cmd:
            return False
        if cmd not in self._blocked_commands:
            return False
        return self.is_in_sleep_window(now)

