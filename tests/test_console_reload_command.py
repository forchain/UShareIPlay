"""`!reload` 控制台命令（#469）。

缝：`RuntimeInputPipeline.drain()` —— console / agent 队列条目的公开入口。
命令是否被消费、是否触发重载、回显了什么，都从这里观察。
"""

import queue

import pytest

from ushareiplay.core.message_queue import MessageQueue
from ushareiplay.core.roles import RolePolicy
from ushareiplay.core.runtime_services import RuntimeInputPipeline


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


def _policy(admin_users=("Outlier",), room_owner="Joyer"):
    return RolePolicy(
        {"soul": {"room_owner": room_owner, "admin_users": list(admin_users)}}
    )


def _pipeline(items=(), reload_config=None, is_admin=None, owner="Joyer"):
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
        reload_config=reload_config,
        is_admin=is_admin,
    )
    return pipeline, screen, logger


def _echoes(logger):
    return [text for level, text in logger.messages if level == "critical"]


@pytest.mark.asyncio
async def test_reload_command_triggers_the_reload_and_echoes_the_result():
    await MessageQueue.instance().clear_queue()
    calls = []

    def reload_config():
        calls.append(True)
        return "配置热重载成功：config.yaml"

    _pipeline_out, screen, logger = _pipeline(
        [{"content": "!reload", "source": "console"}], reload_config=reload_config
    )
    await _pipeline_out.drain()

    assert calls == [True]
    assert _echoes(logger) == ["配置热重载成功：config.yaml"]


@pytest.mark.asyncio
async def test_reload_is_consumed_and_never_reaches_the_public_screen():
    await MessageQueue.instance().clear_queue()

    _pipeline_out, screen, _logger = _pipeline(
        [{"content": "!reload", "source": "console"}], reload_config=lambda: "ok"
    )
    await _pipeline_out.drain()

    assert screen == []
    assert await MessageQueue.instance().get_all_messages() == {}


@pytest.mark.asyncio
async def test_reload_is_refused_for_a_non_admin():
    calls = []
    policy = _policy(admin_users=["Outlier"])

    _pipeline_out, screen, logger = _pipeline(
        [{"content": "!reload", "source": "agent_spool", "nickname": "Alice"}],
        reload_config=lambda: calls.append(True),
        is_admin=policy.is_admin,
    )
    await _pipeline_out.drain()

    assert calls == []
    assert any("拒绝" in text for text in _echoes(logger))
    assert screen == []


@pytest.mark.asyncio
async def test_reload_is_allowed_for_a_configured_admin():
    calls = []
    policy = _policy(admin_users=["Outlier"])

    _pipeline_out, _screen, logger = _pipeline(
        [{"content": "!reload", "source": "agent_spool", "nickname": "Outlier"}],
        reload_config=lambda: calls.append(True) or "ok",
        is_admin=policy.is_admin,
    )
    await _pipeline_out.drain()

    assert calls == [True]
    assert _echoes(logger) == ["ok"]


@pytest.mark.asyncio
async def test_reload_is_allowed_for_the_room_owner():
    calls = []
    policy = _policy(admin_users=["Outlier"], room_owner="Joyer")

    _pipeline_out, _screen, _logger = _pipeline(
        [{"content": "!reload", "source": "agent_spool", "nickname": "Joyer"}],
        reload_config=lambda: calls.append(True) or "ok",
        is_admin=policy.is_admin,
    )
    await _pipeline_out.drain()

    assert calls == [True]


@pytest.mark.asyncio
async def test_reload_with_extra_arguments_replies_with_usage_and_does_not_reload():
    calls = []
    policy = _policy()

    _pipeline_out, _screen, logger = _pipeline(
        [{"content": "!reload now", "source": "console"}],
        reload_config=lambda: calls.append(True),
        is_admin=policy.is_admin,
    )
    await _pipeline_out.drain()

    assert calls == []
    assert any("用法" in text for text in _echoes(logger))


@pytest.mark.asyncio
async def test_reload_usage_line_states_that_only_loaded_modules_are_refreshed():
    """重载的边界：只刷新已加载的事件模块绑定，不加载磁盘上的新事件文件。"""
    policy = _policy()

    _pipeline_out, _screen, logger = _pipeline(
        [{"content": "!reload now", "source": "console"}],
        reload_config=lambda: "ok",
        is_admin=policy.is_admin,
    )
    await _pipeline_out.drain()

    assert any("已加载" in text for text in _echoes(logger))


@pytest.mark.asyncio
async def test_reload_reports_unavailable_when_no_reload_capability_is_injected():
    _pipeline_out, _screen, logger = _pipeline(
        [{"content": "!reload", "source": "console"}]
    )
    await _pipeline_out.drain()

    assert any("不可用" in text for text in _echoes(logger))


@pytest.mark.asyncio
async def test_reload_works_while_the_pipeline_is_paused():
    calls = []

    pipeline, _screen, _logger = _pipeline(
        [{"content": "!stop", "source": "console"}],
        reload_config=lambda: calls.append(True) or "ok",
    )
    await pipeline.drain()
    assert pipeline.paused is True

    pipeline.input_queue.put({"content": "!reload", "source": "console"})
    await pipeline.drain()

    assert calls == [True]
