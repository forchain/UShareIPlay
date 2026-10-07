"""SeatPanelDriver 的测试：面板状态、展开/收起、整排滚动、麦位头像弹窗的安全生命周期。

替身定义在 tests/seat_fixtures.py —— 刻意与生产协作者同形（见 PR #339 review 的
C1/C2）：desk 是真 ElementWrapper，raw WebElement 路径走 find_element 契约，
controller 用真实的 ui_session 异步上下文管理器，元素 key 取自真实 config.yaml。

本文件只在自己的范围内补一个「可变的座位面板按钮」（共用的 FakeElementFinder 只
认弹窗证据节点），不去改共用替身，免得和别的票抢同一个文件。
"""

from unittest.mock import MagicMock

import pytest

from tests.seat_fixtures import (
    ClickableNode,
    FakeController,
    FakeElementFinder,
    RawSeatDesk,
    build_desk_wrapper,
    make_handler,
    soul_elements,
)

from ushareiplay.managers.seat_manager.seat_panel_driver import (
    AvatarTapPolicy,
    SeatPanelDriver,
)

EXPAND_SEATS_KEY = "expand_seats"
COLLAPSE_LABEL = "收起"
EXPAND_LABEL = "展开"


class PanelButtonFinder(FakeElementFinder):
    """在共用替身上补一个可变的座位面板按钮（真实元素 key）。"""

    def __init__(self, elements, button_text=EXPAND_LABEL, **kwargs):
        super().__init__(elements, **kwargs)
        self.button_text = button_text
        self.button = ClickableNode(button_text) if button_text is not None else None
        self.expand_lookups = 0

    def try_find_element(self, element_key, log=False, clickable=False):
        if element_key == EXPAND_SEATS_KEY:
            self.expand_lookups += 1
            return self.button
        return super().try_find_element(element_key, log=log, clickable=clickable)


def make_panel_handler(button_text=EXPAND_LABEL, desks=None, popup_name=None, controller=None):
    handler = make_handler(desks=desks, popup_name=popup_name, controller=controller)
    handler.element_finder = PanelButtonFinder(
        handler.element_finder.elements,
        button_text=button_text,
        desks=desks,
        popup_name=popup_name,
    )
    return handler


# ---------------------------------------------------------------------------
# 面板状态判定
# ---------------------------------------------------------------------------


def test_is_expanded_reads_collapse_label_as_expanded():
    """按钮写着「收起」＝面板当前是展开的。"""
    driver = SeatPanelDriver(make_panel_handler(button_text=COLLAPSE_LABEL))

    assert driver.is_expanded() is True
    assert driver.expanded is True


def test_is_expanded_reads_expand_label_as_collapsed():
    """按钮写着「展开」＝面板当前是收起的。"""
    driver = SeatPanelDriver(make_panel_handler(button_text=EXPAND_LABEL))

    assert driver.is_expanded() is False
    assert driver.expanded is False


def test_is_expanded_keeps_cached_state_when_button_is_missing():
    """按钮不在页面上（面板被弹窗盖住/页面已切走）时不动缓存，只返回上一次判定的值。

    按钮读不到不代表面板变了；把它当成「收起」会让下一轮白点一次展开。
    """
    driver = SeatPanelDriver(make_panel_handler(button_text=COLLAPSE_LABEL))
    assert driver.is_expanded() is True

    driver = SeatPanelDriver(make_panel_handler(button_text=None))
    driver.expanded = True

    assert driver.is_expanded() is True
    assert driver.expanded is True


def test_is_expanded_keeps_cached_state_when_label_is_unreadable():
    """按钮文本两种关键字都不含时无法判定，不许猜。"""
    driver = SeatPanelDriver(make_panel_handler(button_text="座位"))
    driver.expanded = False

    assert driver.is_expanded() is False
    assert driver.expanded is False


def test_is_expanded_without_handler_reports_collapsed():
    driver = SeatPanelDriver(None)

    assert driver.is_expanded() is False


# ---------------------------------------------------------------------------
# 展开 / 收起
# ---------------------------------------------------------------------------


