"""SeatLedger 的纯策略测试：不构造 DOM、ElementWrapper 或 driver。"""

from ushareiplay.managers.seat_manager.seat_ledger import (
    SeatLedger,
    SeatRescanCooldownPolicy,
    SeatSlot,
)


class FakeClock:
    def __init__(self, start: float = 1000.0):
        self.current = start

    def __call__(self) -> float:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += seconds


def _reading(occupied=True, username=None, label="", is_owner=False):
    return (None, "left", {
        "occupied": occupied,
        "is_empty": not occupied,
        "username": username,
        "label": label,
        "is_owner": is_owner,
    })


def _full_readings(*occupied_seats):
    return {
        n: _reading(username=f"U{n}") if n in occupied_seats else _reading(occupied=False, label=str(n))
        for n in range(1, 13)
    }


def test_snapshot_is_an_isolated_copy():
    ledger = SeatLedger()
    ledger._apply_snapshot({1: _reading(username="Alice")})

    snapshot = ledger.snapshot()
    assert snapshot.get_user_seat("Alice") == 1
    assert snapshot.total_seated() == 1

    snapshot.seats[1].username = "Mallory"
    assert ledger.slots[1].username == "Alice"


def test_collision_arbitration_keeps_strongest_evidence_and_records_ghost():
    ledger = SeatLedger()
    observed = {
        1: _reading(username="Bob", label="群主", is_owner=True),
        5: _reading(username="Bob"),
    }

    ledger._apply_snapshot(observed)

    assert ledger.slots[1].occupied is True and ledger.slots[1].username == "Bob"
    assert ledger.slots[5].occupied is False
    assert ledger.gate_state.residual_seats[5] == "Bob"


def test_unknown_identity_probe_backoff_honours_cooldown():
    clock = FakeClock()
    ledger = SeatLedger(cooldown_policy=SeatRescanCooldownPolicy(time_fn=clock))
    observed = {11: _reading()}

    change = ledger.observe(observed)
    assert [seat for seat, _desk, _side in change.plan.pending] == [11]
    ledger.apply_probe_result(change.plan, 11, None)

    assert ledger.observe(observed).plan.pending == []

    clock.advance(61.0)
    assert [seat for seat, _desk, _side in ledger.observe(observed).plan.pending] == [11]


def test_popup_ghost_on_another_seat_becomes_residual_occupant():
    """弹窗认出的人本轮已在别处被读到：这个位子是换座后的残留渲染，不是占座。"""
    ledger = SeatLedger()
    observed = {
        1: _reading(username="Alice"),
        5: _reading(),
    }

    change = ledger.observe(observed)
    ledger.apply_probe_result(change.plan, 5, "Alice")
    applied = ledger.apply(change)

    assert ledger.gate_state.residual_seats[5] == "Alice"
    assert ledger.slots[5].occupied is False
    assert ledger.slots[1].username == "Alice"
    assert observed[5][2]["occupied"] is False
    assert applied.unexplained == set()


def test_known_residual_seat_skips_repeated_popup_during_cooldown():
    """残留位在冷却期内不再点头像；冷却过去后才重新交给全量重扫判定。"""
    clock = FakeClock()
    ledger = SeatLedger(cooldown_policy=SeatRescanCooldownPolicy(time_fn=clock))
    ledger.slots[10] = SeatSlot(seat_number=10, occupied=True, username="Alice")
    ledger.gate_state.residual_seats[2] = "Alice"
    ledger.gate_state.residual_seats_inspected_at[2] = clock.current

    first = ledger.observe({2: _reading()})
    assert first.plan.pending == []
    assert first.readings[2][2]["occupied"] is False

    clock.advance(61.0)
    second = ledger.observe({2: _reading()})
    assert [seat for seat, _desk, _side in second.plan.pending] == [2]


def test_popup_contesting_an_inherited_claim_leaves_the_seat_to_rescan():
    """弹窗把上一轮沿用的身份判到别处：旧位子没有本轮证据，非权威路径不写它。"""
    ledger = SeatLedger()
    ledger.slots[3] = SeatSlot(seat_number=3, occupied=True, username="Alice")
    observed = {
        3: _reading(),
        7: _reading(),
    }

    change = ledger.observe(observed)
    assert observed[3][2]["username"] == "Alice"  # 从上一轮快照沿用

    ledger.apply_probe_result(change.plan, 7, "Alice")
    assert observed[3][2]["identity_contested"] == "Alice"
    assert observed[3][2]["username"] is None

    diff = ledger.apply(change)

    assert (3, "contested") in diff.unexplained
    assert ledger.slots[3].occupied is True and ledger.slots[3].username == "Alice"
    assert ledger.slots[7].occupied is False


