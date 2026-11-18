"""座位业务用例：`SeatObservationService` 与 `SeatService`。

所有外部依赖（面板 UI、邀请弹窗、预约仓储、用户仓储、房间状态、房管名单、
公屏消息、专注变更通知、身份/在线查询）均通过构造函数注入，模块内部不导入
Appium、Tortoise 或任何适配器，也不调用 `.instance()`。
"""

from __future__ import annotations

import asyncio
import logging
import traceback
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Awaitable, Callable, ClassVar, Dict, List, Optional, Set, Tuple

from ushareiplay.modules.room.domain import RoomAdmins, RoomState
from ushareiplay.modules.seat.domain import (
    GUEST_ROOM_CHAT_SCAN_RESULT,
    GUEST_ROOM_EMPTY_DESK_RESULT,
    GUEST_ROOM_ENTRY_CHECK_RESULT,
    GUEST_ROOM_ERROR_RESULT,
    AvatarTapPolicy,
    DeskSnapshot,
    SeatClickPlan,
    guest_room_guard,
    is_seat_number_label,
)
from ushareiplay.modules.seat.ledger import (
    SeatLedger,
    SeatObservationGateState,
    SeatRescanCooldownPolicy,
    claimed_usernames,
    evidence_weight,
)
from ushareiplay.modules.seat.ports import (
    SeatInvitePort,
    SeatPanelPort,
    SeatReservationRepository,
)
from ushareiplay.modules.shared.ports import RoomMessenger
from ushareiplay.modules.user.ports import UserRepository

_OBS_LOGGER = logging.getLogger("ushareiplay.seat_observation")
_SVC_LOGGER = logging.getLogger("ushareiplay.seat_subsystem")


