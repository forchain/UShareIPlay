"""UI 独占锁的日志纪律（铁律：非用户行为触发的监控日志不得刷屏）。

ui_session 过去对每次加解锁无条件打 DEBUG。周期性后台任务
（``MessageContentEvent._process_update_logic`` 的 ``periodic:background-updates``）
每秒持锁一次，于是日志里常驻成片 ``[ui_lock] acquired/released``——它不是任何
用户行为的产物，也不参与任何判断，只把真正的事件挤出视野。

这里锁住的新契约：

* 稳态（无竞争的轮询加解锁）零日志；
* 排障时用 ``UShareIPlay_UI_LOCK_TRACE=1`` 打开完整轨迹；
* 等待超过阈值的真实卡顿仍然会报出来，不需要额外开开关。
"""

import asyncio
import logging
from types import SimpleNamespace

import pytest

from ushareiplay.core.app_controller import AppController
from ushareiplay.events.message_content import MessageContentEvent
from ushareiplay.managers.command_manager import CommandManager
from ushareiplay.state.playback_broadcaster import PlaybackBroadcaster


TRACE_ENV = "UShareIPlay_UI_LOCK_TRACE"


class _RecordingHandler(logging.Handler):
    """收集日志记录，用来断言"到底有没有往日志里写"。"""

    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record):
        self.records.append(record)

    def ui_lock_messages(self) -> list[str]:
        return [r.getMessage() for r in self.records if r.getMessage().startswith("[ui_lock]")]


def _controller_with_recording_logger(monkeypatch, *, trace: bool = False):
    """借用真实的 ui_session（锁语义是真的），只把 logger 换成可断言的记录器。"""
    monkeypatch.delenv(TRACE_ENV, raising=False)
    if trace:
        monkeypatch.setenv(TRACE_ENV, "1")

    controller = AppController.__new__(AppController)
    controller.ui_lock = asyncio.Lock()
    controller._ui_lock_owner = None
    controller._ui_lock_depth = 0

    logger = logging.getLogger(f"test.ui_lock_policy.{id(controller)}")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    recorder = _RecordingHandler()
    logger.addHandler(recorder)
    controller.logger = logger
    return controller, recorder


class _SilentCommands:
    """替身 CommandManager：只提供 update_commands，不产生任何自身日志。"""

    @staticmethod
    def update_commands():
        return None


class _SilentPlayback:
    @staticmethod
    def update_playback_info_cache():
        return None


@pytest.fixture
def patched_managers(monkeypatch):
    monkeypatch.setattr(
        CommandManager, "instance", classmethod(lambda cls: _SilentCommands), raising=False
    )
    monkeypatch.setattr(
        PlaybackBroadcaster,
        "instance",
        classmethod(lambda cls: _SilentPlayback),
        raising=False,
    )


async def test_periodic_background_updates_emit_no_ui_lock_logs(monkeypatch, patched_managers):
    """回归：周期性后台更新跑满多轮，日志里不得出现任何 [ui_lock] 记录。

    这就是线上刷屏的那条路径，轮次越多越能证明它不是偶发。
    """
    controller, recorder = _controller_with_recording_logger(monkeypatch)
    handler = SimpleNamespace(logger=controller.logger, controller=controller)
    event = MessageContentEvent(handler)

    for _ in range(5):
        await event._process_update_logic()

    assert recorder.ui_lock_messages() == [], (
        f"周期性后台任务不该产出 ui_lock 日志，实际: {recorder.ui_lock_messages()}"
    )


async def test_quiet_uncontended_session_stays_silent(monkeypatch):
    """稳态加解锁（无竞争、无痕开启）零日志。"""
    controller, recorder = _controller_with_recording_logger(monkeypatch)

    async with controller.ui_session("seat_inspect"):
        pass

    assert recorder.ui_lock_messages() == []


async def test_short_contention_stays_silent(monkeypatch):
    """正常重叠（命令持锁时轮询短暂排队）属常态，不该因此刷屏。"""
    controller, recorder = _controller_with_recording_logger(monkeypatch)

    await controller.ui_lock.acquire()
    try:
        waiter = asyncio.create_task(
            _enter_and_exit(controller, "periodic:background-updates")
        )
        await asyncio.sleep(0.01)
        controller.ui_lock.release()
        await waiter
    finally:
        if controller.ui_lock.locked():
            controller.ui_lock.release()

    assert recorder.ui_lock_messages() == [], (
        f"亚秒级排队属常态，不该刷屏，实际: {recorder.ui_lock_messages()}"
    )


async def test_trace_env_var_restores_full_tracing(monkeypatch):
    """排障开关：显式开启后恢复完整加解锁轨迹。"""
    controller, recorder = _controller_with_recording_logger(monkeypatch, trace=True)

    async with controller.ui_session("seat_inspect"):
        pass

    messages = recorder.ui_lock_messages()
    assert any("acquired" in m and "seat_inspect" in m for m in messages), messages
    assert any("released" in m and "seat_inspect" in m for m in messages), messages


async def test_stuck_ui_session_wait_is_reported(monkeypatch):
    """等锁超过阈值是真实卡顿，不开开关也要报出来——否则问题彻底静默。"""
    controller, recorder = _controller_with_recording_logger(monkeypatch)
    controller._ui_lock_stuck_seconds = 0.05

    await controller.ui_lock.acquire()
    try:
        waiter = asyncio.create_task(
            _enter_and_exit(controller, "periodic:background-updates")
        )
        await asyncio.sleep(0.2)
        controller.ui_lock.release()
        await waiter
    finally:
        if controller.ui_lock.locked():
            controller.ui_lock.release()

    messages = recorder.ui_lock_messages()
    assert any("wait" in m.lower() for m in messages), (
        f"持锁 0.2s 后才轮到等待方，属于卡顿，应当被报告；实际: {messages}"
    )


async def _enter_and_exit(controller, reason):
    async with controller.ui_session(reason):
        pass