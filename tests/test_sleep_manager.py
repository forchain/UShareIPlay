import datetime as dt


def _fresh_manager(config: dict):
    from ushareiplay.managers.sleep_manager import SleepManager

    # Singleton test isolation (official hook)
    SleepManager.reset_instance()
    return SleepManager.initialize(config)


def test_non_cross_midnight_window_start_inclusive_end_exclusive():
    mgr = _fresh_manager(
        {
            "sleep": {
                "enabled": True,
                "start": "09:00",
                "end": "18:00",
            }
        }
    )

    assert mgr.is_in_guard_window(dt.time(9, 0)) is True
    assert mgr.is_in_guard_window(dt.time(17, 59)) is True
    assert mgr.is_in_guard_window(dt.time(18, 0)) is False
    assert mgr.is_in_guard_window(dt.time(8, 59)) is False

    assert mgr.is_in_configured_window(dt.time(9, 0)) is True
    assert mgr.is_in_configured_window(dt.time(18, 0)) is False


def test_cross_midnight_window():
    mgr = _fresh_manager(
        {
            "sleep": {
                "enabled": True,
                "start": "23:00",
                "end": "06:00",
            }
        }
    )

    assert mgr.is_in_guard_window(dt.time(22, 59)) is False
    assert mgr.is_in_guard_window(dt.time(23, 0)) is True
    assert mgr.is_in_guard_window(dt.time(23, 59)) is True
    assert mgr.is_in_guard_window(dt.time(0, 0)) is True
    assert mgr.is_in_guard_window(dt.time(5, 59)) is True
    assert mgr.is_in_guard_window(dt.time(6, 0)) is False

    assert mgr.is_in_configured_window(dt.time(23, 0)) is True
    assert mgr.is_in_configured_window(dt.time(6, 0)) is False


def test_start_equals_end_means_all_day_guard():
    mgr = _fresh_manager(
        {
            "sleep": {
                "enabled": True,
                "start": "00:00",
                "end": "00:00",
            }
        }
    )

    assert mgr.is_in_guard_window(dt.time(0, 0)) is True
    assert mgr.is_in_guard_window(dt.time(12, 0)) is True
    assert mgr.is_in_guard_window(dt.time(23, 59)) is True

    assert mgr.is_in_configured_window(dt.time(0, 0)) is True
    assert mgr.is_in_configured_window(dt.time(12, 0)) is True


def test_override_priority():
    mgr = _fresh_manager(
        {
            "sleep": {
                "enabled": True,
                "start": "09:00",
                "end": "18:00",
            }
        }
    )

    # default: enabled from config
    assert mgr.effective_enabled is True

    mgr.set_override(False)
    assert mgr.effective_enabled is False

    mgr.set_override(True)
    assert mgr.effective_enabled is True

    mgr.set_override(None)
    assert mgr.effective_enabled is True

    assert mgr.get_default_enabled() is True
    assert mgr.get_override() is None


def test_enabled_parsing_accepts_bool_int_and_str_without_bool_pitfalls():
    mgr_false_str = _fresh_manager(
        {
            "sleep": {
                "enabled": "false",
                "start": "00:00",
                "end": "00:00",
            }
        }
    )
    assert mgr_false_str.effective_enabled is False

    mgr_false_int = _fresh_manager(
        {
            "sleep": {
                "enabled": 0,
                "start": "00:00",
                "end": "00:00",
            }
        }
    )
    assert mgr_false_int.effective_enabled is False

    mgr_true_str = _fresh_manager(
        {
            "sleep": {
                "enabled": "TRUE",
                "start": "00:00",
                "end": "00:00",
            }
        }
    )
    assert mgr_true_str.effective_enabled is True


def test_enabled_false_can_be_overridden_true():
    mgr = _fresh_manager(
        {
            "sleep": {
                "enabled": False,
                "start": "00:00",
                "end": "00:00",
            }
        }
    )

    assert mgr.effective_enabled is False
    mgr.set_override(True)
    assert mgr.effective_enabled is True

    # Window checks must be purely time-based (independent of enabled/override)
    mgr.set_override(False)
    assert mgr.is_in_configured_window(dt.time(12, 0)) is True
    assert mgr.is_in_guard_window(dt.time(12, 0)) is False


def test_parse_failure_defaults_to_not_blocking():
    mgr1 = _fresh_manager(
        {
            "sleep": {
                "enabled": True,
                "start": "xx",
                "end": "06:00",
            }
        }
    )
    assert mgr1.is_in_guard_window(dt.time(0, 0)) is False
    assert mgr1.is_in_configured_window(dt.time(0, 0)) is False

    mgr2 = _fresh_manager(
        {
            "sleep": {
                "enabled": True,
                "start": "23:00",
                "end": "99:99",
            }
        }
    )
    assert mgr2.is_in_guard_window(dt.time(23, 0)) is False
    assert mgr2.is_in_configured_window(dt.time(23, 0)) is False


def test_window_key_is_supported_as_fallback():
    mgr = _fresh_manager(
        {
            "sleep": {
                "enabled": True,
                "window": {"start": "09:00", "end": "18:00"},
            }
        }
    )

    assert mgr.is_in_guard_window(dt.time(9, 0)) is True
    assert mgr.is_in_guard_window(dt.time(18, 0)) is False
    assert mgr.is_in_configured_window(dt.time(9, 0)) is True
    assert mgr.is_in_configured_window(dt.time(18, 0)) is False


def test_default_blocked_commands_contains_required_minimum_set():
    mgr = _fresh_manager(
        {
            "sleep": {
                "enabled": True,
                # all-day guard window so is_blocked_command reflects membership
                "start": "00:00",
                "end": "00:00",
            }
        }
    )

    required = ("play", "next", "fav", "singer", "album", "playlist", "radio")
    for cmd in required:
        assert mgr.is_blocked_command(cmd, dt.time(12, 0)) is True
