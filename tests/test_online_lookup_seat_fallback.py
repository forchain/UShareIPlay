"""复现生产事故：在座的用户在在线列表里查不到，:gift / :admin 反复失败。

真机现象（10-08 12:53:07~12:53:42）：

    open_user_profile_from_online_list: Opened online users list
    scroll_container_until_element: 已到达边界，未找到目标元素:online_user
    open_user_profile_from_online_list: 未找到用户 不约儿童🐏🐏
    送礼失败: User not found in online users list

而同一次运行的座次表日志里，这个人明明在座：

    第三排: [9号: 群主(Joyer)] [10号: 管理(不约儿童🐏🐏)] ...

Soul 的在线用户列表**不包含在座的人**，所以只靠在线列表定位的路径
（:gift / :admin / 私聊）对在座用户永远失败。修复后的契约：

1. 先问座位快照（一直在维护的全量在座名单），命中就如实报出号位；
2. 绝不再为一个在座的人去滚在线列表（空转到边界纯属浪费，还会刷屏）；
3. 不在座的用户仍走在线列表，既有行为不变。

另有一起同源事故：懒加载的在线列表在抽屉刚打开时还在首帧布局，此刻下滑
会被判成「已到达边界」，把列表里的人误报成「未找到」——
12:53:32 送礼失败、12:53:39 同样的搜索却一眼命中。
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
    """在线列表里只有这些人（不含在座用户）。"""
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
    # 列表里滚动到底也找不到目标 —— 复现「已到达边界，未找到目标元素」
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
    """把某人登记为在座（与真机座次表同一份快照）。"""
    handler = MagicMock()
    obs = SeatObservationManager.initialize(handler)
    obs.seats[seat_number] = SeatSlot(
        seat_number=seat_number, occupied=True, username=nickname, label="管理"
    )
    return obs


_seat_on_mic = _seat_user  # 兼容旧调用


@pytest.mark.asyncio
async def test_seated_user_is_reported_with_their_seat_not_as_missing():
    """在座用户：报出号位，而不是谎报「在线列表里没有」。"""
    handler, _elem = _handler_with_online_list(["Joyer", "Chainer"])
    manager = UserManager.initialize(handler)
    _seat_user("不约儿童🐏🐏", seat_number=10)

    result = await manager.open_user_profile("不约儿童🐏🐏")

    assert result.get("seat") == 10, "必须回报座位号，用户才能知道该去哪儿找人"
    assert result.get("user") == "不约儿童🐏🐏"
    assert "10 号座位上" in result["error"], "错误信息必须说清真实原因"
    assert "在线列表里没有" not in result["error"]


@pytest.mark.asyncio
async def test_seated_user_never_scrapes_the_online_list():
    """在座的人根本不在在线列表里：为他空滚一遍列表纯属浪费。"""
    handler, _elem = _handler_with_online_list(["Joyer", "Chainer"])
    manager = UserManager.initialize(handler)
    _seat_user("不约儿童🐏🐏", seat_number=10)

    await manager.open_user_profile("不约儿童🐏🐏")

    handler.gesture_handler.scroll_container_until_element.assert_not_called()
    handler.element_finder.wait_for_element.assert_not_called()


@pytest.mark.asyncio
async def test_online_user_lookup_still_uses_online_list_for_non_seated_user():
    """不在座的用户仍走在线列表路径（既有行为不得回归）。"""
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
    """既不在座也不在列表里：照旧报「未找到」，错误信息不被改写。"""
    handler, _elem = _handler_with_online_list(["Joyer"])
    manager = UserManager.initialize(handler)
    _seat_on_mic("不约儿童🐏🐏", seat_number=10)

    result = await manager.open_user_profile("查无此人")

    assert result["error"] == "User not found in online users list"
    assert result["user"] == "查无此人"


@pytest.mark.asyncio
async def test_online_list_is_allowed_to_settle_before_scrolling():
    """抽屉刚打开时列表还在首帧布局：必须先等稳定，否则首次下滑会被误判成边界。"""
    handler, _elem = _handler_with_online_list(["Joyer"])
    handler.driver = MagicMock()
    # 前两次读取不同（仍在布局），第三次与第二次相同（稳定）
    handler.driver.page_source = "<hierarchy>a</hierarchy>"
    manager = UserManager.initialize(handler)
    _seat_on_mic("不约儿童🐏🐏", seat_number=10)

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
    _seat_on_mic("不约儿童🐏🐏", seat_number=10)
    manager.ONLINE_LIST_SETTLE_INTERVAL = 0

    result = await manager.open_user_profile("斯德哥尔摩情人")

    assert "error" not in result

@pytest.mark.asyncio
async def test_multi_avatar_identity_matches_seat_by_identity_not_string(monkeypatch):
    """同一个人开着多个分身时，必须按身份命中在座的那个分身。

    真机 10-08 15:05:25 回归：`儿童不易~🐏🐏` 与 `不约儿童🐏🐏` 同属
    canonical 1999，前者在座的快照里没有名字，后者占着 10 号位。
    `resolve_visible_username` 传入的是前者（sorted()[0]），
    用 `==` 比座位文本必然漏判，于是又滚回在线列表空转。
    """
    from ushareiplay.dal.user_dao import UserDAO

    handler, _elem = _handler_with_online_list(["Joyer"])
    manager = UserManager.initialize(handler)
    # 座位快照里只有「不约儿童🐏🐏」，另一个分身「儿童不易~🐏🐏」不在座
    _seat_user("不约儿童🐏🐏", seat_number=10)

    async def _same_identity(requested, observed):
        identity = {"儿童不易~🐏🐏", "不约儿童🐏🐏"}
        return requested in identity and observed in identity

    monkeypatch.setattr(UserDAO, "is_same_identity", _same_identity)

    # 调用方传的是「儿童不易~🐏🐏」—— 字符串不等于座位上的名字
    result = await manager.open_user_profile("儿童不易~🐏🐏")

    assert result.get("seat") == 10, "必须按身份命中在座的那个分身"
    assert result.get("user") == "不约儿童🐏🐏", "应回报座位上真实可见的那个分身名"
    assert "10 号座位上" in result["error"]
    handler.gesture_handler.scroll_container_until_element.assert_not_called()


@pytest.mark.asyncio
async def test_identity_lookup_failure_falls_back_to_online_list(monkeypatch):
    """身份判定本身出错（DB 不可用）时不得把命令判死，仍走在线列表。"""
    from ushareiplay.dal.user_dao import UserDAO

    handler, user_elem = _handler_with_online_list(["Joyer", "斯德哥尔摩情人"])
    handler.gesture_handler.scroll_container_until_element.return_value = (
        "online_user",
        user_elem,
        ["Joyer", "斯德哥尔摩情人"],
    )
    manager = UserManager.initialize(handler)
    _seat_on_mic("不约儿童🐏🐏", seat_number=10)

    async def _boom(*_args, **_kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(UserDAO, "is_same_identity", _boom)

    result = await manager.open_user_profile("斯德哥尔摩情人")

    assert "error" not in result
    handler.gesture_handler.scroll_container_until_element.assert_called_once()
