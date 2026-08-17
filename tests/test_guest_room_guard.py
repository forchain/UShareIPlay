from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from ushareiplay.state.room_state import RoomState


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


@pytest.fixture(autouse=True)
def _reset_singletons():
    from ushareiplay.core.message_dispatch import MessageDispatch
    from ushareiplay.managers.command_manager import CommandManager

    CommandManager.reset_instance()
    MessageDispatch.reset_instance()
    MessageDispatch.initialize()
    RoomState.reset_instance()
    room_state = RoomState.initialize()
    room_state._logger = SimpleNamespace(info=lambda _msg: None)
    yield
    CommandManager.reset_instance()
    MessageDispatch.reset_instance()
    RoomState.reset_instance()


@pytest.mark.asyncio
async def test_guest_room_allows_music_commands():
    from ushareiplay.managers.command_manager import CommandManager

    cm = CommandManager.initialize()
    cm.configure_runtime(RuntimeStub())
    cm._handler = HandlerStub(config={"system_users": ["Timer"]})

    room_state = RoomState.instance()
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

    with patch("ushareiplay.dal.user_dao.UserDAO.get_or_create", new_callable=AsyncMock) as mock_user:
        mock_user.return_value = SimpleNamespace(level=1)
        res = await cm.process_command(dummy_cmd, msg, cmd_info)

    assert dummy_cmd.called is True
    assert "OK" in res


@pytest.mark.asyncio
async def test_guest_room_blocks_room_management_commands():
    from ushareiplay.managers.command_manager import CommandManager

    cm = CommandManager.initialize()
    cm.configure_runtime(RuntimeStub())
    cm._handler = HandlerStub(config={"system_users": ["Timer"]})

    room_state = RoomState.instance()
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

        with patch("ushareiplay.dal.user_dao.UserDAO.get_or_create", new_callable=AsyncMock) as mock_user:
            mock_user.return_value = SimpleNamespace(level=9)
            res = await cm.process_command(dummy_cmd, msg, cmd_info)

        assert dummy_cmd.called is False, f"Command :{prefix} should NOT have been called in guest room"
        assert "当前处于他人房间，仅支持点歌功能" in res


@pytest.mark.asyncio
async def test_host_room_allows_all_commands():
    from ushareiplay.managers.command_manager import CommandManager

    cm = CommandManager.initialize()
    cm.configure_runtime(RuntimeStub())
    cm._handler = HandlerStub(config={"system_users": ["Timer"]})

    room_state = RoomState.instance()
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

    with patch("ushareiplay.dal.user_dao.UserDAO.get_or_create", new_callable=AsyncMock) as mock_user:
        mock_user.return_value = SimpleNamespace(level=3)
        res = await cm.process_command(dummy_cmd, msg, cmd_info)

    assert dummy_cmd.called is True
    assert "OK" in res


@pytest.mark.asyncio
async def test_guest_room_filters_commands_for_natural_language_resolver(monkeypatch):
    from ushareiplay.core.chat_intake import ChatIntakeKind, ChatIntakeResult
    from ushareiplay.core.natural_language_resolver import NaturalLanguageResult
    from ushareiplay.managers.keyword_manager import KeywordManager

    KeywordManager.reset_instance()
    km = KeywordManager.initialize()
    km._logger = SimpleNamespace(
        info=lambda *_a, **_k: None,
        error=lambda *_a, **_k: None,
        warning=lambda *_a, **_k: None,
    )
    km._config = {
        "llm": {"enabled": True, "api_key": "test"},
        "commands": [
            {"prefix": "play", "level": 1},
            {"prefix": "theme", "level": 3},
            {"prefix": "vol", "level": 1},
            {"prefix": "seat", "level": 1},
        ],
    }

    room_state = RoomState.instance()
    room_state.is_guest_room = True

    async def _mock_find_keyword(_kw, _user):
        return None

    monkeypatch.setattr(km, "find_keyword", _mock_find_keyword)

    passed_commands = []

    async def _mock_resolve(**kwargs):
        nonlocal passed_commands
        passed_commands = kwargs.get("commands_config", [])
        return NaturalLanguageResult(type="reply", content="只支持点歌")

    km._nl_resolver = SimpleNamespace(resolve=_mock_resolve)

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
async def test_guest_room_blocks_all_seat_manager_actions():
    from ushareiplay.managers.seat_manager import SeatManager

    room_state = RoomState.instance()
    room_state.is_guest_room = True

    seat_mgr = SeatManager()

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
async def test_guest_room_blocks_seat_command_user_enter():
    from ushareiplay.commands.seat import SeatCommand

    room_state = RoomState.instance()
    room_state.is_guest_room = True

    fake_controller = SimpleNamespace(soul_handler=HandlerStub(config={}), music_handler=None)
    seat_cmd = SeatCommand(fake_controller)

    with patch("ushareiplay.managers.seat_manager.SeatManager.check_seats_on_entry", new_callable=AsyncMock) as mock_check:
        await seat_cmd.user_enter("Alice")
        await seat_cmd.user_return("Alice")
        mock_check.assert_not_awaited()


