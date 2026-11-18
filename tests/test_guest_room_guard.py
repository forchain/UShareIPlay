from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from ushareiplay.modules.room.use_cases import RoomStateService


class RuntimeStub:
    def emit(self, *args, **kwargs):
        return None

    @asynccontextmanager
    async def ui_session(self, *_args, **_kwargs):
        yield


class HandlerStub:
    def __init__(self, config: dict):
        self.config = config

        class _Logger:
            def info(self, *_a, **_k):
                return None

            def warning(self, *_a, **_k):
                return None

            def debug(self, *_a, **_k):
                return None

            def error(self, *_a, **_k):
                return None

        self.logger = _Logger()
        self.controller = None


class MessageInfoStub:
    def __init__(self, nickname: str, content: str = ":play"):
        self.nickname = nickname
        self.content = content
        self.sleep_exempt = False


class DummyCommand:
    def __init__(self):
        self.called = False

    async def process(self, *_args, **_kwargs):
        self.called = True
        return {"message": "OK"}


@pytest.fixture
def room_state():
    from ushareiplay.modules.command.domain import CommandCatalogue
    from ushareiplay.adapters.outbound.system.config_loader import ConfigLoader

    state = RoomStateService(
        catalogue=CommandCatalogue.from_config(ConfigLoader.load_config())
    )
    state._logger = SimpleNamespace(info=lambda _msg: None)
    return state


def _make_command_manager(room_state):
    from ushareiplay.adapters.outbound.appium.soul.message_dispatch import MessageDispatch
    from ushareiplay.adapters.outbound.persistence.user_repository import TortoiseUserRepository
    from ushareiplay.adapters.inbound.runtime.command_manager import CommandManager

    cm = CommandManager(
        room_state=room_state,
        users=TortoiseUserRepository(),
        message_dispatch=MessageDispatch(),
    )
    cm.configure_runtime(RuntimeStub())
    cm._handler = HandlerStub(config={"system_users": ["Timer"]})
    return cm


@pytest.mark.asyncio
async def test_guest_room_allows_music_commands(room_state):
    cm = _make_command_manager(room_state)
    room_state.is_guest_room = True

    dummy_cmd = DummyCommand()
    msg = MessageInfoStub(nickname="Alice", content=":play 晴天")
    cmd_info = {
        "prefix": "play",
        "level": 1,
        "parameters": ["晴天"],
        "error_template": "Failed to play music, because {error}",
        "response_template": "{message}",
    }

    with patch("ushareiplay.adapters.outbound.persistence.user_repository.TortoiseUserRepository.get_or_create", new_callable=AsyncMock) as mock_user:
        mock_user.return_value = SimpleNamespace(level=1)
        res = await cm.process_command(dummy_cmd, msg, cmd_info)

    assert dummy_cmd.called is True
    assert "OK" in res


@pytest.mark.asyncio
async def test_guest_room_blocks_room_management_commands(room_state):
    cm = _make_command_manager(room_state)
    room_state.is_guest_room = True

    management_prefixes = ["theme", "title", "topic", "notice", "seat", "pack", "admin", "timer", "recommend"]

    for prefix in management_prefixes:
        dummy_cmd = DummyCommand()
        msg = MessageInfoStub(nickname="Alice", content=f":{prefix} test")
        cmd_info = {
            "prefix": prefix,
            "level": 1,
            "parameters": ["test"],
            "error_template": f"Failed {prefix}, because {{error}}",
            "response_template": "{message}",
        }

        with patch("ushareiplay.adapters.outbound.persistence.user_repository.TortoiseUserRepository.get_or_create", new_callable=AsyncMock) as mock_user:
            mock_user.return_value = SimpleNamespace(level=9)
            res = await cm.process_command(dummy_cmd, msg, cmd_info)

        assert dummy_cmd.called is False, f"Command :{prefix} should NOT have been called in guest room"
        assert "当前处于他人房间，仅支持点歌功能" in res


