"""座位切片测试台：按组合根的方式构造 `SeatObservationService` 与 `SeatService`。"""

from __future__ import annotations

from typing import Optional

from ushareiplay.adapters.outbound.appium.soul.seat_invite_driver import SeatInviteDriver
from ushareiplay.adapters.outbound.appium.soul.seat_panel_driver import SeatPanelDriver
from ushareiplay.adapters.outbound.appium.soul.seat_panel_reader import SeatPanelReader
from ushareiplay.adapters.outbound.persistence.seat_reservation_repository import (
    TortoiseSeatReservationRepository,
)
from ushareiplay.adapters.outbound.persistence.user_repository import TortoiseUserRepository
from ushareiplay.modules.room.use_cases import RoomStateService
from ushareiplay.modules.seat.use_cases import SeatObservationService, SeatService
from ushareiplay.modules.shared.roles import RolePolicy


class _SeatPanelWithCustomUI(SeatPanelDriver):
    """测试辅助：把旧式 `seat_ui` 替身（expand_and_find_desks/collapse_seats/scroll_to_row）接到 SeatPanelPort。"""

    def __init__(self, handler, seat_ui, *, panel_reader=None, lease=None):
        super().__init__(handler, panel_reader=panel_reader, lease=lease)
        self._seat_ui = seat_ui

    def is_expanded(self) -> bool:
        if hasattr(self._seat_ui, "check_seats_state"):
            return self._seat_ui.check_seats_state()
        return super().is_expanded()

    async def expand(self) -> bool:
        if hasattr(self._seat_ui, "expand_seats"):
            return await self._seat_ui.expand_seats()
        return await super().expand()

    async def collapse(self) -> bool:
        if hasattr(self._seat_ui, "collapse_seats"):
            return await self._seat_ui.collapse_seats()
        return await super().collapse()

    async def expand_and_find_desk_snapshots(self):
        if hasattr(self._seat_ui, "expand_and_find_desks"):
            desks = await self._seat_ui.expand_and_find_desks()
            return None if desks is None else self.snapshot_desks(desks)
        return await super().expand_and_find_desk_snapshots()

    def scroll_to_row(self, desk_index: int, seat_desks=None, duration: int = 100) -> bool:
        if hasattr(self._seat_ui, "scroll_to_row"):
            resolved = (
                [self._resolve_desk(d) or d for d in seat_desks]
                if seat_desks is not None
                else None
            )
            return self._seat_ui.scroll_to_row(desk_index, resolved, duration=duration)
        return super().scroll_to_row(desk_index, seat_desks, duration=duration)


def build_seat_observation(
    handler=None,
    *,
    seat_ui=None,
    cooldown_policy=None,
    gate_state=None,
    panel_reader=None,
    panel_driver=None,
    lease=None,
    room_state=None,
    room_admins=None,
    on_focus_change=None,
    owner_nickname_provider=None,
) -> SeatObservationService:
    if lease is None and handler is not None:
        ctrl = getattr(handler, "controller", None)
        lease = getattr(ctrl, "ui_session_lease", None)
    if panel_reader is None:
        panel_reader = SeatPanelReader(handler, lease=lease)
    if panel_driver is None:
        if seat_ui is not None:
            panel_driver = _SeatPanelWithCustomUI(
                handler, seat_ui, panel_reader=panel_reader, lease=lease
            )
        else:
            panel_driver = SeatPanelDriver(handler, panel_reader=panel_reader, lease=lease)
    if room_state is None:
        ctrl = getattr(handler, "controller", None) if handler is not None else None
        room_state = getattr(ctrl, "room_state", None)
        if room_state is None:
            room_state = RoomStateService()
    if owner_nickname_provider is None:

        def _owner():
            cfg = getattr(handler, "config", None) if handler is not None else None
            if cfg is None:
                return None
            return RolePolicy(cfg).configured_room_owner or None

        owner_nickname_provider = _owner

    if on_focus_change is None:

        async def _default_on_focus_change(before, after, **kw):
            ctrl = getattr(handler, "controller", None) if handler is not None else None
            cmd_mgr = getattr(ctrl, "command_manager", None) if ctrl is not None else None
            if cmd_mgr is not None:
                await cmd_mgr.notify_focus_count_change(before, after, **kw)

        on_focus_change = _default_on_focus_change

    return SeatObservationService(
        panel=panel_driver,
        room_state=room_state,
        room_admins=room_admins,
        owner_nickname_provider=owner_nickname_provider,
        on_focus_change=on_focus_change,
        cooldown_policy=cooldown_policy,
        gate_state=gate_state,
        logger=getattr(handler, "logger", None),
    )


def build_seat_service(
    handler=None,
    *,
    panel_driver=None,
    observation: Optional[SeatObservationService] = None,
    seat_ui=None,
    invite_driver=None,
    panel_reader=None,
    lease=None,
    room_state=None,
    reservations=None,
    users=None,
    messenger=None,
    resolve_visible_username=None,
    is_user_online=None,
    is_user_or_avatar_online=None,
) -> SeatService:
    if lease is None and handler is not None:
        ctrl = getattr(handler, "controller", None)
        lease = getattr(ctrl, "ui_session_lease", None)
    if panel_reader is None:
        panel_reader = SeatPanelReader(handler, lease=lease)
    if panel_driver is None:
        if seat_ui is not None:
            panel_driver = _SeatPanelWithCustomUI(
                handler, seat_ui, panel_reader=panel_reader, lease=lease
            )
            if isinstance(observation, SeatObservationService) and hasattr(
                observation._panel, "_desk_registry"
            ):
                panel_driver._desk_registry = observation._panel._desk_registry
        elif isinstance(observation, SeatObservationService):
            panel_driver = observation._panel
        else:
            panel_driver = SeatPanelDriver(handler, panel_reader=panel_reader, lease=lease)
    if invite_driver is None:
        invite_driver = SeatInviteDriver(handler)
    if room_state is None:
        ctrl = getattr(handler, "controller", None) if handler is not None else None
        room_state = getattr(ctrl, "room_state", None)
        if room_state is None:
            room_state = RoomStateService()
    if reservations is None:
        reservations = TortoiseSeatReservationRepository()
    if users is None:
        users = TortoiseUserRepository()
    if observation is None:
        observation = build_seat_observation(
            handler,
            panel_reader=panel_reader,
            panel_driver=panel_driver,
            lease=lease,
            room_state=room_state,
        )

    return SeatService(
        panel=panel_driver,
        invite_driver=invite_driver,
        reservations=reservations,
        users=users,
        observation=observation,
        room_state=room_state,
        messenger=messenger,
        resolve_visible_username=resolve_visible_username,
        is_user_online=is_user_online,
        is_user_or_avatar_online=is_user_or_avatar_online,
        logger=getattr(handler, "logger", None),
    )