@pytest.mark.asyncio
async def test_guest_room_blocks_room_name_and_title_updates():
    from ushareiplay.managers.room_name_manager import RoomNameManager

    room_state = RoomState.instance()
    room_state.is_guest_room = True

    RoomNameManager.reset_instance()
    rnm = RoomNameManager.initialize()
    rnm._handler = HandlerStub(config={})
    rnm._logger = SimpleNamespace(info=lambda _msg: None, warning=lambda _msg: None, error=lambda _msg: None)

    try:
        # set_theme in guest room
        res = rnm.set_theme("听歌")
        assert "error" in res

        # process_pending_update in guest room
        rnm.pending_ui_update = True
        res = rnm.process_pending_update()
        assert res.get("skipped") is True
        assert res.get("reason") == "guest_room"

        # _update_title_ui in guest room
        res = rnm._update_title_ui("新歌速递")
        assert res.get("skipped") is True
        assert res.get("reason") == "guest_room"

        # set_next_title in guest room
        res = rnm.set_next_title("新歌速递")
        assert res.get("skipped") is True
        assert res.get("reason") == "guest_room"
    finally:
        RoomNameManager.reset_instance()


@pytest.mark.asyncio
async def test_guest_room_blocks_notice_updates():
    from ushareiplay.managers.notice_manager import NoticeManager

    room_state = RoomState.instance()
    room_state.is_guest_room = True

    NoticeManager.reset_instance()
    nm = NoticeManager.initialize()
    nm._handler = HandlerStub(config={})
    nm._logger = SimpleNamespace(info=lambda _msg: None, warning=lambda _msg: None, error=lambda _msg: None)

    try:
        res = nm.set_notice_with_cooldown("欢迎来听歌")
        assert res.get("skipped") is True
        assert res.get("reason") == "guest_room"

        res = nm._set_notice_immediate("欢迎来听歌")
        assert res.get("skipped") is True
        assert res.get("reason") == "guest_room"
    finally:
        NoticeManager.reset_instance()


@pytest.mark.asyncio
async def test_guest_room_blocks_recommendation_sync():
    from ushareiplay.managers.recommendation_manager import RecommendationManager

    room_state = RoomState.instance()
    room_state.is_guest_room = True

    RecommendationManager.reset_instance()
    rm = RecommendationManager.initialize()
    rm._handler = HandlerStub(config={})
    rm._logger = SimpleNamespace(info=lambda _msg: None, warning=lambda _msg: None, error=lambda _msg: None)

    try:
        res = rm.ensure_synced_on_return()
        assert res.get("skipped") is True
        assert res.get("reason") == "guest_room"

        res = rm.update_recommendation_ui(True)
        assert "error" in res
    finally:
        RecommendationManager.reset_instance()


