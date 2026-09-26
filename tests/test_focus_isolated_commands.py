import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from ushareiplay.commands.focus import FocusCommand
from ushareiplay.core.db_manager import DatabaseManager
from ushareiplay.core.message_queue import MessageQueue
from ushareiplay.dal.focus_event_dao import FocusEventDao
from ushareiplay.models.message_info import MessageInfo


@pytest.fixture(autouse=True)
async def setup_db():
    db = DatabaseManager(db_url="sqlite://:memory:")
    await db.init()
    yield
    await db.close()


@pytest.fixture(autouse=True)
async def clear_queue():
    queue = MessageQueue.instance()
    await queue.clear_queue()
    yield
    await queue.clear_queue()


@pytest.mark.asyncio
async def test_focus_count_change_user_isolation():
    # Setup Alice and Bob with distinct focus commands
    await FocusEventDao.create("Alice", ":say Alice changed seat")
    await FocusEventDao.create("Bob", ":say Bob changed seat")

    mock_handler = MagicMock()
    mock_handler.logger = MagicMock()
    command = FocusCommand(mock_handler)
    command.handler = mock_handler

    # When only Alice changed seats
    await command.focus_count_change(
        before=1,
        after=2,
        changed_users=["Alice"],
        seat_info={"Alice": {"seat_number": 3, "action": "sit_down"}},
    )

    queue = MessageQueue.instance()
    assert queue.get_queue_size() == 1
    msgs = await queue.get_all_messages()
    msg = list(msgs.values())[0]
    assert msg.nickname == "Alice"
    assert msg.content == ":say Alice changed seat"


@pytest.mark.asyncio
async def test_focus_count_change_macro_substitution():
    await FocusEventDao.create("Charlie", ":say {username} 坐到了 {seat} 号麦位 ({action})")

    mock_handler = MagicMock()
    mock_handler.logger = MagicMock()
    command = FocusCommand(mock_handler)
    command.handler = mock_handler

    await command.focus_count_change(
        before=0,
        after=1,
        changed_users=["Charlie"],
        seat_info={"Charlie": {"seat_number": 5, "action": "sit_down"}},
    )

    queue = MessageQueue.instance()
    assert queue.get_queue_size() == 1
    msgs = await queue.get_all_messages()
    msg = list(msgs.values())[0]
    assert msg.nickname == "Charlie"
    assert msg.content == ":say Charlie 坐到了 5 号麦位 (sit_down)"


@pytest.mark.asyncio
async def test_focus_count_change_fallback_when_changed_users_none():
    await FocusEventDao.create("UserA", ":say A")
    await FocusEventDao.create("UserB", ":say B")

    mock_handler = MagicMock()
    mock_handler.logger = MagicMock()
    command = FocusCommand(mock_handler)
    command.handler = mock_handler

    # Fallback mode (changed_users is None)
    await command.focus_count_change(before=1, after=2, changed_users=None)

    queue = MessageQueue.instance()
    assert queue.get_queue_size() == 2
    msgs = await queue.get_all_messages()
    contents = {m.content for m in msgs.values()}
    assert contents == {":say A", ":say B"}
