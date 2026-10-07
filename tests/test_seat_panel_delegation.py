"""座位操作迁到 SeatPanelDriver 之后的行为（票 #397）。

两条被迁的调用链：

- ``SeatingManager.accompany_user`` —— 陪伴搜索里的头像点名与昵称读取；
- ``SeatCheckManager._handle_occupied_seat`` —— 占座检查里的名片点名与昵称读取。

验收点是一条产品不变量而不是代码风格：**派对房间里一次盲按 back 就是退出派对
房间**。所以这两个流程里的每一次 back 都必须由「弹窗此刻确实在屏幕上」这份证据
授权，而证据只由 SeatPanelDriver 取；本文件里「绝不盲按」的用例就是回归护栏。

替身按 tests/test_seat_panel_driver.py 的做法在本文件内局部补齐（可变的 confirm
按钮、可关闭的弹窗、seat_off 按钮的查找时序点），不去改 tests/seat_fixtures.py ——
别的票也在改那个共用文件。
"""

import ast
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from tests.seat_fixtures import (
    ClickableNode,
    FakeController,
    FakeElementFinder,
    FakeSeatUI,
    RawSeatDesk,
    make_handler,
    soul_elements,
)

from ushareiplay.dal.user_dao import UserDAO
from ushareiplay.managers.seat_manager import seat_check as seat_check_module
from ushareiplay.managers.seat_manager.seat_check import SeatCheckManager
from ushareiplay.managers.seat_manager.seat_panel_driver import SeatCardView
from ushareiplay.managers.seat_manager.seating import SeatingManager

CANONICAL = "主账号"
AVATAR = "分身"
STRANGER = "路人甲"
# 与 DB 侧同构的身份集合：一个主账号 + 它的分身。
IDENTITY = {CANONICAL: AVATAR}


# ---------------------------------------------------------------------------
# 局部替身
# ---------------------------------------------------------------------------
class PopupFinder(FakeElementFinder):
    """在共用替身上补三处生产接口。

    - ``wait_for_element_clickable('confirm_seat' / 'seat_off')``；
    - ``close_popup()``：back 会让名片节点离开 dump（与真机一致）。

    共用替身的 ``on_wait`` 钩子用来制造「读完昵称之后卡片才被关掉」的时序。
    """

    def __init__(self, elements, events, seat_off_visible=True, **kwargs):
        super().__init__(elements, **kwargs)
        self.events = events
        self.seat_off_visible = seat_off_visible
        self.confirm = ClickableNode("确认")

    def close_popup(self):
        """关掉名片：昵称节点离开 dump。"""
        self.popup_open = False

    def wait_for_element_clickable(self, element_key, timeout=10):
        if element_key == "confirm_seat":
            return self.confirm
        if element_key == "seat_off" and self.seat_off_visible:
            return RecordingNode(self.events, "seat_off")
        return None


class RecordingNode:
    """raw WebElement 形状的节点：可点，并把自己的点击记进事件流。"""

    def __init__(self, events, name, text="", children=None):
        self.events = events
        self.name = name
        self._text = text
        self.children = children or {}
        self.clicked = False

    @property
    def text(self):
        return self._text

    def click(self):
        self.clicked = True
        self.events.append(self.name)

    def find_element(self, _by, value):
        """麦位节点自己带一张子节点索引（与 Appium parent.find_element 同形）。"""
        if value not in self.children:
            raise KeyError(value)
        return self.children[value]


def make_popup_handler(events, popup_name, seat_off_visible=True):
    """带真实弹窗证据节点的 handler：名片开/关与 back 的关系是自洽的。"""
    handler = make_handler(popup_name=popup_name)
    finder = PopupFinder(
        handler.element_finder.elements,
        events=events,
        seat_off_visible=seat_off_visible,
        popup_name=popup_name,
    )
    handler.element_finder = finder
    # 真机上 back 就是关掉名片：证据节点跟着消失，流程才自洽
    handler.key_actions.press_back.side_effect = lambda: (
        events.append("back"),
        finder.close_popup(),
    )
    return handler, finder


