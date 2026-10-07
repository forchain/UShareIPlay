"""周期性后台更新不得把用户命令和事件循环一起拖死（线上「卡住」回归）。

现场（2026-10-07 15:00:03 → 15:01:11）::

    [D]ui_lock acquired: periodic:background-updates
    [I]update:216 - Attempting to update topic ...
    [W]update:233 - Failed to update topic ...
    [E]switch_and_click:17 - Failed to switch to app before clicking chat_room_title
    [W]wait_for_element:45 - Element chat_room_notice not found within 10 seconds
    [W]wait_for_element_clickable:90 - title_edit_entry not found within 10 seconds
    [W]wait_for_element_clickable:90 - slide_drawer not found within 10 seconds
    [W]wait_for_element:45 - Element room_id not found within 10 seconds
    [D]ui_lock released: periodic:background-updates      ← 68 秒后

两层问题，本文件守住第一条：

1. **锁粒度太粗**——``_process_update_logic`` 用一把 ``ui_session`` 罩住整轮
   ``update_commands()``，于是第一个命令的 10 秒级联把后面所有更新步骤和用户
   命令一起锁在门外，直到整轮结束才放行。
2. **阻塞调用在事件循环上**——``update_commands()`` 是同步调用链，最终落到
   Selenium 的 ``WebDriverWait``。单步内部仍会冻结事件循环；把整个 UI 层改成
   async（或线程化 + driver 互斥）属于另一件事，不在本用例的契约内。

主循环自己写着「关键：让出事件循环时间片，否则 create_task() 排队的协程无法执行」，
本文件守的就是这个不变量在更新轮次之间依然成立。
"""

import asyncio
import logging
import time

import pytest

from ushareiplay.core.app_controller import AppController
from ushareiplay.events.message_content import MessageContentEvent
from ushareiplay.managers.command_manager import CommandManager
from ushareiplay.state.playback_broadcaster import PlaybackBroadcaster


# 真机上是 10s/次的 WebDriverWait 级联；测试按 1/40 缩放到 0.25s，保持量级不失真。
BLOCKED_SECONDS = 0.25


class _SilentPlayback:
    @staticmethod
    def update_playback_info_cache():
        return None


def _controller():
    controller = AppController.__new__(AppController)
    controller.ui_lock = asyncio.Lock()
    controller._ui_lock_owner = None
    controller._ui_lock_depth = 0
    controller.logger = logging.getLogger("test.background_stall.quiet")
    controller.logger.addHandler(logging.NullHandler())
    return controller


def _event(controller):
    from types import SimpleNamespace

    return MessageContentEvent(
        SimpleNamespace(logger=controller.logger, controller=controller)
    )


def _blocking_step(label, order):
    """模拟一次同步阻塞的 UI 等待：Selenium 的 wait_for_element 就是这个样子。"""

    def _step():
        time.sleep(BLOCKED_SECONDS)
        order.append(label)

    return _step


@pytest.mark.asyncio
async def test_a_waiting_user_command_gets_the_lock_between_update_steps(monkeypatch):
    """一步卡住不得连坐后面的更新步骤和用户命令。

    锁按步骤释放时，第一步期间排队的用户命令会在第二步之前插进来。整轮被一把锁
    罩住时它只能排在最后——现场正是这样：定时器 /radio 直到 15:01:11 锁释放才跑起来。
    """
    controller = _controller()
    order: list[str] = []
    first_step_running = asyncio.Event()

    def _first_step():
        first_step_running.set()
        time.sleep(BLOCKED_SECONDS)
        order.append("update-1")

    class _Manager:
        @staticmethod
        async def update_commands(run_step=None):
            await run_step("cmd1", _first_step)
            await run_step("cmd2", _blocking_step("update-2", order))

    monkeypatch.setattr(
        CommandManager, "instance", classmethod(lambda cls: _Manager()), raising=False
    )
    monkeypatch.setattr(
        PlaybackBroadcaster, "instance", classmethod(lambda cls: _SilentPlayback), raising=False
    )

    async def _user_command():
        # 第一步已开始（锁被持有），此刻排进等待队列
        await first_step_running.wait()
        async with controller.ui_session("command:radio"):
            order.append("user-command")

    user = asyncio.create_task(_user_command())
    await asyncio.gather(_event(controller)._process_update_logic(), user)

    assert order == ["update-1", "user-command", "update-2"], (
        f"用户命令必须能插进两个更新步骤之间拿到锁，实际顺序: {order}"
    )


