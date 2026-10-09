"""统一从在线用户列表中查找用户（无论是否在座）。

由于座位上不见得有所有人，而且座位观测缓存存在滞后，
因此资料页定位（:gift / :admin / 私聊等）永远统一走在线用户列表，
不通过座位去选择用户，避免误报「不走在线列表」或绕过在线抽屉。
"""

from unittest.mock import MagicMock

import pytest

from ushareiplay.managers.seat_manager.seat_observation import (
    SeatObservationManager,
    SeatSlot,
)
from ushareiplay.managers.user_manager import UserManager


@pytest.fixture(autouse=True)
def reset_singletons():
    SeatObservationManager.reset_instance()
    UserManager.reset_instance()
    yield
    SeatObservationManager.reset_instance()
    UserManager.reset_instance()


def _handler_with_online_list(online_names):
    """在线列表里只有这些人。"""
    handler = MagicMock()
    handler.logger = MagicMock()
    handler.key_actions = MagicMock()
    handler.gesture_handler = MagicMock()

    user_elem = MagicMock()
    container = MagicMock()

    finder = MagicMock()
    finder.wait_for_element.side_effect = lambda key, **kw: (
        MagicMock() if key == "user_count" else container
    )
    finder.wait_for_element_clickable.return_value = container
    finder.find_child_elements.return_value = []
    finder.try_get_attribute.return_value = None
    handler.element_finder = finder
    handler.gesture_handler.scroll_container_until_element.return_value = (
        None,
        None,
        list(online_names),
    )
    handler.gesture_handler.click_element_at.return_value = True
    return handler, user_elem


def _seat_user(nickname, seat_number=10):
    """把某人登记为在座（模拟座位观测缓存）。"""
    handler = MagicMock()
    obs = SeatObservationManager.initialize(handler)
    obs.seats[seat_number] = SeatSlot(
        seat_number=seat_number, occupied=True, username=nickname, label="管理"
    )
    return obs


@pytest.mark.asyncio
async def test_seated_user_still_looks_up_in_online_list():
    """即使在座，也必须在在线用户列表中查找并成功打开其名片。"""
    handler, user_elem = _handler_with_online_list(["Joyer", "不约儿童🐏🐏"])
    handler.gesture_handler.scroll_container_until_element.return_value = (
        "online_user",
        user_elem,
        ["Joyer", "不约儿童🐏🐏"],
    )
    manager = UserManager.initialize(handler)
    _seat_user("不约儿童🐏🐏", seat_number=10)

    result = await manager.open_user_profile("不约儿童🐏🐏")

    assert "error" not in result
    assert result.get("user") == "不约儿童🐏🐏"
    user_elem.click.assert_called_once()
    handler.gesture_handler.scroll_container_until_element.assert_called_once()


@pytest.mark.asyncio
async def test_seated_user_not_in_online_list_reports_not_found():
    """在座但在线列表里确实滚动到底未找到：如实回报未找到，不得短路报座位号。"""
    handler, _elem = _handler_with_online_list(["Joyer", "Chainer"])
    manager = UserManager.initialize(handler)
    _seat_user("不约儿童🐏🐏", seat_number=10)

    result = await manager.open_user_profile("不约儿童🐏🐏")

    assert result["error"] == "User not found in online users list"
    assert result["user"] == "不约儿童🐏🐏"
    assert "seat" not in result
    handler.gesture_handler.scroll_container_until_element.assert_called_once()


@pytest.mark.asyncio
async def test_online_user_lookup_still_uses_online_list_for_non_seated_user():
    """不在座的用户仍走在线列表路径。"""
    handler, user_elem = _handler_with_online_list(["Joyer", "斯德哥尔摩情人"])
    handler.gesture_handler.scroll_container_until_element.return_value = (
        "online_user",
        user_elem,
        ["Joyer", "斯德哥尔摩情人"],
    )
    manager = UserManager.initialize(handler)
    _seat_user("不约儿童🐏🐏", seat_number=10)

    result = await manager.open_user_profile("斯德哥尔摩情人")

    assert "error" not in result
    user_elem.click.assert_called_once()
    handler.gesture_handler.scroll_container_until_element.assert_called_once()


@pytest.mark.asyncio
async def test_unknown_user_still_reports_not_found():
    """既不在座也不在列表里：照旧报「未找到」。"""
    handler, _elem = _handler_with_online_list(["Joyer"])
    manager = UserManager.initialize(handler)
    _seat_user("不约儿童🐏🐏", seat_number=10)

    result = await manager.open_user_profile("查无此人")

    assert result["error"] == "User not found in online users list"
    assert result["user"] == "查无此人"


@pytest.mark.asyncio
async def test_online_list_is_allowed_to_settle_before_scrolling():
    """抽屉刚打开时列表还在首帧布局：必须先等稳定，否则首次下滑会被误判成边界。"""
    handler, _elem = _handler_with_online_list(["Joyer"])
    handler.driver = MagicMock()
    handler.driver.page_source = "<hierarchy>a</hierarchy>"
    manager = UserManager.initialize(handler)
    _seat_user("不约儿童🐏🐏", seat_number=10)

    original_settle = manager._wait_for_online_list_settle
    seen_before_scroll = {}

    def _record_settle():
        original_settle()
        seen_before_scroll["reads"] = handler.driver.page_source

    manager._wait_for_online_list_settle = _record_settle
    manager.ONLINE_LIST_SETTLE_INTERVAL = 0

    def _scroll(*args, **kwargs):
        seen_before_scroll["scrolled"] = True
        return None, None, ["Joyer"]

    handler.gesture_handler.scroll_container_until_element.side_effect = _scroll

    manager.open_user_profile_from_online_list("斯德哥尔摩情人")

    assert seen_before_scroll.get("scrolled"), "仍然会滚列表"
    assert "reads" in seen_before_scroll, "滚动前必须先等列表稳定"


@pytest.mark.asyncio
async def test_settle_wait_stops_even_when_driver_is_missing():
    """拿不到 driver/page_source 时不能卡住命令，按原样继续搜索。"""
    handler, user_elem = _handler_with_online_list(["Joyer", "斯德哥尔摩情人"])
    handler.gesture_handler.scroll_container_until_element.return_value = (
        "online_user",
        user_elem,
        ["Joyer"],
    )
    handler.driver = None
    manager = UserManager.initialize(handler)
    _seat_user("不约儿童🐏🐏", seat_number=10)
    manager.ONLINE_LIST_SETTLE_INTERVAL = 0

    result = await manager.open_user_profile("斯德哥尔摩情人")

    assert "error" not in result