def _seat_dom(events, *, left_occupied, right_occupied, left_label="", right_label=""):
    """一张桌位的 raw WebElement 替身（展开重扫路径的形状）。"""
    elements = soul_elements()
    children = {}
    for side, occupied, label in (
        ("left", left_occupied, left_label),
        ("right", right_occupied, right_label),
    ):
        children[elements[f"{side}_seat"]] = RecordingNode(
            events,
            f"sit_{side}",
            text="",
            children={elements[f"{side}_label"]: SimpleNamespace(text=label)},
        )
        if occupied:
            children[elements[f"{side}_state"]] = RecordingNode(events, f"tap_{side}")
        else:
            children[elements[f"{side}_default_name"]] = SimpleNamespace(text="点击入座")
    return RawSeatDesk(children, location={"x": 40, "y": 600})


def _companion_desk(events):
    """一张「只有右侧有人」的桌位：陪伴搜索会点名右侧、去坐左侧。"""
    return _seat_dom(
        events, left_occupied=False, right_occupied=True, right_label="2"
    )


def _occupied_desk(events, occupant="Bob"):
    """1 号位有人占座、label 读得到 —— 占座检查会走的那张桌位。"""
    return _seat_dom(
        events, left_occupied=True, right_occupied=False, left_label=occupant
    )


class RecordingDriver:
    """SeatPanelDriver 的记录替身：证明调用点把点名与读数交了出去。

    签名与生产一致（含 keyword-only 的 prefer_state），并把点击目标一并记下来：
    占座检查那条链路必须钉在 seat 节点上，不能跟着默认路径改点 ClState。
    """

    def __init__(self, opened=True, name=None):
        self.calls = []
        self.card = SeatCardView(opened=opened, name=name)

    @asynccontextmanager
    async def avatar_card(self, desk, side, seat_number, *, prefer_state=True):
        self.calls.append((desk, side, seat_number, prefer_state))
        yield self.card

    def tap_targets(self):
        """各次点名的点击目标（prefer_state 的取值）。"""
        return [call[3] for call in self.calls]


@pytest.fixture(autouse=True)
def _no_sleeps(monkeypatch):
    """流程里的等待（弹窗渲染、关窗回场）在测试里全部即时完成。"""
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())


@pytest.fixture
def same_identity(monkeypatch):
    """身份判定：主账号与它的分身是同一个人（与 UserDAO.is_same_identity 同义）。"""

    async def _is_same_identity(left, right):
        return IDENTITY.get(left, left) == IDENTITY.get(right, right)

    monkeypatch.setattr(UserDAO, "is_same_identity", _is_same_identity)


def _seat_check_levels(monkeypatch, occupant_level=3):
    async def _get_by_username(username):
        return SimpleNamespace(level=5 if username == "Chainer" else occupant_level)

    monkeypatch.setattr(
        seat_check_module, "UserDAO", SimpleNamespace(get_by_username=_get_by_username)
    )


# ---------------------------------------------------------------------------
# SeatingManager.accompany_user —— 委托 + 绝不盲按
# ---------------------------------------------------------------------------
async def test_accompany_user_delegates_the_avatar_read_to_the_panel_driver(same_identity):
    """陪伴搜索的点名/读昵称走 SeatPanelDriver，manager 自己不再点弹窗。"""
    events = []
    desk = _companion_desk(events)
    handler, _finder = make_popup_handler(events, popup_name=AVATAR)
    driver = RecordingDriver(opened=True, name=AVATAR)

    SeatingManager.reset_instance()
    manager = SeatingManager.initialize(
        handler, seat_ui=FakeSeatUI([desk]), panel_driver=driver
    )

    result = await manager.accompany_user(CANONICAL, sender_username=CANONICAL)

    assert result == {"success": "Successfully took a seat"}, result
    assert [(side, seat_number) for _d, side, seat_number, _p in driver.calls] == [("right", 2)]
    # 陪伴搜索只读昵称，跟默认的 ClState 目标即可
    assert driver.tap_targets() == [True], driver.calls
    # 名片是驱动点开的：manager 自己那一路点击里不该再有点头像的动作
    assert "tap_right" not in events, events


