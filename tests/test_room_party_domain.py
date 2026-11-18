from datetime import date, datetime, timedelta

from ushareiplay.modules.room.domain import (
    COUNTDOWN_OPTIONS,
    MAX_REDEMPTIONS,
    OPEN_USAGE,
    PACK_USAGE,
    YELLOW_DUCK_NAME,
    PartyLifecycleState,
    format_packs,
    is_zero_packs,
    parse_countdown,
    parse_heat,
    parse_open_pack_args,
    parse_pack_level,
    party_create_mode,
    should_skip_auto_pack,
)


def test_party_lifecycle_state_initialize_and_duration():
    state = PartyLifecycleState()
    assert state.init_time is None
    assert state.format_duration_info() is None

    start = datetime(2026, 11, 18, 14, 5, 0)
    state.initialize(now=start, trigger_minutes=600)
    assert state.init_time == start
    assert state.trigger_minutes == 600

    # Second initialize does not overwrite init_time
    state.initialize(now=start + timedelta(minutes=30), trigger_minutes=720)
    assert state.init_time == start

    assert state.format_duration_info(now=start + timedelta(minutes=45)) == "14:05, 45分钟"
    assert state.format_duration_info(now=start + timedelta(hours=2, minutes=15)) == "14:05, 2小时15分钟"


def test_party_lifecycle_should_auto_restart():
    start = datetime(2026, 11, 18, 10, 0, 0)
    state = PartyLifecycleState(trigger_minutes=120)
    assert state.should_auto_restart(start, user_count=1, is_guest_room=False) is False

    state.initialize(now=start, trigger_minutes=120)
    later = start + timedelta(minutes=120)

    assert state.should_auto_restart(start + timedelta(minutes=119), user_count=1, is_guest_room=False) is False
    assert state.should_auto_restart(later, user_count=1, is_guest_room=True) is False
    assert state.should_auto_restart(later, user_count=2, is_guest_room=False) is False
    assert state.should_auto_restart(later, user_count=-1, is_guest_room=False) is False
    assert state.should_auto_restart(later, user_count=1, is_guest_room=False) is True

    state.mark_auto_ended(date(2026, 11, 18))
    assert state.should_auto_restart(later, user_count=1, is_guest_room=False) is False


def test_party_create_mode_normalizes_unknown_values():
    assert party_create_mode("new_party_entry") == "new_party_entry"
    assert party_create_mode("restore_party") == "restore_party"
    assert party_create_mode("unexpected") == "new_party_entry"
    assert party_create_mode(None) == "new_party_entry"


def test_gift_and_pack_constants_and_parsers():
    assert YELLOW_DUCK_NAME == "小黄鸭"
    assert MAX_REDEMPTIONS == 50
    assert COUNTDOWN_OPTIONS == {0: "即刻抢", 1: "1分钟", 3: "3分钟", 5: "5分钟", 10: "10分钟"}
    assert PACK_USAGE.startswith("用法: :pack")
    assert OPEN_USAGE.startswith("用法: :pack open")

    assert is_zero_packs("礼物福袋  (0个)") is True
    assert is_zero_packs("礼物福袋 (10个)") is False

    assert parse_heat("1,234") == 1234
    assert parse_heat("1.5万") == 15000
    assert parse_heat("2w") == 20000
    assert parse_heat("无数字") is None

    assert parse_pack_level("第一阶段奖励") == 1
    assert parse_pack_level("第五阶段奖励") == 5
    assert parse_pack_level("普通礼物") is None

    assert parse_countdown("即刻抢 | 所有人") == 0
    assert parse_countdown("3分钟 | 所有人") == 3
    assert parse_countdown("未知") is None

    assert format_packs([(3, "高级福袋"), (1, "初级福袋"), (1, "初级福袋")]) == (
        "福袋列表（共3个）：高级福袋（3级）、初级福袋（1级）×2"
    )

    assert parse_open_pack_args([]) == (None, 0, None)
    assert parse_open_pack_args(["2", "5"]) == (2, 5, None)
    assert parse_open_pack_args(["6"]) == (None, None, OPEN_USAGE)
    assert parse_open_pack_args(["1", "2"]) == (None, None, OPEN_USAGE)
    assert parse_open_pack_args(["1", "3", "extra"]) == (None, None, OPEN_USAGE)

    assert should_skip_auto_pack(8, "高级福袋") is True
    assert should_skip_auto_pack(8, "初级福袋") is False
    assert should_skip_auto_pack(11, "高级福袋") is False
    assert should_skip_auto_pack(None, "高级福袋") is False
