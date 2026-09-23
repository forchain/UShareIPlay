from types import SimpleNamespace

import pytest
from unittest.mock import MagicMock, patch

from ushareiplay.state.presence_tracker import PresenceTracker


@pytest.fixture
def presence_tracker():
    PresenceTracker.reset_instance()
    tracker = PresenceTracker.initialize()
    tracker._logger = SimpleNamespace(
        info=lambda _msg: None,
        debug=lambda _msg: None,
        critical=lambda _msg: None,
        error=lambda _msg: None,
    )
    return tracker


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


@pytest.mark.asyncio
async def test_update_online_users_notifies_enter_and_leave(presence_tracker):
    with patch(
        "ushareiplay.managers.command_manager.CommandManager.instance"
    ) as mock_cmd_instance:
        mock_cmd = MagicMock()
        mock_cmd_instance.return_value = mock_cmd
        mock_cmd.notify_user_enter = MagicMock()
        mock_cmd.notify_user_leave = MagicMock()

        # First snapshot establishes baseline, no notifications
        presence_tracker.update_online_users(["alice", "bob"])

        # Second snapshot: alice left, carol entered
        presence_tracker.update_online_users(["bob", "carol"])

        mock_cmd.notify_user_leave.assert_called_once_with("alice")
        mock_cmd.notify_user_enter.assert_called_once_with("carol")


def test_clear_clears_users(presence_tracker):
    presence_tracker.update_online_users(["alice"])
    presence_tracker.record_return("alice")
    presence_tracker.clear()
    assert presence_tracker.get_online_users() == set()
    assert presence_tracker.should_trigger_return("alice") is True


def test_should_trigger_return_when_user_online_and_not_recently_entered(presence_tracker):
    # Establish baseline with alice online
    presence_tracker.update_online_users(["alice", "bob"])
    assert presence_tracker.should_trigger_return("alice") is True
    assert presence_tracker.should_trigger_return("bob") is True


def test_should_trigger_return_false_when_user_not_in_online_list(presence_tracker):
    # Online list has alice and bob; carol is NOT in online list (represents enter from outside, not return)
    presence_tracker.update_online_users(["alice", "bob"])
    assert presence_tracker.should_trigger_return("carol") is False


@pytest.mark.asyncio
async def test_should_trigger_return_false_when_user_recently_entered(presence_tracker):
    with patch("ushareiplay.managers.command_manager.CommandManager.instance") as mock_cmd:
        mock_cmd.return_value.notify_user_enter = MagicMock()
        mock_cmd.return_value.notify_user_leave = MagicMock()

        presence_tracker.update_online_users(["alice"])
        # carol enters now
        presence_tracker.update_online_users(["alice", "carol"])

        assert presence_tracker.was_recently_entered("carol") is True
        # Since carol just entered, arrival message should NOT trigger return
        assert presence_tracker.should_trigger_return("carol") is False


def test_should_trigger_return_debounces_consecutive_returns(presence_tracker):
    presence_tracker.update_online_users(["alice"])
    assert presence_tracker.should_trigger_return("alice") is True

    # Record return (e.g. from follower banner)
    presence_tracker.record_return("alice")

    # Second arrival message (e.g. from chat intake 1s later) is debounced
    assert presence_tracker.should_trigger_return("alice") is False

