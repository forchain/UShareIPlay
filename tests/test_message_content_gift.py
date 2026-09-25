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

class _Wrapper:
    """ElementWrapper 替身：composed_message_text 只读它的 content。"""

    def __init__(self, text):
        self.content = text


@pytest.mark.asyncio
async def test_message_content_event_gift_handling(db_init, monkeypatch, chat_window):
    from ushareiplay.core.message_queue import MessageQueue
    from ushareiplay.dal.user_dao import UserDAO
    try:
        MessageQueue.initialize()
    except Exception:
        pass
    await MessageQueue.instance().clear_queue()

    chat_window.handler.config = {"soul": {"room_owner": "Joyer"}}
    event_handler = MessageContentEvent(chat_window.handler)

    notify_mock = AsyncMock()
    monkeypatch.setattr("ushareiplay.managers.command_manager.CommandManager.notify_gift_receive", notify_mock, raising=False)

    wrapper = _Wrapper("souler[🍻🥂🥃🍸🍷🍺]送给Joyer")

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
async def test_message_content_event_heat_contribution_handling(db_init, monkeypatch, chat_window):
    from ushareiplay.core.message_queue import MessageQueue
    from ushareiplay.dal.user_dao import UserDAO
    try:
        MessageQueue.initialize()
    except Exception:
        pass
    await MessageQueue.instance().clear_queue()

    chat_window.handler.config = {"soul": {"room_owner": "Joyer"}}
    event_handler = MessageContentEvent(chat_window.handler)

    notify_mock = AsyncMock()
    monkeypatch.setattr("ushareiplay.managers.command_manager.CommandManager.notify_gift_receive", notify_mock, raising=False)

    wrapper = _Wrapper("恭喜Alice在此房间贡献出3120热力值")

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
async def test_message_content_event_gift_higher_level_not_downgraded(db_init, monkeypatch, chat_window):
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

    chat_window.handler.config = {"soul": {"room_owner": "Joyer"}}
    event_handler = MessageContentEvent(chat_window.handler)

    monkeypatch.setattr("ushareiplay.managers.message_manager.get_chat_logger", lambda cfg: MagicMock())

    notify_mock = AsyncMock()
    monkeypatch.setattr("ushareiplay.managers.command_manager.CommandManager.notify_gift_receive", notify_mock, raising=False)

    wrapper = _Wrapper("souler[HighLevelUser]送给Joyer 【爱心】")

    await event_handler.handle("message_content", wrapper)

    # Level must remain 7
    user = await UserDAO.get_by_username("HighLevelUser")
    assert user.level == 7

    # Thank you message must still be enqueued
    queue_msgs = await MessageQueue.instance().get_all_messages()
    assert any(m.content == "@HighLevelUser 谢谢" for m in queue_msgs.values())

@pytest.mark.asyncio
async def test_message_content_event_gift_to_non_owner_ignored(db_init, monkeypatch, chat_window):
    from ushareiplay.core.message_queue import MessageQueue
    from ushareiplay.dal.user_dao import UserDAO
    try:
        MessageQueue.initialize()
    except Exception:
        pass
    await MessageQueue.instance().clear_queue()

    chat_window.handler.config = {"soul": {"room_owner": "Joyer"}}
    event_handler = MessageContentEvent(chat_window.handler)

    monkeypatch.setattr("ushareiplay.managers.message_manager.get_chat_logger", lambda cfg: MagicMock())

    notify_mock = AsyncMock()
    monkeypatch.setattr("ushareiplay.managers.command_manager.CommandManager.notify_gift_receive", notify_mock, raising=False)

    wrapper = _Wrapper("souler[Sender]送给OtherUser")

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
async def test_process_missed_messages_heat_contribution(db_init, monkeypatch, chat_window):
    from ushareiplay.core.message_queue import MessageQueue
    from ushareiplay.dal.user_dao import UserDAO
    from ushareiplay.managers.message_manager import MessageManager

    try:
        MessageQueue.initialize()
    except Exception:
        pass
    await MessageQueue.instance().clear_queue()

    manager = chat_window.manager
    manager.observe(["old_anchor"])

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
async def test_process_missed_messages_owner_gift(db_init, monkeypatch, chat_window):
    from ushareiplay.core.message_queue import MessageQueue
    from ushareiplay.dal.user_dao import UserDAO
    from ushareiplay.managers.message_manager import MessageManager

    try:
        MessageQueue.initialize()
    except Exception:
        pass
    await MessageQueue.instance().clear_queue()

    manager = chat_window.manager
    manager.observe(["old_anchor"])

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


