import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from types import SimpleNamespace

from ushareiplay.commands.focus import FocusCommand
from ushareiplay.adapters.outbound.persistence.db_manager import DatabaseManager
from ushareiplay.adapters.outbound.persistence.user_event_hook_repository import (
    TortoiseUserEventHookRepository,
)
from ushareiplay.core.message_queue import MessageQueue
from ushareiplay.models.message_info import MessageInfo
from ushareiplay.modules.room.registry import FOCUS
from tests.room_support import make_hooks


def _command(hooks):
    handler = MagicMock()
    handler.logger = MagicMock()
    controller = SimpleNamespace(
        soul_handler=handler, music_handler=handler, user_event_hooks=hooks
    )
    return FocusCommand(controller)


def _repository():
    return TortoiseUserEventHookRepository()


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
    await _repository().create(FOCUS, "Alice", ":say Alice changed seat")
    await _repository().create(FOCUS, "Bob", ":say Bob changed seat")

    command = _command(make_hooks())

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
    await _repository().create(FOCUS, "Charlie", ":say {username} 坐到了 {seat} 号座位 ({action})")

    command = _command(make_hooks())

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
    assert msg.content == ":say Charlie 坐到了 5 号座位 (sit_down)"


@pytest.mark.asyncio
async def test_focus_count_change_fallback_when_changed_users_none():
    await _repository().create(FOCUS, "UserA", ":say A")
    await _repository().create(FOCUS, "UserB", ":say B")

    command = _command(make_hooks())

    # Fallback mode (changed_users is None)
    await command.focus_count_change(before=1, after=2, changed_users=None)

    queue = MessageQueue.instance()
    assert queue.get_queue_size() == 2
    msgs = await queue.get_all_messages()
    contents = {m.content for m in msgs.values()}
    assert contents == {":say A", ":say B"}


@pytest.mark.asyncio
async def test_focus_count_change_deduplicates_same_canonical_user_aliases():
    """当同属于一个主账号的多个分身同时出现在 changed_users 时，联动命令只入队一次。"""
    from ushareiplay.dal.user_dao import UserDAO

    canonical = await UserDAO.get_or_create_raw("David")
    avatar1 = await UserDAO.get_or_create_raw("David_Avatar1")
    avatar1.canonical_user_id = canonical.id
    await avatar1.save(update_fields=["canonical_user_id"])
    avatar2 = await UserDAO.get_or_create_raw("David_Avatar2")
    avatar2.canonical_user_id = canonical.id
    await avatar2.save(update_fields=["canonical_user_id"])

    await _repository().create(FOCUS, "David", ":say David changed seat")

    command = _command(make_hooks())

    await command.focus_count_change(
        before=0,
        after=2,
        changed_users=["David_Avatar1", "David_Avatar2"],
        seat_info={"David_Avatar1": {"seat_number": 1, "action": "sit_down"}},
    )

    queue = MessageQueue.instance()
    assert queue.get_queue_size() == 1
    msgs = await queue.get_all_messages()
    msg = list(msgs.values())[0]
    assert msg.nickname == "David"
    assert msg.content == ":say David changed seat"

