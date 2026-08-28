from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ushareiplay.core.db_manager import DatabaseManager
from ushareiplay.dal.user_dao import UserDAO
from ushareiplay.managers.command_manager import CommandManager
from ushareiplay.managers.memory_manager import MemoryManager
from ushareiplay.managers.party_manager import PartyManager
from ushareiplay.models.user import User


@pytest.mark.asyncio
async def test_party_manager_lifecycle_schedules_memory_consolidation(monkeypatch):
    db = DatabaseManager(db_url="sqlite://:memory:")
    await db.init()
    try:
        if not MemoryManager.is_initialized():
            MemoryManager.initialize()
        mm = MemoryManager.instance()
        mm.configure({"llm": {"memory": {"enabled": True}}})

        schedule_all_calls = []

        def mock_schedule_all():
            schedule_all_calls.append(True)

        monkeypatch.setattr(mm, "schedule_consolidation_all", mock_schedule_all)

        pm = PartyManager.instance() if PartyManager.is_initialized() else PartyManager.initialize()

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
                notice_manager=SimpleNamespace(set_default_notice=AsyncMock(return_value={"success": True})),
                seat_manager=SimpleNamespace(find_owner_seat=AsyncMock(return_value={"success": True})),
                post_party_create_automation=None,
            )
        )
        pm._handler = mock_handler

        # 1. Test _after_party_created
        await pm._after_party_created()
        assert len(schedule_all_calls) == 1

        # 2. Test end_party
        res = pm.end_party()
        assert "success" in res
        assert len(schedule_all_calls) == 2

    finally:
        await db.close()


@pytest.mark.asyncio
async def test_command_manager_presence_schedules_memory_consolidation(monkeypatch):
    db = DatabaseManager(db_url="sqlite://:memory:")
    await db.init()
    try:
        if not MemoryManager.is_initialized():
            MemoryManager.initialize()
        mm = MemoryManager.instance()
        mm.configure({"llm": {"memory": {"enabled": True}}})

        scheduled_users = []

        def mock_schedule_user(username):
            scheduled_users.append(username)

        monkeypatch.setattr(mm, "schedule_consolidation_user", mock_schedule_user)

        cm = CommandManager.instance() if CommandManager.is_initialized() else CommandManager.initialize()
        cm._logger = SimpleNamespace(info=MagicMock(), warning=MagicMock(), error=MagicMock(), debug=MagicMock())


        # Test notify_user_enter
        await cm.notify_user_enter("alice")
        assert "alice" in scheduled_users

        # Test notify_user_return
        await cm.notify_user_return("bob")
        assert "bob" in scheduled_users

        # Test notify_user_leave with canonical resolution
        main_user = await User.create(username="charlie_main", level=1)
        await User.create(username="charlie_alias", level=0, canonical_user=main_user)

        # When alias leaves, UserDAO.resolve_canonical resolves to charlie_main
        # Mock get_all_avatar_usernames to return empty online avatars so leave is not skipped
        from ushareiplay.managers.info_manager import InfoManager
        from ushareiplay.state.presence_tracker import PresenceTracker

        if not PresenceTracker.is_initialized():
            PresenceTracker.initialize()
        PresenceTracker.instance()._online_users = set()

        if not InfoManager.is_initialized():
            InfoManager.initialize()
        InfoManager.instance()._presence_tracker._online_users = set()

        with patch.object(UserDAO, "get_all_avatar_usernames", return_value={"charlie_alias"}):
            await cm.notify_user_leave("charlie_alias")
            assert "charlie_main" in scheduled_users


    finally:
        await db.close()