async def test_accompany_user_never_presses_back_when_no_popup_opened(same_identity):
    """点名没打开任何弹窗时一次 back 都不许按（盲按 back 就是退出派对房间）。

    这正是真机 09-28 20:46 那次事故：残留渲染被读成「占座但身份未知」，读不到昵称
    之后的一次盲按 back 把房间界面关掉了。
    """
    events = []
    desk = _companion_desk(events)
    handler, _finder = make_popup_handler(events, popup_name=None)

    SeatingManager.reset_instance()
    manager = SeatingManager.initialize(handler, seat_ui=FakeSeatUI([desk]))

    result = await manager.accompany_user(CANONICAL, sender_username=CANONICAL)

    assert result == {"error": f"User {CANONICAL} not found on any seat"}
    assert "back" not in events, events


async def test_accompany_user_does_not_press_back_when_the_card_vanished(same_identity):
    """读到昵称之后卡片已被别的流程关掉：此刻再按 back 就是拿房间去赌。"""
    events = []
    desk = _companion_desk(events)
    handler, finder = make_popup_handler(events, popup_name=STRANGER)
    # 读完昵称就把名片关掉（别的任务抢了锁 / 页面被切走）
    finder.on_wait = finder.close_popup

    SeatingManager.reset_instance()
    manager = SeatingManager.initialize(handler, seat_ui=FakeSeatUI([desk]))

    result = await manager.accompany_user(CANONICAL, sender_username=CANONICAL)

    assert result == {"error": f"User {CANONICAL} not found on any seat"}
    assert "back" not in events, events


async def test_accompany_user_closes_the_card_before_sitting_next_to_the_target(same_identity):
    """命中目标时：名片先被安全关掉（一次有证据的 back），再去坐旁边的麦位。"""
    events = []
    desk = _companion_desk(events)
    handler, _finder = make_popup_handler(events, popup_name=AVATAR)

    SeatingManager.reset_instance()
    manager = SeatingManager.initialize(handler, seat_ui=FakeSeatUI([desk]))

    result = await manager.accompany_user(CANONICAL, sender_username=CANONICAL)

    assert result == {"success": "Successfully took a seat"}, result
    assert events == ["tap_right", "back", "sit_left"], events


async def test_accompany_user_does_not_deadlock_when_a_command_session_holds_the_ui_lock(same_identity):
    """驱动绝不能自己再去拿 ui_lock：调用链已经在命令的 ui_session 里了。

    ui_lock 是不可重入的 asyncio.Lock，驱动再取一次就是自己等自己（不是报错，是挂住）。
    """
    events = []
    desk = _companion_desk(events)
    handler, _finder = make_popup_handler(events, popup_name=AVATAR)
    controller = FakeController()
    handler.controller = controller

    SeatingManager.reset_instance()
    manager = SeatingManager.initialize(handler, seat_ui=FakeSeatUI([desk]))

    async with controller.ui_session("command:seat 3"):
        assert controller.ui_lock.locked() is True
        result = await asyncio.wait_for(
            manager.accompany_user(CANONICAL, sender_username=CANONICAL), timeout=2
        )

    assert result == {"success": "Successfully took a seat"}, result
    assert controller.ui_lock.locked() is False


# ---------------------------------------------------------------------------
# SeatCheckManager —— 占座检查的名片点名同样交给驱动
# ---------------------------------------------------------------------------
async def _seat_check_run(events, handler, finder, driver=None, occupant="Bob"):
    """跑一遍 check_user_specific_seat（公开入口），返回事件流。"""
    desk = _occupied_desk(events, occupant=occupant)
    SeatCheckManager.reset_instance()
    manager = SeatCheckManager.initialize(handler, FakeSeatUI([desk]), panel_driver=driver)
    manager._message_dispatch = SimpleNamespace(send_screen_message=lambda *a, **k: None)
    await manager.check_user_specific_seat("Chainer", 1)
    return events


