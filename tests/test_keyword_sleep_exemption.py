import asyncio
from types import SimpleNamespace

import pytest


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _clear_message_queue():
    from ushareiplay.core.message_queue import MessageQueue

    queue = MessageQueue.instance()
    _run(queue.clear_queue())
    yield
    _run(queue.clear_queue())


def test_keyword_command_execution_does_not_sleep_exempt_by_default():
    from ushareiplay.core.message_queue import MessageQueue
    from ushareiplay.managers.keyword_manager import KeywordManager

    keyword_manager = KeywordManager.initialize()
    keyword_manager._logger = SimpleNamespace(
        info=lambda *_args, **_kwargs: None,
        error=lambda *_args, **_kwargs: None,
    )
    keyword_record = SimpleNamespace(
        keyword="520",
        command=":play love song",
        mode="sequence",
    )

    _run(keyword_manager.execute_keyword(keyword_record, "Alice"))

    messages = _run(MessageQueue.instance().get_all_messages())

    assert len(messages) == 1
    queued = next(iter(messages.values()))
    assert queued.content == ":play love song"
    assert queued.nickname == "Alice"
    assert queued.sleep_exempt is False


@pytest.mark.asyncio
async def test_at_keyword_message_executes_keyword_with_sleep_exemption(monkeypatch):
    from ushareiplay.events.message_content import MessageContentEvent
    from ushareiplay.managers import keyword_manager as keyword_manager_module
    from ushareiplay.managers import message_manager as message_manager_module

    calls = []

    class _FakeKeywordManager:
        async def find_keyword(self, keyword, username):
            return SimpleNamespace(keyword=keyword, command=":play love song", mode="sequence")

        async def execute_keyword(self, keyword_record, username, params="", sleep_exempt=False):
            calls.append(
                {
                    "keyword": keyword_record.keyword,
                    "username": username,
                    "params": params,
                    "sleep_exempt": sleep_exempt,
                }
            )

        async def dispatch_mention(self, result, sleep_exempt=True):
            keyword_record = await self.find_keyword(result.text, result.nickname)
            if keyword_record:
                await self.execute_keyword(
                    keyword_record, result.nickname, params=result.params, sleep_exempt=sleep_exempt
                )

    class _FakeMessageManager:
        def __init__(self):
            self.latest_chats = []
            self.recent_chats = []

    class _Logger:
        def critical(self, *_args, **_kwargs):
            return None

        def info(self, *_args, **_kwargs):
            return None

        def error(self, *_args, **_kwargs):
            return None

    class _Handler:
        config = {}
        logger = _Logger()
        controller = None

    monkeypatch.setattr(
        message_manager_module.MessageManager,
        "instance",
        staticmethod(lambda: _FakeMessageManager()),
    )
    monkeypatch.setattr(
        message_manager_module,
        "get_chat_logger",
        lambda _config: _Logger(),
    )
    monkeypatch.setattr(
        keyword_manager_module.KeywordManager,
        "instance",
        staticmethod(lambda: _FakeKeywordManager()),
    )

    event = MessageContentEvent(_Handler())

    async def _noop_update_logic():
        return None

    event._process_update_logic = _noop_update_logic

    await event.handle(
        "message_content",
        [SimpleNamespace(content="souler[Alice]说：@我 520 晚安")],
    )

    assert calls == [
        {
            "keyword": "520",
            "username": "Alice",
            "params": "晚安",
            "sleep_exempt": True,
        }
    ]