async def test_expand_clicks_the_button_when_the_panel_is_collapsed():
    handler = make_panel_handler(button_text=EXPAND_LABEL)
    driver = SeatPanelDriver(handler)

    assert await driver.expand() is True
    assert handler.element_finder.button.clicked is True
    assert driver.expanded is True


async def test_expand_is_a_noop_when_the_panel_is_already_open():
    """已经展开时一次点击都不该有：多点一次就是点进了第一个麦位。"""
    handler = make_panel_handler(button_text=COLLAPSE_LABEL)
    driver = SeatPanelDriver(handler)

    assert await driver.expand() is True
    assert handler.element_finder.button.clicked is False


async def test_expand_refuses_to_click_an_unreadable_button():
    """按钮文本认不出来时宁可不点：瞎点一次的落点不可预测。"""
    handler = make_panel_handler(button_text="座位")
    driver = SeatPanelDriver(handler)

    assert await driver.expand() is False
    assert handler.element_finder.button.clicked is False
    assert driver.expanded is False


async def test_expand_fails_when_the_button_is_missing():
    handler = make_panel_handler(button_text=None)
    driver = SeatPanelDriver(handler)

    assert await driver.expand() is False
    assert driver.expanded is False


async def test_collapse_clicks_the_button_when_the_panel_is_open():
    handler = make_panel_handler(button_text=COLLAPSE_LABEL)
    driver = SeatPanelDriver(handler)

    assert await driver.collapse() is True
    assert handler.element_finder.button.clicked is True
    assert driver.expanded is False


async def test_collapse_is_a_noop_when_the_panel_is_already_closed():
    handler = make_panel_handler(button_text=EXPAND_LABEL)
    driver = SeatPanelDriver(handler)

    assert await driver.collapse() is True
    assert handler.element_finder.button.clicked is False


async def test_collapse_refuses_to_click_an_unreadable_button():
    """按钮文本认不出来时宁可不点：瞎点一次的落点不可预测。"""
    handler = make_panel_handler(button_text="座位")
    driver = SeatPanelDriver(handler)
    driver.expanded = True  # 面板确实开着，只是按钮文本认不出来

    assert await driver.collapse() is False
    assert handler.element_finder.button.clicked is False
    assert driver.expanded is True


async def test_collapse_is_a_noop_when_the_button_is_unreadable_but_the_panel_is_closed():
    """按钮认不出来、缓存又已是收起：本来就没得收，如实返回成功且不点。"""
    handler = make_panel_handler(button_text="座位")
    driver = SeatPanelDriver(handler)

    assert await driver.collapse() is True
    assert handler.element_finder.button.clicked is False


async def test_collapse_fails_when_the_panel_is_open_but_the_button_is_missing():
    """面板开着却读不到按钮：必须报失败，不能谎称已经收起。

    谎称成功会让调用方以为房间已经回到收起态，下一轮照着「已收起」去点展开，
    而面板其实一直开着。
    """
    handler = make_panel_handler(button_text=None)
    driver = SeatPanelDriver(handler)
    driver.expanded = True

    assert await driver.collapse() is False
    assert driver.expanded is True


# ---------------------------------------------------------------------------
# 展开后重扫桌位
# ---------------------------------------------------------------------------


async def test_expand_and_find_desks_returns_the_six_desks():
    desks = [object() for _ in range(6)]
    handler = make_panel_handler(button_text=EXPAND_LABEL, desks=desks)
    driver = SeatPanelDriver(handler)

    assert await driver.expand_and_find_desks() == desks
    assert handler.element_finder.button.clicked is True


async def test_expand_and_find_desks_rejects_an_incomplete_expansion():
    """只渲染出 3 张桌位说明面板没真展开：宁可空手返回，也不能拿半张面板读麦位。"""
    handler = make_panel_handler(button_text=EXPAND_LABEL, desks=[object()] * 3)
    driver = SeatPanelDriver(handler)

    assert await driver.expand_and_find_desks() is None