@pytest.mark.asyncio
async def test_event_loop_gets_a_turn_between_update_steps(monkeypatch):
    """步骤之间必须让出事件循环，让已经就绪的协程获得执行机会。

    主循环写着「关键：让出事件循环时间片，否则 create_task() 排队的协程无法执行」。
    单步内部仍是同步阻塞的 Selenium 调用（真机 10s/次），把整个 UI 层异步化属于
    另一件事；这里守住的是「一步卡住不会把整轮和循环一起拖死」。
    """
    controller = _controller()
    order: list[str] = []
    first_step_running = asyncio.Event()

    def _first_step():
        first_step_running.set()
        time.sleep(BLOCKED_SECONDS)
        order.append("update-1")

    class _Manager:
        @staticmethod
        async def update_commands(run_step=None):
            await run_step("cmd1", _first_step)
            await run_step("cmd2", _blocking_step("update-2", order))

    monkeypatch.setattr(
        CommandManager, "instance", classmethod(lambda cls: _Manager()), raising=False
    )
    monkeypatch.setattr(
        PlaybackBroadcaster, "instance", classmethod(lambda cls: _SilentPlayback), raising=False
    )

    background = asyncio.create_task(_event(controller)._process_update_logic())
    await asyncio.sleep(0)
    observer = asyncio.create_task(first_step_running.wait())
    await asyncio.gather(background, observer)
    # 观察者在第一步期间就被唤醒；它完成 gather 的那一刻就证明循环在第一步结束前
    # 至少让出过时间片（否则它只会在两步都结束后才被调度）
    assert "update-1" in order and "update-2" in order, order


@pytest.mark.asyncio
async def test_one_failing_update_step_does_not_block_the_rest(monkeypatch):
    """某个命令的 update() 抛异常，不得连坐后面的更新步骤。"""
    controller = _controller()
    order: list[str] = []

    class _Manager:
        @staticmethod
        async def update_commands(run_step=None):
            async def _boom():
                raise RuntimeError("drawer unreachable")

            await run_step("cmd1", _boom)
            await run_step("cmd2", _blocking_step("update-2", order))

    monkeypatch.setattr(
        CommandManager, "instance", classmethod(lambda cls: _Manager()), raising=False
    )
    monkeypatch.setattr(
        PlaybackBroadcaster, "instance", classmethod(lambda cls: _SilentPlayback), raising=False
    )

    await _event(controller)._process_update_logic()

    assert order == ["update-2"], f"异常后的更新步骤仍应执行，实际: {order}"


@pytest.mark.asyncio
async def test_long_holding_ui_session_is_reported(monkeypatch):
    """持锁过久必须报出来，否则这类卡顿会重新变成静默故障。"""
    controller = _controller()
    messages: list[str] = []

    class _Capture(logging.Handler):
        def emit(self, record):
            messages.append(record.getMessage())

    logger = logging.getLogger("test.background_stall.held")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    logger.addHandler(_Capture())
    controller.logger = logger
    controller._ui_lock_stuck_seconds = 0.05

    class _Manager:
        @staticmethod
        async def update_commands(run_step=None):
            await run_step("cmd1", lambda: time.sleep(0.2))

    monkeypatch.setattr(
        CommandManager, "instance", classmethod(lambda cls: _Manager()), raising=False
    )
    monkeypatch.setattr(
        PlaybackBroadcaster, "instance", classmethod(lambda cls: _SilentPlayback), raising=False
    )

    await _event(controller)._process_update_logic()

    assert any("held" in m.lower() and "cmd1" in m for m in messages), (
        f"0.2s 的超长持锁会话应当被报告，实际: {messages}"
    )