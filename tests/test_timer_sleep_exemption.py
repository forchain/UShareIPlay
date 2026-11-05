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

from types import SimpleNamespace

import pytest


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


@pytest.mark.asyncio
async def test_timer_fired_message_is_sleep_exempt():
    """定时器触发的消息必须带 sleep_exempt，睡眠保护才不会拦下它。"""
    from ushareiplay.core.db_manager import DatabaseManager
    from ushareiplay.core.message_queue import MessageQueue
    from ushareiplay.managers.timer_manager import TimerManager

    manager = DatabaseManager(db_url="sqlite://:memory:")
    await manager.init()

    try:
        tm = TimerManager.instance()
        tm._logger = _DummyLogger()

        await tm.create_timer(
            key="night",
            message=":playlist 助眠",
            target_time="10",
            repeat=False,
        )
        await tm.fire_timer("night")

        messages = await MessageQueue.instance().get_all_messages()
        assert len(messages) == 1
        fired = next(iter(messages.values()))
        assert fired.nickname == "Timer"
        assert fired.sleep_exempt is True
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_keyword_run_forwards_sleep_exemption():
    """`:keyword run` 必须把入站消息的 sleep_exempt 转发给关键字执行。"""
    from ushareiplay.commands.keyword import KeywordCommand
    from ushareiplay.managers.keyword_manager import KeywordManager

    KeywordManager.initialize()
    recorded = {}

    class _FakeKeywordManager:
        async def find_keyword(self, keyword, username):
            return SimpleNamespace(keyword=keyword, command=":playlist 助眠", mode="sequence")

        async def execute_keyword(self, keyword_record, username, params="", sleep_exempt=False):
            recorded["username"] = username
            recorded["sleep_exempt"] = sleep_exempt

    cmd = KeywordCommand(_DummyController())
    cmd.keyword_manager = _FakeKeywordManager()

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
    from ushareiplay.commands.keyword import KeywordCommand
    from ushareiplay.core.db_manager import DatabaseManager
    from ushareiplay.core.message_queue import MessageQueue
    from ushareiplay.managers.keyword_manager import KeywordManager
    from ushareiplay.managers.timer_manager import TimerManager

    manager = DatabaseManager(db_url="sqlite://:memory:")
    await manager.init()

    try:
        tm = TimerManager.instance()
        tm._logger = _DummyLogger()
        await tm.create_timer(
            key="night",
            message=":keyword run 助眠",
            target_time="10",
            repeat=False,
        )
        await tm.fire_timer("night")

        timer_message = next(iter((await MessageQueue.instance().get_all_messages()).values()))

        km = KeywordManager.initialize()
        km._logger = _DummyLogger()

        async def _fake_find_keyword(keyword, username):
            return SimpleNamespace(keyword=keyword, command=":playlist 助眠", mode="sequence")

        monkeypatch.setattr(km, "find_keyword", _fake_find_keyword)

        cmd = KeywordCommand(_DummyController())
        cmd.keyword_manager = km

        await cmd.do_process(timer_message, ["run", "助眠"])

        inner = next(iter((await MessageQueue.instance().get_all_messages()).values()))
        assert inner.content == ":playlist 助眠"
        assert inner.nickname == "Timer"
        assert inner.sleep_exempt is True
    finally:
        await manager.close()