async def test_expand_and_find_desks_reports_when_nothing_expanded():
    handler = make_panel_handler(button_text=None, desks=[object()] * 6)
    driver = SeatPanelDriver(handler)

    assert await driver.expand_and_find_desks() is None


async def test_expand_and_find_desks_without_handler_returns_none():
    driver = SeatPanelDriver(None)

    assert await driver.expand_and_find_desks() is None


async def test_expand_and_find_desks_survives_a_failing_rescan():
    """重扫抛错时如实报失败，不把异常甩给调用方。"""
    handler = make_panel_handler(button_text=EXPAND_LABEL, desks=make_desks())
    handler.element_finder.find_elements = MagicMock(side_effect=RuntimeError("dump 超时"))
    driver = SeatPanelDriver(handler)

    assert await driver.expand_and_find_desks() is None


async def test_expand_and_find_desks_without_an_element_finder_returns_none():
    handler = make_panel_handler(button_text=EXPAND_LABEL, desks=make_desks())
    handler.element_finder = None
    driver = SeatPanelDriver(handler)

    assert await driver.expand_and_find_desks() is None


# ---------------------------------------------------------------------------
# 整排滚动
# ---------------------------------------------------------------------------

# 参考桌位（seat_desks[2]）的几何：中心 (220, 180)，高 160
# 下滑一排 -> (220, 340)，上滑一排 -> (220, 20)
SWIPE_DOWN = (220, 180, 220, 340)
SWIPE_UP = (220, 180, 220, 20)


class BoundsOnlyDesk:
    """只暴露 bounds 的桌位（部分 raw WebElement 就是这个形状）。"""

    def __init__(self, bounds):
        self.bounds = bounds


def make_desks(count=6):
    return [RawSeatDesk({}, location={"x": 40, "y": 100}) for _ in range(count)]


def test_scroll_to_row_skips_the_middle_row_that_is_already_visible():
    """第 2 排（desk 2/3）开屏就在中间，滑动只会把已经读到的麦位晃走。"""
    handler = make_panel_handler()
    driver = SeatPanelDriver(handler)
    desks = make_desks()

    assert driver.scroll_to_row(2, desks) is False
    assert driver.scroll_to_row(3, desks) is False
    handler.gesture_handler.swipe.assert_not_called()


def test_scroll_to_row_swipes_down_to_reach_the_first_row():
    handler = make_panel_handler()
    driver = SeatPanelDriver(handler)
    desks = make_desks()

    assert driver.scroll_to_row(0, desks, duration=1000) is True
    assert handler.gesture_handler.swipe.call_args.args == (*SWIPE_DOWN, 1000)


def test_scroll_to_row_swipes_down_for_the_right_seat_of_the_first_row():
    handler = make_panel_handler()
    driver = SeatPanelDriver(handler)
    desks = make_desks()

    assert driver.scroll_to_row(1, desks) is True
    assert handler.gesture_handler.swipe.call_args.args == (*SWIPE_DOWN, 100)


def test_scroll_to_row_swipes_up_to_reach_the_third_row():
    handler = make_panel_handler()
    driver = SeatPanelDriver(handler)
    desks = make_desks()

    assert driver.scroll_to_row(4, desks) is True
    assert driver.scroll_to_row(5, desks) is True
    assert handler.gesture_handler.swipe.call_args.args == (*SWIPE_UP, 100)


def test_scroll_to_row_skips_when_there_are_too_few_desks():
    """参考桌位（seat_desks[2]）不存在时没有滑动锚点，直接不动。"""
    handler = make_panel_handler()
    driver = SeatPanelDriver(handler)

    assert driver.scroll_to_row(4, None) is False
    assert driver.scroll_to_row(4, make_desks(2)) is False
    handler.gesture_handler.swipe.assert_not_called()


def test_scroll_to_row_falls_back_to_bounds_geometry():
    handler = make_panel_handler()
    driver = SeatPanelDriver(handler)
    desks = [BoundsOnlyDesk({"x": 40, "y": 100, "width": 360, "height": 160})] * 6

    assert driver.scroll_to_row(4, desks) is True
    assert handler.gesture_handler.swipe.call_args.args == (*SWIPE_UP, 100)