class SeatObservationService:
    """麦位被动观测、全量 12 麦位状态维护、3 排视觉快照日志输出及背离重扫用例。"""

    SEAT_COLOR_OCCUPIED: ClassVar[str] = "\033[1;36m"
    SEAT_COLOR_CHANGED: ClassVar[str] = "\033[1;32m"
    SEAT_COLOR_IDLE: ClassVar[str] = "\033[90m"
    SEAT_COLOR_RESET: ClassVar[str] = "\033[0m"

    _SIDE_SEAT_PARITY: ClassVar[Dict[str, int]] = {"left": 1, "right": 0}

    def __init__(
        self,
        *,
        panel: SeatPanelPort,
        room_state: Optional[RoomState] = None,
        room_admins: Optional[RoomAdmins] = None,
        owner_nickname_provider: Optional[Callable[[], Optional[str]]] = None,
        on_focus_change: Optional[Callable[..., Awaitable[None]]] = None,
        cooldown_policy: Optional[SeatRescanCooldownPolicy] = None,
        gate_state: Optional[SeatObservationGateState] = None,
        logger: Optional[logging.Logger] = None,
    ):
        self._panel = panel
        self.room_state = room_state
        self.room_admins = room_admins
        self._owner_nickname_provider = owner_nickname_provider or (lambda: None)
        self._on_focus_change = on_focus_change
        self._logger = logger or _OBS_LOGGER
        self._last_unexplained: Set[Tuple[int, str]] = set()
        self.ledger = SeatLedger(
            cooldown_policy=cooldown_policy,
            gate_state=gate_state,
            logger=self.logger,
            owner_nickname=self._owner_nickname,
            is_room_admin=self._admin_manager_has,
            record_room_admin=self._admin_manager_add,
        )

    @property
    def logger(self) -> logging.Logger:
        return self._logger

    @logger.setter
    def logger(self, value: logging.Logger) -> None:
        self._logger = value
        self.ledger.logger = value

    def _admin_manager_has(self, username: str) -> bool:
        return self.room_admins.is_admin(username) if self.room_admins is not None else False

    def _admin_manager_add(self, username: str) -> None:
        if self.room_admins is not None:
            self.room_admins.add(username)

    def clear(self) -> None:
        """重置所有麦位状态与决策闸门状态。"""
        self.ledger.clear()
        self._last_unexplained = set()
        self.logger.info("Cleared seat observation snapshot")

    def read_focus_count_from_ui(self) -> Optional[int]:
        """按需读一次界面上的专注人数。"""
        return self._panel.read_focus_count()

    def format_3row_layout(
        self,
        trigger_source: str = "可视区域变更",
        focus_count: Optional[int] = None,
        changed_seats: Optional[Set[int]] = None,
    ) -> str:
        """输出 3 排 12 麦位视觉快照。"""
        if focus_count is None:
            focus_count = self.ledger.gate_state.last_focus_count
        if focus_count is None and self.room_state is not None:
            focus_count = self.room_state.focus_count
        focus_str = str(focus_count) if focus_count is not None else "未知"
        changed_seats = changed_seats or set()

        room_admins = self.room_admins.all() if self.room_admins is not None else set()

        def format_seat(num: int) -> str:
            slot = self.ledger.slots.get(num)
            if not slot or not slot.occupied:
                return f"{self.SEAT_COLOR_IDLE}[{num}号: 空闲]{self.SEAT_COLOR_RESET}"
            if slot.is_owner:
                name = (
                    f"群主({slot.username})"
                    if slot.username and slot.username != "群主"
                    else "群主"
                )
            else:
                is_admin = (slot.username in room_admins) if slot.username else False
                if not is_admin and (
                    slot.label == "管理" or self.ledger.is_known_room_admin(slot.username)
                ):
                    is_admin = True
                    if slot.username:
                        self.ledger.record_room_admin(slot.username)

                if is_admin:
                    name = (
                        f"管理({slot.username})"
                        if slot.username and slot.username != "管理"
                        else "管理"
                    )
                else:
                    name = slot.username or slot.label or "已占用"
            color = self.SEAT_COLOR_CHANGED if num in changed_seats else self.SEAT_COLOR_OCCUPIED
            return f"{color}[{num}号: {name}]{self.SEAT_COLOR_RESET}"

        lines = [
            f"[FocusSeatObservation] 专注麦位状态变更 (触发源: {trigger_source}, 专注人数: {focus_str}):",
            f"  第一排: {format_seat(1)} {format_seat(2)}  |  {format_seat(3)} {format_seat(4)}",
            f"  第二排: {format_seat(5)} {format_seat(6)}  |  {format_seat(7)} {format_seat(8)}",
            f"  第三排: {format_seat(9)} {format_seat(10)}  |  {format_seat(11)} {format_seat(12)}",
        ]
        return "\n".join(lines)

    def get_user_seat(self, username: str) -> Optional[int]:
        return self.ledger.get_user_seat(username)

    def get_all_seated_users(self) -> Dict[str, int]:
        return self.ledger.get_all_seated_users()

    def _to_snapshots(self, desks: list) -> List[DeskSnapshot]:
        if not desks:
            return []
        if all(isinstance(d, DeskSnapshot) for d in desks):
            return desks
        return self._panel.snapshot_desks(desks)

    def _as_snapshot(self, desk) -> Optional[DeskSnapshot]:
        if desk is None or isinstance(desk, DeskSnapshot):
            return desk
        snaps = self._panel.snapshot_desks([desk])
        return snaps[0] if snaps else None

    def map_desks_to_indices(self, desk_wrappers: list) -> List[Tuple[int, DeskSnapshot]]:
        snapshots = self._to_snapshots(desk_wrappers)
        mapped, _dropped, _source = self._map_desks_with_identity(snapshots)
        return [(desk_idx, desk) for desk_idx, desk, _own in mapped]

    def _map_desks_with_identity(
        self, desks: List[DeskSnapshot], *, band: Optional[str] = None
    ) -> Tuple[List[Tuple[int, DeskSnapshot, bool]], List[Tuple[DeskSnapshot, str]], str]:
        visible_desks: List[DeskSnapshot] = []
        dropped: List[Tuple[DeskSnapshot, str]] = []
        for desk in desks:
            if self._is_desk_visible(desk):
                visible_desks.append(desk)
            else:
                dropped.append((desk, "无麦位 DOM（底座残片或未渲染）"))
        if not visible_desks:
            return [], dropped, "无可见桌位"

        ordered = sorted(visible_desks, key=self._desk_sort_key)

        anchored: Dict[int, int] = {}
        for rank, desk in enumerate(ordered):
            desk_idx = self._detect_desk_index_from_labels(desk)
            if desk_idx is not None and 0 <= desk_idx <= 5:
                anchored[rank] = desk_idx

        offsets = {idx - rank for rank, idx in anchored.items()}
        if len(offsets) == 1:
            offset: Optional[int] = offsets.pop()
            offset_source = f"锚定({offset})"
        else:
            phase_offset = self._band_offset_from_phase(ordered, band, dropped)
            if phase_offset is not None:
                offset = phase_offset
                offset_source = f"相位({band})"
            else:
                offset = None
                offset_source = "锚点矛盾" if offsets else "锚点缺失"

        mapped: List[Tuple[int, DeskSnapshot, bool]] = []
        for rank, desk in enumerate(ordered):
            desk_idx = anchored.get(rank)
            own_seat_number = desk_idx is not None
            if desk_idx is None:
                if offset is None:
                    dropped.append((desk, "身份未知（无锚点）"))
                    continue
                desk_idx = offset + rank
                if not 0 <= desk_idx <= 5:
                    dropped.append((desk, f"推定座位号越界({desk_idx})"))
                    continue
            if band == "top" and desk_idx > 3:
                dropped.append((desk, f"超出顶相位视口(desk_idx={desk_idx})"))
                continue
            if band == "bottom" and desk_idx < 2:
                dropped.append((desk, f"超出底相位视口(desk_idx={desk_idx})"))
                continue
            mapped.append((desk_idx, desk, own_seat_number))

        mapped.sort(key=lambda item: item[0])
        return mapped, dropped, offset_source

    def _band_offset_from_phase(
        self,
        ordered: List[DeskSnapshot],
        band: Optional[str],
        dropped: List[Tuple[DeskSnapshot, str]],
    ) -> Optional[int]:
        if band not in ("top", "bottom") or not ordered:
            return None

        first_key = self._desk_sort_key(ordered[0])
        last_key = self._desk_sort_key(ordered[-1])
        fragment_keys = [
            self._desk_sort_key(desk)
            for desk, _reason in dropped
            if desk.bounds is not None
        ]

        if band == "top":
            if any(key < first_key for key in fragment_keys):
                return None
            return 0
        if any(key > last_key for key in fragment_keys):
            return None
        return 6 - len(ordered)

    @staticmethod
    def _desk_sort_key(desk: DeskSnapshot) -> Tuple[int, int]:
        bounds = desk.bounds
        if isinstance(bounds, dict):
            row_y = (bounds.get("y", 0) // 40) * 40
            x = bounds.get("x", 0)
            return (row_y, x)
        return (0, 0)

    def _label_seat_number(self, desk: DeskSnapshot, side: str) -> Optional[int]:
        reading = desk.left if side == "left" else desk.right
        label_text = reading.label.strip()
        if not is_seat_number_label(label_text):
            return None
        return int(label_text)

    def _seat_number_from_label(self, desk: DeskSnapshot, side: str) -> Optional[int]:
        seat_num = self._label_seat_number(desk, side)
        if seat_num is None or seat_num % 2 != self._SIDE_SEAT_PARITY[side]:
            return None
        return seat_num

    def _detect_desk_index_from_labels(self, desk) -> Optional[int]:
        desk = self._as_snapshot(desk)
        if desk is None:
            return None
        left_raw = self._label_seat_number(desk, "left")
        right_raw = self._label_seat_number(desk, "right")

        if left_raw is not None and right_raw is not None:
            if left_raw % 2 == 0 or right_raw != left_raw + 1:
                return None
            return (left_raw - 1) // 2

        seat_num = self._seat_number_from_label(desk, "left")
        if seat_num is None:
            seat_num = self._seat_number_from_label(desk, "right")
        if seat_num is None:
            return None
        return (seat_num - 1) // 2

    def room_owner_nickname(self) -> Optional[str]:
        return self._owner_nickname()

    def _owner_nickname(self) -> Optional[str]:
        if self.room_state is not None and self.room_state.is_guest_room:
            return None
        try:
            owner = self._owner_nickname_provider()
            return owner if isinstance(owner, str) and owner else None
        except Exception:
            return None

    def _extract_seat_info(
        self, desk, side: str, seat_num: Optional[int] = None
    ) -> dict:
        desk = self._as_snapshot(desk)
        reading = desk.left if side == "left" else desk.right
        label = reading.label

        is_owner = label == "群主"
        username = None
        if is_owner:
            username = self._owner_nickname() or "群主"
        elif label and not label.isdigit() and label not in ("管理", "已占用", "点击入座"):
            username = label

        return {
            "occupied": reading.occupied,
            "is_empty": reading.is_empty,
            "label": label,
            "is_owner": is_owner,
            "username": username,
            "has_state": reading.has_state,
            "has_default": reading.has_default,
            "has_rank": reading.has_rank,
            "avatar_images": reading.avatar_images,
        }

    def _has_desk_content(self, desk) -> bool:
        desk = self._as_snapshot(desk)
        if desk is None:
            return False
        for reading in (desk.left, desk.right):
            if reading.occupied or reading.is_empty or reading.label.strip():
                return True
        return False

    def _is_desk_visible(self, desk) -> bool:
        desk = self._as_snapshot(desk)
        if desk is None or not desk.displayed:
            return False
        return self._has_desk_content(desk)

    async def inspect_occupant(
        self, desk: DeskSnapshot, side: str, seat_number: int
    ) -> Optional[str]:
        if not self._panel.is_handler_ready:
            return None
        self.logger.info(f"Inspecting occupant on seat {seat_number} ({side} side)")
        desk_id = (
            desk.desk_id
            if isinstance(desk, DeskSnapshot)
            else self._panel.snapshot_desks([desk])[0].desk_id
        )
        return await self._panel.read_occupant(desk_id, side, seat_number)

    def _visible_band_signature(self, desks: list) -> Optional[Tuple]:
        desks = self._to_snapshots(desks)
        rows = []
        for desk in sorted(desks or [], key=self._desk_sort_key):
            if not self._has_desk_content(desk):
                continue
            sides = []
            for reading in (desk.left, desk.right):
                sides.append(
                    (
                        reading.label.strip(),
                        int(reading.avatar_images),
                        bool(reading.has_state),
                        bool(reading.has_default),
                        bool(reading.has_rank),
                    )
                )
            rows.append(tuple(sides))
        return tuple(rows) if rows else None

    def _visible_band_geometry_key(self, desks: list) -> Optional[Tuple]:
        desks = self._to_snapshots(desks)
        keys = tuple(
            self._desk_sort_key(desk)
            for desk in sorted(desks or [], key=self._desk_sort_key)
            if self._has_desk_content(desk)
        )
        return keys or None

    def _read_band_baseline(self, desks: List[DeskSnapshot]) -> Tuple:
        geometry = self._visible_band_geometry_key(desks)
        signature = self._visible_band_signature(desks)
        previous = self.ledger.gate_state.last_visible_band
        if signature is not None:
            self.ledger.gate_state.last_visible_band = (geometry, signature)
        return previous, geometry, signature

    def _note_band_change(self, desks: list) -> None:
        desks = self._to_snapshots(desks)
        previous, geometry, signature = self._read_band_baseline(desks)
        if signature is None or previous is None:
            return
        previous_geometry, previous_signature = previous
        if previous_geometry != geometry:
            return
        if previous_signature != signature:
            self.ledger.gate_state.band_change_reason = (
                "Visible seat band changed while seat identity is unknown "
                "(no numeric seat label anchor); triggering full rescan."
            )

    def _read_visible_seats(
        self, desks: list, *, band: Optional[str] = None
    ) -> Dict[int, Tuple[DeskSnapshot, str, dict]]:
        desks = self._to_snapshots(desks)
        mapped, _dropped, _offset_source = self._map_desks_with_identity(desks, band=band)
        observed: Dict[int, Tuple[DeskSnapshot, str, dict]] = {}
        for desk_idx, desk, _self_anchored in mapped:
            for side, offset in (("left", 1), ("right", 2)):
                seat_num = desk_idx * 2 + offset
                observed[seat_num] = (desk, side, self._extract_seat_info(desk, side, seat_num))
        return observed

    async def _resolve_usernames(
        self,
        observed: Dict[int, Tuple[DeskSnapshot, str, dict]],
        plan=None,
    ) -> None:
        plan = plan or self.ledger.prepare_identity_resolution(observed)

        pending = [
            (seat_num, snap, side)
            for seat_num, desk, side in plan.pending
            if (snap := self._as_snapshot(desk)) is not None and snap.interactable
        ]
        if not pending:
            return

        if not self._panel.can_probe_ui:
            self.logger.debug("UI 锁被外部任务持有，本轮座位名片探测跳过")
            return

        async def _inspect_pending():
            for seat_num, desk, side in pending:
                username = await self.inspect_occupant(desk, side, seat_num)
                self.ledger.apply_probe_result(plan, seat_num, username)

        if self._panel.holds_session:
            await _inspect_pending()
        else:
            async with self._panel.session("seat_inspect"):
                await _inspect_pending()

    async def _sync_desks(
        self,
        desks: List[DeskSnapshot],
        trigger_source: str,
        focus_count: Optional[int],
        *,
        notify_after: Optional[int] = None,
    ) -> Tuple[bool, Set[Tuple[int, str]]]:
        observed = self._read_visible_seats(desks)
        if not observed:
            self._note_band_change(desks)
            return False, set()

        self._read_band_baseline(desks)

        change = self.ledger.observe(observed)
        await self._resolve_usernames(observed, change.plan)

        # 锁只罩 apply：observe → 弹窗 → apply 之间不能持锁，否则闸门锁与 UI 会话形成 AB-BA 死锁。
        async with self.ledger.gate_state.lock:
            diff = self.ledger.apply(change)

        if diff.has_changes:
            self.logger.info(
                self.format_3row_layout(
                    trigger_source=trigger_source,
                    focus_count=focus_count,
                    changed_seats=diff.changed_seats,
                )
            )

            if diff.changed_users and self._on_focus_change is not None:
                if notify_after is None:
                    notify_after = self.ledger.total_seated()
                await self._on_focus_change(
                    self.ledger.gate_state.last_focus_count,
                    notify_after,
                    changed_users=diff.changed_users,
                    seat_info=diff.seat_info,
                )

        if focus_count is not None:
            self.ledger.gate_state.last_focus_count = focus_count

        if diff.unexplained != self._last_unexplained:
            self._last_unexplained = set(diff.unexplained)
            if diff.unexplained:
                self.logger.debug(f"[seat-obs] 变更去向不明 {sorted(diff.unexplained)}")

        return diff.has_changes, diff.unexplained

    async def observe_visible_desks(
        self, desk_wrappers: list, current_focus_count: Optional[int] = None
    ) -> bool:
        if not desk_wrappers:
            return False

        desks = self._to_snapshots(desk_wrappers)
        has_changes, unexplained = await self._sync_desks(
            desks,
            "可视区域变更",
            current_focus_count,
        )
        band_change_reason = self.ledger.gate_state.band_change_reason
        self.ledger.gate_state.band_change_reason = None

        target_focus = self._resolve_target_focus(current_focus_count)

        scanned = await self._reconcile_focus_count(target_focus)
        if band_change_reason is not None and not scanned:
            await self._request_full_scan(target_focus=target_focus, reason=band_change_reason)
            if not self.ledger.gate_state.last_rescan_ok:
                self.ledger.gate_state.band_change_reason = band_change_reason
        await self._resolve_unexplained_changes(
            unexplained, target_focus, already_scanned=scanned
        )

        return has_changes

    def _resolve_target_focus(self, current_focus_count: Optional[int]) -> Optional[int]:
        if current_focus_count is not None:
            return current_focus_count
        if self.ledger.gate_state.last_focus_count is not None:
            return self.ledger.gate_state.last_focus_count
        return self.room_state.focus_count if self.room_state is not None else None

    async def on_focus_count(self, before: Optional[int], current_focus_count: int) -> bool:
        self.ledger.gate_state.last_focus_count = current_focus_count
        return await self._reconcile_focus_count(current_focus_count)

    async def _reconcile_focus_count(self, target_focus: Optional[int]) -> bool:
        should_scan, total_seated = self.ledger.begin_focus_reconciliation(target_focus)
        if not should_scan:
            return False

        attempted = await self._request_full_scan(
            target_focus=target_focus,
            reason=(
                f"Focus divergence detected: focus_count={target_focus}, known_seated={total_seated}. "
                "Triggering active expansion rescan."
            ),
        )
        if not attempted or not self.ledger.gate_state.last_rescan_ok:
            self.ledger.rollback_focus_reconciliation()
        return attempted and self.ledger.gate_state.last_rescan_ok

    async def _resolve_unexplained_changes(
        self,
        unexplained: Set[Tuple[int, str]],
        target_focus: Optional[int],
        *,
        already_scanned: bool = False,
    ) -> bool:
        fingerprint = self.ledger.unexplained_scan_fingerprint(
            unexplained, already_scanned=already_scanned
        )
        if fingerprint is None:
            return False
        return await self._request_full_scan(
            target_focus=target_focus,
            fingerprint=fingerprint,
            reason=(
                f"Seat change with unknown destination {sorted(unexplained)}; "
                "triggering full rescan."
            ),
        )

    async def _request_full_scan(
        self,
        *,
        target_focus: Optional[int],
        reason: str,
        fingerprint: Optional[frozenset] = None,
    ) -> bool:
        if not self.ledger.begin_rescan(fingerprint):
            return False
        self.logger.info(reason)
        await self.expand_rescan_and_collapse(target_focus)
        if not self.ledger.gate_state.last_rescan_ok and fingerprint is not None:
            self.ledger.clear_scanned_fingerprint()
        return True

    async def _scan_all_rows_expanded(
        self, initial_desks: List[DeskSnapshot]
    ) -> Dict[int, Tuple[DeskSnapshot, str, dict]]:
        observed_all: Dict[int, Tuple[DeskSnapshot, str, dict]] = {}

        try:
            self._panel.scroll_to_row(0, initial_desks, duration=300)
            await asyncio.sleep(0.3)
        except Exception as e:
            self.logger.debug(f"Scroll to top row failed: {e}")

        top_desks = self._panel.find_on_screen_desks() or initial_desks

        top_observed = self._read_visible_seats(top_desks, band="top")
        await self._resolve_usernames(top_observed)
        observed_all.update(top_observed)

        try:
            self._panel.scroll_to_row(4, top_desks, duration=300)
            await asyncio.sleep(0.3)
        except Exception as e:
            self.logger.debug(f"Scroll to bottom row failed: {e}")

        bottom_desks = self._panel.find_on_screen_desks() or top_desks

        bottom_observed = self._read_visible_seats(bottom_desks, band="bottom")
        for seat_num, item in bottom_observed.items():
            shared = top_observed.get(seat_num)
            if (
                item[2].get("occupied")
                and not item[2].get("username")
                and shared is not None
                and shared[2].get("username")
            ):
                shared_name = shared[2]["username"]
                if shared_name not in claimed_usernames(bottom_observed):
                    item[2]["username"] = shared_name
                    if not item[2].get("label") and shared[2].get("label"):
                        item[2]["label"] = shared[2]["label"]
                        item[2]["is_owner"] = shared[2].get("is_owner", False)

        await self._resolve_usernames(bottom_observed)

        for seat_num, item in bottom_observed.items():
            if seat_num not in observed_all:
                observed_all[seat_num] = item
            elif evidence_weight(item[2]) > evidence_weight(observed_all[seat_num][2]):
                if not item[2].get("label") and observed_all[seat_num][2].get("label"):
                    item[2]["label"] = observed_all[seat_num][2]["label"]
                    item[2]["is_owner"] = observed_all[seat_num][2].get("is_owner", False)
                observed_all[seat_num] = item
            else:
                if not observed_all[seat_num][2].get("label") and item[2].get("label"):
                    observed_all[seat_num][2]["label"] = item[2]["label"]
                    observed_all[seat_num][2]["is_owner"] = item[2].get("is_owner", False)

        try:
            self._panel.scroll_to_row(0, bottom_desks, duration=300)
            await asyncio.sleep(0.2)
        except Exception as e:
            self.logger.debug(f"Reset scroll to top failed: {e}")

        return observed_all

    async def expand_rescan_and_collapse(self, target_focus_count: Optional[int]) -> bool:
        if not self._panel.is_handler_ready:
            return False

        self.ledger.gate_state.last_rescan_ok = False
        self.ledger.gate_state.consistency_retry_due = False

        async with self._panel.session("seat_expansion"):
            try:
                if target_focus_count is None:
                    target_focus_count = self.read_focus_count_from_ui()

                seat_desks = await self._panel.expand_and_find_desk_snapshots()
                if not seat_desks:
                    seat_desks = self._panel.find_on_screen_desks()
                    if not seat_desks:
                        self.logger.warning("Failed to expand seats for full rescan")
                        return False
                    self.logger.warning(
                        f"Seat expansion unavailable; rescanning {len(seat_desks)} on-screen desks"
                    )

                observed = await self._scan_all_rows_expanded(seat_desks)
                if not observed:
                    return False

                async with self.ledger.gate_state.lock:
                    change = self.ledger.observe(
                        observed, resolve_identity=False, authoritative=True
                    )
                    diff = self.ledger.apply(change)
                    self.ledger.gate_state.last_rescan_ok = True

                self.logger.info(
                    self.format_3row_layout(
                        trigger_source="专注人数背离展开重扫",
                        focus_count=target_focus_count,
                        changed_seats=diff.changed_seats,
                    )
                )

                if diff.changed_users and self._on_focus_change is not None:
                    await self._on_focus_change(
                        self.ledger.gate_state.last_focus_count,
                        target_focus_count,
                        changed_users=diff.changed_users,
                        seat_info=diff.seat_info,
                    )

                if target_focus_count is not None:
                    self.ledger.gate_state.last_focus_count = target_focus_count

                self.ledger.verify_focus_consistency(observed, target_focus_count)
                return diff.has_changes

            except Exception:
                self.logger.error(
                    f"Error during expand_rescan_and_collapse: {traceback.format_exc()}"
                )
                return False
            finally:
                try:
                    await self._panel.collapse()
                except Exception as e:
                    self.logger.error(f"Failed to collapse seats after rescan: {e}")

    async def sync_current_viewport(
        self, band: Optional[str] = None, page_source: Optional[str] = None
    ) -> Dict[int, Tuple[DeskSnapshot, str, dict]]:
        desks = self._panel.read_page_source_desks(page_source)
        if not desks:
            return {}

        async with self.ledger.gate_state.lock:
            observed = self._read_visible_seats(desks, band=band)
            if not observed:
                return {}

            for seat_num, (_desk, _side, info) in observed.items():
                if info["occupied"] and not info.get("username"):
                    old_slot = self.ledger.slots.get(seat_num)
                    if old_slot and old_slot.occupied and old_slot.username:
                        info["username"] = old_slot.username

            diff = self.ledger.apply_viewport(observed)

            if diff.has_changes:
                self.logger.info(
                    self.format_3row_layout(
                        trigger_source="视口同步",
                        focus_count=self.ledger.gate_state.last_focus_count,
                        changed_seats=diff.changed_seats,
                    )
                )

            return observed

    def mark_owner_seated(self, seat_number: int, username: Optional[str] = None) -> None:
        owner_username = username or self._owner_nickname() or "群主"
        delta = self.ledger.mark_owner_seated(seat_number, owner_username)

        current = self.ledger.gate_state.last_focus_count
        if current is None and self.room_state is not None:
            current = self.room_state.focus_count

        if current is not None:
            new_count = current + delta
        else:
            new_count = self.ledger.total_seated()

        self.ledger.gate_state.last_focus_count = new_count
        self.ledger.gate_state.reconciled_focus_count = new_count

        if self.room_state is not None:
            self.room_state.focus_count = new_count


class SeatService:
    """座位管理用例：占座、下麦、占座人清退、预约数据流、自动邀请与聊天扫描前收起。"""

    VIEWPORT_SETTLE_SECONDS: ClassVar[float] = 0.5

    def __init__(
        self,
        *,
        panel: SeatPanelPort,
        invite_driver: SeatInvitePort,
        reservations: SeatReservationRepository,
        users: UserRepository,
        observation: Optional[SeatObservationService] = None,
        room_state: Optional[RoomState] = None,
        messenger: Optional[RoomMessenger] = None,
        resolve_visible_username: Optional[Callable[[str], Awaitable[str]]] = None,
        is_user_online: Optional[Callable[[str], bool]] = None,
        is_user_or_avatar_online: Optional[Callable[[str], Awaitable[bool]]] = None,
        logger: Optional[logging.Logger] = None,
    ):
        self._panel = panel
        self._invite_driver = invite_driver
        self._reservations = reservations
        self._users = users
        self._observation = observation
        self._room_state = room_state
        self._messenger = messenger
        self._resolve_visible_username_fn = resolve_visible_username
        self._is_user_online_fn = is_user_online
        self._is_user_or_avatar_online_fn = is_user_or_avatar_online
        self._logger = logger or _SVC_LOGGER
        self.current_desk_index = 0
        self.current_side: Optional[str] = None

    @property
    def room_state(self) -> Optional[RoomState]:
        return self._room_state

    @property
    def observation(self) -> Optional[SeatObservationService]:
        return self._observation

    @property
    def logger(self) -> logging.Logger:
        return self._logger

    def _send_screen_message(self, message: str) -> None:
        if self._messenger is not None:
            self._messenger.send_screen_message(message)

    @asynccontextmanager
    async def _ui_session(self, reason: str):
        async with self._panel.session(reason):
            yield

    # ------------------------------------------------------------------
    # 面板控制与聊天扫描会话
    # ------------------------------------------------------------------

    def check_seats_state(self) -> bool:
        return self._panel.is_expanded()

    async def expand_seats(self) -> bool:
        return await self._panel.expand()

    async def collapse_seats(self) -> bool:
        return await self._panel.collapse()

    async def expand_and_find_desks(self) -> Optional[List[DeskSnapshot]]:
        return await self._panel.expand_and_find_desk_snapshots()

    def scroll_to_row(
        self, desk_index: int, seat_desks: Optional[List[DeskSnapshot]] = None, duration: int = 100
    ) -> bool:
        return self._panel.scroll_to_row(desk_index, seat_desks, duration=duration)

    @guest_room_guard(GUEST_ROOM_CHAT_SCAN_RESULT)
    async def prepare_for_chat_scan(self) -> bool:
        async with self._panel.session("prepare_for_chat_scan", skip_if_busy=True) as held:
            if not held:
                self.logger.debug("UI 锁被持有，座位面板归持锁流程所有，本次聊天扫描不收起面板")
                return True

            if self.check_seats_state():
                return await self.collapse_seats()
            return True

    @asynccontextmanager
    async def chat_scan_session(self):
        if self.room_state is not None and self.room_state.is_guest_room:
            yield
            return
        async with self._panel.session("chat_backfill"):
            try:
                await self.prepare_for_chat_scan()
            except Exception:
                self.logger.error(
                    f"收起座位失败（不影响补漏继续执行）: {traceback.format_exc()}"
                )
            yield

    # ------------------------------------------------------------------
    # 预约管理
    # ------------------------------------------------------------------

    @guest_room_guard(GUEST_ROOM_ERROR_RESULT)
    async def reserve_seat(self, username: str, seat_number: int) -> dict:
        try:
            self.logger.info(
                f"Starting seat reservation process for user {username} on seat {seat_number}"
            )

            user = await self._users.get_or_create(username)
            if not user:
                self.logger.error(f"Failed to get or create user {username}")
                return {"error": f"Failed to get or create user {username}"}
            self.logger.info(
                f"User {username} (level {user.level}) retrieved/created successfully"
            )

            existing_reservation = await self._reservations.get_by_user_id(user.id)
            if existing_reservation:
                self.logger.info(
                    f"Found existing reservation for user {username} on seat {existing_reservation.seat_number}, removing it"
                )
                await self._reservations.remove_by_id(existing_reservation.id)
                self.logger.info("Existing reservation removed successfully")

            existing_seat = await self._reservations.get_by_seat_number(seat_number)
            if existing_seat:
                self.logger.info(
                    f"Seat {seat_number} is already reserved by {existing_seat.username} (level {existing_seat.user_level})"
                )
                if user.level <= existing_seat.user_level:
                    self.logger.warning(
                        f"User {username} (level {user.level}) cannot override reservation of {existing_seat.username} (level {existing_seat.user_level})"
                    )
                    return {
                        "error": f"Seat {seat_number} is already reserved by {existing_seat.username} with level {existing_seat.user_level}"
                    }
                self.logger.info(
                    f"User {username} has higher level ({user.level} > {existing_seat.user_level}), removing existing reservation"
                )
                await self._reservations.remove_by_id(existing_seat.id)
                self.logger.info("Existing reservation removed successfully")

            duration_hours = min(max(user.level, 1), 24)
            self.logger.info(
                f"Creating new reservation: seat {seat_number} for {duration_hours} hours"
            )
            reservation = await self._reservations.create(
                user.id, seat_number, duration_hours
            )
            self.logger.info(
                f"Reservation created successfully: no. {reservation.id} seat {seat_number} for {duration_hours} hours"
            )

            await self.check_user_specific_seat(username, seat_number)
            return {
                "success": f"Successfully reserved seat {seat_number} for {duration_hours} hours"
            }

        except Exception as e:
            self.logger.error(f"Error reserving seat: {traceback.format_exc()}")
            return {"error": f"Failed to reserve seat: {str(e)}"}

    @guest_room_guard(GUEST_ROOM_ERROR_RESULT)
    async def remove_user_reservation(self, username: str) -> dict:
        try:
            user = await self._users.get_or_create(username)
            if not user:
                return {"error": f"Failed to get or create user {username}"}

            reservation = await self._reservations.get_by_user_id(user.id)
            if not reservation:
                return {"error": f"No reservation found for user {username}"}

            await self._reservations.remove_by_id(reservation.id)
            return {
                "success": f"Successfully removed reservation for seat {reservation.seat_number}"
            }

        except Exception as e:
            self.logger.error(f"Error removing reservation: {traceback.format_exc()}")
            return {"error": f"Failed to remove reservation: {str(e)}"}

    # ------------------------------------------------------------------
    # 进房检查与自动邀请
    # ------------------------------------------------------------------

    @guest_room_guard(GUEST_ROOM_ENTRY_CHECK_RESULT)
    async def check_seats_on_entry(self, username: Optional[str] = None) -> None:
        if not self._panel.is_handler_ready:
            self.logger.warning(
                "check_seats_on_entry: handler is None, skipping the entry check"
            )
            return
        if not username:
            self.logger.warning("check_seats_on_entry called without a username")
            return

        try:
            self.logger.debug(f"Starting seat check for user {username}")

            user = await self._users.get_or_create(username)
            user_reservation = await self._reservations.get_by_user_id(user.id)
            if not user_reservation:
                self.logger.debug(f"No reservation found for user {username}")
                await self._auto_invite_to_isolated_desk(username)
                return

            self.logger.info(
                f"Found reservation for user {username} on seat {user_reservation.seat_number}"
            )

            now = datetime.now()
            start_time = user_reservation.start_time
            if start_time.tzinfo is not None:
                start_time = start_time.replace(tzinfo=None)
            end_time = start_time + timedelta(hours=user_reservation.duration_hours)

            if now > end_time:
                self.logger.info(
                    f"Reservation for user {username} has expired, removing it"
                )
                await self._reservations.remove_by_id(user_reservation.id)
                self.logger.info(
                    f"Successfully removed expired reservation for user {username}"
                )
                await self._auto_invite_to_isolated_desk(username)
                return

            duration_hours = min(max(user_reservation.user_level, 1), 24)
            self.logger.info(
                f"Auto-renewing reservation for user {username} (level {user_reservation.user_level}) with duration {duration_hours} hours"
            )
            await self._reservations.update_start_time(user_reservation.id, now)
            self.logger.info(f"Successfully auto-renewed reservation for user {username}")

            refreshed = await self._reservations.get_by_user_id(user.id)
            if not refreshed:
                return

            await self.check_user_specific_seat(username, refreshed.seat_number)

        except Exception:
            self.logger.error(f"Error checking seats: {traceback.format_exc()}")

    async def _auto_invite_to_isolated_desk(self, username: str) -> None:
        if not self._panel.is_handler_ready or not username:
            return

        visible_name = await self._resolve_visible_name(username)
        if not visible_name:
            return

        if await self._is_user_already_seated(username, visible_name=visible_name):
            return

        result = None
        seat_number = None
        async with self._ui_session(f"seat_auto_invite:{username}"):
            try:
                desk = await self.find_verified_isolated_empty_desk()
                if desk:
                    _desk_index, seat_number = desk
                    result = await self.invite_user_to_seat(seat_number, visible_name)
            finally:
                try:
                    await self.collapse_seats()
                except Exception as e:
                    self.logger.error(f"Failed to collapse seats: {e}")

        if not result:
            return

        if result.get("success"):
            self.logger.info(
                f"进房用户 {visible_name} 已自动邀请入座 {seat_number} 号座位"
            )
            self._send_screen_message(f"已邀请 {visible_name} 入座 {seat_number} 号座位")
        else:
            self.logger.info(
                f"自动邀请 {visible_name} 入座 {seat_number} 号座位失败: {result.get('error')}"
            )

    async def _resolve_visible_name(self, username: str) -> str:
        if self._resolve_visible_username_fn is None:
            return username
        try:
            visible = await self._resolve_visible_username_fn(username)
        except Exception as e:
            self.logger.debug(f"解析 {username} 的可见昵称失败，按原名继续: {e}")
            return username
        return visible or username

    async def _is_user_already_seated(
        self, username: str, visible_name: Optional[str] = None
    ) -> bool:
        obs = self.observation
        if obs is None:
            return False

        if visible_name is None:
            visible_name = await self._resolve_visible_name(username)

        user_names = {username.strip().lower()}
        if visible_name:
            user_names.add(visible_name.strip().lower())

        owner_name = obs.room_owner_nickname()
        if owner_name:
            visible_owner = await self._resolve_visible_name(owner_name)
            owner_aliases = {owner_name.strip().lower()}
            if visible_owner:
                owner_aliases.add(visible_owner.strip().lower())
            if user_names & owner_aliases:
                return True

        seats = obs.ledger.slots
        for slot in seats.values():
            if not slot.occupied or not slot.username:
                continue
            if slot.is_owner or slot.label == "群主":
                continue

            slot_norm = slot.username.strip().lower()
            if slot_norm in user_names:
                return True

            if await self._same_identity(slot.username, username):
                if self._is_user_online_fn is not None and self._is_user_online_fn(slot.username):
                    continue
                return True

        return False

    async def _same_identity(self, first: str, second: str) -> bool:
        try:
            return await self._users.is_same_identity(first, second)
        except Exception:
            return False

    async def check_user_specific_seat(self, username: str, seat_number: int) -> None:
        async with self._ui_session(f"seat_check:{seat_number}"):
            self.logger.info("expanding seats for check")
            seat_desks = await self.expand_and_find_desks()
            if not seat_desks:
                return
            self.logger.info(f"found {len(seat_desks)} seat desks")
            self.logger.info(f"checking specific seat {seat_number} for user {username}")

            desk_index = (seat_number - 1) // 2
            self.scroll_to_row(desk_index, seat_desks, duration=1000)
            if desk_index // 2 in (0, 2):
                await asyncio.sleep(0.5)

            await self._handle_occupied_seat(username, seat_desks, seat_number)

    async def _handle_occupied_seat(
        self, username: str, seat_desks: List[DeskSnapshot], seat_number: int
    ) -> None:
        if not self._panel.is_handler_ready:
            return

        side = "left" if seat_number % 2 else "right"
        desk_index = (seat_number - 1) // 2
        desk = seat_desks[desk_index]
        reading = desk.left if side == "left" else desk.right
        has_seat = desk.left_has_seat if side == "left" else desk.right_has_seat

        if not has_seat:
            self.logger.error(f"Cannot find seat element for seat {seat_number}")
            self._send_screen_message(f"Failed to locate seat {seat_number} for {username}")
            return

        if not reading.label:
            self.logger.warning(f"No occupant for seat {seat_number}")
            return
        self.logger.info(f"Found seat {seat_number} with label {reading.label}")

        self._send_screen_message(f"Welcome {username}!")
        await asyncio.sleep(1)

        async with self._panel.avatar_card(
            desk.desk_id, side, seat_number, tap_target=AvatarTapPolicy.SEAT_NODE
        ) as card:
            if card.opened:
                self.logger.info(f"Opened seat {seat_number} card to check the occupant")
            souler_name_text = card.name if card.opened else None
            if not souler_name_text:
                self.logger.error(f"No souler name found for seat {seat_number}")
                self._send_screen_message(f"Failed to verify occupant on seat {seat_number}")
                return

            if souler_name_text == username:
                self.logger.error(f"Souler {username} is already in seat {seat_number}")
                return

            user = await self._users.get_by_username(username)
            souler = await self._users.get_by_username(souler_name_text)
            if user and souler and user.level <= souler.level:
                self.logger.info(
                    f"Souler {souler_name_text} has higher or equal level ({souler.level}) than {username} ({user.level}), skipping"
                )
                self._send_screen_message(
                    f"Cannot seat {username}: Seat {seat_number} occupied by higher level user"
                )
                return

            err = self._panel.click_seat_off_button(seat_number)
            if err:
                self._send_screen_message(f"Unable to manage seat {seat_number} for {username}")
                return

            self.logger.info(
                f"Successfully removed occupant {souler_name_text} from seat {seat_number} by {username}"
            )

    # ------------------------------------------------------------------
    # 占座、下麦、邀请、找搭子、独立空桌
    # ------------------------------------------------------------------

    @guest_room_guard(GUEST_ROOM_ERROR_RESULT)
    async def take_seat(self, seat_number: int) -> dict:
        return await self.sit_at_specific_seat(seat_number)

    async def sit_at_specific_seat(self, seat_number: int) -> dict:
        if not self._panel.is_handler_ready:
            return {"error": "Handler not initialized"}

        if not 1 <= seat_number <= 12:
            return {"error": f"Invalid seat number {seat_number}. Must be between 1 and 12"}

        try:
            obs = self.observation
            plan = await self._prepare_empty_seat_click(seat_number, obs)
            error = self._seat_click_error(plan, seat_number, style="seat")
            if error:
                return {"error": error}

            result = self._panel.confirm_seat()
            if result.get("success"):
                if obs is not None:
                    obs.mark_owner_seated(seat_number)
                if plan.desk_index is not None:
                    self.current_desk_index = plan.desk_index
                self.current_side = plan.side

            return result

        except Exception as e:
            self.logger.error(f"Error sitting at specific seat: {traceback.format_exc()}")
            return {"error": f"Failed to sit at seat {seat_number}: {str(e)}"}
        finally:
            try:
                await self.collapse_seats()
            except Exception as e:
                self.logger.error(f"Failed to collapse seats: {e}")

    async def _prepare_empty_seat_click(
        self,
        seat_number: int,
        obs: Optional[SeatObservationService],
        scroll_duration: int = 100,
    ) -> SeatClickPlan:
        seat_desks = await self.expand_and_find_desks()
        if not seat_desks:
            return SeatClickPlan(reason="no_desks")

        desk_index = (seat_number - 1) // 2
        row_index = desk_index // 2
        side = "left" if seat_number % 2 == 1 else "right"

        band = "bottom" if row_index == 2 else "top"
        scroll_target_desk = desk_index if row_index == 2 else 0

        self.scroll_to_row(scroll_target_desk, seat_desks, duration=scroll_duration)
        await asyncio.sleep(0.3)

        observed = await obs.sync_current_viewport(band=band) if obs is not None else {}
        if not observed or seat_number not in observed:
            return SeatClickPlan(reason="not_in_viewport", desk_index=desk_index, side=side)

        desk, _seat_side, info = observed[seat_number]
        if info.get("occupied"):
            occupied_label = info.get("label") or info.get("username") or "occupant"
            return SeatClickPlan(
                reason="occupied",
                occupied_label=occupied_label,
                desk_index=desk_index,
                side=side,
            )
        if not info.get("is_empty"):
            return SeatClickPlan(reason="unjudgable", desk_index=desk_index, side=side)

        desk_id = (
            desk.desk_id
            if isinstance(desk, DeskSnapshot)
            else self._panel.snapshot_desks([desk])[0].desk_id
        )
        click_err = self._panel.click_empty_seat(desk_id, side)
        if click_err is not None:
            return SeatClickPlan(reason=click_err, desk_index=desk_index, side=side)

        await asyncio.sleep(0.3)
        return SeatClickPlan(
            desk_index=desk_index,
            side=side,
            clicked=True,
        )

    @staticmethod
    def _seat_click_error(plan: SeatClickPlan, seat_number: int, style: str) -> Optional[str]:
        reason = plan.reason
        if reason is None:
            return None
        if reason == "no_desks":
            return "Failed to find seat desks"
        if reason == "no_bounds":
            return f"Could not determine click bounds for seat {seat_number}"
        if reason == "no_gesture":
            return f"Gesture handler cannot click; seat {seat_number} was not selected"
        if style == "invite":
            if reason == "not_in_viewport":
                return f"座位 {seat_number} 无法核验"
            if reason == "occupied":
                return f"座位 {seat_number} 已被占用"
            if reason == "unjudgable":
                return f"座位 {seat_number} 无法核验为空座"
            return f"座位 {seat_number} 无法核验"
        if reason == "occupied":
            return f'Seat {seat_number} is already occupied by {plan.occupied_label or "occupant"}'
        return f"Seat {seat_number} could not be verified in viewport"

    @guest_room_guard(GUEST_ROOM_ERROR_RESULT)
    async def invite_user_to_seat(self, seat_number: int, target_visible_name: str) -> dict:
        if not self._panel.is_handler_ready:
            return {"error": "Handler not initialized"}

        if not isinstance(seat_number, int) or not 1 <= seat_number <= 12:
            return {"error": f"座位号 {seat_number} 无效，必须在 1~12 之间"}

        if not target_visible_name:
            return {"error": "未指定要邀请入座的用户"}

        driver = self._invite_driver
        sheet_possible = False

        async with self._ui_session(f"seat_invite:{seat_number}"):
            try:
                obs = self.observation
                if obs is None:
                    return {"error": f"座位 {seat_number} 无法核验"}

                plan = await self._prepare_empty_seat_click(
                    seat_number, obs, scroll_duration=1000
                )
                error = self._seat_click_error(plan, seat_number, style="invite")
                if error:
                    return {"error": error}
                sheet_possible = plan.clicked

                if not await driver.wait_until_open():
                    self.logger.info(
                        f"点开 {seat_number} 号座位后没有出现「邀请入座」弹窗"
                    )
                    return {"error": "未打开邀请入座弹窗"}

                row = await driver.find_row(target_visible_name)
                if row is None:
                    return {"error": f"未在邀请列表中找到 {target_visible_name}"}
                if not row.invitable:
                    return {"error": f"{target_visible_name} 已在座"}
                if not driver.click_invite(row):
                    return {"error": f"邀请 {target_visible_name} 入座失败"}

                self.logger.info(f"已邀请 {target_visible_name} 入座 {seat_number} 号座位")
                return {"success": f"已邀请 {target_visible_name} 入座 {seat_number} 号座位"}

            except Exception as e:
                self.logger.error(
                    f"邀请 {target_visible_name} 入座 {seat_number} 号座位失败: {e}"
                )
                return {"error": f"邀请 {target_visible_name} 入座失败: {e}"}
            finally:
                if sheet_possible:
                    try:
                        if driver.close():
                            self.logger.info("已关闭邀请入座弹窗")
                    except Exception as e:
                        self.logger.warning(f"关闭邀请入座弹窗失败: {e}")
                try:
                    await self.collapse_seats()
                except Exception as e:
                    self.logger.error(f"Failed to collapse seats: {e}")

    @guest_room_guard(GUEST_ROOM_EMPTY_DESK_RESULT)
    async def find_verified_isolated_empty_desk(self) -> Optional[Tuple[int, int]]:
        async with self._ui_session("seat_empty_desk"):
            return await self._find_verified_isolated_empty_desk()

    async def _find_verified_isolated_empty_desk(self) -> Optional[Tuple[int, int]]:
        obs = self.observation
        if obs is None:
            return None

        candidates = self._isolated_empty_desk_candidates(obs)
        if not candidates:
            return None

        seat_desks = await self.expand_and_find_desks()
        if not seat_desks:
            return None

        for desk_index in candidates:
            row_index = desk_index // 2
            band = "bottom" if row_index == 2 else "top"
            scroll_target_desk = desk_index if row_index == 2 else 0
            self.scroll_to_row(scroll_target_desk, seat_desks, duration=1000)
            await asyncio.sleep(self.VIEWPORT_SETTLE_SECONDS)

            observed = await obs.sync_current_viewport(band=band)
            empty, occupied = self._verify_isolated_empty_desk(observed, desk_index)
            if empty:
                left_seat, right_seat = desk_index * 2 + 1, desk_index * 2 + 2
                self.logger.info(
                    f"选定独立空桌：{desk_index + 1} 号桌（{left_seat}/{right_seat} 号座位都空），"
                    f"推荐座位 {left_seat}"
                )
                return (desk_index, left_seat)
            if occupied:
                self.logger.info(
                    f"缓存座次表已过期：{desk_index + 1} 号桌现场有人在座，改核验下一张候选桌"
                )

        self.logger.debug("没有可用的独立空桌（左右两座都空）")
        return None

    @staticmethod
    def _isolated_empty_desk_candidates(obs: SeatObservationService) -> list:
        seats = obs.ledger.slots
        candidates = []
        for desk_index in range(6):
            left = seats.get(desk_index * 2 + 1)
            right = seats.get(desk_index * 2 + 2)
            if left is None or right is None:
                continue
            if not left.occupied and not right.occupied:
                candidates.append(desk_index)
        return candidates

    @staticmethod
    def _verify_isolated_empty_desk(
        observed: Dict[int, Tuple[DeskSnapshot, str, dict]], desk_index: int
    ) -> Tuple[bool, bool]:
        for side, seat_number in (("left", desk_index * 2 + 1), ("right", desk_index * 2 + 2)):
            entry = (observed or {}).get(seat_number)
            if entry is None:
                return (False, False)
            desk, seat_side, _info = entry
            actual_side = seat_side or side
            reading = desk.left if actual_side == "left" else desk.right
            if reading.occupied:
                return (False, True)
            if not reading.is_empty:
                return (False, False)
        return (True, False)

    @guest_room_guard(GUEST_ROOM_ERROR_RESULT)
    async def find_owner_seat(self, force_relocate: bool = False) -> dict:
        if not self._panel.is_handler_ready:
            return {"error": "Handler not initialized"}

        try:
            seat_desks = await self.expand_and_find_desks()
            if not seat_desks:
                return {"error": "Failed to find seat desks"}

            if self.current_desk_index >= len(seat_desks):
                self.current_desk_index = 0

            owner_position = self._get_owner_position(seat_desks)
            if owner_position:
                self.current_desk_index = owner_position["desk_index"]
                self.current_side = owner_position["side"]

                if owner_position["has_neighbor"] and not force_relocate:
                    self.logger.info(
                        f"Owner already accompanying {owner_position['neighbor_label']} at desk {owner_position['desk_index'] + 1}"
                    )
                    return {"success": "Owner already has a companion"}

            start_index = self.current_desk_index
            if owner_position:
                start_index = (owner_position["desk_index"] + 1) % len(seat_desks)

            scan_order = self._build_scan_order(len(seat_desks), start_index)
            first_empty_candidate = None

            for desk_index in scan_order:
                self.scroll_to_row(desk_index, seat_desks)
                desk = seat_desks[desk_index]
                desk_info = self._collect_desk_info(desk)

                companion_candidate = self._select_companion_candidate(desk_info)
                if companion_candidate:
                    return self._take_seat(
                        desk_index,
                        companion_candidate["seat"],
                        neighbor_label=companion_candidate["neighbor_label"],
                    )

                if not first_empty_candidate:
                    empty_candidate = self._select_empty_candidate(desk_info)
                    if empty_candidate:
                        first_empty_candidate = {
                            "desk_index": desk_index,
                            "seat": empty_candidate,
                        }

            if first_empty_candidate:
                self.scroll_to_row(first_empty_candidate["desk_index"], seat_desks)
                return self._take_seat(
                    first_empty_candidate["desk_index"],
                    first_empty_candidate["seat"],
                )

            return {"error": "No available seats found"}

        except Exception as e:
            self.logger.error(f"Error finding seat: {traceback.format_exc()}")
            return {"error": f"Failed to find seat: {str(e)}"}

    @guest_room_guard(GUEST_ROOM_ERROR_RESULT)
    async def accompany_user(
        self, target_username: str, sender_username: Optional[str] = None
    ) -> dict:
        if not self._panel.is_handler_ready:
            return {"error": "Handler not initialized"}

        try:
            if not await self._same_identity(sender_username or "", target_username):
                if (
                    self._is_user_or_avatar_online_fn is not None
                    and not await self._is_user_or_avatar_online_fn(target_username)
                ):
                    return {"error": f"User {target_username} is not online"}

            seat_desks = await self.expand_and_find_desks()
            if not seat_desks:
                return {"error": "Failed to find seat desks"}

            last_scrolled_row = -1
            for desk_index, desk in enumerate(seat_desks):
                row_index = desk_index // 2
                if row_index != last_scrolled_row:
                    self.scroll_to_row(desk_index, seat_desks)
                    last_scrolled_row = row_index
                desk_info = self._collect_desk_info(desk)

                occupied_sides = []
                if desk_info["left"]["occupied"]:
                    occupied_sides.append("left")
                if desk_info["right"]["occupied"]:
                    occupied_sides.append("right")

                if not occupied_sides:
                    continue

                for side in occupied_sides:
                    other_side = "right" if side == "left" else "left"
                    seat = desk_info[side]
                    other_seat = desk_info[other_side]

                    if seat.get("is_owner"):
                        continue

                    seat_number = desk_index * 2 + (1 if side == "left" else 2)

                    async with self._panel.avatar_card(
                        desk.desk_id, side, seat_number, tap_target=AvatarTapPolicy.STATE_ONLY
                    ) as card:
                        if card.opened:
                            self.logger.info(
                                f"Checked {side} seat at desk {desk_index + 1} to check user"
                            )
                        actual_username = card.name

                    if not actual_username:
                        self.logger.warning(
                            f"No user name found for {side} seat at desk {desk_index + 1}"
                        )
                        continue

                    self.logger.info(
                        f"Found user '{actual_username}' at desk {desk_index + 1}, {side} side"
                    )

                    if not await self._same_identity(target_username, actual_username):
                        continue

                    if other_seat["occupied"]:
                        return {"error": f"User {target_username} has no empty adjacent seat"}

                    self.logger.info(
                        f"Sitting next to {actual_username} at desk {desk_index + 1}, {other_seat['side']} side"
                    )
                    return self._take_seat(
                        desk_index,
                        other_seat,
                        neighbor_label=actual_username,
                    )

            return {"error": f"User {target_username} not found on any seat"}

        except Exception as e:
            self.logger.error(f"Error accompanying user: {traceback.format_exc()}")
            return {"error": f"Failed to accompany user {target_username}: {str(e)}"}
        finally:
            try:
                await self.collapse_seats()
            except Exception as e:
                self.logger.error(f"Failed to collapse seats: {e}")

    @guest_room_guard(GUEST_ROOM_ERROR_RESULT)
    async def remove_seat_occupant(self, seat_number: Optional[int] = None) -> dict:
        if seat_number is None:
            return await self.seat_off_owner()
        return await self.seat_off_specific_seat(seat_number)

    async def seat_off_owner(self) -> dict:
        if not self._panel.is_handler_ready:
            return {"error": "Handler not initialized"}

        try:
            seat_desks = await self.expand_and_find_desks()
            if not seat_desks:
                return {"error": "Failed to find seat desks"}

            for desk_index, desk in enumerate(seat_desks):
                self.scroll_to_row(desk_index, seat_desks)
                desk_info = self._collect_desk_info(desk)

                for seat in (desk_info["left"], desk_info["right"]):
                    if seat.get("is_owner") and seat.get("occupied"):
                        seat_number = desk_index * 2 + (1 if seat["side"] == "left" else 2)
                        return self._panel.seat_off_by_element(
                            desk.desk_id, seat["side"], seat_number
                        )

            self.logger.warning("Owner is not on any seat")
            return {"error": "Owner is not on any seat"}

        except Exception as e:
            self.logger.error(f"Error removing owner from seat: {traceback.format_exc()}")
            return {"error": f"Failed to remove owner from seat: {str(e)}"}

    async def seat_off_specific_seat(self, seat_number: int) -> dict:
        if not self._panel.is_handler_ready:
            return {"error": "Handler not initialized"}

        try:
            desk_index = (seat_number - 1) // 2
            side = "left" if seat_number % 2 == 1 else "right"

            seat_desks = await self.expand_and_find_desks()
            if not seat_desks:
                return {"error": "Failed to find seat desks"}

            if desk_index >= len(seat_desks):
                return {"error": f"Desk {desk_index + 1} does not exist"}

            self.scroll_to_row(desk_index, seat_desks)
            desk = seat_desks[desk_index]
            desk_info = self._collect_desk_info(desk)
            target_seat = desk_info[side]

            if not target_seat.get("occupied"):
                return {"error": f"Seat {seat_number} is empty"}

            return self._panel.seat_off_by_element(desk.desk_id, side, seat_number)

        except Exception as e:
            self.logger.error(f"Error removing seat occupant: {traceback.format_exc()}")
            return {"error": f"Failed to remove occupant from seat {seat_number}: {str(e)}"}

    # ------------------------------------------------------------------
    # 占座内部读数
    # ------------------------------------------------------------------

    def _get_owner_position(self, seat_desks: List[DeskSnapshot]) -> Optional[dict]:
        for index, desk in enumerate(seat_desks):
            desk_info = self._collect_desk_info(desk)
            left = desk_info["left"]
            right = desk_info["right"]

            if left["is_owner"]:
                has_neighbor = right["occupied"] and not right["is_owner"]
                return {
                    "desk_index": index,
                    "side": "left",
                    "has_neighbor": has_neighbor,
                    "neighbor_label": right["label"] if has_neighbor else "",
                }

            if right["is_owner"]:
                has_neighbor = left["occupied"] and not left["is_owner"]
                return {
                    "desk_index": index,
                    "side": "right",
                    "has_neighbor": has_neighbor,
                    "neighbor_label": left["label"] if has_neighbor else "",
                }

        return None

    @staticmethod
    def _collect_desk_info(desk: DeskSnapshot) -> dict:
        return {
            "left": {
                "desk_id": desk.desk_id,
                "has_seat": desk.left_has_seat,
                "occupied": desk.left.occupied,
                "label": desk.left.label,
                "is_owner": desk.left.label == "群主",
                "side": "left",
            },
            "right": {
                "desk_id": desk.desk_id,
                "has_seat": desk.right_has_seat,
                "occupied": desk.right.occupied,
                "label": desk.right.label,
                "is_owner": desk.right.label == "群主",
                "side": "right",
            },
        }

    @staticmethod
    def _select_companion_candidate(desk_info: dict) -> Optional[dict]:
        left = desk_info["left"]
        right = desk_info["right"]

        if right["has_seat"] and left["occupied"] and not left["is_owner"] and not right["occupied"]:
            return {"seat": right, "neighbor_label": left["label"] or "Unknown"}

        if left["has_seat"] and right["occupied"] and not right["is_owner"] and not left["occupied"]:
            return {"seat": left, "neighbor_label": right["label"] or "Unknown"}

        return None

    @staticmethod
    def _select_empty_candidate(desk_info: dict) -> Optional[dict]:
        for seat in (desk_info["left"], desk_info["right"]):
            if seat["has_seat"] and not seat["occupied"] and not seat["is_owner"]:
                return seat
        return None

    @staticmethod
    def _build_scan_order(total_count: int, start_index: int) -> List[int]:
        return [(start_index + offset) % total_count for offset in range(total_count)]

    def _take_seat(
        self, desk_index: int, seat_info: dict, neighbor_label: Optional[str] = None
    ) -> dict:
        if not self._panel.is_handler_ready or not seat_info or not seat_info.get("has_seat"):
            return {"error": "Seat element not available"}

        if neighbor_label:
            self.logger.info(
                f"Accompanying {neighbor_label} at desk {desk_index + 1}, {seat_info['side']} seat"
            )
        else:
            self.logger.info(
                f"Taking empty {seat_info['side']} seat at desk {desk_index + 1}"
            )

        result = self._panel.take_seat_by_element(seat_info["desk_id"], seat_info["side"])
        if result.get("success"):
            self.current_desk_index = desk_index
            self.current_side = seat_info["side"]
        return result
