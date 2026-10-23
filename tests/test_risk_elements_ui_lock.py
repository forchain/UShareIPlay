"""风险元素「收起座位」必须给持锁的流程让路。

真机事故（10-23 11:42:52）：座位流程 `seat_auto_invite:片段` 持有 ui_lock 展开
面板，EventManager 的风险元素处理器在同一秒点了「收起座位」—— 座位带视口从
513px 缩回 290px，RecyclerView 把第三排回收掉，桌位从 6 张掉回 4 张，
`expand_and_find_desks` 报 "found 4 desks, expected 6"，整条座位命令失败。

不变式：**持有 UI 锁的流程拥有座位面板**。锁被持有时，谁都不许去动面板。
其余风险元素（「不管你在干什么先把挡路的清掉」）不受这条约束影响。
"""

import asyncio
from unittest.mock import MagicMock

from ushareiplay.core.runtime_context import EventRuntimeContext
from ushareiplay.events.risk_elements import RiskElementsEvent


class _RecordingNode:
    def __init__(self, clicks, key):
        self.clicks = clicks
        self.key = key

    def click(self):
        self.clicks.append(self.key)


class _RecordingFinder:
    def __init__(self, clicks):
        self.clicks = clicks

    def wait_for_element_clickable(self, key):
        return _RecordingNode(self.clicks, key)


class _FakeHandler:
    def __init__(self):
        self.logger = MagicMock()
        self.controller = None
        self.clicks = []
        self.element_finder = _RecordingFinder(self.clicks)


def _event(lock):
    handler = _FakeHandler()
    return handler, RiskElementsEvent(handler, runtime=EventRuntimeContext(ui_lock=lock))


async def test_collapse_seats_is_skipped_while_the_ui_lock_is_held():
    """别人正在驱动屏幕时，「收起座位」必须让路。"""
    lock = asyncio.Lock()
    await lock.acquire()
    handler, event = _event(lock)

    try:
        assert await event.handle("collapse_seats", None) is False
        assert handler.clicks == []
    finally:
        lock.release()


async def test_collapse_seats_is_clicked_when_the_ui_lock_is_free():
    """没人驱动屏幕时，收起面板照旧要做。"""
    lock = asyncio.Lock()
    handler, event = _event(lock)

    assert await event.handle("collapse_seats", None) is True
    assert handler.clicks == ["collapse_seats"]


async def test_urgent_risk_elements_are_still_clicked_while_the_ui_lock_is_held():
    """「先把挡路的清掉」类风险元素不受 UI 锁影响：清障优先于让路。"""
    lock = asyncio.Lock()
    await lock.acquire()
    handler, event = _event(lock)

    try:
        assert await event.handle("close_button", None) is True
        assert handler.clicks == ["close_button"]
    finally:
        lock.release()