def test_scroll_to_row_skips_when_the_anchor_geometry_is_unreadable():
    handler = make_panel_handler()
    driver = SeatPanelDriver(handler)
    desks = [BoundsOnlyDesk(None)] * 6

    assert driver.scroll_to_row(4, desks) is False
    handler.gesture_handler.swipe.assert_not_called()


def test_scroll_to_row_skips_without_a_gesture_handler():
    handler = make_panel_handler()
    handler.gesture_handler = None
    driver = SeatPanelDriver(handler)

    assert driver.scroll_to_row(4, make_desks()) is False


async def test_reveal_seat_expands_and_scrolls_the_target_row_into_view():
    """:seat 9 这类要先把面板展开、滚到第 3 排再读。"""
    desks = make_desks()
    handler = make_panel_handler(button_text=EXPAND_LABEL, desks=desks)
    driver = SeatPanelDriver(handler)

    assert await driver.reveal_seat(9) == desks
    assert handler.element_finder.button.clicked is True
    assert handler.gesture_handler.swipe.call_args.args == (*SWIPE_UP, 100)


async def test_reveal_seat_does_not_swipe_for_a_middle_row_seat():
    desks = make_desks()
    handler = make_panel_handler(button_text=EXPAND_LABEL, desks=desks)
    driver = SeatPanelDriver(handler)

    assert await driver.reveal_seat(5) == desks
    handler.gesture_handler.swipe.assert_not_called()


async def test_reveal_seat_reports_failure_when_the_panel_never_expanded():
    handler = make_panel_handler(button_text=None, desks=make_desks())
    driver = SeatPanelDriver(handler)

    assert await driver.reveal_seat(9) is None
    handler.gesture_handler.swipe.assert_not_called()


async def test_reveal_seat_rejects_a_seat_number_outside_the_panel():
    handler = make_panel_handler(button_text=EXPAND_LABEL, desks=make_desks())
    driver = SeatPanelDriver(handler)

    assert await driver.reveal_seat(13) is None
    assert await driver.reveal_seat(0) is None


# ---------------------------------------------------------------------------
# 麦位头像弹窗：安全生命周期
# ---------------------------------------------------------------------------


def build_raw_desk_with_avatar(elements=None):
    """raw WebElement 形状的桌位，带一个可点的 left_state 子节点（真实元素 key）。"""
    elements = elements or soul_elements()
    avatar = ClickableNode()
    return RawSeatDesk({elements["left_state"]: avatar}, location={"x": 40, "y": 100}), avatar


def build_raw_desk_with_state_and_seat(elements=None):
    """真机上的占座桌位：left_state（ClState）与 left_seat（UserView）同时渲染。"""
    elements = elements or soul_elements()
    avatar = ClickableNode()
    seat = ClickableNode()
    return (
        RawSeatDesk(
            {elements["left_state"]: avatar, elements["left_seat"]: seat},
            location={"x": 40, "y": 100},
        ),
        avatar,
        seat,
    )


def build_raw_desk_without_state(elements=None):
    """只渲染了 UserView（left_seat）、没有 ClState 的桌位。"""
    elements = elements or soul_elements()
    seat = ClickableNode()
    return RawSeatDesk({elements["left_seat"]: seat}, location={"x": 40, "y": 100}), seat


def build_raw_desk_with_state_only(elements=None):
    """只渲染了 ClState（left_state）、没有 UserView 的桌位。"""
    elements = elements or soul_elements()
    avatar = ClickableNode()
    return RawSeatDesk({elements["left_state"]: avatar}, location={"x": 40, "y": 100}), avatar


async def test_avatar_card_taps_the_state_node_by_default():
    """默认点 ClState：#395 立下的行为，面板观测那条链路依赖它。"""
    handler = make_panel_handler(popup_name="Bob")
    driver = SeatPanelDriver(handler)
    desk, avatar, seat = build_raw_desk_with_state_and_seat()

    async with driver.avatar_card(desk, "left", 9) as card:
        assert card.opened is True

    assert avatar.clicked is True
    assert seat.clicked is False


