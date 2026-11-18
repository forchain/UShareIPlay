import asyncio
import logging
from collections import deque
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from tests.seat_support import build_seat_service


class _FakeSeatUI:
    def __init__(self, expanded):
        self.expanded = expanded
        self.collapsed = False

    def check_seats_state(self):
        return self.expanded

    async def collapse_seats(self):
        self.collapsed = True
        return True


def _manager_with_fakes(ui=None):
    return build_seat_service(seat_ui=ui or _FakeSeatUI(expanded=False))


@pytest.mark.asyncio
async def test_prepare_for_chat_scan_collapses_only_when_seats_are_expanded():
    expanded_ui = _FakeSeatUI(expanded=True)
    collapsed_ui = _FakeSeatUI(expanded=False)

    assert await _manager_with_fakes(ui=expanded_ui).prepare_for_chat_scan() is True
    assert expanded_ui.collapsed is True

    assert await _manager_with_fakes(ui=collapsed_ui).prepare_for_chat_scan() is True
    assert collapsed_ui.collapsed is False


# #402 删掉 reservation / seating / seat_check 三个转发接缝之后，原来那两个
# 「委托替身返回什么就转发什么」的用例断的是一条已经不存在的路径：它们断言的是
# 替身自己的返回值，对生产代码什么都没说。相同命题（八个公开接口的返回形状来自
# 真实实现、`:seat 4` 的两条路径没混起来）迁到了
# tests/test_seat_subsystem_consolidation.py，并且改成对真实实现断言 —— 覆盖面
# 只增不减：这里原本钉的「转发」已无对象可钉。


def test_seat_manager_owns_a_single_seat_panel():
    handler = object()
    seat_ui = _FakeSeatUI(expanded=False)
    service = build_seat_service(handler, seat_ui=seat_ui)

    assert service._panel._seat_ui is seat_ui


@pytest.mark.asyncio
async def test_message_manager_backfills_inside_the_seat_chat_scan_session(monkeypatch):
    """回溯补漏整段跑在座位子系统的 UI 独占会话里。

    收起面板与滚动聊天历史是同一段屏幕动作：会话外收起会被持锁流程随后的
    展开顶掉，会话里才能保证「扫描期间面板是收起的」。
    """
    from ushareiplay.adapters.inbound.runtime.message_manager import MessageManager

    calls = []

    class _FakeSeatManagement:
        @asynccontextmanager
        async def chat_scan_session(self):
            calls.append("session-enter")
            try:
                yield
            finally:
                calls.append("session-exit")

    class _FakeGesture:
        def scroll_container_until_element(self, *_args, **_kwargs):
            calls.append("scroll")
            return None, None, []

    manager = MessageManager()
    manager._handler = SimpleNamespace(
        logger=SimpleNamespace(error=lambda message: None, critical=lambda message: None),
        key_actions=SimpleNamespace(switch_to_app=lambda: True),
        gesture_handler=_FakeGesture(),
        send_message=lambda message: calls.append("send"),
    )
    manager._chat_logger = logging.getLogger("test_chat_scan_session")
    manager.observe(["souler[Anchor]说：:noop"])

    monkeypatch.setattr(
        MessageManager,
        "_get_seat_manager",
        lambda self: _FakeSeatManagement(),
    )

    assert await manager.process_missed_messages() is None
    assert calls == ["session-enter", "scroll", "send", "session-exit"]
