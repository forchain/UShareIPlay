"""Passive seat change detection: turn room signals into debounced probes.

Two cheap signals tell us the seat panel *may* have changed without looking at
any individual seat:

* ``focus_count`` ("N人专注中") moves when somebody joins or leaves;
* the visible seat containers change when a seat in view is taken or freed.

Neither is precise, and both can flap. So a signal only arms a debounce window;
once the stream has been quiet for that long, one differential probe runs and the
resulting transitions are published as domain events.
"""

import asyncio
import traceback
from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import Callable, Iterable, Optional

from ushareiplay.managers.seat_manager.domain_events import seat_change_event
from ushareiplay.state.room_state import is_guest_room

#: How long the signal stream must stay quiet before a probe is worth running.
DEFAULT_DEBOUNCE_SECONDS = 3.0


class SeatRosterWatcher:
    """Debounces passive room signals into background differential probes."""

    def __init__(
        self,
        handler,
        seat_ui,
        probe,
        *,
        debounce_seconds: float = DEFAULT_DEBOUNCE_SECONDS,
        is_busy: Optional[Callable[[], bool]] = None,
    ):
        self._handler = handler
        self._seat_ui = seat_ui
        self._probe = probe
        self._debounce_seconds = debounce_seconds
        self._is_busy = is_busy or (lambda: _default_is_busy(self._handler))

        self._focus_count = None
        self._occupancy_mask = None
        self._generation = 0
        self._task: Optional[asyncio.Task] = None

    # --- passive signals -------------------------------------------------

    def note_focus_count(self, focus_count: Optional[int]) -> bool:
        """Record focus count without arming a probe.

        Focus count ("N人专注中") tracks room study attendance, not seat
        occupancy. Room headcount movements must never trigger seat expansion.
        """
        if focus_count == self._focus_count:
            return False
        self._focus_count = focus_count
        return False

    def note_occupancy_mask(self, occupancy_mask: Iterable[Optional[bool]]) -> bool:
        """Arm a probe when visible seat occupancy changes.

        Invisible seats (marked None) are ignored and preserve their last-known
        state, so collapsed viewports and transient element coverage never
        trigger false-alarm probes or infinite expansion loops.

        The first observation sets the baseline without expanding seats.
        """
        mask = tuple(occupancy_mask)
        if self._occupancy_mask is None:
            self._occupancy_mask = mask
            return False

        has_change = False
        new_mask = list(self._occupancy_mask)
        for i, val in enumerate(mask):
            if val is None:
                continue
            prev_val = self._occupancy_mask[i]
            if prev_val is not None and prev_val != val:
                has_change = True
            new_mask[i] = val

        self._occupancy_mask = tuple(new_mask)
        if not has_change:
            return False

        self._arm()
        return True

    # --- debounce --------------------------------------------------------

    def _arm(self) -> None:
        """(Re)start the quiet window; only the last signal in a burst probes."""
        self._generation += 1
        generation = self._generation
        self._cancel_pending()
        self._task = asyncio.ensure_future(self._probe_after_quiet(generation))

    async def _probe_after_quiet(self, generation: int) -> None:
        try:
            await asyncio.sleep(self._debounce_seconds)
        except asyncio.CancelledError:
            return
        if generation != self._generation:
            return
        try:
            await self.probe_now()
        except Exception:
            # Nobody awaits this task, so a failure here would otherwise surface
            # only as an unretrieved-task warning.
            self._handler.log_error(
                f"Seat roster probe failed: {traceback.format_exc()}"
            )

    def _cancel_pending(self) -> None:
        task = self._task
        if task is not None and not task.done():
            task.cancel()

    async def drain(self) -> None:
        """Wait for the pending debounced probe to finish, if there is one."""
        task = self._task
        if task is None or task.done():
            return
        try:
            await task
        except asyncio.CancelledError:
            return

    async def close(self) -> None:
        """Stop watching: cancel any probe that has not fired yet.

        Cancelling the task itself rather than only bumping the generation keeps
        shutdown from waiting out the debounce window.
        """
        self._generation += 1
        task = self._task
        self._task = None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    # --- the probe itself ------------------------------------------------

    async def probe_now(self):
        """Run one differential probe and publish whatever transitions it found.

        Yields to music and chat commands, never touches a guest room, and always
        leaves the seat panel collapsed so chat scanning is not obstructed. Once
        it runs it holds the UI lock: the panel is open and profile popups are
        being read, so the screen belongs to the probe until it is done.
        """
        if self._probe is None or self._is_busy() or is_guest_room():
            return None

        async with _ui_session(self._handler):
            try:
                result = await self._seat_ui.probe_roster()
            finally:
                await self._seat_ui.collapse_seats()
        if result is not None and self._probe is not None:
            self._occupancy_mask = self._probe.roster.occupancy_mask
        self._publish(result)
        return result

    def _publish(self, result) -> None:
        if result is None:
            return
        for change in result.changes:
            _publish_to_runtime(self._handler, seat_change_event(change))


@asynccontextmanager
async def _ui_session(handler):
    """Hold the UI lock for a whole probe.

    Expanding the panel and reading profile popups rewrites the screen, and
    EventManager's fallback ``press_back`` respects this same lock — so a probe
    that does not hold it can have its popups dismissed from under it. A handler
    without a controller lock (tests, one-off wiring) simply runs unlocked.
    """
    controller = getattr(handler, "controller", None)
    session = getattr(controller, "ui_session", None)
    if not callable(session):
        yield
        return
    async with session("seat_roster_probe"):
        yield


def _publish_to_runtime(handler, event) -> None:
    controller = getattr(handler, "controller", None)
    obs = getattr(controller, "obs", None)
    if obs is None:
        return
    obs.emit(type(event).__name__, level="INFO", ctx=asdict(event))


def _default_is_busy(handler) -> bool:
    """Yield to queued chat commands and to whatever already owns the screen."""
    return _chat_commands_queued() or _ui_is_busy(handler)


def _chat_commands_queued() -> bool:
    """Yield to pending chat commands so audio and replies stay responsive."""
    try:
        from ushareiplay.core.message_queue import MessageQueue

        return MessageQueue.instance().get_queue_size() > 0
    except Exception:
        return False


def _ui_is_busy(handler) -> bool:
    """A command or recovery task holding the UI lock must not be interrupted."""
    controller = getattr(handler, "controller", None)
    runtime = getattr(controller, "event_runtime_context", None)
    is_ui_busy = getattr(runtime, "is_ui_busy", None)
    if not callable(is_ui_busy):
        return False
    try:
        return bool(is_ui_busy())
    except Exception:
        return False