async def test_avatar_card_state_then_seat_policy_falls_back_to_the_seat_node():
    """STATE_THEN_SEAT 是长期行为：ClState 缺席时退到 seat 节点（面板观测链路靠它读昵称）。"""
    handler = make_panel_handler(popup_name="Bob")
    driver = SeatPanelDriver(handler)
    desk, seat = build_raw_desk_without_state()

    async with driver.avatar_card(
        desk, "left", 9, tap_target=AvatarTapPolicy.STATE_THEN_SEAT
    ) as card:
        assert card.opened is True

    assert seat.clicked is True


async def test_avatar_card_seat_node_policy_taps_the_seat_node_when_the_caller_asks():
    """要「请下麦」的那条链路必须点 seat 节点，不能跟着默认路径改点 ClState。

    没有任何证据证明「点 ClState 弹出的名片」里带着 seat_off（tvSeatDownUp）——
    真机 dump 里根本没有这个节点，全仓只有测试替身凭空造了一个。点错了就静默
    退化成「Unable to manage seat N」，:seat 占位不再清人。所以把点击目标显式
    钉回迁移前的 seat 节点：重构不该顺手改掉没被验证过的点击目标。
    """
    handler = make_panel_handler(popup_name="Bob")
    driver = SeatPanelDriver(handler)
    desk, avatar, seat = build_raw_desk_with_state_and_seat()

    async with driver.avatar_card(
        desk, "left", 9, tap_target=AvatarTapPolicy.SEAT_NODE
    ) as card:
        assert card.opened is True

    assert seat.clicked is True
    assert avatar.clicked is False


async def test_avatar_card_seat_node_policy_never_taps_the_state_node():
    """SEAT_NODE 不看 ClState：只有 UserView 才在这条链路的证据里。"""
    handler = make_panel_handler(popup_name="Bob")
    driver = SeatPanelDriver(handler)
    desk, avatar = build_raw_desk_with_state_only()

    async with driver.avatar_card(
        desk, "left", 9, tap_target=AvatarTapPolicy.SEAT_NODE
    ) as card:
        assert card.opened is True

    assert avatar.clicked is False


async def test_avatar_card_state_only_policy_taps_the_state_node_when_present():
    handler = make_panel_handler(popup_name="Bob")
    driver = SeatPanelDriver(handler)
    desk, avatar, seat = build_raw_desk_with_state_and_seat()

    async with driver.avatar_card(
        desk, "left", 9, tap_target=AvatarTapPolicy.STATE_ONLY
    ) as card:
        assert card.opened is True
        assert card.name == "Bob"

    assert avatar.clicked is True
    assert seat.clicked is False


async def test_avatar_card_state_only_policy_taps_nothing_when_the_state_node_is_absent():
    """STATE_ONLY 读不到 ClState 就一次都别点 —— 这是「别点」，不是「改点别的」。

    迁移前这条链路（找搭子）在 ClState 缺席时是 `continue`：整张桌位跳过，一次
    点击都不发。退到 seat 节点会凭空点出一张 UserView 名片，而那次点击没有任何
    证据支持：迁到这条链路上的读数要的是 ClState 名片，读错了就是静默坐错人旁边。
    """
    handler = make_panel_handler(popup_name="Bob")
    driver = SeatPanelDriver(handler)
    desk, seat = build_raw_desk_without_state()

    async with driver.avatar_card(
        desk, "left", 9, tap_target=AvatarTapPolicy.STATE_ONLY
    ) as card:
        assert card.opened is False
        assert card.name is None

    assert seat.clicked is False
    handler.key_actions.press_back.assert_not_called()
    # 一次都没点，就不该去等一张不会出现的卡片
    assert handler.element_finder.wait_calls == 0