@pytest.mark.asyncio
async def test_host_room_allows_all_commands(room_state):
    cm = _make_command_manager(room_state)
    room_state.is_guest_room = False

    dummy_cmd = DummyCommand()
    msg = MessageInfoStub(nickname="Alice", content=":theme 听歌")
    cmd_info = {
        "prefix": "theme",
        "level": 1,
        "parameters": ["听歌"],
        "error_template": "Failed to set theme, because {error}",
        "response_template": "{message}",
    }

    with patch("ushareiplay.adapters.outbound.persistence.user_repository.TortoiseUserRepository.get_or_create", new_callable=AsyncMock) as mock_user:
        mock_user.return_value = SimpleNamespace(level=3)
        res = await cm.process_command(dummy_cmd, msg, cmd_info)

    assert dummy_cmd.called is True
    assert "OK" in res


@pytest.mark.asyncio
async def test_guest_room_filters_commands_for_natural_language_resolver(monkeypatch, room_state):
    from ushareiplay.adapters.inbound.runtime.keyword_nl_fallback import (
        NaturalLanguageFallbackAdapter,
        RoomInfoProvider,
    )
    from ushareiplay.adapters.inbound.runtime.chat_intake import ChatIntakeKind, ChatIntakeResult
    from ushareiplay.modules.command.domain import NaturalLanguageResult
    from ushareiplay.modules.command.use_cases import KeywordUseCases
    from tests.fakes.in_memory_keyword_repository import InMemoryKeywordRepository
    from tests.fakes.in_memory_user_repository import InMemoryUserRepository

    passed_commands = []

    async def _mock_resolve(**kwargs):
        nonlocal passed_commands
        passed_commands = kwargs.get("commands_config", [])
        return NaturalLanguageResult(type="reply", content="只支持点歌")

    commands_config = [
        {"prefix": "play", "level": 1},
        {"prefix": "theme", "level": 3},
        {"prefix": "vol", "level": 1},
        {"prefix": "seat", "level": 1},
    ]
    room_state.is_guest_room = True
    fallback = NaturalLanguageFallbackAdapter(
        commands_config=lambda: commands_config,
        catalogue=lambda: None,
        room_info=RoomInfoProvider(room_state),
        playback_info=lambda: None,
        resolver=SimpleNamespace(resolve=_mock_resolve),
    )

    users = InMemoryUserRepository()
    km = KeywordUseCases(
        repository=InMemoryKeywordRepository(users),
        users=users,
        presence=SimpleNamespace(is_user_online=lambda _name: True),
        queue=SimpleNamespace(enqueue=lambda *_a, **_k: None),
        chat_logs=SimpleNamespace(record=lambda *_a, **_k: None),
        config_source=SimpleNamespace(load=lambda: None),
        fallback=fallback,
        logger=SimpleNamespace(
            info=lambda *_a, **_k: None,
            error=lambda *_a, **_k: None,
            warning=lambda *_a, **_k: None,
        ),
    )

    result = ChatIntakeResult(
        kind=ChatIntakeKind.KEYWORD_MENTION,
        nickname="Alice",
        text="改个房间主题",
        params="",
    )

    await km.dispatch_mention(result, sleep_exempt=True)

    passed_prefixes = [c.get("prefix") for c in passed_commands]
    assert "play" in passed_prefixes
    assert "vol" in passed_prefixes
    assert "theme" not in passed_prefixes
    assert "seat" not in passed_prefixes


@pytest.mark.asyncio
async def test_guest_room_blocks_all_seat_manager_actions(room_state):
    from tests.seat_support import build_seat_service

    room_state.is_guest_room = True

    seat_mgr = build_seat_service(room_state=room_state)

    # take seat
    res = await seat_mgr.take_seat(1)
    assert res.get("error") == "他人房间不支持座位功能"

    # reserve seat
    res = await seat_mgr.reserve_seat("Alice", 1)
    assert res.get("error") == "他人房间不支持座位功能"

    # find owner seat
    res = await seat_mgr.find_owner_seat()
    assert res.get("error") == "他人房间不支持座位功能"

    # accompany user
    res = await seat_mgr.accompany_user("Bob")
    assert res.get("error") == "他人房间不支持座位功能"

    # remove seat occupant
    res = await seat_mgr.remove_seat_occupant(1)
    assert res.get("error") == "他人房间不支持座位功能"

    # remove user reservation
    res = await seat_mgr.remove_user_reservation("Alice")
    assert res.get("error") == "他人房间不支持座位功能"

    # check seats on entry (should return None safely without touching UI)
    res = await seat_mgr.check_seats_on_entry("Alice")
    assert res is None

    # prepare for chat scan (should return True immediately without collapsing seat panel)
    res = await seat_mgr.prepare_for_chat_scan()
    assert res is True