async def test_seat_check_reads_the_occupant_through_the_panel_driver(monkeypatch):
    """占座检查的点名/读昵称走 SeatPanelDriver，manager 自己不再点弹窗。"""
    _seat_check_levels(monkeypatch)
    events = []
    handler, finder = make_popup_handler(events, popup_name="Bob")
    driver = RecordingDriver(opened=True, name="Bob")

    await _seat_check_run(events, handler, finder, driver=driver)

    assert [(side, seat_number) for _d, side, seat_number, _p in driver.calls] == [("left", 1)]
    # 点击目标钉在 seat 节点：要读 seat_off，点 ClState 弹出的名片是否带这个按钮
    # 全仓无从验证，点错的症状是静默的「Unable to manage seat N」。
    assert driver.tap_targets() == [False], driver.calls
    assert "seat_off" in events, events
    assert "tap_left" not in events, events


async def test_seat_check_never_presses_back_when_the_card_never_opened(monkeypatch):
    """名片没开出来就一次 back 都不许按。"""
    _seat_check_levels(monkeypatch)
    events = []
    handler, finder = make_popup_handler(events, popup_name=None)

    await _seat_check_run(events, handler, finder)

    assert "back" not in events, events
    assert "seat_off" not in events, events


async def test_seat_check_does_not_press_back_when_the_card_vanished_before_the_level_check(
    monkeypatch,
):
    """占座人等级更高 → 放弃接管；但名片此刻已不在屏幕上时不得再按 back。"""
    _seat_check_levels(monkeypatch, occupant_level=9)
    events = []
    handler, finder = make_popup_handler(events, popup_name="Boss")
    # 读完昵称之后名片就被别的流程关掉了
    finder.on_wait = finder.close_popup

    await _seat_check_run(events, handler, finder, occupant="Boss")

    assert "back" not in events, events


async def test_seat_check_closes_the_card_it_opened_when_the_level_check_rejects(monkeypatch):
    """占座人等级更高但名片仍在屏幕上：驱动授权那一次 back 关掉它。"""
    _seat_check_levels(monkeypatch, occupant_level=9)
    events = []
    handler, finder = make_popup_handler(events, popup_name="Boss")

    await _seat_check_run(events, handler, finder, occupant="Boss")

    assert "back" in events, events
    assert finder.popup_open is False


async def test_seat_check_closes_the_card_it_opened_when_the_user_is_already_seated(monkeypatch):
    """本人已经在该号位上：名片是唯一能为那一次 back 授权的证据。"""
    _seat_check_levels(monkeypatch)
    events = []
    handler, finder = make_popup_handler(events, popup_name="Chainer")

    await _seat_check_run(events, handler, finder, occupant="Chainer")

    assert "back" in events, events
    assert finder.popup_open is False


async def test_seat_check_closes_the_card_when_the_seat_off_button_is_missing(monkeypatch):
    """请下麦按钮读不到时，弹窗不能留在屏幕上挡住后续读数。"""
    _seat_check_levels(monkeypatch)
    events = []
    handler, finder = make_popup_handler(events, popup_name="Bob", seat_off_visible=False)

    await _seat_check_run(events, handler, finder)

    assert "seat_off" not in events, events
    assert "back" in events, events
    assert finder.popup_open is False


# ---------------------------------------------------------------------------
# AC #3 的机械见证：这两个模块里不再有任何 press_back 调用
# ---------------------------------------------------------------------------
def _press_back_nodes(path: Path) -> list:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        node
        for node in ast.walk(tree)
        if (isinstance(node, ast.Attribute) and node.attr == "press_back")
        or (isinstance(node, ast.Name) and node.id == "press_back")
    ]


@pytest.mark.parametrize("module_name", ["seating.py", "seat_check.py"])
def test_the_seat_managers_never_call_press_back_directly(module_name):
    """按返回只能由 SeatPanelDriver 授权：这两个模块里一处 press_back 都不该有。

    行为用例各自覆盖了具体分支，这一层用 AST 把「完全移除」钉死 —— 注释与文档字符串
    里的提及不算调用。
    """
    path = (
        Path(__file__).resolve().parents[1]
        / "src/ushareiplay/managers/seat_manager"
        / module_name
    )
    assert _press_back_nodes(path) == [], f"{module_name} 仍在直接调用 press_back"