from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ushareiplay.adapters.outbound.persistence.db_manager import DatabaseManager
from ushareiplay.dal.user_dao import UserDAO
from ushareiplay.adapters.inbound.runtime.command_manager import CommandManager
from ushareiplay.managers.party_manager import PartyManager
from ushareiplay.adapters.outbound.persistence.models.user import User


class RecordingMemory:
    def __init__(self):
        self.sweeps = 0
        self.users = []

    def schedule_all(self):
        self.sweeps += 1

    def schedule_user(self, username):
        self.users.append(username)


@pytest.mark.asyncio
async def test_party_manager_lifecycle_schedules_memory_consolidation():
    memory = RecordingMemory()
    pm = PartyManager.instance() if PartyManager.is_initialized() else PartyManager.initialize()
    pm.user_memory = memory

    # Mock handler and sub-managers
    mock_handler = SimpleNamespace(
        logger=SimpleNamespace(info=MagicMock(), warning=MagicMock(), error=MagicMock(), debug=MagicMock()),
        party_id="test_party_123",
        element_finder=SimpleNamespace(
            try_find_element=lambda key, log=True: MagicMock(click=MagicMock()) if key == "exit_room_btn" else None,
            wait_for_element_clickable=lambda key, timeout=3: MagicMock(click=MagicMock()),
        ),
        key_actions=SimpleNamespace(switch_to_app=lambda: True),
        controller=SimpleNamespace(
            room_profile_manager=SimpleNamespace(
                set_default_notice=AsyncMock(return_value={"success": True})
            ),
            seat_manager=SimpleNamespace(find_owner_seat=AsyncMock(return_value={"success": True})),
            post_party_create_automation=None,
        )
    )
    pm._handler = mock_handler

    # 1. Test _after_party_created
    await pm._after_party_created()
    assert memory.sweeps == 1

    # 2. Test end_party
    res = pm.end_party()
    assert "success" in res
    assert memory.sweeps == 2


@pytest.mark.asyncio
async def test_command_manager_presence_schedules_memory_consolidation():
    db = DatabaseManager(db_url="sqlite://:memory:")
    await db.init()
    try:
        memory = RecordingMemory()

        from tests.legacy_state import PresenceTracker
        from tests.room_support import make_hooks

        cm = CommandManager.instance() if CommandManager.is_initialized() else CommandManager.initialize()
        cm._logger = SimpleNamespace(info=MagicMock(), warning=MagicMock(), error=MagicMock(), debug=MagicMock())
        cm.user_memory = memory
        cm.user_event_hooks = make_hooks(
            presence=PresenceTracker.instance(), memory=memory
        )

        # Test notify_user_enter
        await cm.notify_user_enter("alice")
        assert "alice" in memory.users

        # Test notify_user_return
        await cm.notify_user_return("bob")
        assert "bob" in memory.users

        # Test notify_user_leave with canonical resolution
        main_user = await User.create(username="charlie_main", level=1)
        await User.create(username="charlie_alias", level=0, canonical_user=main_user)

        # When alias leaves, the exit gate resolves to charlie_main.
        PresenceTracker.instance()._online_users = set()

        await cm.notify_user_leave("charlie_alias")
        assert "charlie_main" in memory.users


    finally:
        await db.close()