def test_authoritative_apply_clears_contested_residual():
    """全量重扫读过全部 12 个位子后，被弹窗判走的旧位子就是残留渲染，必须清空。"""
    ledger = SeatLedger()
    ledger.slots[3] = SeatSlot(seat_number=3, occupied=True, username="Alice")
    observed = _full_readings()
    observed[3] = _reading()
    observed[7] = _reading()

    change = ledger.observe(observed)
    ledger.apply_probe_result(change.plan, 7, "Alice")
    assert observed[3][2]["identity_contested"] == "Alice"

    ledger.apply(ledger.observe(observed, resolve_identity=False, authoritative=True))

    assert ledger.slots[3].occupied is False
    assert ledger.gate_state.residual_seats[3] == "Alice"
    assert ledger.slots[7].username == "Alice"


def test_verify_focus_consistency_branches():
    ledger = SeatLedger()
    observed = _full_readings(1)
    ledger._apply_snapshot(observed)

    # 一致：不欠补扫
    ledger.verify_focus_consistency(observed, 1)
    assert ledger.gate_state.consistency_retry_due is False
    assert ledger.gate_state.last_scan_fingerprint is not None

    # 新指纹且仍不一致：账重新挂回去，欠一次补扫
    changed = _full_readings(1)
    changed[2] = _reading(occupied=False, label="点击入座")
    ledger.gate_state.reconciled_focus_count = 2
    ledger.verify_focus_consistency(changed, 2)
    assert ledger.gate_state.consistency_retry_due is True
    assert ledger.gate_state.reconciled_focus_count is None

    # 同指纹且仍不一致：同样的 DOM 只会得到同样的答案，不再追着重扫
    ledger.gate_state.reconciled_focus_count = 2
    ledger.verify_focus_consistency(changed, 2)
    assert ledger.gate_state.consistency_retry_due is False
    assert ledger.gate_state.reconciled_focus_count == 2


def test_verify_focus_consistency_ignores_incomplete_readings():
    ledger = SeatLedger()
    ledger.verify_focus_consistency({1: _reading()}, 5)
    assert ledger.gate_state.last_scan_fingerprint is None
    assert ledger.gate_state.consistency_retry_due is False


def test_in_viewport_move_merges_into_move_seat():
    ledger = SeatLedger()
    ledger.slots[3] = SeatSlot(seat_number=3, occupied=True, username="Alice")
    observed = {
        3: _reading(occupied=False, label="3"),
        7: _reading(username="Alice"),
    }

    diff = ledger.apply(ledger.observe(observed))

    assert diff.seat_info["Alice"] == {"seat_number": 7, "action": "move_seat"}
    assert ledger.slots[3].occupied is False
    assert ledger.slots[7].username == "Alice"


def test_mark_owner_seated_reports_seat_count_delta():
    ledger = SeatLedger()

    assert ledger.mark_owner_seated(2, "群主") == 1
    assert ledger.mark_owner_seated(2, "群主") == 0
    assert ledger.mark_owner_seated(7, "群主") == 0

    assert ledger.slots[2].occupied is False
    assert ledger.slots[7].is_owner is True and ledger.slots[7].username == "群主"


def test_focus_reconciliation_runs_once_per_focus_value():
    ledger = SeatLedger()

    assert ledger.begin_focus_reconciliation(2) == (True, 0)
    assert ledger.begin_focus_reconciliation(2) == (False, 0)

    ledger.rollback_focus_reconciliation()
    assert ledger.begin_focus_reconciliation(2) == (True, 0)


def test_unexplained_fingerprint_suppresses_identical_anomalies():
    ledger = SeatLedger()
    unexplained = {(1, "swap")}

    fingerprint = ledger.unexplained_scan_fingerprint(unexplained)
    assert fingerprint is not None
    ledger.begin_rescan(fingerprint)
    assert ledger.unexplained_scan_fingerprint(unexplained) is None

    # 读数恢复一致后指纹清空，同样的异常下次还会触发
    assert ledger.unexplained_scan_fingerprint(set()) is None
    assert ledger.unexplained_scan_fingerprint(unexplained) == fingerprint