async def test_avatar_card_closes_only_the_popup_it_opened():
    """读到昵称节点＝弹窗真开着，必须关掉：它会挡住后面的麦位读数。"""
    handler = make_panel_handler(popup_name="Bob")
    driver = SeatPanelDriver(handler)
    desk = build_desk_wrapper(handler, left="", right="10", left_occupied=True)

    async with driver.avatar_card(desk, "left", 9) as card:
        assert card.opened is True
        assert card.name == "Bob"

    handler.key_actions.press_back.assert_called_once()


async def test_avatar_card_never_presses_back_when_no_popup_opened():
    """点名没打开任何弹窗时绝不能按 back：房间界面上的一次 back 就是退出派对房间。

    真机 09-28 20:46：房主换座后 9 号位的残留渲染被读成「占座但身份未知」，点了个
    空位什么也没弹出，接着的盲按 back 直接把房间界面关掉了，后面全量重扫连座位
    按钮都找不到。读不到昵称节点就是「没有可关的弹窗」。
    """
    handler = make_panel_handler(popup_name=None)
    driver = SeatPanelDriver(handler)
    desk = build_desk_wrapper(handler, left="", right="10", left_occupied=True)

    async with driver.avatar_card(desk, "left", 9) as card:
        assert card.opened is False
        assert card.name is None

    handler.key_actions.press_back.assert_not_called()


async def test_avatar_card_never_presses_back_when_the_card_was_already_dismissed():
    """读到昵称之后、按下之前卡片已经被别的流程关掉了：再按 back 就是盲按。

    房间里的 back 权限必须由「按下那一刻的证据」授权，不能由「刚才读到过」授权。
    """
    handler = make_panel_handler(popup_name="Bob")
    handler.element_finder.on_wait = lambda: setattr(handler.element_finder, "popup_open", False)
    driver = SeatPanelDriver(handler)
    desk = build_desk_wrapper(handler, left="", right="10", left_occupied=True)

    async with driver.avatar_card(desk, "left", 9) as card:
        assert card.name == "Bob"  # 证据确实读到过

    handler.key_actions.press_back.assert_not_called()


async def test_avatar_card_never_presses_back_when_the_tap_never_landed():
    """连点都没点出去（缺 bounds / 手势失败）时按 back 同样是盲按。"""
    handler = make_panel_handler(popup_name="Bob")
    handler.gesture_handler.click_at.return_value = False
    driver = SeatPanelDriver(handler)
    desk = build_desk_wrapper(handler, left="", right="10", left_occupied=True)

    async with driver.avatar_card(desk, "left", 9) as card:
        assert card.opened is False

    handler.key_actions.press_back.assert_not_called()
    # 弹窗都没点出来就不该去等它渲染
    assert handler.element_finder.wait_calls == 0


async def test_avatar_card_closes_a_card_that_rendered_after_the_timeout():
    """昵称没读出来但卡片已经在屏幕上：仍要关掉，否则它会挡住后面的麦位读数。"""
    handler = make_panel_handler(popup_name=None)
    handler.element_finder.popup_open = True  # 卡片在屏幕上，只是昵称读不出文字
    driver = SeatPanelDriver(handler)
    desk = build_desk_wrapper(handler, left="", right="10", left_occupied=True)

    async with driver.avatar_card(desk, "left", 9) as card:
        assert card.opened is True
        assert card.name is None

    handler.key_actions.press_back.assert_called_once()


async def test_avatar_card_never_presses_back_when_the_read_raises():
    """读数抛错且屏幕上也确实没有卡片：读失败不构成任何授权。"""
    handler = make_panel_handler(popup_name=None)
    handler.element_finder.wait_for_any_element = MagicMock(side_effect=RuntimeError("dump 超时"))
    driver = SeatPanelDriver(handler)
    desk = build_desk_wrapper(handler, left="", right="10", left_occupied=True)

    async with driver.avatar_card(desk, "left", 9) as card:
        assert card.opened is False
        assert card.name is None

    handler.key_actions.press_back.assert_not_called()


