from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from tests.room_support import configured_room_state


@pytest.fixture
def room_state():
    state = configured_room_state()
    state._logger = SimpleNamespace(
        info=lambda _msg: None, error=lambda _msg: None
    )
    return state


def test_user_count_setter_updates_value(room_state):
    room_state.user_count = 5
    assert room_state.user_count == 5


def test_focus_count_setter_updates_value(room_state):
    room_state.focus_count = 3
    assert room_state.focus_count == 3


def test_room_id_setter_updates_value(room_state):
    room_state.room_id = "FM123"
    assert room_state.room_id == "FM123"


def test_clear_resets_all_state(room_state):
    room_state.user_count = 5
    room_state.focus_count = 3
    room_state.room_id = "FM123"
    room_state.is_guest_room = True

    room_state.clear()

    assert room_state.user_count is None
    assert room_state.focus_count is None
    assert room_state.room_id is None
    assert room_state.is_guest_room is False


def test_clear_wipes_seat_observation_snapshot():
    """换房后不能拿上一间房的麦位快照做 diff。"""
    from tests.seat_support import build_seat_observation
    from ushareiplay.modules.seat.ledger import SeatSlot

    observation = build_seat_observation()
    observation.ledger.slots[1] = SeatSlot(seat_number=1, occupied=True, username="张三")
    room_state = configured_room_state(on_clear=[observation.clear])

    room_state.clear()
    assert observation.ledger.slots[1].occupied is False
    assert observation.ledger.slots[1].username is None


def test_clear_reports_seat_observation_failure():
    """清快照失败要留痕，不能裸 except 吞掉（否则脏快照无声沿用）。"""
    errors = []

    def boom():
        raise RuntimeError("boom")

    room_state = configured_room_state(on_clear=[boom], logger=MagicMock())
    room_state._logger = SimpleNamespace(info=lambda _msg: None, error=errors.append)

    room_state.clear()

    assert any("boom" in str(message) for message in errors)


def test_is_guest_room_when_matching_default_party_id(room_state):
    room_state.default_party_id = "FM123456"
    room_state.room_id = "FM123456"
    assert room_state.is_guest_room is False
    assert room_state.is_host_room is True


def test_is_guest_room_when_different_from_default_party_id(room_state):
    room_state.default_party_id = "FM123456"
    room_state.room_id = "FM999999"
    assert room_state.is_guest_room is True
    assert room_state.is_host_room is False


def test_explicit_is_guest_room_setter_overrides_comparison(room_state):
    room_state.default_party_id = "FM123456"
    room_state.room_id = "FM123456"
    room_state.is_guest_room = True
    assert room_state.is_guest_room is True
    assert room_state.is_host_room is False

    room_state.is_guest_room = False
    assert room_state.is_guest_room is False
    assert room_state.is_host_room is True


def test_adopt_host_room_promotes_when_the_id_is_the_configured_room(room_state):
    room_state.default_party_id = "FM123456"
    room_state.expected_party_id = "FM18633292"
    room_state.is_guest_room = True

    assert room_state.adopt_host_room("FM123456") is True
    assert room_state.is_guest_room is False
    assert room_state.room_id == "FM123456"
    assert room_state.expected_party_id is None


def test_adopt_host_room_ignores_unrecognized_ids(room_state):
    room_state.default_party_id = "FM123456"
    room_state.expected_party_id = "FM18633292"
    room_state.room_id = "FM18633292"
    room_state.is_guest_room = True

    for room_id in ("FM999999", None, "", "   "):
        assert room_state.adopt_host_room(room_id) is False

    assert room_state.is_guest_room is True
    assert room_state.room_id == "FM18633292"
    assert room_state.expected_party_id == "FM18633292"


def test_adopt_host_room_without_configured_default_does_nothing(room_state):
    room_state.default_party_id = None
    room_state.is_guest_room = True

    assert room_state.adopt_host_room("FM123456") is False
    assert room_state.is_guest_room is True


def test_promote_to_host_room_clears_guest_mode(room_state):
    room_state.default_party_id = "FM123456"
    room_state.expected_party_id = "FM18633292"
    room_state.room_id = "FM18633292"
    room_state.is_guest_room = True

    room_state.promote_to_host_room("FM123456")

    assert room_state.expected_party_id is None
    assert room_state.room_id == "FM123456"
    assert room_state.is_guest_room is False
    assert room_state.is_host_room is True
    assert room_state.get_expected_party_id() == "FM123456"


def test_promote_to_host_room_keeps_unknown_room_id(room_state):
    """Creating a party may not have resolved the room ID yet: host mode still wins."""
    room_state.default_party_id = "FM123456"
    room_state.room_id = "FM18633292"
    room_state.is_guest_room = True

    room_state.promote_to_host_room()

    assert room_state.room_id == "FM18633292"
    assert room_state.expected_party_id is None
    assert room_state.is_guest_room is False


def test_is_command_allowed_in_guest_room(room_state):
    allowed = ["play", "next", "fav", "skip", "pause", "vol", "mode", "acc", "lyrics", "singer", "album", "playlist", "radio", "info", "help", "room", "mic", "say", "end"]
    for cmd in allowed:
        assert room_state.is_command_allowed_in_guest_room(cmd) is True
        assert room_state.is_command_allowed_in_guest_room(f":{cmd}") is True

    blocked = ["theme", "title", "topic", "notice", "seat", "pack", "admin", "alias", "keyword", "enter", "exit", "return", "gift", "timer", "recommend"]
    for cmd in blocked:
        assert room_state.is_command_allowed_in_guest_room(cmd) is False
        assert room_state.is_command_allowed_in_guest_room(f":{cmd}") is False
