"""Differential seat probing: the only place that keeps the Seat Roster honest.

Probing costs profile popups, so it is strictly differential:

* a seat that just became empty is dropped from the roster with zero clicks;
* an occupant already identified and still sitting there is left alone;
* only newly occupied or still unidentified seats get a popup read.

The engine never decides *when* to run — callers (the opportunistic sync hook in
:class:`~ushareiplay.managers.seat_manager.seat_ui.SeatUIManager`, the passive
debounce detector, the accompany fallback) own that policy.
"""

import traceback
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from ushareiplay.managers.seat_manager.desks import (
    SIDES,
    desk_index_of,
    read_desk,
    seat_number_of,
    side_of,
)
from ushareiplay.managers.seat_manager.roster import (
    SEAT_NUMBERS,
    UNKNOWN_USERNAME,
    SeatChange,
    SeatRoster,
    diff_snapshots,
)
from ushareiplay.managers.seat_manager.roster_format import log_seat_roster
from ushareiplay.state.room_state import is_guest_room

#: Element keys that may render the nickname inside the profile popup.
NAME_ELEMENT_KEYS = ("souler_name", "user_name")


@dataclass
class SyncResult:
    """What one differential sync changed, for callers and tests to inspect."""

    changes: List[SeatChange] = field(default_factory=list)
    probed_seats: List[int] = field(default_factory=list)
    cleared_seats: List[int] = field(default_factory=list)
    blocked_seat: Optional[int] = None