@pytest.mark.asyncio
async def test_guest_room_blocks_events_and_auditor():
    from ushareiplay.events.chat_room_title import ChatRoomTitleEvent
    from ushareiplay.events.party_name_violation_later import PartyNameViolationLaterEvent
    from ushareiplay.managers.room_info_auditor import RoomInfoWindowAuditor

    room_state = RoomState.instance()
    room_state.is_guest_room = True

    handler = HandlerStub(config={})

    # ChatRoomTitleEvent in guest room
    evt = ChatRoomTitleEvent(handler)
    fake_wrapper = SimpleNamespace(text="开发测试，慎入", content="开发测试，慎入")
    res = await evt.handle("chat_room_title", fake_wrapper)
    assert res is False

    # RoomInfoWindowAuditor in guest room
    RoomInfoWindowAuditor.reset_instance()
    auditor = RoomInfoWindowAuditor.initialize()
    auditor._handler = handler
    auditor._logger = SimpleNamespace(info=lambda _msg: None, warning=lambda _msg: None, error=lambda _msg: None)

    try:
        res = auditor.audit_all_in_open_window()
        assert res.get("skipped") is True
        assert res.get("reason") == "guest_room"

        res = auditor.process_pending_retry()
        assert res.get("skipped") == "guest_room"
    finally:
        RoomInfoWindowAuditor.reset_instance()


@pytest.mark.asyncio
async def test_room_id_event_mismatch_triggers_leave_and_recreate(tmp_path, monkeypatch):
    from unittest.mock import AsyncMock
    from ushareiplay.events.room_id import RoomIdEvent

    room_state = RoomState.instance()
    room_state.expected_party_id = "FM18633292"

    mock_party_manager = type('_MockPM', (), {
        'leave_and_recreate_party': AsyncMock(return_value=True)
    })()

    handler = HandlerStub(config={})
    handler.controller = type('_MockController', (), {
        'party_manager': mock_party_manager
    })()

    evt = RoomIdEvent(handler)
    # 模拟系统自动调入随机房间 FM99999999
    wrapper = SimpleNamespace(text="FM99999999", content="FM99999999")
    res = await evt.handle("room_id", wrapper)

    assert res is True
    mock_party_manager.leave_and_recreate_party.assert_awaited_once()


@pytest.mark.asyncio
async def test_room_id_event_match_updates_state():
    from unittest.mock import AsyncMock
    from ushareiplay.events.room_id import RoomIdEvent

    room_state = RoomState.instance()
    room_state.expected_party_id = "FM18633292"

    mock_party_manager = type('_MockPM', (), {
        'leave_and_recreate_party': AsyncMock(return_value=True)
    })()

    handler = HandlerStub(config={})
    handler.controller = type('_MockController', (), {
        'party_manager': mock_party_manager
    })()

    evt = RoomIdEvent(handler)
    # 模拟在预期的客房 FM18633292
    wrapper = SimpleNamespace(text="FM18633292", content="FM18633292")
    res = await evt.handle("room_id", wrapper)

    assert res is False
    assert room_state.room_id == "FM18633292"
    assert handler.party_id == "FM18633292"
    mock_party_manager.leave_and_recreate_party.assert_not_awaited()


@pytest.mark.asyncio
async def test_detect_initial_room_state_mismatch_triggers_leave(monkeypatch):
    from unittest.mock import AsyncMock
    from ushareiplay.core.app_controller import AppController

    room_state = RoomState.instance()
    room_state.expected_party_id = "FM18633292"

    mock_party_manager = type('_MockPM', (), {
        'leave_and_recreate_party': AsyncMock(return_value=True)
    })()

    element_finder = type('_EF', (), {
        'try_find_element': lambda self, key, log=False: object(),
        'get_element_text': lambda self, elem: "FM99999999"
    })()

    soul_handler = type('_SH', (), {
        'element_finder': element_finder,
        'party_id': None,
    })()

    controller = SimpleNamespace(
        soul_handler=soul_handler,
        party_manager=mock_party_manager,
        logger=type('_L', (), {'warning': lambda *a: None, 'info': lambda *a: None, 'debug': lambda *a: None})(),
    )

    await AppController._detect_initial_room_state(controller)
    mock_party_manager.leave_and_recreate_party.assert_awaited_once()