@pytest.mark.asyncio
async def test_process_missed_messages_does_not_re_dispatch_a_previous_screen_line(
    db_init, monkeypatch, chat_window
):
    """回溯滚过上一次屏幕上的行时不得重复派发。

    去重集是「观察前的窗口 ∪ 本次增量」。只看当前窗口时，屏幕滚走之后那些
    已经派发过的行就不在去重集里了，回溯会把它们当成补漏行再派发一次 ——
    礼物会被重复道谢、热力值重复写库。
    """
    from ushareiplay.core.message_queue import MessageQueue

    try:
        MessageQueue.initialize()
    except Exception:
        pass
    await MessageQueue.instance().clear_queue()

    manager = chat_window.manager
    owner_provider = {"soul": {"room_owner": "Joyer"}}

    # 上一屏：一条礼物（已派发过道谢）+ 一条普通发言
    gift_line = "souler[GiftSender]送给Joyer"
    plain_line = "souler[A]说: 在的"
    live = manager.observe([gift_line, plain_line])
    await manager.dispatch(live.new_lines, room_owner="Joyer")

    # 屏幕整段滚走：这一屏全是没见过的行，带出 missed
    delta = manager.observe(["souler[P]说: 1", "souler[Q]说: 2", "souler[R]说: 3"])
    assert delta.missed is True
    assert delta.anchor == plain_line

    handler_mock = MagicMock()
    handler_mock.config = owner_provider
    handler_mock.key_actions.switch_to_app.return_value = True
    handler_mock.gesture_handler.scroll_container_until_element.return_value = (
        "message_list",
        MagicMock(),
        # 回溯滚动越过了上一屏的内容，也捞到一条真正漏掉的礼物
        ["souler[Missed]送给Joyer", gift_line, plain_line],
    )
    handler_mock.element_finder.try_find_element.return_value = None
    manager._handler = handler_mock

    monkeypatch.setattr(manager, "_get_seat_manager", lambda: None)

    await manager.process_missed_messages(delta.anchor)

    contents = [m.content for m in (await MessageQueue.instance().get_all_messages()).values()]
    # 上一屏的礼物不重复道谢，真正漏掉的那条照常道谢
    assert contents.count("@GiftSender 谢谢") == 1
    assert contents.count("@Missed 谢谢") == 1


@pytest.mark.asyncio
async def test_resolve_room_owner_falls_back_to_the_level_9_user_in_db(db_init, chat_window):
    """配置没写 room_owner 时，房主从库里 level=9 的用户解析。

    `RolePolicy.room_owner` 在配置缺省时会给出代码默认值，用它判断「有没有配」
    会让这条回落永远走不到 —— 礼物就识别不出「送给房主」。
    """
    from ushareiplay.dal.user_dao import UserDAO

    chat_window.handler.config = {"soul": {}}  # 没有 room_owner

    user = await UserDAO.get_or_create("HostFromDB")
    await UserDAO.update_level(user.id, 9)

    assert await chat_window.manager.resolve_room_owner() == "HostFromDB"


@pytest.mark.asyncio
async def test_resolve_room_owner_prefers_the_configured_owner(db_init, chat_window):
    from ushareiplay.dal.user_dao import UserDAO

    chat_window.handler.config = {"soul": {"room_owner": "ConfiguredHost"}}

    user = await UserDAO.get_or_create("HostFromDB")
    await UserDAO.update_level(user.id, 9)

    assert await chat_window.manager.resolve_room_owner() == "ConfiguredHost"
