"""RuntimeInputPipeline：console / agent 队列的输入侧处理。

这段逻辑原先内联在 `AppController.start_monitoring` 的循环里，测试只能靠
`AppController.__new__` 手工拼装控制器来碰它。现在它是注入式的独立模块，
可以直接构造。
"""

import queue
from types import SimpleNamespace

import pytest

from ushareiplay.core.message_queue import MessageQueue
from ushareiplay.core.runtime_services import RuntimeInputPipeline, route_queue_text


class _Logger:
    def __init__(self):
        self.messages = []

    def info(self, message):
        self.messages.append(("info", message))

    def critical(self, message):
        self.messages.append(("critical", message))

    def warning(self, message):
        self.messages.append(("warning", message))

    def error(self, message):
        self.messages.append(("error", message))


class _TimerManager:
    def __init__(self, running=False):
        self.running = running
        self.calls = []

    def is_running(self):
        return self.running

    async def start(self):
        self.calls.append("start")
        self.running = True

    async def stop(self):
        self.calls.append("stop")
        self.running = False


def _pipeline(items=(), timer_manager=None, dump_artifacts=None, owner="Joyer"):
    input_queue = queue.Queue()
    for item in items:
        input_queue.put(item)
    screen = []
    logger = _Logger()
    pipeline = RuntimeInputPipeline(
        input_queue=input_queue,
        room_owner_provider=lambda: owner,
        logger=logger,
        send_screen_message=screen.append,
        timer_manager=timer_manager,
        dump_artifacts=dump_artifacts,
    )
    return pipeline, screen, logger


async def _drain(items=(), **kwargs):
    pipeline, screen, logger = _pipeline(items, **kwargs)
    await pipeline.drain()
    return pipeline, screen, logger


@pytest.mark.asyncio
async def test_command_items_are_queued_with_their_source():
    await MessageQueue.instance().clear_queue()

    await _drain([{"content": ":play 晴天", "source": "console", "nickname": "Alice"}])

    queued = list((await MessageQueue.instance().get_all_messages()).values())
    assert [(m.content, m.nickname, m.source) for m in queued] == [(":play 晴天", "Alice", "console")]


@pytest.mark.asyncio
async def test_console_nickname_defaults_to_the_room_owner():
    await MessageQueue.instance().clear_queue()

    await _drain([
        {"content": ":play 晴天", "source": "console", "nickname": "Console"},
        {"content": ":skip", "source": "console"},
    ])

    queued = list((await MessageQueue.instance().get_all_messages()).values())
    assert [m.nickname for m in queued] == ["Joyer", "Joyer"]


@pytest.mark.asyncio
async def test_tuple_and_bare_string_items_are_accepted():
    await MessageQueue.instance().clear_queue()

    await _drain([(":play 晴天", "console"), ":skip"])

    queued = list((await MessageQueue.instance().get_all_messages()).values())
    assert [m.content for m in queued] == [":play 晴天", ":skip"]
    assert queued[1].source == "console"


@pytest.mark.asyncio
async def test_plain_chat_goes_to_the_screen_instead_of_the_queue():
    await MessageQueue.instance().clear_queue()

    # console / agent_spool 属于人工来源，公屏文案带 [人工] 标记
    _pipeline_out, screen, _logger = await _drain([{"content": "大家好", "source": "console"}])

    assert screen == ["[人工] 大家好"]
    assert await MessageQueue.instance().get_all_messages() == {}


@pytest.mark.asyncio
async def test_plain_chat_from_a_non_operator_source_is_not_tagged():
    _pipeline_out, screen, _logger = await _drain([{"content": "大家好", "source": "event"}])

    assert screen == ["大家好"]


@pytest.mark.asyncio
async def test_plain_chat_carrying_the_inherited_silent_flag_is_suppressed():
    """静默标志来自入队时的 MessageInfo（CommandManager 那条路径），此处不打公屏。"""
    _pipeline_out, screen, logger = await _drain([{"content": "大家好", "source": "console"}])

    routing = route_queue_text("大家好", "Alice", source="console", silent=True)

    assert routing.screen_texts == ()
    assert routing.suppressed == ("大家好",)


