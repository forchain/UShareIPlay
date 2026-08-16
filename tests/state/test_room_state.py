from types import SimpleNamespace

import pytest

from ushareiplay.state.room_state import RoomState


@pytest.fixture
def room_state():
    RoomState.reset_instance()
    state = RoomState.initialize()
    state._logger = SimpleNamespace(info=lambda _msg: None)
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


def test_is_guest_room_when_matching_default_party_id(room_state, monkeypatch):
    monkeypatch.setattr(room_state, "_get_default_party_id", lambda: "FM123456")
    room_state.room_id = "FM123456"
    assert room_state.is_guest_room is False
    assert room_state.is_host_room is True


def test_is_guest_room_when_different_from_default_party_id(room_state, monkeypatch):
    monkeypatch.setattr(room_state, "_get_default_party_id", lambda: "FM123456")
    room_state.room_id = "FM999999"
    assert room_state.is_guest_room is True
    assert room_state.is_host_room is False


def test_explicit_is_guest_room_setter_overrides_comparison(room_state, monkeypatch):
    monkeypatch.setattr(room_state, "_get_default_party_id", lambda: "FM123456")
    room_state.room_id = "FM123456"
    room_state.is_guest_room = True
    assert room_state.is_guest_room is True
    assert room_state.is_host_room is False

    room_state.is_guest_room = False
    assert room_state.is_guest_room is False
    assert room_state.is_host_room is True


def test_is_command_allowed_in_guest_room(room_state):
    allowed = ["play", "next", "fav", "skip", "pause", "vol", "mode", "acc", "lyrics", "singer", "album", "playlist", "radio", "info", "help", "room"]
    for cmd in allowed:
        assert room_state.is_command_allowed_in_guest_room(cmd) is True
        assert room_state.is_command_allowed_in_guest_room(f":{cmd}") is True

    blocked = ["theme", "title", "topic", "notice", "seat", "mic", "pack", "end", "admin", "alias", "keyword", "enter", "exit", "return", "gift", "timer", "recommend"]
    for cmd in blocked:
        assert room_state.is_command_allowed_in_guest_room(cmd) is False
        assert room_state.is_command_allowed_in_guest_room(f":{cmd}") is False