async def test_avatar_card_closes_a_card_found_by_the_second_probe_after_a_failed_read():
    """读数抛错但二次取证看到卡片还在：照关不误 —— 授权来自这次成功的探测。

    这正是「授权只看证据、不看上一次调用成功与否」的意义：读挂了不等于卡片没了。
    """
    handler = make_panel_handler(popup_name="Bob")
    handler.element_finder.wait_for_any_element = MagicMock(side_effect=RuntimeError("dump 超时"))
    driver = SeatPanelDriver(handler)
    desk = build_desk_wrapper(handler, left="", right="10", left_occupied=True)

    async with driver.avatar_card(desk, "left", 9) as card:
        assert card.opened is True
        assert card.name is None

    handler.key_actions.press_back.assert_called_once()


async def test_avatar_card_releases_the_card_when_the_body_raises():
    """调用方在上下文里抛错也必须走完关闭流程。"""
    handler = make_panel_handler(popup_name="Bob")
    driver = SeatPanelDriver(handler)
    desk = build_desk_wrapper(handler, left="", right="10", left_occupied=True)

    with pytest.raises(RuntimeError):
        async with driver.avatar_card(desk, "left", 9):
            raise RuntimeError("读数崩了")

    handler.key_actions.press_back.assert_called_once()


async def test_avatar_card_without_a_desk_never_presses_back():
    handler = make_panel_handler(popup_name="Bob")
    driver = SeatPanelDriver(handler)

    async with driver.avatar_card(None, "left", 9) as card:
        assert card.opened is False
        assert card.name is None

    handler.key_actions.press_back.assert_not_called()


async def test_avatar_card_without_a_handler_yields_a_closed_card():
    driver = SeatPanelDriver(None)

    async with driver.avatar_card(object(), "left", 9) as card:
        assert card.opened is False
        assert card.name is None


async def test_avatar_card_taps_the_left_quarter_of_the_desk_bounds():
    """ElementWrapper 的子元素没有 element key，click() 静默 False ⇒ 退回按坐标点。"""
    handler = make_panel_handler(popup_name="Bob")
    driver = SeatPanelDriver(handler)
    desk = build_desk_wrapper(handler, left="", right="10", left_occupied=True)  # bounds [40,100][400,260]

    async with driver.avatar_card(desk, "left", 9):
        pass

    assert handler.gesture_handler.click_at.call_args.args == (130, 180)


async def test_avatar_card_taps_the_right_three_quarters_for_the_right_seat():
    handler = make_panel_handler(popup_name="Bob")
    driver = SeatPanelDriver(handler)
    desk = build_desk_wrapper(handler, left="", right="10", right_occupied=True)

    async with driver.avatar_card(desk, "right", 10):
        pass

    assert handler.gesture_handler.click_at.call_args.args == (310, 180)


async def test_avatar_card_clicks_a_raw_webelement_child_directly():
    """raw WebElement 路径能真点就真点，不多绕一次坐标。"""
    handler = make_panel_handler(popup_name="Bob")
    driver = SeatPanelDriver(handler)
    desk, avatar = build_raw_desk_with_avatar()

    async with driver.avatar_card(desk, "left", 9):
        pass

    assert avatar.clicked is True
    handler.gesture_handler.click_at.assert_not_called()


async def test_avatar_card_never_presses_back_when_the_desk_has_no_geometry():
    handler = make_panel_handler(popup_name="Bob")
    handler.gesture_handler.click_at.return_value = False
    driver = SeatPanelDriver(handler)
    desk = RawSeatDesk({}, location=None)  # 既没有 bounds 也没有可点的子节点

    async with driver.avatar_card(desk, "left", 9) as card:
        assert card.opened is False

    handler.key_actions.press_back.assert_not_called()


# ---------------------------------------------------------------------------
# read_occupant：把一次头像点名包成「读昵称」
# ---------------------------------------------------------------------------


async def test_read_occupant_returns_the_name_and_closes_the_card():
    handler = make_panel_handler(popup_name="Bob")
    driver = SeatPanelDriver(handler)
    desk = build_desk_wrapper(handler, left="", right="10", left_occupied=True)

    assert await driver.read_occupant(desk, "left", 9) == "Bob"
    handler.key_actions.press_back.assert_called_once()


