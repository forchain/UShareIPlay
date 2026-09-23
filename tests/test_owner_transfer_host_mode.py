"""Ticket #316: a 群主 transfer back to the bot restores host mode.

While the bot is a guest in someone else's room, the room ID differs from the
configured main-room ID. When ownership is transferred to the bot the room ID
becomes the configured ID — that is a promotion, not an unauthorized room, so
the bot must adopt it and unlock host mode instead of leaving and recreating
its party.
"""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from ushareiplay.state.room_state import RoomState

HOST_ROOM_ID = "FM15321640"   # soul.default_party_id in config.yaml
GUEST_ROOM_ID = "FM18633292"  # someone else's room we were invited into
RANDOM_ROOM_ID = "FM99999999"  # unrelated room (system redirect)


class _Logger:
    def info(self, *_args, **_kwargs):
        pass

    def warning(self, *_args, **_kwargs):
        pass

    def debug(self, *_args, **_kwargs):
        pass

    def error(self, *_args, **_kwargs):
        pass


class _HandlerStub:
    def __init__(self, config=None):
        self.config = config or {}
        self.logger = _Logger()
        self.controller = None
        self.party_id = None


class _RuntimeStub:
    def emit(self, *_args, **_kwargs):
        return None

    @asynccontextmanager
    async def ui_session(self, *_args, **_kwargs):
        yield


class _MessageInfoStub:
    def __init__(self, nickname="Alice", content=":theme"):
        self.nickname = nickname
        self.content = content
        self.sleep_exempt = False


class _DummyCommand:
    def __init__(self):
        self.called = False

    async def process(self, *_args, **_kwargs):
        self.called = True
        return {"message": "OK"}


@pytest.fixture(autouse=True)
def _isolate_singletons():
    from ushareiplay.core.message_dispatch import MessageDispatch
    from ushareiplay.managers.command_manager import CommandManager

    CommandManager.reset_instance()
    MessageDispatch.reset_instance()
    MessageDispatch.initialize()
    RoomState.reset_instance()
    room_state = RoomState.initialize()
    room_state._logger = SimpleNamespace(info=lambda _msg: None)
    yield
    CommandManager.reset_instance()
    MessageDispatch.reset_instance()
    RoomState.reset_instance()


def _guest_room_state(monkeypatch, explicit_guest_flag=True):
    """Room state as it looks while the bot is a guest in another room."""
    state = RoomState.instance()
    monkeypatch.setattr(state, "_get_default_party_id", lambda: HOST_ROOM_ID)
    state.expected_party_id = GUEST_ROOM_ID
    state.room_id = GUEST_ROOM_ID
    if explicit_guest_flag:
        state.is_guest_room = True
    return state


def _room_id_event(party_manager):
    from ushareiplay.events.room_id import RoomIdEvent

    handler = _HandlerStub(config={})
    handler.controller = SimpleNamespace(party_manager=party_manager)
    return RoomIdEvent(handler), handler


def _wrapper(room_id):
    return SimpleNamespace(text=room_id, content=room_id)


@pytest.mark.asyncio
async def test_room_id_becoming_configured_id_promotes_to_host_mode(monkeypatch):
    state = _guest_room_state(monkeypatch)
    party_manager = SimpleNamespace(leave_and_recreate_party=AsyncMock(return_value=True))
    event, handler = _room_id_event(party_manager)

    result = await event.handle("room_id", _wrapper(HOST_ROOM_ID))

    assert result is False
    party_manager.leave_and_recreate_party.assert_not_awaited()
    assert state.is_guest_room is False
    assert state.is_host_room is True
    assert state.room_id == HOST_ROOM_ID
    assert state.expected_party_id is None
    assert handler.party_id == HOST_ROOM_ID
    # The adopted room is now the expected room, so later scans stay put.
    assert state.get_expected_party_id() == HOST_ROOM_ID


@pytest.mark.asyncio
async def test_room_id_becoming_configured_id_promotes_from_derived_guest_mode(monkeypatch):
    """Guest mode derived from the room ID (no explicit flag) is promoted too."""
    state = _guest_room_state(monkeypatch, explicit_guest_flag=False)
    assert state.is_guest_room is True
    party_manager = SimpleNamespace(leave_and_recreate_party=AsyncMock(return_value=True))
    event, _handler = _room_id_event(party_manager)

    await event.handle("room_id", _wrapper(HOST_ROOM_ID))

    assert state.is_guest_room is False
    party_manager.leave_and_recreate_party.assert_not_awaited()


@pytest.mark.asyncio
async def test_unrelated_room_id_still_triggers_leave_and_recreate(monkeypatch):
    state = _guest_room_state(monkeypatch)
    party_manager = SimpleNamespace(leave_and_recreate_party=AsyncMock(return_value=True))
    event, _handler = _room_id_event(party_manager)

    result = await event.handle("room_id", _wrapper(RANDOM_ROOM_ID))

    assert result is True
    party_manager.leave_and_recreate_party.assert_awaited_once()
    assert state.is_guest_room is True


@pytest.mark.asyncio
async def test_startup_room_detection_promotes_to_host_mode(monkeypatch):
    from ushareiplay.core.app_controller import AppController

    state = _guest_room_state(monkeypatch)
    party_manager = SimpleNamespace(leave_and_recreate_party=AsyncMock(return_value=True))

    element_finder = SimpleNamespace(
        try_find_element=lambda key, log=False: object(),
        get_element_text=lambda _element: HOST_ROOM_ID,
    )
    soul_handler = SimpleNamespace(element_finder=element_finder, party_id=None)
    controller = SimpleNamespace(
        soul_handler=soul_handler,
        party_manager=party_manager,
        logger=_Logger(),
    )

    await AppController._detect_initial_room_state(controller)

    party_manager.leave_and_recreate_party.assert_not_awaited()
    assert state.is_guest_room is False
    assert state.room_id == HOST_ROOM_ID
    assert soul_handler.party_id == HOST_ROOM_ID


@pytest.mark.asyncio
async def test_host_only_commands_are_unlocked_after_promotion(monkeypatch):
    """Acceptance: host privileges (seat/theme/notice/...) come back with the room."""
    from ushareiplay.managers.command_manager import CommandManager

    state = _guest_room_state(monkeypatch)
    command_manager = CommandManager.initialize()
    command_manager.configure_runtime(_RuntimeStub())
    command_manager._handler = _HandlerStub(config={"system_users": ["Timer"]})

    dummy_command = _DummyCommand()
    command_info = {
        "prefix": "theme",
        "level": 1,
        "parameters": ["听歌"],
        "error_template": "Failed to set theme, because {error}",
        "response_template": "{message}",
    }
    message = _MessageInfoStub(content=":theme 听歌")

    with patch("ushareiplay.dal.user_dao.UserDAO.get_or_create", new_callable=AsyncMock) as dao:
        dao.return_value = SimpleNamespace(level=3)
        blocked = await command_manager.process_command(dummy_command, message, command_info)

    assert dummy_command.called is False
    assert "当前处于他人房间" in blocked

    party_manager = SimpleNamespace(leave_and_recreate_party=AsyncMock(return_value=True))
    event, _handler = _room_id_event(party_manager)
    await event.handle("room_id", _wrapper(HOST_ROOM_ID))

    dummy_command = _DummyCommand()
    with patch("ushareiplay.dal.user_dao.UserDAO.get_or_create", new_callable=AsyncMock) as dao:
        dao.return_value = SimpleNamespace(level=3)
        allowed = await command_manager.process_command(dummy_command, message, command_info)

    assert dummy_command.called is True
    assert "OK" in allowed
    assert state.is_host_room is True