@pytest.mark.asyncio
async def test_guest_room_blocks_seat_check_on_enter_and_return(room_state):
    """客房里进入/返回都不复核**座位**。

    #436 之前这条守卫挂在 `:seat` 命令的 `user_enter` / `user_return` 钩子上，靠
    `CommandManager` 按属性名反射分发。反射分发收掉后座位复核改由 `notify_*` 显式
    调用，守卫也跟着搬过来 —— 这里钉的是新缝上的同一件事。
    """
    from ushareiplay.adapters.inbound.runtime.command_manager import CommandManager

    room_state.is_guest_room = True

    cm = CommandManager(room_state=room_state)
    mock_check = AsyncMock()
    cm.controller = SimpleNamespace(seat_service=SimpleNamespace(check_seats_on_entry=mock_check))

    cm.user_event_hooks = MagicMock()
    cm.user_event_hooks.fire = AsyncMock(return_value=0)
    await cm.notify_user_enter("Alice")
    await cm.notify_user_return("Alice")

    mock_check.assert_not_awaited()


@pytest.mark.asyncio
async def test_host_room_checks_seats_on_enter_and_return(room_state):
    """本房进入/返回都要复核座位。

    这条是 #436 的**回归哨**：座位复核原本是 `:seat` 命令的一个副作用订阅者，只靠
    反射分发连到事件上。反射删掉而显式调用忘了补，进入/返回时的座位自动认领会
    静默失效 —— 不报错，只是座位再也不动了。
    """
    from ushareiplay.adapters.inbound.runtime.command_manager import CommandManager

    room_state.is_guest_room = False

    cm = CommandManager(room_state=room_state)
    mock_check = AsyncMock()
    cm.controller = SimpleNamespace(seat_service=SimpleNamespace(check_seats_on_entry=mock_check))

    cm.user_event_hooks = MagicMock()
    cm.user_event_hooks.fire = AsyncMock(return_value=0)
    await cm.notify_user_enter("Alice")
    await cm.notify_user_return("Bob")

    assert mock_check.await_args_list == [call("Alice"), call("Bob")]


@pytest.mark.asyncio
async def test_guest_room_blocks_room_name_and_title_updates(room_state):
    from tests.room_profile_support import RoomProfileManager

    room_state.is_guest_room = True

    profile = RoomProfileManager(room_state=room_state)
    profile.adopt_handler(HandlerStub(config={}))
    profile._logger = SimpleNamespace(
        info=lambda _msg: None, warning=lambda _msg: None, error=lambda _msg: None
    )

    # set_theme in guest room
    res = profile.set_theme("听歌")
    assert "error" in res

    # update_title in guest room
    profile.pending_ui_update = True
    res = profile.update_title()
    assert res.get("skipped") is True
    assert res.get("reason") == "guest_room"

    # _write_title_in_drawer in guest room
    res = profile._write_title_in_drawer("新歌速递")
    assert res.get("skipped") is True
    assert res.get("reason") == "guest_room"

    # set_title in guest room
    res = profile.set_title("新歌速递")
    assert res.get("skipped") is True
    assert res.get("reason") == "guest_room"


@pytest.mark.asyncio
async def test_guest_room_blocks_notice_updates(room_state):
    from tests.room_profile_support import RoomProfileManager

    room_state.is_guest_room = True

    profile = RoomProfileManager(handler=HandlerStub(config={}), room_state=room_state)
    profile._logger = SimpleNamespace(info=lambda _msg: None, warning=lambda _msg: None, error=lambda _msg: None)

    res = profile.set_notice("欢迎来听歌")
    assert res.get("skipped") is True
    assert res.get("reason") == "guest_room"

    # 已经排队的公告在别人房间里也不会被写出去（草稿留着，冷却不动）
    profile.drafts.set_pending("notice", "欢迎来听歌")
    res = profile.update_notice()
    assert res.get("skipped") is True
    assert res.get("reason") == "guest_room"
    assert profile.drafts.pending("notice") == "欢迎来听歌"

    res = profile.restore_notice("欢迎来听歌")
    assert res.get("skipped") is True
    assert res.get("reason") == "guest_room"