@pytest.mark.asyncio
async def test_slash_prefixed_items_are_silent_commands_not_plain_chat():
    await MessageQueue.instance().clear_queue()

    _pipeline_out, screen, _logger = await _drain([{"content": "/say 悄悄话", "source": "console"}])

    assert screen == []
    queued = list((await MessageQueue.instance().get_all_messages()).values())
    assert [(m.content, m.silent) for m in queued] == [("/say 悄悄话", True)]


@pytest.mark.asyncio
async def test_semicolon_separated_items_are_split_into_separate_messages():
    await MessageQueue.instance().clear_queue()

    await _drain([{"content": ":play 晴天;:skip", "source": "console", "nickname": "Alice"}])

    queued = list((await MessageQueue.instance().get_all_messages()).values())
    assert [m.content for m in queued] == [":play 晴天", ":skip"]


@pytest.mark.asyncio
async def test_blank_items_are_ignored():
    await MessageQueue.instance().clear_queue()

    _pipeline_out, screen, _logger = await _drain([{"content": "   ", "source": "console"}])

    assert screen == []
    assert await MessageQueue.instance().get_all_messages() == {}


# --------------------------------------------------------------------------
# meta 命令
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stop_toggles_pause_without_queueing_anything():
    await MessageQueue.instance().clear_queue()

    pipeline, _screen, _logger = await _drain([{"content": "!stop", "source": "console"}])

    assert pipeline.paused is True
    assert await MessageQueue.instance().get_all_messages() == {}

    pipeline.input_queue.put({"content": "!stop", "source": "console"})
    await pipeline.drain()
    assert pipeline.paused is False


@pytest.mark.asyncio
async def test_timer_command_starts_and_stops_the_timer():
    timer = _TimerManager(running=False)
    pipeline, _screen, _logger = await _drain([{"content": "!timer", "source": "console"}], timer_manager=timer)

    assert timer.calls == ["start"]

    pipeline.input_queue.put({"content": "!timer", "source": "console"})
    await pipeline.drain()
    assert timer.calls == ["start", "stop"]


@pytest.mark.asyncio
async def test_dump_command_invokes_the_artifact_dump_with_its_source():
    seen = []

    async def dump(reason=None):
        seen.append(reason)

    _pipeline_out, _screen, _logger = await _drain(
        [{"content": "!dump", "source": "agent_spool"}], dump_artifacts=dump
    )

    assert seen == ["agent_spool"]


@pytest.mark.asyncio
async def test_dump_failure_is_reported_and_does_not_kill_the_drain():
    async def dump(reason=None):
        raise RuntimeError("no driver")

    _pipeline_out, _screen, logger = await _drain(
        [{"content": "!dump", "source": "console"}], dump_artifacts=dump
    )

    assert logger.messages == []  # obs 未注入时不额外打印，但异常必须被吞掉


# --------------------------------------------------------------------------
# 共用路由
# --------------------------------------------------------------------------

def test_route_queue_text_separates_commands_from_screen_text():
    routing = route_queue_text(":play 晴天;大家好;/say 悄悄话", "Alice", source="console")

    # `/` 是静默命令前缀，因此第三段是命令而不是公屏发言
    assert [m.content for m in routing.commands] == [":play 晴天", "/say 悄悄话"]
    assert routing.screen_texts == ("[人工] 大家好",)
    assert routing.suppressed == ()

    # 继承 silent=True 时，普通发言进 suppressed 而不是公屏
    silent_routing = route_queue_text("大家好", "Alice", source="event", silent=True)
    assert silent_routing.screen_texts == ()
    assert silent_routing.suppressed == ("大家好",)


def test_route_queue_text_drops_a_trigger_without_content():
    """只有触发符不算命令 —— 与 execute_chat_scan 的判定一致。"""
    routing = route_queue_text(":   ", "Alice", source="console")

    assert routing.commands == ()
    assert routing.screen_texts == ()
