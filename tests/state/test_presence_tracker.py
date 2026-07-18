from types import SimpleNamespace

import pytest
from unittest.mock import MagicMock, patch

from ushareiplay.state.presence_tracker import PresenceTracker


@pytest.fixture
def presence_tracker():
    if hasattr(PresenceTracker, "_instance"):
        del PresenceTracker._instance
    tracker = PresenceTracker.instance()
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
    presence_tracker.clear()
    assert presence_tracker.get_online_users() == set()
