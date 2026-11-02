"""座位账本：12 个号位的域状态与策略，不依赖 Appium / DOM。

`SeatObservationManager` 负责读 DOM、点头像、展开收起；本模块只接收归一化后的读数
（`{seat_number: (desk, side, info)}`，`info` 为字典），维护快照与策略闸门。
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Set, Tuple


@dataclass(frozen=True)
class SeatRescanCooldownPolicy:
    """重扫冷却策略值对象，集中管理各类重扫/补扫的退避时长与时间流逝判定。"""

    rescan_cooldown: float = 3.0
    rescan_retry_cooldown: float = 30.0
    consistency_rescan_cooldown: float = 10.0
    residual_inspect_cooldown: float = 60.0
    # 占座成立但弹窗里始终读不出昵称的号位，两次弹窗之间的最小间隔。
    # 与残留位冷却是两个不同的理由：残留位是「已知是谁、不必再问」，
    # 这里是「问过了、读不出来」，同样不能让每轮被动观测都去点一次头像。
    unknown_identity_probe_cooldown: float = 60.0
    time_fn: Callable[[], float] = time.monotonic

    def is_residual_inspect_cooldown_expired(self, last_inspect_time: float) -> bool:
        return (self.now() - last_inspect_time) >= self.residual_inspect_cooldown

    def is_unknown_probe_cooldown_expired(self, last_probe_time: float) -> bool:
        return (self.now() - last_probe_time) >= self.unknown_identity_probe_cooldown

    def get_cooldown(self, *, last_rescan_ok: bool, consistency_retry_due: bool) -> float:
        cooldown = self.rescan_cooldown if last_rescan_ok else self.rescan_retry_cooldown
        if consistency_retry_due:
            cooldown = max(cooldown, self.consistency_rescan_cooldown)
        return cooldown

    def is_cooldown_expired(
        self,
        last_rescan_time: float,
        *,
        last_rescan_ok: bool,
        consistency_retry_due: bool,
    ) -> bool:
        cooldown = self.get_cooldown(
            last_rescan_ok=last_rescan_ok,
            consistency_retry_due=consistency_retry_due,
        )
        return (self.now() - last_rescan_time) >= cooldown

    def now(self) -> float:
        return self.time_fn()


@dataclass
class SeatObservationGateState:
    """Seat Observation 决策与协调闸门状态，支持单动作整体重置。

    包含 12 个协调字段（另有一个 `lock`，不参与 `reset()` 的语义）：
    - last_focus_count: 最近一次视口/外部同步的专注人数
    - reconciled_focus_count: 最近一次已完成对账的专注人数（防展开收起死循环）
    - scanned_seat_change_fingerprint: 最近一次「去向不明」变更的读数指纹
    - last_rescan_ok: 最近一次全量重扫是否真正落地
    - last_rescan_time: 最近一次重扫执行时刻
    - last_visible_band: 身份未知时可见座位带基线 (几何形状, 内容指纹)
    - band_change_reason: 带变化原因
    - residual_seats: 已确认的残留渲染 {位子: 人}
    - unknown_identity_probed_at: 弹窗读不出昵称的号位的最近一次弹窗时刻 {位子: 时刻}
    - residual_seats_inspected_at: 残留位最近一次弹窗核验时刻 {位子: 时刻}
    - last_scan_fingerprint: 最近一次全量确定的重扫读数指纹
    - consistency_retry_due: 是否欠一次补扫
    """

    last_focus_count: Optional[int] = None
    reconciled_focus_count: Optional[int] = None
    scanned_seat_change_fingerprint: Optional[frozenset] = None
    last_rescan_ok: bool = False
    last_rescan_time: float = 0.0
    last_visible_band: Optional[Tuple] = None
    band_change_reason: Optional[str] = None
    residual_seats: Dict[int, str] = field(default_factory=dict)
    unknown_identity_probed_at: Dict[int, float] = field(default_factory=dict)
    residual_seats_inspected_at: Dict[int, float] = field(default_factory=dict)
    last_scan_fingerprint: Optional[frozenset] = None
    consistency_retry_due: bool = False
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def reset(self) -> None:
        """单动作整体重置所有协调与决策闸门状态回初始默认值。"""
        fresh = SeatObservationGateState()
        for f in self.__dataclass_fields__:
            setattr(self, f, getattr(fresh, f))


@dataclass
class SeatSlot:
    seat_number: int  # 1..12
    occupied: bool = False
    username: Optional[str] = None
    label: str = ""
    is_owner: bool = False

    def copy(self) -> "SeatSlot":
        return SeatSlot(
            seat_number=self.seat_number,
            occupied=self.occupied,
            username=self.username,
            label=self.label,
            is_owner=self.is_owner,
        )


@dataclass(frozen=True)
class SeatSnapshot:
    """12 个号位的只读副本。"""

    seats: Dict[int, SeatSlot]

    def get_seat(self, seat_number: int) -> Optional[SeatSlot]:
        return self.seats.get(seat_number)

    def get_user_seat(self, username: str) -> Optional[int]:
        if not username:
            return None
        for num, slot in self.seats.items():
            if slot.occupied and slot.username == username:
                return num
        return None

    def get_all_seated_users(self) -> Dict[str, int]:
        return {
            slot.username: num
            for num, slot in self.seats.items()
            if slot.occupied and slot.username
        }

    def total_seated(self) -> int:
        return sum(1 for slot in self.seats.values() if slot.occupied)


@dataclass(frozen=True)
class ChangeSet:
    """一轮观测的读数与身份解析计划；分类只发生在 `apply()`。"""

    readings: Dict[int, Tuple[object, str, dict]]
    plan: Optional[IdentityResolutionPlan] = None
    authoritative: bool = False


@dataclass(frozen=True)
class SeatDiff:
    has_changes: bool
    changed_seats: Set[int]
    changed_users: List[str]
    seat_info: Dict[str, dict]
    unexplained: Set[Tuple[int, str]] = field(default_factory=set)


@dataclass
class IdentityResolutionPlan:
    """`_resolve_usernames` 单轮的一次性簿记，供 UI 代理执行弹窗后回填。"""

    observed: Dict[int, Tuple[object, str, dict]]
    residual_seats: Dict[int, str]
    read_claims: Dict[str, int]
    inherited_claims: Dict[str, int]
    claimed: Set[str]
    pending: List[Tuple[int, object, str]]


def claimed_usernames(observed: Dict[int, Tuple[object, str, dict]]) -> Set[str]:
    """本轮读数里已经确定归属的昵称（label 直接读到昵称的那些座位）。"""
    return {
        info["username"]
        for (_desk, _side, info) in observed.values()
        if info.get("occupied") and info.get("username")
    }


def evidence_weight(info: dict) -> int:
    """一份读数对「这个位子到底是谁 / 到底空不空」的回答力度。

    占座且有昵称 > 占座但没读到昵称 > 明确空座 > 什么都没读到。
    """
    if info.get("occupied"):
        return 3 if info.get("username") else 2
    if info.get("is_empty"):
        return 1
    return 0


class SeatLedger:
    """12 号位账本：策略与状态都在这里，UI 动作由观测器执行。

    并发契约：所有公共动词都是同步的，在事件循环里天然原子；但一轮被动观测是
    「observe → 弹窗读身份（await）→ apply」的复合动作，账本是这一段唯一的写者，
    因此由持有它的 `SeatObservationManager` 用闸门锁串行化 apply。锁不跨弹窗的
    await 持有 —— 否则 UI 会话与闸门锁会形成 AB-BA 死锁。`apply()` 因此按**当前**
    快照重新分类，而不是 observe 时刻的旧快照：并发落下的视口同步不会被覆盖。
    """

    DEFAULT_COOLDOWN_POLICY: SeatRescanCooldownPolicy = SeatRescanCooldownPolicy()

    def __init__(
        self,
        *,
        cooldown_policy: Optional[SeatRescanCooldownPolicy] = None,
        gate_state: Optional[SeatObservationGateState] = None,
        logger=None,
        owner_nickname: Optional[Callable[[], Optional[str]]] = None,
        is_room_admin: Optional[Callable[[str], bool]] = None,
        record_room_admin: Optional[Callable[[str], None]] = None,
    ):
        self.cooldown_policy = cooldown_policy or self.DEFAULT_COOLDOWN_POLICY
        self.gate_state = gate_state or SeatObservationGateState()
        self.slots: Dict[int, SeatSlot] = {i: SeatSlot(seat_number=i) for i in range(1, 13)}
        self.logger = logger or logging.getLogger("ushareiplay.seat_ledger")
        self._owner_nickname = owner_nickname or (lambda: None)
        self._is_room_admin = is_room_admin or (lambda _name: False)
        self.record_room_admin_hook = record_room_admin or (lambda _name: None)

    # ------------------------------------------------------------------
    # 三个核心动词
    # ------------------------------------------------------------------

    def snapshot(self) -> SeatSnapshot:
        return SeatSnapshot({num: slot.copy() for num, slot in self.slots.items()})

    def observe(
        self,
        readings: Dict[int, Tuple[object, str, dict]],
        *,
        resolve_identity: bool = True,
        authoritative: bool = False,
    ) -> ChangeSet:
        """对一轮读数做身份策略判定；不落快照、不执行 UI。

        分类（可写 / 可清 / 去向不明）只在 `apply()` 做一次：弹窗回填会在这两步
        之间修改读数，observe 时刻的分类结果必然是过期的。
        """
        plan = self.prepare_identity_resolution(readings) if resolve_identity else None
        return ChangeSet(readings=readings, plan=plan, authoritative=authoritative)

    def apply(self, change: ChangeSet) -> SeatDiff:
        """把 ChangeSet 中可落快照的读数提交进账本，返回结构化差异。"""
        old_slots = self._copy_slots()
        if change.authoritative:
            self._apply_snapshot(change.readings)
            return self._build_diff(old_slots, set(change.readings), unexplained=set())

        writable, clearable, unexplained = self._plan_observation_changes(
            old_slots, change.readings
        )
        to_apply = {
            num: item for num, item in change.readings.items() if num in writable
        }
        if to_apply:
            self._apply_snapshot(to_apply, clearable=clearable)
        return self._build_diff(old_slots, set(to_apply), unexplained=unexplained)

    def apply_viewport(self, readings) -> SeatDiff:
        """视口同步路径：可见读数具有直接 DOM 证据，明确空座即可清空。"""
        old_slots = self._copy_slots()
        self._apply_snapshot(readings, clearable=set(readings))
        return self._build_diff(old_slots, set(readings), unexplained=set())

    # ------------------------------------------------------------------
    # 快照与差异
    # ------------------------------------------------------------------

    def _copy_slots(self) -> Dict[int, SeatSlot]:
        return {k: v.copy() for k, v in self.slots.items()}

    def _build_diff(
        self,
        old_slots: Dict[int, SeatSlot],
        applied: Set[int],
        *,
        unexplained: Set[Tuple[int, str]],
    ) -> SeatDiff:
        has_changes, changed_users, seat_info = self._compute_diff(
            old_slots, self.slots, applied
        )
        return SeatDiff(
            has_changes=has_changes,
            changed_seats=self._changed_seat_numbers(old_slots, self.slots, applied),
            changed_users=changed_users,
            seat_info=seat_info,
            unexplained=unexplained,
        )

    def clear(self) -> None:
        self.slots = {i: SeatSlot(seat_number=i) for i in range(1, 13)}
        self.gate_state.reset()

    def total_seated(self) -> int:
        return sum(1 for slot in self.slots.values() if slot.occupied)

    def get_user_seat(self, username: str) -> Optional[int]:
        return self.snapshot().get_user_seat(username)

    def get_all_seated_users(self) -> Dict[str, int]:
        return self.snapshot().get_all_seated_users()

    def mark_owner_seated(self, seat_number: int, owner_username: str) -> int:
        """房主就座：先腾空旧位子，再写入新位子。返回在座人数增量（0 或 1）。

        增量按操作前后 `total_seated()` 之差计算：换座（旧位腾空、新位落座）与
        原地重记都是 0，只有真正新增一个在座者才是 1。
        """
        before = self.total_seated()
        stale = [
            num
            for num, slot in self.slots.items()
            if num != seat_number
            and slot.occupied
            and (slot.is_owner or slot.username in {owner_username, "群主"})
        ]
        for num in stale:
            old = self.slots[num]
            old.occupied = False
            old.username = None
            old.label = ""
            old.is_owner = False

        slot = self.slots.get(seat_number)
        if slot:
            slot.occupied = True
            slot.username = owner_username
            slot.label = "群主"
            slot.is_owner = True
        return self.total_seated() - before

    # ------------------------------------------------------------------
    # 身份解析（证据来路 / 一人一座位 / 残留渲染 / 未知身份退避）
    # ------------------------------------------------------------------

    def prepare_identity_resolution(
        self, observed: Dict[int, Tuple[object, str, dict]]
    ) -> IdentityResolutionPlan:
        residual_seats = self._prune_residual_records(observed)
        self._prune_unknown_probe_records(observed)

        read_claims: Dict[str, int] = {
            info["username"]: seat_num
            for seat_num, (_desk, _side, info) in observed.items()
            if info.get("occupied") and info.get("username")
        }
        inherited_claims: Dict[str, int] = {}
        claimed = set(read_claims)
        pending: List[Tuple[int, object, str]] = []
        for seat_num, (desk, side, info) in observed.items():
            if not info["occupied"] or info.get("username"):
                if info.get("occupied") and info.get("username") and info.get("label") == "管理":
                    self.record_room_admin(info["username"])
                continue
            residual_name = residual_seats.get(seat_num)
            if residual_name and self._placed_elsewhere(residual_name, seat_num, observed):
                # 处于冷却期内的已知残留位，无需且严禁反复点击头像弹窗（防止高频弹窗骚扰用户）
                last_inspect = self.gate_state.residual_seats_inspected_at.get(seat_num, 0.0)
                if not self.cooldown_policy.is_residual_inspect_cooldown_expired(last_inspect):
                    self._mark_residual_seat(seat_num, info, residual_name)
                    continue
            old_slot = self.slots[seat_num]
            if old_slot.occupied and old_slot.username and old_slot.username not in claimed:
                info["username"] = old_slot.username
                claimed.add(old_slot.username)
                inherited_claims[old_slot.username] = seat_num
                if not info.get("label"):
                    if old_slot.label:
                        info["label"] = old_slot.label
                        info["is_owner"] = old_slot.is_owner
                    elif self._is_known_owner(old_slot.username):
                        info["label"] = "群主"
                        info["is_owner"] = True
                    elif self.is_known_room_admin(old_slot.username):
                        info["label"] = "管理"
                        info["is_owner"] = False
                if info.get("label") == "管理":
                    self.record_room_admin(info["username"])
                continue
            # 占座成立、但上一轮点头像没读出昵称，且还在冷却期内：本轮不再弹窗。
            last_probe = self.gate_state.unknown_identity_probed_at.get(seat_num)
            if (
                last_probe is not None
                and not self.cooldown_policy.is_unknown_probe_cooldown_expired(last_probe)
            ):
                continue
            pending.append((seat_num, desk, side))

        return IdentityResolutionPlan(
            observed=observed,
            residual_seats=residual_seats,
            read_claims=read_claims,
            inherited_claims=inherited_claims,
            claimed=claimed,
            pending=pending,
        )

    def apply_probe_result(
        self, plan: IdentityResolutionPlan, seat_num: int, username: Optional[str]
    ) -> None:
        observed = plan.observed
        info = observed[seat_num][2]
        # 弹窗没读出昵称：记下这次探测时刻，进入退避，挡住下一轮的重复弹窗
        if not username:
            self.gate_state.unknown_identity_probed_at[seat_num] = self.cooldown_policy.now()
        else:
            self.gate_state.unknown_identity_probed_at.pop(seat_num, None)
        residual_name = plan.residual_seats.get(seat_num)
        if residual_name:
            if not self._placed_elsewhere(residual_name, seat_num, observed):
                # 这个人别处已经没有位置了：这里就是他真实的落座处，
                # 残留判定作废（宁可重扫一次，也不能把人从账上抹掉）
                self.gate_state.residual_seats.pop(seat_num, None)
                self.gate_state.residual_seats_inspected_at.pop(seat_num, None)
            elif not username or username == residual_name:
                self._mark_residual_seat(seat_num, info, residual_name)
                self.gate_state.residual_seats_inspected_at[seat_num] = self.cooldown_policy.now()
                return
            else:
                # 残留位上真坐了别人：作废残留记录，按正常落座处理
                self.gate_state.residual_seats.pop(seat_num, None)
                self.gate_state.residual_seats_inspected_at.pop(seat_num, None)
        if not username:
            return
        # 弹窗读出的人本轮在别处有**读到的**证据：该位为换座后的残留渲染
        # （ghost avatar）。一个人不能同时占两个位子，且弹窗证实头像是已落座
        # 之人而非他人，故该位实为空座，清除占座标记，避免虚增在座人数引发
        # 专注人数对账矛盾。
        if username in plan.read_claims:
            self.logger.warning(
                f"Seat {seat_num}: popup shows {username!r}, who is already read on "
                f"another seat this round; clearing ghost/residual occupant on seat {seat_num}"
            )
            self._mark_residual_seat(seat_num, info, username)
            self.gate_state.residual_seats_inspected_at[seat_num] = self.cooldown_policy.now()
            return
        # 冲突对象只是上一轮快照的沿用值：撤销它，旧位子的身份本轮无证据。
        stale_seat = plan.inherited_claims.pop(username, None)
        if stale_seat is not None and stale_seat != seat_num:
            plan.claimed.discard(username)
            stale_info = observed[stale_seat][2]
            stale_info["username"] = None
            stale_info["identity_contested"] = username
            self.logger.warning(
                f"Seat {seat_num}: popup identifies {username!r}; seat {stale_seat} only "
                f"inherited them from the previous snapshot, so the move is unresolved "
                f"there and the full rescan decides"
            )
        info["username"] = username
        plan.claimed.add(username)
        plan.read_claims[username] = seat_num
        if not info.get("label"):
            if self._is_known_owner(username):
                info["label"] = "群主"
                info["is_owner"] = True
            elif self.is_known_room_admin(username):
                info["label"] = "管理"
                info["is_owner"] = False
        if info.get("label") == "管理":
            self.record_room_admin(username)

    # ------------------------------------------------------------------
    # 焦点对账 / 重扫闸门 / 指纹
    # ------------------------------------------------------------------

    def begin_focus_reconciliation(self, target_focus: Optional[int]) -> Tuple[bool, int]:
        """登记本次对账；返回 (是否需要重扫, 当前在座数)。

        返回在座数是因为调用方拼 reason 时还要用它，而这一步已经算过一次。
        """
        if target_focus is None or target_focus == self.gate_state.reconciled_focus_count:
            return False, self.total_seated()
        # 先登记再重扫：重扫耗时十几秒，期间事件轮询还会反复进来
        self.gate_state.reconciled_focus_count = target_focus
        total_seated = self.total_seated()
        return total_seated != target_focus, total_seated

    def rollback_focus_reconciliation(self) -> None:
        self.gate_state.reconciled_focus_count = None

    def begin_rescan(self, fingerprint: Optional[frozenset] = None) -> bool:
        """冷却通过则登记本次重扫并返回 True；否则根本不该扫。"""
        if not self.cooldown_policy.is_cooldown_expired(
            self.gate_state.last_rescan_time,
            last_rescan_ok=self.gate_state.last_rescan_ok,
            consistency_retry_due=self.gate_state.consistency_retry_due,
        ):
            return False
        if fingerprint is not None:
            self.gate_state.scanned_seat_change_fingerprint = fingerprint
        self.gate_state.last_rescan_time = self.cooldown_policy.now()
        return True

    def clear_scanned_fingerprint(self) -> None:
        self.gate_state.scanned_seat_change_fingerprint = None

    def unexplained_scan_fingerprint(
        self,
        unexplained: Set[Tuple[int, str]],
        *,
        already_scanned: bool = False,
    ) -> Optional[frozenset]:
        """去向不明的变更指纹；返回 None 表示本轮不需要再扫。"""
        if not unexplained:
            self.gate_state.scanned_seat_change_fingerprint = None
            return None
        fingerprint = frozenset(unexplained)
        if fingerprint == self.gate_state.scanned_seat_change_fingerprint:
            return None
        if already_scanned:
            # 本轮已经因为专注人数对账全量扫过了，这份读数已经被那次扫描服务过
            self.gate_state.scanned_seat_change_fingerprint = fingerprint
            return None
        return fingerprint

    def verify_focus_consistency(
        self,
        observed: Dict[int, Tuple[object, str, dict]],
        target_focus_count: Optional[int],
    ) -> None:
        """重扫落地不等于对上账：结论与专注人数矛盾时把账重新挂回去，欠一次补扫。"""
        if target_focus_count is None:
            return

        unresolved = [
            seat_num
            for seat_num, (_desk, _side, info) in observed.items()
            if not info.get("occupied") and not info.get("is_empty")
        ]
        if len(observed) != 12 or unresolved:
            # 这一轮没把 12 个位子都读出确定结论，「在座数 != 专注数」不算矛盾：
            # 差值可能只是没看见的位子，不能据此判定表格出错、更不能据此反复展开。
            self.gate_state.last_scan_fingerprint = None
            return

        fingerprint = self._scan_fingerprint(observed)
        same_as_last = fingerprint == self.gate_state.last_scan_fingerprint
        self.gate_state.last_scan_fingerprint = fingerprint

        seated = self.total_seated()
        if seated == target_focus_count:
            self.gate_state.consistency_retry_due = False
            return

        seated_nums = sorted(n for n, s in self.slots.items() if s.occupied)
        if same_as_last:
            self.gate_state.consistency_retry_due = False
            self.logger.warning(
                f"Rescan still disagrees with focus count ({seated} seated vs {target_focus_count}) "
                f"with byte-identical readings; not re-scanning — same DOM yields same answer, "
                f"waiting for new information. seated seats: {seated_nums}"
            )
            return

        self.gate_state.consistency_retry_due = True
        # 账没对上：撤掉「这个人数已经对过账」的登记，让下一轮按补扫冷却再来一次
        self.gate_state.reconciled_focus_count = None
        self.logger.warning(
            f"Rescan is not self-consistent: {seated} seats occupied but focus count is "
            f"{target_focus_count} (occupied: {seated_nums}); ledger reopened, "
            f"will re-scan after {self.cooldown_policy.consistency_rescan_cooldown}s"
        )

    @staticmethod
    def _scan_fingerprint(observed: Dict[int, Tuple[object, str, dict]]) -> frozenset:
        """一次重扫的读数指纹（号位 + 占/空 + label 原文），不含坐标。"""
        return frozenset(
            (
                seat_num,
                bool(info.get("occupied")),
                bool(info.get("is_empty")),
                (info.get("label") or "").strip(),
            )
            for seat_num, (_desk, _side, info) in observed.items()
        )

    # ------------------------------------------------------------------
    # 读数分类与快照提交
    # ------------------------------------------------------------------

    def _plan_observation_changes(
        self,
        old_slots: Dict[int, SeatSlot],
        observed: Dict[int, Tuple[object, str, dict]],
    ) -> Tuple[Set[int], Set[int], Set[Tuple[int, str]]]:
        """把本轮视口读数与快照比对，分成「可以落快照」「视口内换座的旧位」「去向不明」。"""
        writable: Set[int] = set()
        clearable: Set[int] = set()
        unexplained: Set[Tuple[int, str]] = set()
        appears: Dict[int, Optional[str]] = {}
        disappears: Dict[int, Optional[str]] = {}

        for seat_num, (_desk, _side, info) in observed.items():
            old = old_slots.get(seat_num)
            if old is None:
                continue
            if info.get("identity_contested"):
                # 写「还坐着」等于替残留渲染背书（可视范围内换座就是被这样吞掉的），
                # 写「空了」又是拿局部读数猜去向 —— 一律不写，交给全量重扫。
                unexplained.add((seat_num, "contested"))
                continue
            if info["occupied"]:
                new_user = info.get("username")
                if not old.occupied:
                    appears[seat_num] = new_user
                elif old.username and new_user and old.username != new_user:
                    unexplained.add((seat_num, "swap"))
                else:
                    writable.add(seat_num)
            elif info.get("is_empty") and old.occupied:
                disappears[seat_num] = old.username
            # 读不到内容（不可见/渲染缺失）不算变更，保持快照原值

        for seat_num, user in disappears.items():
            matched = None
            if user:
                matched = next((s for s, u in appears.items() if u == user), None)
            if matched is None:
                unexplained.add((seat_num, "disappear"))
            else:
                # 视口内换座：去向已确定，旧位清空 + 新位占座都可以直接落快照
                writable.add(seat_num)
                writable.add(matched)
                clearable.add(seat_num)
                appears.pop(matched)

        for seat_num, user in appears.items():
            stale_seat = bool(user) and any(
                slot.occupied and slot.username == user
                for num, slot in old_slots.items()
                if num != seat_num
            )
            if user is None or stale_seat:
                # 昵称读不出来，或这个人还挂在快照的其它位子上（可能刚从看不见的位子挪过来）
                unexplained.add((seat_num, "appear"))
            else:
                writable.add(seat_num)

        return writable, clearable, unexplained

    def _apply_snapshot(
        self,
        observed: Dict[int, Tuple[object, str, dict]],
        *,
        clearable: Optional[Set[int]] = None,
    ) -> None:
        """落快照。clearable=None 表示权威路径（全量重扫读过全部座位）。"""
        colliding = self._colliding_usernames(observed)
        winner_seats: Dict[str, int] = {}
        for name, seat_nums in colliding.items():
            self.logger.warning(
                f"Seat identity conflict: {name!r} read on seats {sorted(seat_nums)} "
                f"in one observation; resolving to seat with stronger evidence"
            )

            def _score(s_num: int) -> tuple:
                _desk, _side, s_info = observed[s_num]
                is_owner_score = 2 if s_info.get("is_owner") else 0
                has_label = 1 if bool(s_info.get("label", "").strip()) else 0
                weight = evidence_weight(s_info)
                return (is_owner_score, has_label, weight, s_num)

            winner_seats[name] = max(seat_nums, key=_score)

        for seat_num, (desk, side, info) in observed.items():
            slot = self.slots[seat_num]
            if info.get("identity_contested") and clearable is None:
                # 权威路径：这个位子本轮没有自己的身份证据，而快照挂在它上面的人已被
                # 弹窗落在别处 —— 它就是换座后的残留渲染。
                self.logger.warning(
                    f"Seat {seat_num}: residual render after an in-viewport move, clearing "
                    f"(the occupant is accounted for on another seat this round)"
                )
                slot.occupied = False
                slot.username = None
                slot.label = info.get("label", "")
                slot.is_owner = False
                info["occupied"] = False
                info["is_empty"] = True
                # 记下这笔残留：下一轮它还渲染成占座，不能再跟真正的落座处抢身份
                self.gate_state.residual_seats[seat_num] = str(
                    info.get("identity_contested") or ""
                )
                self.gate_state.residual_seats_inspected_at[seat_num] = (
                    self.cooldown_policy.now()
                )
                continue
            if info["occupied"]:
                username = info.get("username")
                if username in colliding:
                    if seat_num == winner_seats[username]:
                        slot.occupied = True
                        slot.username = username
                        self._apply_seat_role(slot, info, username)
                    else:
                        self.logger.warning(
                            f"Seat {seat_num}: clearing ghost duplicate of {username!r} "
                            f"(retained on seat {winner_seats[username]})"
                        )
                        slot.occupied = False
                        slot.username = None
                        slot.label = ""
                        slot.is_owner = False
                        info["occupied"] = False
                        info["is_empty"] = True
                        info["username"] = None
                        info["label"] = ""
                        info["is_owner"] = False
                        # 记下这笔残留：下一轮它还渲染成占座，不能再反复弹窗
                        self.gate_state.residual_seats[seat_num] = username
                        self.gate_state.residual_seats_inspected_at[seat_num] = (
                            self.cooldown_policy.now()
                        )
                    continue
                slot.occupied = True
                slot.username = username
                self._apply_seat_role(slot, info, username)
            elif info.get("is_empty"):
                if clearable is None or seat_num in clearable:
                    slot.occupied = False
                    slot.username = None
                    slot.label = info.get("label", "")
                    slot.is_owner = False
                elif slot.occupied:
                    self.logger.debug(
                        f"Seat {seat_num}: read as empty but not clearable "
                        f"(clearable={clearable}); "
                        f"keeping known occupant {slot.username!r}"
                    )
            else:
                # 不可见/稀疏内容状态（例如仅有 leftBottomView，出了视口或被折叠）
                # 严禁将不可见误认为下座！
                pass

    def _apply_seat_role(self, slot: SeatSlot, info: dict, username: Optional[str]) -> None:
        """应用座位角色（群主/管理/普通）并维护角色状态的一致性与持久性。"""
        new_label = info.get("label", "")
        new_is_owner = info.get("is_owner", False)

        if new_label == "管理":
            slot.label = "管理"
            slot.is_owner = False
            self.record_room_admin(username)
        elif new_is_owner or new_label == "群主":
            slot.is_owner = True
            slot.label = "群主"
        elif new_label and not self._is_seat_number_label(new_label):
            slot.label = new_label
            slot.is_owner = False
        else:
            # new_label 为空（视口被折叠/截断或 label 节点未 dump）或纯数字编号占位
            if self._is_known_owner(username) or (slot.username == username and slot.is_owner):
                slot.is_owner = True
                slot.label = "群主"
            elif self.is_known_room_admin(username) or (
                slot.username == username and slot.label == "管理"
            ):
                slot.label = "管理"
                slot.is_owner = False
                self.record_room_admin(username)
            elif slot.username == username and slot.occupied and slot.label:
                # 同一用户在同一座位，新读数无 label，保留旧 label 与身份
                pass
            else:
                slot.label = ""
                slot.is_owner = False

        info["label"] = slot.label
        info["is_owner"] = slot.is_owner

    @staticmethod
    def _is_seat_number_label(label: str) -> bool:
        return label.isdigit() and 1 <= int(label) <= 12

    @staticmethod
    def _seat_differs(old: SeatSlot, new: SeatSlot) -> bool:
        """同一个号位两次快照之间是否真的变了（占座与否 / 是谁 / label）。"""
        return (
            old.occupied != new.occupied
            or old.username != new.username
            or old.label != new.label
        )

    def _changed_seat_numbers(
        self,
        old_slots: Dict[int, SeatSlot],
        new_slots: Dict[int, SeatSlot],
        observed_seat_numbers: Set[int],
    ) -> Set[int]:
        """本轮落快照后确实变了的号位（座次表着色用）。"""
        return {
            num
            for num in observed_seat_numbers
            if old_slots.get(num)
            and new_slots.get(num)
            and self._seat_differs(old_slots[num], new_slots[num])
        }

    def _compute_diff(
        self,
        old_slots: Dict[int, SeatSlot],
        new_slots: Dict[int, SeatSlot],
        observed_seat_numbers: Set[int],
    ) -> Tuple[bool, List[str], Dict[str, dict]]:
        """比对观测到的座位，产出变更用户与 seat_info（{action} 宏的来源）。"""
        changed_users = []
        seat_info = {}
        has_changes = False
        left_users: Set[str] = set()
        sat_seats: Dict[str, int] = {}

        for num in observed_seat_numbers:
            old = old_slots.get(num)
            new = new_slots.get(num)
            if not old or not new:
                continue

            if self._seat_differs(old, new):
                has_changes = True

            # 检测用户上座
            if not old.occupied and new.occupied and new.username:
                if new.username not in changed_users:
                    changed_users.append(new.username)
                sat_seats[new.username] = num
                seat_info[new.username] = {
                    "seat_number": num,
                    "action": "sit_down",
                }
            # 检测用户离座
            elif old.occupied and not new.occupied and old.username:
                if old.username not in changed_users:
                    changed_users.append(old.username)
                left_users.add(old.username)
                seat_info[old.username] = {
                    "seat_number": num,
                    "action": "leave_seat",
                }
            # 检测换人
            elif (
                old.occupied
                and new.occupied
                and old.username
                and new.username
                and old.username != new.username
            ):
                if old.username not in changed_users:
                    changed_users.append(old.username)
                seat_info[old.username] = {"seat_number": num, "action": "leave_seat"}

                if new.username not in changed_users:
                    changed_users.append(new.username)
                seat_info[new.username] = {"seat_number": num, "action": "sit_down"}

        # 同一次观测里离开又落座 = 换座位，合并成一条 move_seat
        for username in left_users:
            new_seat = sat_seats.get(username)
            if new_seat is not None:
                seat_info[username] = {"seat_number": new_seat, "action": "move_seat"}

        return has_changes, changed_users, seat_info

    # ------------------------------------------------------------------
    # 残留渲染 / 未知身份 / 一人一座位
    # ------------------------------------------------------------------

    def _colliding_usernames(
        self, observed: Dict[int, Tuple[object, str, dict]]
    ) -> Dict[str, List[int]]:
        """同一次观测里被两个及以上座位读到的昵称 -> 号位列表。"""
        seen: Dict[str, List[int]] = {}
        for seat_num, (_desk, _side, info) in observed.items():
            if not info.get("occupied"):
                continue
            username = info.get("username")
            if username:
                seen.setdefault(username, []).append(seat_num)
        return {name: nums for name, nums in seen.items() if len(nums) > 1}

    def _placed_elsewhere(
        self, username: str, seat_num: int, observed: Dict[int, Tuple[object, str, dict]]
    ) -> bool:
        """本轮读数或快照里，这个人是不是在**别的**位子上有位置。"""
        # 1. 优先看本轮视口内其它座位（最新读数）
        for other, (_desk, _side, info) in observed.items():
            if other != seat_num and info.get("occupied") and info.get("username") == username:
                return True
        # 2. 视口外的座位看当前快照
        for other, slot in self.slots.items():
            if (
                other != seat_num
                and other not in observed
                and slot.occupied
                and slot.username == username
            ):
                return True
        return False

    def _mark_residual_seat(self, seat_num: int, info: dict, username: str) -> None:
        """把一个位子判成换座后的残留渲染：本轮读数的"占座"是像素，不是人。"""
        info["occupied"] = False
        info["is_empty"] = True
        info["username"] = None
        info["label"] = ""
        info["is_owner"] = False
        self.gate_state.residual_seats[seat_num] = username

    def _prune_residual_records(
        self, observed: Dict[int, Tuple[object, str, dict]]
    ) -> Dict[int, str]:
        """清掉已经不成立的残留渲染记录，返回本轮仍然在场的：{位子: 人}。"""
        for seat_num in list(self.gate_state.residual_seats):
            username = self.gate_state.residual_seats[seat_num]
            item = observed.get(seat_num)
            if item is not None:
                info = item[2]
                if not info["occupied"]:
                    # 视口内明确读出非占座（面板已重绘），残留作废
                    del self.gate_state.residual_seats[seat_num]
                    self.gate_state.residual_seats_inspected_at.pop(seat_num, None)
                elif info.get("username") and info["username"] != username:
                    # 视口内明确读出新用户，残留作废
                    del self.gate_state.residual_seats[seat_num]
                    self.gate_state.residual_seats_inspected_at.pop(seat_num, None)
            else:
                # 视口外座位：若该用户在快照中已不在任何座位上，残留作废
                if not any(
                    s.occupied and s.username == username for s in self.slots.values()
                ):
                    del self.gate_state.residual_seats[seat_num]
                    self.gate_state.residual_seats_inspected_at.pop(seat_num, None)
        return {
            seat_num: name
            for seat_num, name in self.gate_state.residual_seats.items()
            if seat_num in observed
        }

    def _prune_unknown_probe_records(
        self, observed: Dict[int, Tuple[object, str, dict]]
    ) -> None:
        """清掉不再需要退避的「读不出昵称」记录。"""
        for seat_num in list(self.gate_state.unknown_identity_probed_at):
            item = observed.get(seat_num)
            if item is None:
                del self.gate_state.unknown_identity_probed_at[seat_num]
                continue
            info = item[2]
            if info.get("username") or not info.get("occupied"):
                del self.gate_state.unknown_identity_probed_at[seat_num]

    # ------------------------------------------------------------------
    # 角色
    # ------------------------------------------------------------------

    def _is_known_owner(self, username: Optional[str]) -> bool:
        """检查用户是否为已知群主/房主。"""
        if not username or username == "群主":
            return False
        owner_name = self._owner_nickname()
        if owner_name and username == owner_name:
            return True
        return any(
            s.occupied and s.username == username and (s.is_owner or s.label == "群主")
            for s in self.slots.values()
        )

    def is_known_room_admin(self, username: Optional[str]) -> bool:
        """检查用户是否为已知房间管理员。"""
        if not username or username == "管理":
            return False
        if self._is_room_admin(username):
            return True
        if any(
            s.occupied and s.username == username and s.label == "管理"
            for s in self.slots.values()
        ):
            self.record_room_admin(username)
            return True
        return False

    def record_room_admin(self, username: Optional[str]) -> None:
        """记录用户为房间管理员（由观测器同步至 AdminManager）。"""
        if not username or username == "管理":
            return
        self.record_room_admin_hook(username)
