"""定时器时间规则：纯函数，时钟显式传入。"""

from datetime import datetime, timedelta

import pytest

from ushareiplay.modules.timer.domain import (
    InvalidTimerSpec,
    Timer,
    advance_repeat,
    compute_next_trigger,
    is_time_token,
    next_daily_trigger,
    reschedule_expired_repeat,
)

NOW = datetime(2026, 1, 1, 12, 0, 0)


def test_is_time_token_accepts_delay_and_clock_forms():
    assert is_time_token("10")
    assert is_time_token("08:30")
    assert is_time_token("8:30")
    assert is_time_token("08:30:15")
    assert not is_time_token("")
    assert not is_time_token("dawn")
    assert not is_time_token("8:3")


def test_numeric_delay_is_relative_to_the_injected_clock():
    assert compute_next_trigger("10", False, NOW) == NOW + timedelta(seconds=10)


def test_numeric_delay_rejects_zero_and_oversized_values_with_the_existing_texts():
    with pytest.raises(InvalidTimerSpec, match="延迟秒数必须为正整数"):
        compute_next_trigger("0", False, NOW)
    with pytest.raises(InvalidTimerSpec, match="延迟秒数过大"):
        compute_next_trigger(str(86400 * 30 + 1), False, NOW)


def test_numeric_delay_cannot_repeat():
    with pytest.raises(InvalidTimerSpec, match="延迟模式不支持 repeat"):
        compute_next_trigger("10", True, NOW)


def test_clock_time_later_today_stays_today():
    assert compute_next_trigger("13:00", True, NOW) == datetime(2026, 1, 1, 13, 0)


def test_clock_time_already_passed_moves_to_tomorrow():
    assert compute_next_trigger("08:00", False, NOW) == datetime(2026, 1, 2, 8, 0)


def test_clock_time_accepts_seconds():
    assert compute_next_trigger("13:00:30", False, NOW) == datetime(2026, 1, 1, 13, 0, 30)


def test_invalid_clock_time_keeps_the_public_message():
    with pytest.raises(
        InvalidTimerSpec,
        match="时间格式错误：支持 HH:MM / HH:MM:SS，或纯数字 N 表示延迟 N 秒",
    ):
        compute_next_trigger("25:00", False, NOW)


def test_next_daily_trigger_uses_tomorrow_when_today_has_passed():
    assert next_daily_trigger("08:00", NOW) == datetime(2026, 1, 2, 8, 0)


def test_advance_repeat_skips_every_missed_day():
    stale = NOW - timedelta(days=3)

    assert advance_repeat(stale, NOW) == datetime(2026, 1, 2, 12, 0)


def test_reschedule_expired_repeat_only_touches_expired_repeat_timers():
    expired = Timer(
        key="daily",
        message="hello",
        target_time="19:00",
        repeat=True,
        next_trigger=datetime(2025, 12, 31, 19, 0),
    )
    future = Timer(
        key="later",
        message="hello",
        target_time="19:00",
        repeat=True,
        next_trigger=datetime(2026, 1, 1, 19, 0),
    )
    one_shot = Timer(
        key="once",
        message="hello",
        target_time="19:00",
        repeat=False,
        next_trigger=datetime(2025, 12, 31, 19, 0),
    )

    assert reschedule_expired_repeat(expired, NOW) == datetime(2026, 1, 1, 19, 0)
    assert reschedule_expired_repeat(future, NOW) is None
    assert reschedule_expired_repeat(one_shot, NOW) is None


def test_reschedule_expired_repeat_ignores_non_hh_mm_targets_like_the_old_resume_path():
    timer = Timer(
        key="daily",
        message="hello",
        target_time="19:00:00",
        repeat=True,
        next_trigger=datetime(2025, 12, 31, 19, 0),
    )

    with pytest.raises(ValueError):
        reschedule_expired_repeat(timer, NOW)
