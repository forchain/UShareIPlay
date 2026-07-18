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

    room_state.clear()

    assert room_state.user_count is None
    assert room_state.focus_count is None
    assert room_state.room_id is None
