import pytest
from unittest.mock import AsyncMock, MagicMock
from ushareiplay.commands.room import RoomCommand
from ushareiplay.models import MessageInfo


class _MockController:
    def __init__(self):
        self.soul_handler = MagicMock()
        self.music_handler = MagicMock()


@pytest.mark.asyncio
async def test_room_command_missing_party_id():
    controller = _MockController()
    command = RoomCommand(controller)

    msg = MessageInfo(nickname="Alice", content=":room")
    result = await command.process(msg, [])

    assert result['error'] == 'Missing party ID parameter'
    assert result['party_id'] == 'unknown'


@pytest.mark.asyncio
async def test_room_command_target_room_not_open():
    controller = _MockController()
    command = RoomCommand(controller)
    mock_pm = MagicMock()
    mock_pm.invite_user = AsyncMock(return_value={
        'error': 'Party 123456 not found or not open',
        'party_id': '123456'
    })
    command._party_manager = mock_pm

    msg = MessageInfo(nickname="Bob", content=":room 123456")
    result = await command.process(msg, ["123456"])

    assert result['error'] == 'Party 123456 not found or not open'
    assert result['party_id'] == '123456'


@pytest.mark.asyncio
async def test_room_command_target_room_success():
    controller = _MockController()
    command = RoomCommand(controller)
    mock_pm = MagicMock()
    mock_pm.invite_user = AsyncMock(return_value={
        'party_id': '654321',
        'user': 'Charlie'
    })
    command._party_manager = mock_pm

    msg = MessageInfo(nickname="Charlie", content=":room 654321")
    result = await command.process(msg, ["654321"])

    assert 'error' not in result
    assert result['party_id'] == '654321'
    assert result['user'] == 'Charlie'


@pytest.mark.asyncio
async def test_room_command_exception_handled():
    controller = _MockController()
    command = RoomCommand(controller)
    mock_pm = MagicMock()
    mock_pm.invite_user = AsyncMock(side_effect=RuntimeError("UI Timeout"))
    command._party_manager = mock_pm

    msg = MessageInfo(nickname="David", content=":room 777777")
    result = await command.process(msg, ["777777"])

    assert 'error' in result
    assert 'UI Timeout' in result['error']
    assert result['party_id'] == '777777'