@pytest.mark.asyncio
async def test_guest_room_blocks_recommendation_sync(room_state):
    from tests.room_profile_support import RoomProfileManager

    room_state.is_guest_room = True

    rm = RoomProfileManager(handler=HandlerStub(config={}), room_state=room_state)
    rm._logger = SimpleNamespace(info=lambda _msg: None, warning=lambda _msg: None, error=lambda _msg: None)

    res = rm.ensure_synced_on_return()
    assert res.get("skipped") is True
    assert res.get("reason") == "guest_room"

    res = rm.update_recommendation_ui(True)
    assert "error" in res


@pytest.mark.asyncio
async def test_guest_room_blocks_events_and_window_audit(room_state):
    from ushareiplay.adapters.inbound.ui_events.chat_room_title import ChatRoomTitleEvent
    from ushareiplay.adapters.inbound.ui_events.party_name_violation_later import PartyNameViolationLaterEvent
    from tests.room_profile_support import RoomProfileManager

    room_state.is_guest_room = True

    handler = HandlerStub(config={})
    profile = RoomProfileManager(handler=handler, room_state=room_state)
    profile._logger = SimpleNamespace(info=lambda _msg: None, warning=lambda _msg: None, error=lambda _msg: None)
    handler.controller = SimpleNamespace(room_state=room_state, room_profile_manager=profile)

    # ChatRoomTitleEvent in guest room
    evt = ChatRoomTitleEvent(handler)
    fake_wrapper = SimpleNamespace(text="开发测试，慎入", content="开发测试，慎入")
    res = await evt.handle("chat_room_title", fake_wrapper)
    assert res is False

    res = profile.audit_and_repair()
    assert res.get("skipped") is True
    assert res.get("reason") == "guest_room"

    res = profile.process_pending_retry()
    assert res.get("skipped") == "guest_room"


def _party_manager_with_stub_handler(monkeypatch, room_state):
    """真实的 PartyService + stub handler：房间核对判定现在归它所有。"""
    from ushareiplay.adapters.outbound.appium.soul.party_driver import SoulPartyDriver
    from ushareiplay.modules.room import PartyService

    handler = HandlerStub(config={})
    manager = PartyService(
        driver=SoulPartyDriver(handler),
        room_state=room_state,
        logger=handler.logger,
    )
    handler.controller = SimpleNamespace(party_service=manager, room_state=room_state)
    return manager, handler


@pytest.mark.asyncio
async def test_room_id_event_mismatch_triggers_leave_and_recreate(tmp_path, monkeypatch, room_state):
    from unittest.mock import AsyncMock
    from ushareiplay.adapters.inbound.ui_events.room_id import RoomIdEvent

    room_state.expected_party_id = "FM18633292"

    party_manager, handler = _party_manager_with_stub_handler(monkeypatch, room_state)
    monkeypatch.setattr(party_manager, "leave_and_recreate_party", AsyncMock(return_value=True))

    evt = RoomIdEvent(handler)
    # 模拟系统自动调入随机房间 FM99999999
    wrapper = SimpleNamespace(text="FM99999999", content="FM99999999")
    res = await evt.handle("room_id", wrapper)

    assert res is True
    party_manager.leave_and_recreate_party.assert_awaited_once()


@pytest.mark.asyncio
async def test_room_id_event_match_updates_state(monkeypatch, room_state):
    from unittest.mock import AsyncMock
    from ushareiplay.adapters.inbound.ui_events.room_id import RoomIdEvent

    room_state.expected_party_id = "FM18633292"

    party_manager, handler = _party_manager_with_stub_handler(monkeypatch, room_state)
    monkeypatch.setattr(party_manager, "leave_and_recreate_party", AsyncMock(return_value=True))

    evt = RoomIdEvent(handler)
    # 模拟在预期的客房 FM18633292
    wrapper = SimpleNamespace(text="FM18633292", content="FM18633292")
    res = await evt.handle("room_id", wrapper)

    assert res is False
    assert room_state.room_id == "FM18633292"
    assert handler.party_id == "FM18633292"
    party_manager.leave_and_recreate_party.assert_not_awaited()


