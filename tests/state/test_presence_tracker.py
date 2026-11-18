import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from ushareiplay.modules.room.use_cases import PresenceTracker


@pytest.fixture
def presence_tracker():
    tracker = PresenceTracker()
    tracker._logger = SimpleNamespace(
        info=lambda _msg: None,
        debug=lambda _msg: None,
        critical=lambda _msg: None,
        error=lambda _msg: None,
    )
    return tracker


@pytest.mark.asyncio
async def test_update_online_users_notifies_enter_and_leave():
    on_enter = AsyncMock()
    on_leave = AsyncMock()
    tracker = PresenceTracker(on_user_enter=on_enter, on_user_leave=on_leave)

    # First snapshot establishes baseline, no notifications
    tracker.update_online_users(["alice", "bob"])

    # Second snapshot: alice left, carol entered
    tracker.update_online_users(["bob", "carol"])
    await asyncio.sleep(0)

    on_leave.assert_awaited_once_with("alice")
    on_enter.assert_awaited_once_with("carol")


def test_update_online_users_sets_users(presence_tracker):
    presence_tracker.update_online_users(["alice", "bob"])
    assert presence_tracker.get_online_users() == {"alice", "bob"}


def test_get_online_users_returns_copy(presence_tracker):
    presence_tracker.update_online_users(["alice"])
    users = presence_tracker.get_online_users()
    users.add("bob")
    assert presence_tracker.get_online_users() == {"alice"}


def test_is_user_online(presence_tracker):
    presence_tracker.update_online_users(["alice"])
    assert presence_tracker.is_user_online("alice") is True
    assert presence_tracker.is_user_online("bob") is False


def test_clear_clears_users(presence_tracker):
    presence_tracker.update_online_users(["alice"])
    presence_tracker.record_return("alice")
    presence_tracker.clear()
    assert presence_tracker.get_online_users() == set()
    assert presence_tracker.should_trigger_return("alice") is True


def test_should_trigger_return_when_user_online_and_not_recently_entered(presence_tracker):
    presence_tracker.update_online_users(["alice", "bob"])
    assert presence_tracker.should_trigger_return("alice") is True
    assert presence_tracker.should_trigger_return("bob") is True


def test_should_trigger_return_false_when_user_not_in_online_list(presence_tracker):
    presence_tracker.update_online_users(["alice", "bob"])
    assert presence_tracker.should_trigger_return("carol") is False


def test_should_trigger_return_false_when_user_recently_entered():
    tracker = PresenceTracker(on_user_enter=MagicMock(), on_user_leave=MagicMock())

    tracker.update_online_users(["alice"])
    tracker.update_online_users(["alice", "carol"])

    assert tracker.was_recently_entered("carol") is True
    assert tracker.should_trigger_return("carol") is False


def test_should_trigger_return_debounces_consecutive_returns(presence_tracker):
    presence_tracker.update_online_users(["alice"])
    assert presence_tracker.should_trigger_return("alice") is True

    presence_tracker.record_return("alice")

    assert presence_tracker.should_trigger_return("alice") is False
