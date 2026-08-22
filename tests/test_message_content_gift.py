import pytest
import pytest_asyncio
from unittest.mock import MagicMock, AsyncMock
from ushareiplay.core.db_manager import DatabaseManager
from ushareiplay.events.message_content import MessageContentEvent
from ushareiplay.core.chat_intake import ChatIntakeKind, classify_chat_line


@pytest_asyncio.fixture
async def db_init():
    manager = DatabaseManager(db_url="sqlite://:memory:")
    await manager.init()
    yield
    await manager.close()


@pytest.mark.asyncio
async def test_message_content_event_gift_handling(db_init, monkeypatch):
    from ushareiplay.core.message_queue import MessageQueue
    from ushareiplay.dal.user_dao import UserDAO
    try:
        MessageQueue.initialize()
    except Exception:
        pass
    await MessageQueue.instance().clear_queue()

    handler_mock = MagicMock()
    handler_mock.config = {"soul": {"room_owner": "Joyer"}}
    event_handler = MessageContentEvent(handler_mock)

    # Mock MessageManager and chat_logger
    mock_msg_manager = MagicMock()
    mock_msg_manager.latest_chats = ["souler[🍻🥂🥃🍸🍷🍺]送给Joyer"]
    mock_msg_manager.recent_chats = []

    monkeypatch.setattr("ushareiplay.managers.message_manager.MessageManager.instance", lambda: mock_msg_manager)
    monkeypatch.setattr("ushareiplay.managers.message_manager.get_chat_logger", lambda cfg: MagicMock())

    notify_mock = AsyncMock()
    monkeypatch.setattr("ushareiplay.managers.command_manager.CommandManager.notify_gift_receive", notify_mock, raising=False)

    wrapper = MagicMock()
    wrapper.content = "souler[🍻🥂🥃🍸🍷🍺]送给Joyer"

    await event_handler.handle("message_content", wrapper)

    # Verify notify_gift_receive was called with the giver's nickname
    notify_mock.assert_called_once_with("🍻🥂🥃🍸🍷🍺")

    # Verify user level was upgraded to 4
    user = await UserDAO.get_by_username("🍻🥂🥃🍸🍷🍺")
    assert user is not None
    assert user.level == 4

    # Verify thank you message was placed in message queue
    queue_msgs = await MessageQueue.instance().get_all_messages()
    assert any(m.content == "@🍻🥂🥃🍸🍷🍺 谢谢" for m in queue_msgs.values())


@pytest.mark.asyncio
async def test_message_content_event_heat_contribution_handling(db_init, monkeypatch):
    from ushareiplay.core.message_queue import MessageQueue
    from ushareiplay.dal.user_dao import UserDAO
    try:
        MessageQueue.initialize()
    except Exception:
        pass
    await MessageQueue.instance().clear_queue()

    handler_mock = MagicMock()
    handler_mock.config = {"soul": {"room_owner": "Joyer"}}
    event_handler = MessageContentEvent(handler_mock)

    mock_msg_manager = MagicMock()
    mock_msg_manager.latest_chats = ["恭喜Alice在此房间贡献出3120热力值"]
    mock_msg_manager.recent_chats = []

    monkeypatch.setattr("ushareiplay.managers.message_manager.MessageManager.instance", lambda: mock_msg_manager)
    monkeypatch.setattr("ushareiplay.managers.message_manager.get_chat_logger", lambda cfg: MagicMock())

    notify_mock = AsyncMock()
    monkeypatch.setattr("ushareiplay.managers.command_manager.CommandManager.notify_gift_receive", notify_mock, raising=False)

    wrapper = MagicMock()
    wrapper.content = "恭喜Alice在此房间贡献出3120热力值"

    await event_handler.handle("message_content", wrapper)

    # Verify notify_gift_receive was called with Alice
    notify_mock.assert_called_once_with("Alice")

    # Verify user level was upgraded to 5 and heat value recorded
    user = await UserDAO.get_by_username("Alice")
    assert user is not None
    assert user.level == 5
    assert user.heat_value == 3120

    # Verify thank you message in queue
    queue_msgs = await MessageQueue.instance().get_all_messages()
    assert any(m.content == "@Alice 谢谢" for m in queue_msgs.values())


@pytest.mark.asyncio
async def test_message_content_event_gift_higher_level_not_downgraded(db_init, monkeypatch):
    from ushareiplay.core.message_queue import MessageQueue
    from ushareiplay.dal.user_dao import UserDAO
    try:
        MessageQueue.initialize()
    except Exception:
        pass
    await MessageQueue.instance().clear_queue()

    # Pre-create user with level 7
    user7 = await UserDAO.get_or_create("HighLevelUser")
    user7.level = 7
    await user7.save()

    handler_mock = MagicMock()
    handler_mock.config = {"soul": {"room_owner": "Joyer"}}
    event_handler = MessageContentEvent(handler_mock)

    mock_msg_manager = MagicMock()
    mock_msg_manager.latest_chats = ["souler[HighLevelUser]送给Joyer 【爱心】"]
    mock_msg_manager.recent_chats = []

    monkeypatch.setattr("ushareiplay.managers.message_manager.MessageManager.instance", lambda: mock_msg_manager)
    monkeypatch.setattr("ushareiplay.managers.message_manager.get_chat_logger", lambda cfg: MagicMock())

    notify_mock = AsyncMock()
    monkeypatch.setattr("ushareiplay.managers.command_manager.CommandManager.notify_gift_receive", notify_mock, raising=False)

    wrapper = MagicMock()
    wrapper.content = "souler[HighLevelUser]送给Joyer 【爱心】"

    await event_handler.handle("message_content", wrapper)

    # Level must remain 7
    user = await UserDAO.get_by_username("HighLevelUser")
    assert user.level == 7

    # Thank you message must still be enqueued
    queue_msgs = await MessageQueue.instance().get_all_messages()
    assert any(m.content == "@HighLevelUser 谢谢" for m in queue_msgs.values())