@pytest.mark.asyncio
async def test_room_id_event_does_not_spam_info_logs_when_room_id_unchanged(monkeypatch, room_state):
    from unittest.mock import MagicMock
    from ushareiplay.adapters.inbound.ui_events.room_id import RoomIdEvent

    room_state.expected_party_id = "FM18633292"

    party_manager, handler = _party_manager_with_stub_handler(monkeypatch, room_state)
    info_mock = MagicMock()
    debug_mock = MagicMock()
    party_manager._logger = SimpleNamespace(
        info=info_mock,
        warning=lambda *a, **k: None,
        debug=debug_mock,
        error=lambda *a, **k: None,
    )

    evt = RoomIdEvent(handler)
    wrapper = SimpleNamespace(text="FM18633292", content="FM18633292")

    # 第一次扫描：房间首次核验，记录一次 info 日志
    await evt.handle("room_id", wrapper)
    assert info_mock.call_count == 1
    assert "Room verified at room_id_event: FM18633292" in info_mock.call_args[0][0]

    # 后续扫描（房间未变且无需告警）：高频检测类日志不允许输出，即便 debug 也不允许
    await evt.handle("room_id", wrapper)
    await evt.handle("room_id", wrapper)
    assert info_mock.call_count == 1
    debug_mock.assert_not_called()


@pytest.mark.asyncio
async def test_detect_initial_room_state_mismatch_triggers_leave(monkeypatch, room_state):
    from unittest.mock import AsyncMock
    from ushareiplay.bootstrap.runtime_loop import RuntimeLoop

    room_state.expected_party_id = "FM18633292"

    party_manager, _stub_handler = _party_manager_with_stub_handler(monkeypatch, room_state)
    monkeypatch.setattr(party_manager, "leave_and_recreate_party", AsyncMock(return_value=True))

    element_finder = type('_EF', (), {
        'try_find_element': lambda self, key, log=False: object(),
        'get_element_text': lambda self, elem: "FM99999999"
    })()

    soul_handler = type('_SH', (), {
        'element_finder': element_finder,
        'party_id': None,
    })()

    loop = RuntimeLoop.__new__(RuntimeLoop)
    loop.soul_handler = soul_handler
    loop.party_service = party_manager
    loop.logger = type('_L', (), {'warning': lambda *a: None, 'info': lambda *a: None, 'debug': lambda *a: None})()

    await loop._detect_initial_room_state()
    party_manager.leave_and_recreate_party.assert_awaited_once()


@pytest.mark.asyncio
async def test_new_seat_entry_inherits_guest_room_guard(room_state):
    """证明新增座位入口无需复制守卫即可获得同样的客房行为。"""
    from ushareiplay.modules.seat.domain import (
        guest_room_guard,
        GUEST_ROOM_ERROR_RESULT,
        GUEST_ROOM_CHAT_SCAN_RESULT,
        GUEST_ROOM_ENTRY_CHECK_RESULT,
    )

    executed = {"error_entry": False, "scan_entry": False, "check_entry": False}

    class DummySeatManager:
        @guest_room_guard(GUEST_ROOM_ERROR_RESULT)
        async def new_action(self):
            executed["error_entry"] = True
            return {"success": "done"}

        @guest_room_guard(GUEST_ROOM_CHAT_SCAN_RESULT)
        async def new_scan(self):
            executed["scan_entry"] = True
            return False

        @guest_room_guard(GUEST_ROOM_ENTRY_CHECK_RESULT)
        async def new_check(self):
            executed["check_entry"] = True
            return {"user": "checked"}

    mgr = DummySeatManager()
    mgr.room_state = room_state

    # 1. 客房状态：无需复制任何客房检测样板，直接短路返回对应显式命名的返回形状
    room_state.is_guest_room = True

    assert await mgr.new_action() == GUEST_ROOM_ERROR_RESULT
    assert executed["error_entry"] is False

    assert await mgr.new_scan() == GUEST_ROOM_CHAT_SCAN_RESULT
    assert executed["scan_entry"] is False

    assert await mgr.new_check() == GUEST_ROOM_ENTRY_CHECK_RESULT
    assert executed["check_entry"] is False

    # 2. 主房状态：正常穿透并执行方法体
    room_state.is_guest_room = False

    assert await mgr.new_action() == {"success": "done"}
    assert executed["error_entry"] is True

    assert await mgr.new_scan() is False
    assert executed["scan_entry"] is True

    assert await mgr.new_check() == {"user": "checked"}
    assert executed["check_entry"] is True







