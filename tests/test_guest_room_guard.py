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

            def error(self, *_a, **_k):
                return None

        self.logger = _Logger()


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

    management_prefixes = ["theme", "title", "topic", "notice", "seat", "mic", "pack", "end", "room", "admin", "timer", "recommend"]

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