class SeatProbe:
    """Reconciles a :class:`SeatRoster` against the live seat panel."""

    def __init__(
        self,
        handler,
        seat_ui,
        roster: SeatRoster,
        focus_count_provider: Optional[Callable[[], Optional[int]]] = None,
    ):
        self._handler = handler
        self._seat_ui = seat_ui
        self._roster = roster
        self._focus_count_provider = focus_count_provider or _room_focus_count

    @property
    def roster(self) -> SeatRoster:
        return self._roster

    async def sync(
        self,
        seat_desks,
        *,
        focus_count: Optional[int] = None,
        guard_seat: Optional[int] = None,
        full_scan: bool = False,
    ) -> SyncResult:
        """Reconcile the roster against the currently readable desks.

        ``guard_seat`` names a seat the caller is about to act on. When that seat
        is occupied no profile popup is opened at all — the caller already knows
        how to reject the action, and probing would only delay the answer.
        """
        result = SyncResult()
        if not seat_desks or self._handler is None or is_guest_room():
            return result

        if focus_count is None:
            focus_count = self._focus_count_provider()

        before = self._roster.snapshot()

        if full_scan:
            return await self._sync_full_scan(
                seat_desks,
                before=before,
                focus_count=focus_count,
                guard_seat=guard_seat,
            )

        mask = self._read_occupancy_mask(seat_desks)

        result.cleared_seats = self._purge_empty_seats(mask)
        self._mark_unidentified_occupants(mask)

        # Compare against the *previous* cache before committing the new one, so
        # this is a real dirty check rather than a comparison with itself.
        if guard_seat is not None and mask[guard_seat - 1]:
            result.blocked_seat = guard_seat
        elif self._roster.is_stale(focus_count=focus_count, occupancy_mask=mask):
            result.probed_seats = await self._probe_unidentified(seat_desks, mask)

        self._roster.note_occupancy_mask(mask)
        self._roster.note_focus_count(focus_count)
        self._roster.mark_synced()
        result.changes = diff_snapshots(before, self._roster.snapshot())
        if result.changes or result.cleared_seats:
            log_seat_roster(
                self._handler.logger,
                self._roster,
                self._reported_changes(result.changes, result.cleared_seats),
            )
        return result

    async def _sync_full_scan(
        self,
        seat_desks,
        *,
        before: Dict[int, str],
        focus_count: Optional[int],
        guard_seat: Optional[int],
    ) -> SyncResult:
        result = SyncResult()
        rows = [
            (0, (0, 1)),
            (1, (2, 3)),
            (2, (4, 5)),
        ]
        settle = getattr(self._seat_ui, "EXPANSION_SETTLE_SECONDS", 0.0)

        for row_index, desk_indices in rows:
            first_desk = desk_indices[0]
            if first_desk < len(seat_desks):
                self._seat_ui.scroll_to_row(first_desk, seat_desks)
                if settle > 0:
                    await asyncio.sleep(settle)

            for desk_index in desk_indices:
                if desk_index >= len(seat_desks):
                    continue
                try:
                    desk_info = read_desk(self._handler, seat_desks[desk_index])
                except Exception:
                    self._report(
                        f"Failed to read desk {desk_index + 1} during full scan: {traceback.format_exc()}"
                    )
                    continue

                for side in SIDES:
                    seat_number = seat_number_of(desk_index, side)
                    entry = desk_info.get(side) or {}
                    occupied = bool(entry.get("occupied"))

                    self._roster.note_occupancy(seat_number, occupied)

                    if not occupied:
                        if self._roster.is_occupied(seat_number):
                            removed = self._roster.clear_seat(seat_number)
                            if removed is not None:
                                result.cleared_seats.append(seat_number)
                                self._log_info(
                                    f"Seat {seat_number} became empty; dropped {removed.username} from the roster"
                                )
                        continue

                    # Seat is occupied
                    if guard_seat is not None and seat_number == guard_seat:
                        result.blocked_seat = guard_seat
                        if not self._roster.is_occupied(seat_number):
                            self._roster.set_occupant(
                                seat_number,
                                UNKNOWN_USERNAME,
                                is_owner=bool(entry.get("is_owner")),
                                verified=False,
                            )
                        continue

                    occupant = self._roster.occupant(seat_number)
                    if occupant is not None and occupant.verified:
                        continue

                    self.identify_seat(seat_number, entry)
                    result.probed_seats.append(seat_number)

        # Restore to Row 0 after full scan
        if len(seat_desks) > 0:
            self._seat_ui.scroll_to_row(0, seat_desks)
            if settle > 0:
                await asyncio.sleep(settle)

        self._roster.note_focus_count(focus_count)
        self._roster.mark_synced()
        result.changes = diff_snapshots(before, self._roster.snapshot())
        if result.changes or result.cleared_seats:
            log_seat_roster(
                self._handler.logger,
                self._roster,
                self._reported_changes(result.changes, result.cleared_seats),
            )
        return result

    def _reported_changes(self, changes, cleared_seats) -> List[SeatChange]:
        """Everything the log should explain, departures included.

        A seat freed of somebody we never identified leaves no trace in the
        identity diff, so the reader would otherwise watch a seat go empty in
        the table with nothing in the summary to account for it.
        """
        released = {change.previous_seat for change in changes}
        return list(changes) + [
            SeatChange(username=UNKNOWN_USERNAME, previous_seat=seat, current_seat=None)
            for seat in cleared_seats
            if seat not in released
        ]

    def observe_desk(self, desk_index: int, desk_info) -> List[int]:
        """Fold a freshly read desk row into the roster without opening any popup.

        Called while scrolling a row into view for a targeted action, so that
        seats passing through the viewport are sensed for free.
        """
        changed: List[int] = []
        for side in SIDES:
            seat_number = seat_number_of(desk_index, side)
            entry = desk_info.get(side) or {}
            occupied = bool(entry.get("occupied"))

            self._roster.note_occupancy(seat_number, occupied)
            occupant = self._roster.occupant(seat_number)

            if not occupied:
                if occupant is not None:
                    self._roster.clear_seat(seat_number)
                    changed.append(seat_number)
                continue

            if occupant is not None and occupant.verified:
                continue

            # Somebody we have not identified: the next sync will click the seat.
            self._roster.set_occupant(
                seat_number,
                UNKNOWN_USERNAME,
                is_owner=bool(entry.get("is_owner")),
                verified=False,
            )
            changed.append(seat_number)
        return changed

    def _read_occupancy_mask(self, seat_desks) -> Tuple[bool, ...]:
        """Occupancy of every seat, from element presence alone."""
        mask = list(self._roster.occupancy_mask)
        current_row = getattr(self._seat_ui, "current_row_index", None)
        for desk_index, desk in enumerate(seat_desks):
            if desk_index >= len(SEAT_NUMBERS) // len(SIDES):
                break
            for side in SIDES:
                seat_number = seat_number_of(desk_index, side)
                try:
                    seat_element = self._handler.element_finder.find_child_element(
                        desk, f"{side}_seat", log_failure=False
                    )
                    if seat_element is None:
                        # The desk is scrolled out of the visible viewport.
                        # Preserve existing occupancy state for this seat.
                        continue
                    state = self._handler.element_finder.find_child_element(
                        desk, f"{side}_state", log_failure=False
                    )
                except Exception:
                    self._report(
                        f"Failed to read occupancy of seat {seat_number}: {traceback.format_exc()}"
                    )
                    continue

                if state is not None:
                    mask[seat_number - 1] = True
                elif current_row is None or (desk_index // 2) == current_row:
                    mask[seat_number - 1] = False
                # If state is None and desk is offscreen, preserve existing mask state
        return tuple(mask)

    def _purge_empty_seats(self, mask) -> List[int]:
        """Drop departed occupants. This is the only zero-click update path."""
        cleared: List[int] = []
        for seat_number in SEAT_NUMBERS:
            if mask[seat_number - 1] or not self._roster.is_occupied(seat_number):
                continue
            removed = self._roster.clear_seat(seat_number)
            if removed is not None:
                cleared.append(seat_number)
                self._log_info(
                    f"Seat {seat_number} became empty; dropped {removed.username} from the roster"
                )
        return cleared

    def _mark_unidentified_occupants(self, mask) -> None:
        """Record occupancy for seats we have not identified yet.

        Keeps the roster truthful about *where* people are even when a sync stops
        short of opening popups, so callers can still report a seat as taken.
        """
        for seat_number in SEAT_NUMBERS:
            if not mask[seat_number - 1] or self._roster.is_occupied(seat_number):
                continue
            self._roster.set_occupant(seat_number, UNKNOWN_USERNAME, verified=False)

    async def _probe_unidentified(self, seat_desks, mask) -> List[int]:
        """Open a profile popup for every occupied seat whose identity we lack."""
        targets: Dict[int, List[str]] = {}
        for seat_number in SEAT_NUMBERS:
            if not mask[seat_number - 1]:
                continue
            occupant = self._roster.occupant(seat_number)
            if occupant is not None and occupant.verified:
                continue
            desk_index = desk_index_of(seat_number)
            if desk_index >= len(seat_desks):
                continue
            targets.setdefault(desk_index, []).append(side_of(seat_number))

        probed: List[int] = []
        for desk_index in sorted(targets):
            self._seat_ui.scroll_to_row(desk_index, seat_desks)
            try:
                desk_info = read_desk(self._handler, seat_desks[desk_index])
            except Exception:
                self._report(
                    f"Failed to read desk {desk_index + 1} for probing: {traceback.format_exc()}"
                )
                continue

            for side in targets[desk_index]:
                seat_number = seat_number_of(desk_index, side)
                entry = desk_info.get(side) or {}
                if not entry.get("occupied"):
                    # The occupant left while the row was scrolling; the next
                    # occupancy read settles it.
                    continue
                self.identify_seat(seat_number, entry)
                probed.append(seat_number)
        return probed

    def identify_seat(self, seat_number: int, entry) -> str:
        """Read one seat's occupant and record it, at a cost of one profile popup.

        Shared by the differential probe and by targeted workflows that need to
        confirm a single seat without probing the whole panel.
        """
        username = self._identify_occupant(entry)
        self._roster.set_occupant(
            seat_number,
            username,
            is_owner=bool(entry.get("is_owner")),
            verified=True,
        )
        return username

    def _identify_occupant(self, entry) -> str:
        state_element = entry.get("state")
        if state_element is None:
            return UNKNOWN_USERNAME

        # Only dismiss what actually opened: a Back press on the room itself can
        # be read as "leave the party", and a failed click opens no popup.
        popup_opened = False
        try:
            state_element.click()
            popup_opened = True
            _key, name_element = self._handler.element_finder.wait_for_any_element(
                list(NAME_ELEMENT_KEYS)
            )
            username = (name_element.text or "").strip() if name_element is not None else ""
            return username or UNKNOWN_USERNAME
        except Exception:
            self._report(
                f"Failed to identify the {entry.get('side')} seat occupant: "
                f"{traceback.format_exc()}"
            )
            return UNKNOWN_USERNAME
        finally:
            if popup_opened:
                self._close_popup()

    def _close_popup(self) -> None:
        try:
            self._handler.key_actions.press_back()
        except Exception:
            self._report(f"Failed to dismiss the seat popup: {traceback.format_exc()}")

    def _report(self, message: str) -> None:
        self._handler.log_error(message)

    def _log_info(self, message: str) -> None:
        self._handler.logger.info(message)


def _room_focus_count() -> Optional[int]:
    try:
        from ushareiplay.state.room_state import RoomState

        if not RoomState.is_initialized():
            return None
        return RoomState.instance().focus_count
    except Exception:
        return None