@pytest.mark.asyncio
async def test_message_content_event_gift_to_non_owner_ignored(db_init, monkeypatch):
    from ushareiplay.core.message_queue import MessageQueue
    from ushareiplay.dal.user_dao import UserDAO
    try:
        MessageQueue.initialize()
    except Exception:
        pass
    await MessageQueue.instance().clear_queue()

    handler_mock = MagicMock()
    handler_mock.config = {"soul": {"room_owner": "Joyer"}}
    event_handler = MessageContentEvent(handler_mock)

    mock_msg_manager = MagicMock()
    mock_msg_manager.latest_chats = ["souler[Sender]送给OtherUser"]
    mock_msg_manager.recent_chats = []

    monkeypatch.setattr("ushareiplay.managers.message_manager.MessageManager.instance", lambda: mock_msg_manager)
    monkeypatch.setattr("ushareiplay.managers.message_manager.get_chat_logger", lambda cfg: MagicMock())

    notify_mock = AsyncMock()
    monkeypatch.setattr("ushareiplay.managers.command_manager.CommandManager.notify_gift_receive", notify_mock, raising=False)

    wrapper = MagicMock()
    wrapper.content = "souler[Sender]送给OtherUser"

    await event_handler.handle("message_content", wrapper)

    # notify_mock should NOT be called
    notify_mock.assert_not_called()

    # User should not be created or promoted
    user = await UserDAO.get_by_username("Sender")
    assert user is None

    # No thank you message in queue
    queue_msgs = await MessageQueue.instance().get_all_messages()
    assert len(queue_msgs) == 0


@pytest.mark.asyncio
async def test_process_missed_messages_heat_contribution(db_init, monkeypatch):
    from ushareiplay.core.message_queue import MessageQueue
    from ushareiplay.dal.user_dao import UserDAO
    from ushareiplay.managers.message_manager import MessageManager

    try:
        MessageQueue.initialize()
    except Exception:
        pass
    await MessageQueue.instance().clear_queue()

    manager = object.__new__(MessageManager)
    manager.recent_chats = ["old_anchor"]
    manager.latest_chats = []
    manager._chat_logger = MagicMock()

    handler_mock = MagicMock()
    handler_mock.config = {"soul": {"room_owner": "Joyer"}}
    handler_mock.key_actions.switch_to_app.return_value = True
    handler_mock.gesture_handler.scroll_container_until_element.return_value = (
        "message_list",
        MagicMock(),
        ["old_anchor", "恭喜 dio🤐 在此房间贡献出 11667热力值"],
    )
    handler_mock.element_finder.try_find_element.return_value = None
    manager._handler = handler_mock

    # Mock seat manager
    monkeypatch.setattr(manager, "_get_seat_manager", lambda: None)

    notify_mock = AsyncMock()
    monkeypatch.setattr(
        "ushareiplay.managers.command_manager.CommandManager.notify_gift_receive",
        notify_mock,
        raising=False,
    )

    await manager.process_missed_messages()

    # Verify user heat was recorded in database
    user = await UserDAO.get_by_username("dio🤐")
    assert user is not None
    assert user.heat_value == 11667
    assert user.level == 6

    # Verify thank you message was queued
    queue_msgs = await MessageQueue.instance().get_all_messages()
    assert any(m.content == "@dio🤐 谢谢" for m in queue_msgs.values())

    # Verify notify_gift_receive called
    notify_mock.assert_called_once_with("dio🤐")


@pytest.mark.asyncio
async def test_process_missed_messages_owner_gift(db_init, monkeypatch):
    from ushareiplay.core.message_queue import MessageQueue
    from ushareiplay.dal.user_dao import UserDAO
    from ushareiplay.managers.message_manager import MessageManager

    try:
        MessageQueue.initialize()
    except Exception:
        pass
    await MessageQueue.instance().clear_queue()

    manager = object.__new__(MessageManager)
    manager.recent_chats = ["old_anchor"]
    manager.latest_chats = []
    manager._chat_logger = MagicMock()

    handler_mock = MagicMock()
    handler_mock.config = {"soul": {"room_owner": "Joyer"}}
    handler_mock.key_actions.switch_to_app.return_value = True
    handler_mock.gesture_handler.scroll_container_until_element.return_value = (
        "message_list",
        MagicMock(),
        ["old_anchor", "souler[GiftSender]送给Joyer"],
    )
    handler_mock.element_finder.try_find_element.return_value = None
    manager._handler = handler_mock

    monkeypatch.setattr(manager, "_get_seat_manager", lambda: None)

    notify_mock = AsyncMock()
    monkeypatch.setattr(
        "ushareiplay.managers.command_manager.CommandManager.notify_gift_receive",
        notify_mock,
        raising=False,
    )

    await manager.process_missed_messages()

    # Verify user level upgraded to 4
    user = await UserDAO.get_by_username("GiftSender")
    assert user is not None
    assert user.level == 4

    # Verify thank you message was queued
    queue_msgs = await MessageQueue.instance().get_all_messages()
    assert any(m.content == "@GiftSender 谢谢" for m in queue_msgs.values())

    # Verify notify_gift_receive called
    notify_mock.assert_called_once_with("GiftSender")