async def test_read_occupant_strips_the_nickname():
    handler = make_panel_handler(popup_name="  Bob  ")
    driver = SeatPanelDriver(handler)
    desk = build_desk_wrapper(handler, left="", right="10", left_occupied=True)

    assert await driver.read_occupant(desk, "left", 9) == "Bob"


async def test_read_occupant_returns_none_without_touching_the_back_key():
    handler = make_panel_handler(popup_name=None)
    driver = SeatPanelDriver(handler)
    desk = build_desk_wrapper(handler, left="", right="10", left_occupied=True)

    assert await driver.read_occupant(desk, "left", 9) is None
    handler.key_actions.press_back.assert_not_called()


async def test_read_occupant_without_a_handler_returns_none():
    assert await SeatPanelDriver(None).read_occupant(object(), "left", 9) is None


# ---------------------------------------------------------------------------
# 铁律：press_back 的次数只能由「按下那一刻屏幕上有没有卡片」决定
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "scenario, setup, expect_back",
    [
        ("弹窗真开着", {}, 1),
        ("弹窗没开", {"popup_name": None}, 0),
        ("超时但卡片还在", {"popup_name": None, "popup_open": True}, 1),
        ("点都没点出去", {"popup_name": "Bob", "tap_fails": True}, 0),
        ("读完就被关掉", {"popup_name": "Bob", "dismissed_during_read": True}, 0),
        ("读数抛错且无卡片", {"popup_name": None, "read_raises": True}, 0),
        ("读数抛错但卡片还在", {"popup_name": "Bob", "read_raises": True}, 1),
    ],
)
async def test_press_back_is_authorized_only_by_live_evidence(scenario, setup, expect_back):
    """一张表钉死「证据 ⇔ back」的关系：拿不到卡片就一次 back 都不许按。"""
    dismissed = setup.pop("dismissed_during_read", False)
    read_raises = setup.pop("read_raises", False)
    tap_fails = setup.pop("tap_fails", False)

    handler = make_panel_handler(popup_name=setup.get("popup_name", "Bob"))
    if "popup_open" in setup:
        handler.element_finder.popup_open = setup["popup_open"]
    if tap_fails:
        handler.gesture_handler.click_at.return_value = False
    if read_raises:
        handler.element_finder.wait_for_any_element = MagicMock(
            side_effect=RuntimeError("dump 超时")
        )
    if dismissed:
        handler.element_finder.on_wait = lambda: setattr(
            handler.element_finder, "popup_open", False
        )

    driver = SeatPanelDriver(handler)
    desk = build_desk_wrapper(handler, left="", right="10", left_occupied=True)

    await driver.read_occupant(desk, "left", 9)

    assert handler.key_actions.press_back.call_count == expect_back, scenario


# ---------------------------------------------------------------------------
# UI 独占
# ---------------------------------------------------------------------------


async def test_ui_session_holds_the_controller_lock():
    controller = FakeController()
    handler = make_panel_handler(popup_name="Bob", controller=controller)
    driver = SeatPanelDriver(handler)
    desk = build_desk_wrapper(handler, left="", right="10", left_occupied=True)
    lock_states = []
    handler.element_finder.on_wait = lambda: lock_states.append(controller.ui_lock.locked())

    async with driver.ui_session("seat_panel:inspect"):
        async with driver.avatar_card(desk, "left", 9):
            pass

    # 点头像读弹窗必须持 ui_session，否则命令任务与兜底 press_back 会踩进来
    assert lock_states and all(lock_states)
    assert controller.sessions == ["seat_panel:inspect"]
    assert controller.ui_lock.locked() is False


async def test_ui_session_is_a_noop_without_a_controller():
    driver = SeatPanelDriver(make_panel_handler())

    async with driver.ui_session("seat_panel:inspect"):
        pass


async def test_ui_session_is_a_noop_without_a_handler():
    async with SeatPanelDriver(None).ui_session("seat_panel:inspect"):
        pass
