"""定时器不该被睡眠保护拦下。

线上回归（2026-11-04 01:00，控制台记录）：

    [I]execute_keyword:607 - Keyword '助眠' executed by Timer
    [I]send_screen_message:51 - Silent command suppressed screen message: Failed to play playlist, because 休息中（11pm-6am）

根因有两处，缺一不可：

1. `TimerManager._trigger_timer` 注入队列的消息没有带 `sleep_exempt`，
   定时器在睡眠时段内触发的播放类命令会被睡眠保护拦下；
2. `KeywordCommand` 执行关键字时没有把入站消息的 `sleep_exempt` 转发给
   `KeywordManager.execute_keyword`，于是「定时器 → 关键字 → 内层播放命令」
   这条链在内层丢失豁免标记。

豁免标记是「来源」而不是「昵称」：只有真正由定时器排程产生的消息才带它，
普通用户在房间里自称 Timer 依然会被拦。
"""

from datetime import datetime
from types import SimpleNamespace

import pytest

from tests.fakes.fake_clock import FakeClock
from tests.fakes.in_memory_timer_repository import InMemoryTimerRepository
from ushareiplay.adapters.inbound.runtime.timer_message_sink import (
    QueueTimerMessageSink,
)
from ushareiplay.adapters.inbound.runtime.message_queue import MessageQueue
from ushareiplay.modules.timer.use_cases import TimerUseCases

NOW = datetime(2026, 1, 1, 12, 0, 0)


def _timer_use_cases(message_queue=None):
    return TimerUseCases(
        repository=InMemoryTimerRepository(),
        clock=FakeClock(NOW),
        sink=QueueTimerMessageSink(message_queue or MessageQueue()),
        logger=_DummyLogger(),
    )


class _DummyLogger:
    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass


class _DummySoulHandler:
    def __init__(self):
        self.logger = _DummyLogger()

    def log_error(self, *args, **kwargs):
        pass


class _DummyController:
    def __init__(self):
        self.soul_handler = _DummySoulHandler()
        self.music_handler = object()
        self.keyword_use_cases = None


@pytest.mark.asyncio
async def test_timer_fired_message_is_sleep_exempt():
    """定时器触发的消息必须带 sleep_exempt，睡眠保护才不会拦下它。"""
    queue = MessageQueue()
    use_cases = _timer_use_cases(queue)

    await use_cases.create_timer(
        key="night",
        message=":playlist 助眠",
        target_time="10",
        repeat=False,
    )
    await use_cases.fire_timer("night")

    messages = await queue.get_all_messages()
    assert len(messages) == 1
    fired = next(iter(messages.values()))
    assert fired.nickname == "Timer"
    assert fired.sleep_exempt is True


@pytest.mark.asyncio
async def test_keyword_run_forwards_sleep_exemption():
    """`:keyword run` 必须把入站消息的 sleep_exempt 转发给关键字执行。"""
    from ushareiplay.adapters.inbound.chat.keyword import KeywordCommand

    recorded = {}

    class _FakeKeywordManager:
        async def find_keyword(self, keyword, username):
            return SimpleNamespace(keyword=keyword, command=":playlist 助眠", mode="sequence")

        async def execute_keyword(self, keyword_record, username, params="", sleep_exempt=False):
            recorded["username"] = username
            recorded["sleep_exempt"] = sleep_exempt

    cmd = KeywordCommand(_DummyController())
    cmd.keyword_use_cases = _FakeKeywordManager()

    result = await cmd.do_process(
        SimpleNamespace(content=":keyword run 助眠", nickname="Timer", sleep_exempt=True),
        ["run", "助眠"],
    )

    assert result.get("message") == '已执行关键字 "助眠"'
    assert recorded["username"] == "Timer"
    assert recorded["sleep_exempt"] is True


@pytest.mark.asyncio
async def test_timer_sourced_keyword_command_keeps_the_sleep_exemption(monkeypatch):
    """整条链：定时器 → 关键字 → 内层播放命令，豁免标记必须一路传下去。"""
    from ushareiplay.adapters.inbound.chat.keyword import KeywordCommand
    from ushareiplay.adapters.inbound.runtime.keyword_command_sink import (
        QueueKeywordCommandSink,
    )
    from ushareiplay.modules.command.use_cases import KeywordUseCases
    from tests.fakes.in_memory_keyword_repository import InMemoryKeywordRepository
    from tests.fakes.in_memory_user_repository import InMemoryUserRepository

    queue = MessageQueue()
    use_cases = _timer_use_cases(queue)
    await use_cases.create_timer(
        key="night",
        message=":keyword run 助眠",
        target_time="10",
        repeat=False,
    )
    await use_cases.fire_timer("night")

    timer_message = next(iter((await queue.get_all_messages()).values()))

    users = InMemoryUserRepository()
    repository = InMemoryKeywordRepository(users)
    timer_user = await users.get_or_create("Timer")
    await repository.create(
        keyword="助眠", command=":playlist 助眠", creator_id=timer_user.id, is_public=True
    )
    km = KeywordUseCases(
        repository=repository,
        users=users,
        presence=SimpleNamespace(is_user_online=lambda _name: True),
        queue=QueueKeywordCommandSink(queue),
        chat_logs=SimpleNamespace(record=lambda *_a, **_k: None),
        config_source=SimpleNamespace(load=lambda: None),
        fallback=SimpleNamespace(resolve=lambda **_kwargs: None),
        logger=_DummyLogger(),
    )

    cmd = KeywordCommand(_DummyController())
    cmd.keyword_use_cases = km

    await cmd.do_process(timer_message, ["run", "助眠"])

    inner = next(iter((await queue.get_all_messages()).values()))
    assert inner.content == ":playlist 助眠"
    assert inner.nickname == "Timer"
    assert inner.sleep_exempt is True
