"""在线用户抽屉深模块的离线单测。

被测的是 `OnlineDrawerManager` 的会话契约（`drawer_session` / `resolve_visible_username`）
与驱动端口契约，不碰任何 Appium 时序：真实屏幕在这里整块换成了
`tests/fakes/in_memory_online_drawer_driver.py`。

这些断言保护的是 spec #426 的问题陈述 #1：**无人认领的抽屉生命周期**。因此本文件里
最要紧的不是「抽屉能不能打开」，而是三条归属规则 —— 只关自己打开的那一次、正文抛
异常时照样收尾、任何路径下都不许出现盲按返回（盲按返回会退出派对房间）。
"""

import asyncio
import inspect
import logging
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from ushareiplay.managers.online_drawer import (
    Handover,
    OnlineDrawerDriverPort,
    OnlineDrawerManager,
    SoulOnlineDrawerDriver,
)
from tests.fakes.in_memory_online_drawer_driver import InMemoryOnlineDrawerDriver


class _FakeController:
    """最小 UI 独占替身。

    用真的 `asyncio.Lock`（而不是 bool 标记），这样「会话期间锁确实被持有」是
    可观测的事实，而不是替身自己声称的事实。
    """

    def __init__(self):
        self.ui_lock = asyncio.Lock()
        self.reasons = []

    @asynccontextmanager
    async def ui_session(self, reason: str = ""):
        self.reasons.append(reason)
        async with self.ui_lock:
            yield


def _make_manager(driver=None, *, controller=None, name_resolver=None, handler=None):
    """装配一个受保护单例实例（ADR-0009：只能经 initialize 创建）。"""
    fake_handler = handler
    if fake_handler is None:
        fake_handler = SimpleNamespace(
            logger=None,
            controller=controller if controller is not None else _FakeController(),
        )
    return OnlineDrawerManager.initialize(
        handler=fake_handler,
        driver=driver,
        name_resolver=name_resolver,
    )


# ---------------------------------------------------------------------------
# 会话生命周期
# ---------------------------------------------------------------------------


async def test_session_opens_settles_then_closes_in_order():
    """正常退出：打开 -> 落定 -> 正文 -> 关闭，且抽屉回到关闭状态。"""
    journal = []
    driver = InMemoryOnlineDrawerDriver(members=["小明", "小红"], journal=journal)
    manager = _make_manager(driver)

    async with manager.drawer_session(reason="test:normal") as open_error:
        assert open_error is None
        journal.append("body")

    assert journal == ["drawer:open", "drawer:settle", "body", "drawer:close"]
    assert driver.drawer_open is False


async def test_session_yields_open_error_and_does_not_close_when_open_failed():
    """打不开抽屉：正文拿到 error dict，且不去关闭一个自己没打开的抽屉。"""
    journal = []
    driver = InMemoryOnlineDrawerDriver(members=["小明"], open_fails=True, journal=journal)
    manager = _make_manager(driver)

    async with manager.drawer_session(reason="test:open-fails") as open_error:
        assert isinstance(open_error, dict)
        assert "error" in open_error
        journal.append("body")

    assert "drawer:close" not in journal
    assert driver.drawer_open is False


async def test_session_does_not_close_a_drawer_that_was_already_open():
    """进场时抽屉已经开着：不夺取归属，退出后保持原状，交给外层决定何时关。

    这是「只关自己打开的那一次」的全部意义：#432 迁移在线名单抓取时，抽屉会话会
    互相嵌套，谁也不该把别人的抽屉关掉。
    """
    journal = []
    driver = InMemoryOnlineDrawerDriver(members=["小明"], drawer_open=True, journal=journal)
    manager = _make_manager(driver)

    async with manager.drawer_session(reason="test:already-open") as open_error:
        assert open_error is None
        journal.append("body")

    assert journal == ["body"]
    assert driver.drawer_open is True


async def test_session_closes_when_body_raises_and_lets_it_propagate():
    """正文抛异常：照样收尾，然后让异常继续往外走。

    没有这条 finally，抽屉就会悬在屏幕上，等下一次盲按返回把它和房间一起带走。
    """
    journal = []
    driver = InMemoryOnlineDrawerDriver(members=["小明"], journal=journal)
    manager = _make_manager(driver)

    with pytest.raises(RuntimeError, match="正文炸了"):
        async with manager.drawer_session(reason="test:raises") as open_error:
            assert open_error is None
            journal.append("body")
            raise RuntimeError("正文炸了")

    assert journal == ["drawer:open", "drawer:settle", "body", "drawer:close"]
    assert driver.drawer_open is False


async def test_session_closes_when_body_raises_even_for_a_drawer_it_did_not_open():
    """抽屉不是本会话打开的，正文抛异常也不越权去关 —— 归属只属于外层。"""
    driver = InMemoryOnlineDrawerDriver(members=["小明"], drawer_open=True)
    manager = _make_manager(driver)

    with pytest.raises(RuntimeError):
        async with manager.drawer_session(reason="test:raises-not-mine"):
            raise RuntimeError("正文炸了")

    assert driver.drawer_open is True
    assert driver.close_calls == 0


async def test_session_yields_error_and_closes_when_settle_fails():
    """抽屉开了却没落定：这是本会话打开的，必须收尾，绝不留一个半开的抽屉。"""
    journal = []
    driver = InMemoryOnlineDrawerDriver(members=["小明"], settle_fails=True, journal=journal)
    manager = _make_manager(driver)

    async with manager.drawer_session(reason="test:settle-fails") as open_error:
        assert isinstance(open_error, dict)
        assert "error" in open_error
        journal.append("body")

    # with 正文一定会被进入（上下文管理器不替你 return），但拿到的 open_error
    # 已经在它之前就把抽屉收走了：调用方看到 error 就直接 return，不做无用功。
    assert journal == ["drawer:open", "drawer:close", "body"]
    assert driver.drawer_open is False


# ---------------------------------------------------------------------------
# 关不掉时：记警告，不抛，不退房间
# ---------------------------------------------------------------------------


async def test_close_failure_is_logged_and_does_not_raise_out_of_the_session(caplog):
    """两个 ivClose 都点不到：记一条警告、保持原状，绝不把异常抛给调用方。

    抽屉留在屏幕上只是难看一次；抛出去会让一次正常的命令变成任务失败，而用
    `press_back` 去「救」它会直接退出派对房间。
    """
    driver = InMemoryOnlineDrawerDriver(members=["小明"], close_fails=True)
    manager = _make_manager(driver)

    with caplog.at_level(logging.WARNING):
        async with manager.drawer_session(reason="test:close-fails") as open_error:
            assert open_error is None

    assert any("未能通过 ivClose" in r.message for r in caplog.records)
    assert driver.drawer_open is True


async def test_close_failure_during_error_cleanup_does_not_mask_the_original_error(caplog):
    """正文抛异常且同时关不掉抽屉：警告归警告，原异常原样往外走。"""
    driver = InMemoryOnlineDrawerDriver(members=["小明"], close_fails=True)
    manager = _make_manager(driver)

    with caplog.at_level(logging.WARNING):
        with pytest.raises(RuntimeError, match="正文炸了"):
            async with manager.drawer_session(reason="test:close-fails-and-raises"):
                raise RuntimeError("正文炸了")

    assert any("未能通过 ivClose" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# 盲按返回的禁令（spec #426 问题陈述 #1）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "driver_kwargs, body",
    [
        ({}, None),                                   # 正常退出
        ({}, "raise"),                                # 正文抛异常
        ({"open_fails": True}, None),                 # 打不开
        ({"drawer_open": True}, None),                # 进场时就开着
        ({"settle_fails": True}, None),               # 开了但没落定
        ({"close_fails": True}, None),                # 关不掉
    ],
)
async def test_no_back_press_ever_happens_on_any_path(driver_kwargs, body):
    """无论走哪条路径，事件流里都不该出现一次盲按返回。

    旧实现在关不掉时会 `press_back` 再点遮罩，而盲按返回会误退出派对房间
    （真机 09-28）。这条断言是那张账单的直接防线。
    """
    journal = []
    driver = InMemoryOnlineDrawerDriver(members=["小明"], journal=journal, **driver_kwargs)
    manager = _make_manager(driver)

    if body == "raise":
        with pytest.raises(RuntimeError):
            async with manager.drawer_session(reason="test:no-back"):
                raise RuntimeError("正文炸了")
    else:
        async with manager.drawer_session(reason="test:no-back"):
            pass

    assert not any("back" in event for event in journal), journal


def test_the_port_has_no_back_press_primitive_at_all():
    """结构上的保证：端口里根本没有 press_back，drawer_session 就**不可能**发它。

    只靠「记得别按返回」这种约定约束不住一个赶时间的修改；端口里没有这个方法，
    约束力来自接口本身。

    （对照：房间档案的端口**保留**了 `press_back`，因为那个抽屉关不掉时已经确认
    自己还在派对房间里，而在线用户抽屉没有这层证据。）
    """
    assert not hasattr(OnlineDrawerDriverPort, "press_back")
    for adapter_class in (SoulOnlineDrawerDriver, InMemoryOnlineDrawerDriver):
        assert not hasattr(adapter_class, "press_back"), adapter_class.__name__


# ---------------------------------------------------------------------------
# UI 独占
# ---------------------------------------------------------------------------


async def test_ui_lock_is_held_for_the_whole_session_and_released_after():
    """打开、落定、找行、关闭全程持锁，退出后释放。

    不持锁时 EventManager 的兜底 `press_back` 会在这些 await 点把抽屉当成未知
    页面关掉 —— 正好是本模块要消灭的那种退房。这里读的是替身里那个真的
    `asyncio.Lock`，不是替身自己声称的「我加过锁了」。
    """
    controller = _FakeController()
    driver = InMemoryOnlineDrawerDriver(members=["小明"])
    manager = _make_manager(driver, controller=controller)

    assert controller.ui_lock.locked() is False

    async with manager.drawer_session(reason="event:refresh_online_users") as open_error:
        assert open_error is None
        assert controller.ui_lock.locked() is True

    assert controller.ui_lock.locked() is False
    assert controller.reasons == ["event:refresh_online_users"]


async def test_ui_lock_is_released_even_when_the_body_raises():
    """正文抛异常时锁也必须还回去，否则一次失败就让后续 UI 操作永远排队。"""
    controller = _FakeController()
    driver = InMemoryOnlineDrawerDriver(members=["小明"])
    manager = _make_manager(driver, controller=controller)

    with pytest.raises(RuntimeError):
        async with manager.drawer_session(reason="test:lock-on-raise"):
            assert controller.ui_lock.locked() is True
            raise RuntimeError("正文炸了")

    assert controller.ui_lock.locked() is False


async def test_session_still_works_when_no_controller_is_wired():
    """controller 缺席（离线装配）时退化为不加锁，而不是抛错。"""
    driver = InMemoryOnlineDrawerDriver(members=["小明"])
    manager = OnlineDrawerManager.initialize(
        handler=SimpleNamespace(logger=None, controller=None), driver=driver
    )

    async with manager.drawer_session(reason="test:no-controller") as open_error:
        assert open_error is None


# ---------------------------------------------------------------------------
# 两个命名域：DB canonical 名 vs Soul UI 可见昵称
# ---------------------------------------------------------------------------


async def test_resolve_visible_username_uses_the_injected_resolver():
    """canonical 名（主账号）经解析器换成 UI 上的分身名。

    房间里只有 UI 名字是可用坐标：在线列表按屏幕上显示的文本找人。两个命名域
    的字符串**不同**，拿 canonical 名直接 `==` UI 文本永远不成立。
    """
    seen = []

    async def resolver(username):
        seen.append(username)
        return {"forchain": "链子"}.get(username, username)

    manager = _make_manager(
        InMemoryOnlineDrawerDriver(), name_resolver=resolver
    )

    assert await manager.resolve_visible_username("forchain") == "链子"
    # 已经在 UI 域里的名字原样通过，不会被二次翻译。
    assert await manager.resolve_visible_username("链子") == "链子"
    assert seen == ["forchain", "链子"]


async def test_resolve_visible_username_is_identity_without_a_resolver():
    """没有注入解析器时按恒等处理 —— 那时调用方给的名字本来就是 UI 文本。"""
    manager = _make_manager(InMemoryOnlineDrawerDriver())

    assert await manager.resolve_visible_username("小明") == "小明"
    assert await manager.resolve_visible_username("") == ""


async def test_canonical_name_must_be_resolved_before_searching_the_drawer():
    """端到端串一遍：canonical 名 -> 可见昵称 -> 在抽屉里找得到那一行。

    这是本 ticket 要交付的那条完整接线；名字解析错一次，抽屉里就永远找不到人。
    """
    driver = InMemoryOnlineDrawerDriver(members=[("链子", "密友"), ("小红", None)])

    async def resolver(username):
        return {"forchain": "链子"}.get(username, username)

    manager = _make_manager(driver, name_resolver=resolver)

    async with manager.drawer_session(reason="test:naming-domains") as open_error:
        assert open_error is None
        visible = await manager.resolve_visible_username("forchain")
        row = await driver.find_member_row(visible)

    assert row is not None
    assert row.visible_name == "链子"
    assert row.follow_state == "密友"
    # 反证：直接拿 canonical 名去找，在抽屉里是找不到的。
    assert await driver.find_member_row("forchain") is None


# ---------------------------------------------------------------------------
# 找一个人：翻页判据的唯一所有者（#440）
# ---------------------------------------------------------------------------
#
# 这段循环此前在 `UserManager` 与 `AdminManager` 里各抄了一份逐字相同的实现（送礼物、
# 私聊、房管三处调用点）。#440 把它整段搬进抽屉会话的唯一所有者：翻到哪一页、翻够
# 几页、什么时候如实回报「未找到」都是**抽屉会话的决策**，端口只负责如实回答「此刻
# 屏幕上有哪些行」。
#
# 下面四条锁的是搬动前后的行为等价：先查当前页、到底提示出现就停、滑不动就停、翻够
# 50 页就停。搬运不该改变其中任何一条。


async def test_member_search_paginates_until_it_finds_the_row():
    """人在后面几页：一页一页翻过去，找到为止，且不越翻越远。"""
    journal = []
    driver = InMemoryOnlineDrawerDriver(
        members=["a", "b", "c", "d", "e", "f"], page_size=2, journal=journal
    )
    manager = _make_manager(driver)

    assert await manager.find_member_in_drawer("e") is True
    # 找 5 个人之前必须真的滑过页，而不是靠一次 dump 蒙对。
    assert journal.count("drawer:scroll") >= 2
    assert journal.index("drawer:scroll") < journal.index("drawer:find:e")


async def test_member_search_gives_up_at_the_end_of_list_without_swiping_past_it():
    """翻到底提示出现：如实回报未找到，并在那之后不再多滑一下。"""
    journal = []
    driver = InMemoryOnlineDrawerDriver(
        members=["a", "b", "c"], page_size=2, journal=journal
    )
    manager = _make_manager(driver)

    assert await manager.find_member_in_drawer("查无此人") is False
    assert driver.at_end_reads > 0
    # 第一页看完（2 行）还剩 1 行，所以滑一次到最后一页；到那一页就收工。
    assert journal.count("drawer:scroll") == 1


async def test_member_search_stops_immediately_when_the_list_will_not_swipe():
    """手势滑不动：停在这一页，不把一次定位变成无上限轮询。

    `end_hint=False` 是必要的另一半条件：到底提示读不到，`is_at_end()` 才会返回 False
    而让代码真的走到 `scroll_container()`；否则它会先被「已经到底了」那条分支截走，
    这条断言就考不到滑动手势了。
    """
    driver = InMemoryOnlineDrawerDriver(
        members=["a", "b"], page_size=2, swipe_fails=True, end_hint=False
    )
    manager = _make_manager(driver)

    assert await manager.find_member_in_drawer("查无此人") is False
    assert driver.scroll_durations == [800]


async def test_member_search_stops_after_fifty_pages_when_the_list_never_ends():
    """到底提示一直读不到（老版本的列表就是）：翻够上限就如实回报未找到。

    50 这个上限是搬运前就有的既有行为，与在线名单抓取的 `MAX_SWIPES` 同源 ——
    别把一次定位变成无上限轮询。

    滑动次数锁在 **51** 而不是 50：被搬过来的是 `for _ in range(MAX + 1)` 这一段，
    每一轮都是「查一次、判一次到底、滑一次」，所以最后一次也会滑一下才跳出循环 ——
    那一下其实没意义（结果不参与任何判断），但**搬动不改行为**，所以照旧锁住。
    真要去掉它是另一个话题：会改变真机上翻页次数，属于行为变更而非重构。
    """
    driver = InMemoryOnlineDrawerDriver(
        members=["a", "b"], page_size=2, end_hint=False
    )
    manager = _make_manager(driver)

    assert await manager.find_member_in_drawer("查无此人") is False
    assert len(driver.scroll_durations) == 51
    assert driver.at_end_reads == 51


def test_the_legacy_managers_no_longer_carry_their_own_copy_of_the_search_loop():
    """送礼物 / 私聊 / 房管三个调用点共用抽屉会话的这一段循环。

    两份逐字相同的实现意味着改翻页上限要改三处、漏一处就在真机上翻到天荒地老。
    这里锁的是「只有唯一所有者才有这段循环」这条归属，而不是某个私有方法的名字。
    """
    from ushareiplay.managers.admin_manager import AdminManager
    from ushareiplay.managers.user_manager import UserManager

    for legacy_manager in (UserManager, AdminManager):
        assert not hasattr(legacy_manager, "_find_member_in_drawer"), legacy_manager.__name__
        # 上限常量同样只在抽屉会话这一侧定义。
        assert not hasattr(legacy_manager, "MAX_SEARCH_SWIPES"), legacy_manager.__name__


def test_recovery_manager_no_longer_owns_any_online_drawer_closing_machinery():
    """`RecoveryManager` 不再持有在线用户抽屉的关窗机制（#440）。

    它原先有一张 `DRAWER_CLOSE_BUTTONS` 表，表里唯一的一行就是 `online_drawer`，
    外加一层「先找抽屉自带关闭按钮」的分支。全仓最后一个传 `'online_drawer'` 的调用点
    早就不存在了（`events/drawer_elements.py` 里那一条一直是注释状态），所以整层机制
    连同那张表一起删掉。

    `close_drawer` **方法本身保留**：它仍是 `DrawerElementsEvent` 关 `input_drawer`
    的通用入口，那类遮罩式抽屉本来就没有关闭按钮可用。

    这里锁的是「通用机制还在、在线用户抽屉的专属机制没了」这条分界，防止有人日后
    又把 `ivClose` 那张表加回来 —— 那样在线用户抽屉就又有了第二个关闭手势的归属，
    正是 spec #426 要消灭的东西。
    """
    from ushareiplay.managers import recovery_manager
    from ushareiplay.managers.recovery_manager import RecoveryManager

    # 通用入口仍在。
    assert callable(RecoveryManager.close_drawer)
    # 在线用户抽屉的专属机制已退役。
    assert not hasattr(recovery_manager, "DRAWER_CLOSE_BUTTONS")
    assert not hasattr(RecoveryManager, "_close_via_close_button")


# ---------------------------------------------------------------------------
# 端口契约：两个适配器必须遵守同一份签名
# ---------------------------------------------------------------------------

#: 端口的全部原语。两个适配器都逐个对得上，替身才不会悄悄漂移成另一套接口 ——
#: 那会让「离线的单测通过」变成一句谎话。
PORT_METHODS = (
    "is_open",
    "open",
    "close",
    "wait_for_settle",
    "scroll_container",
    "find_member_row",
    # #432 在线名单抓取要的三条读数：人数、整页行、到底提示。
    "read_online_count",
    "visible_member_rows",
    "is_at_end",
    # #435 资料页与私信要的八步：卡片开/判/收，私聊导航三步，加回房间。
    "open_member_profile",
    "is_profile_card_open",
    "dismiss_profile_card",
    "open_member_home",
    "open_private_chat_page",
    "type_private_message",
    "submit_private_message",
    "return_to_room",
    # #438 送礼要的八步：进弹窗、判弹窗、读礼物名与灵魂力、点礼物/动作、确认、收弹窗。
    "open_gift_entry",
    "gift_popup_action",
    "read_gift_item_name",
    "read_gift_soul_power",
    "click_gift_item",
    "click_gift_action",
    "confirm_gift_use",
    "dismiss_gift_popup",
    # #439 房管要的四个原语：开关文案、开关、确认框、收确认框。刻意没有「盲按返回」
    # 那一档 —— 端口里不存在这个原语，收不掉只允许记警告保持原状。
    "read_admin_invite_label",
    "click_admin_invite",
    "confirm_admin_action",
    "dismiss_admin_confirm",
)

ADAPTER_CLASSES = (SoulOnlineDrawerDriver, InMemoryOnlineDrawerDriver)


@pytest.mark.parametrize("adapter_class", ADAPTER_CLASSES)
def test_adapter_implements_the_whole_port(adapter_class):
    assert issubclass(adapter_class, OnlineDrawerDriverPort)
    # 一个没实现完的 ABC 是实例化不了的；这里显式断言，避免有人把抽象方法删掉。
    assert not getattr(adapter_class, "__abstractmethods__", frozenset())
    for method_name in PORT_METHODS:
        assert callable(getattr(adapter_class, method_name)), method_name


@pytest.mark.parametrize("method_name", PORT_METHODS)
def test_both_adapters_have_identical_signatures_to_the_port(method_name):
    """参数名、关键字限定、默认值、返回标注必须逐字一致。

    签名漂移比行为漂移更阴险：调用点先坏，而且坏在测试之外的地方。
    """
    port_signature = inspect.signature(getattr(OnlineDrawerDriverPort, method_name))
    for adapter_class in ADAPTER_CLASSES:
        adapter_signature = inspect.signature(getattr(adapter_class, method_name))
        assert adapter_signature == port_signature, adapter_class.__name__


# ---------------------------------------------------------------------------
# 生产适配器：手势必须与既有在线名单抓取逐字一致
# ---------------------------------------------------------------------------


class _StubElement:
    """最小 WebElement 替身：只带适配器真正读得到的属性。"""

    def __init__(self, text="", location=None, size=None, displayed=True):
        self.text = text
        self.location = location or {"x": 0, "y": 0}
        self.size = size or {"width": 0, "height": 0}
        self.displayed = displayed
        self.clicked = False
        self.typed = []

    def click(self):
        self.clicked = True

    def send_keys(self, text):
        self.typed.append(text)

    def is_displayed(self):
        return self.displayed


class _StubFinder:
    """按元素 key 服务的屏幕替身，并记录每次查找。"""

    def __init__(self, screen=None, children=None, any_element=(None, None), elements_stay=False):
        self.screen = screen or {}
        self.children = children or {}
        self.any_element = any_element
        self.elements_stay = elements_stay
        self.looked_up = []

    def try_find_element(self, key, log=False, clickable=False):
        self.looked_up.append(key)
        return self.screen.get(key)

    def wait_for_element(self, key, timeout=10):
        self.looked_up.append(key)
        return self.screen.get(key)

    def wait_for_element_clickable(self, key, timeout=10):
        self.looked_up.append(key)
        return self.screen.get(key)

    def wait_for_element_disappear(self, key, timeout=10, poll_frequency=None):
        # 真机上「等元素消失」就是元素不再出现在 dump 里，替身照此把它从屏上摘掉，
        # 好让「关掉了」这件事在后面的断言里是真的，而不是替身自己声称的。
        # `elements_stay=True` 描述「点了也赖着不走」的那种卡片。
        if not self.elements_stay:
            self.screen.pop(key, None)
        return True

    def wait_for_any_element(self, element_keys, timeout=10):
        return self.any_element

    def find_child_elements(self, parent, key):
        return list(self.children.get((parent, key), []))

    def find_child_element(self, parent, key, log_failure=True):
        return self.children.get((parent, key))


class _StubGesture:
    def __init__(self, works=True):
        self.swipes = []
        self.clicks = []
        self.works = works

    def swipe(self, x1, y1, x2, y2, duration_ms=600):
        self.swipes.append((x1, y1, x2, y2, duration_ms))
        return self.works

    def click_element_at(self, element, x_ratio=0.5, y_ratio=0.5, x_offset=0, y_offset=0):
        self.clicks.append((element, y_ratio))
        return self.works


class _ExplodingKeyActions:
    """一旦被按返回就当场失败。

    旧实现在关不掉抽屉时会走 `press_back`，而盲按返回会误退出派对房间
    （spec #426 问题陈述 #1）。这里让它没有机会「顺手兜底」。
    """

    def press_back(self):
        raise AssertionError("盲按返回会误退出派对房间，不得出现在抽屉收尾路径上")


def _make_soul_adapter(finder, gesture=None):
    handler = SimpleNamespace(
        logger=None,
        element_finder=finder,
        gesture_handler=gesture or _StubGesture(),
        key_actions=_ExplodingKeyActions(),
    )
    return SoulOnlineDrawerDriver(handler)


@pytest.fixture(autouse=True)
def _no_settle_sleep(monkeypatch):
    """离线的单测里没有真机，落定静默直接去掉（时序本身不是这里要断言的东西）。"""

    async def _instant(_seconds):
        return None

    monkeypatch.setattr(
        "ushareiplay.managers.online_drawer.soul_driver.asyncio.sleep", _instant
    )


async def test_production_open_clicks_the_user_count_entry():
    """打开 = 点 `user_count` 入口，与旧 `_scrape_online_user_names` 的前两步一致。"""
    entry = _StubElement(text="6人")
    finder = _StubFinder(screen={"user_count": entry})
    driver = _make_soul_adapter(finder)

    assert await driver.open(error_message="打不开") == {}
    assert entry.clicked is True


async def test_production_open_reports_the_callers_error_message_when_entry_is_absent():
    """入口读不到：返回调用方自己的文案，让聊天气泡里的报错保持原样。"""
    driver = _make_soul_adapter(_StubFinder(screen={}))

    assert await driver.open(error_message="打不开在线用户列表") == {
        "error": "打不开在线用户列表"
    }


async def test_production_close_clicks_iv_close_and_never_presses_back():
    """关闭只点 `ivClose`；`key_actions` 就在旁边也不会被碰。"""
    close_btn = _StubElement()
    finder = _StubFinder(screen={"online_users_close": close_btn})
    driver = _make_soul_adapter(finder)

    assert await driver.close() is True
    assert close_btn.clicked is True


async def test_production_close_falls_back_to_the_second_close_key():
    """第一个 key 没渲染出来时按顺序试第二个，两个都指向 `ivClose`。"""
    fallback_btn = _StubElement()
    finder = _StubFinder(screen={"close_button": fallback_btn})
    driver = _make_soul_adapter(finder)

    assert await driver.close() is True
    assert fallback_btn.clicked is True


async def test_production_close_returns_false_when_both_close_keys_are_missing():
    """两个按钮都没有：如实返回 False，让调用方决定，绝不自己换成按返回。"""
    driver = _make_soul_adapter(_StubFinder(screen={}))

    assert await driver.close() is False


async def test_production_scroll_uses_container_geometry_at_the_slow_duration():
    """滑动坐标由容器的 location/size 算出，时长 800ms（避免惯性飞滚跳过未渲染行）。"""
    container = _StubElement(location={"x": 100, "y": 200}, size={"width": 500, "height": 800})
    gesture = _StubGesture()
    driver = _make_soul_adapter(
        _StubFinder(screen={"online_users": container}), gesture
    )

    assert await driver.scroll_container() is True
    # 中心 x=350；手指从 0.75 高度(800) 划到 0.30 高度(440)。
    assert gesture.swipes == [(350, 800, 350, 440, 800)]


async def test_production_find_member_row_matches_the_visible_nickname():
    """按 UI 可见昵称匹配，并带出关注关系文案。"""
    container = _StubElement()
    row = _StubElement()
    name_elem = _StubElement(text="链子")
    follow_elem = _StubElement(text="密友")
    finder = _StubFinder(
        screen={"online_users": container},
        children={
            (container, "user_container"): [row],
            (row, "online_user"): name_elem,
            (row, "follow_state"): follow_elem,
        },
    )
    driver = _make_soul_adapter(finder)

    found = await driver.find_member_row("链子")
    assert found is not None
    assert found.visible_name == "链子"
    assert found.follow_state == "密友"
    # 找不到的人返回 None，元素对象一个也不外泄。
    assert await driver.find_member_row("查无此人") is None


async def test_production_adapter_fails_gracefully_without_a_handler():
    """没有 handler 时每个动作都以「App 不可用」失败，而不是抛 AttributeError。

    与 `SoulDrawerDriver._require_handler` 同一份纪律：离线装配与半启动状态下
    都要能问出答案，而不是把调用方炸掉。
    """
    driver = SoulOnlineDrawerDriver(None)

    assert await driver.is_open() is False
    assert await driver.open(error_message="打不开") == {"error": "打不开"}
    assert await driver.close() is False
    assert await driver.wait_for_settle() is False
    assert await driver.scroll_container() is False
    assert await driver.find_member_row("链子") is None
    # #432 起在线名单抓取还需要的三个读数，同样必须能问出答案。
    assert await driver.read_online_count() is None
    assert await driver.visible_member_rows() == []
    assert await driver.is_at_end() is False
    # #435 的资料卡与私聊那八步同理：离线装配与半启动状态下都要能问出答案。
    assert await driver.open_member_profile("链子") is False
    assert await driver.is_profile_card_open() is False
    assert await driver.dismiss_profile_card() is False
    assert await driver.open_member_home() is False
    assert await driver.open_private_chat_page() is False
    assert await driver.type_private_message("你好") is False
    assert await driver.submit_private_message() is False
    assert await driver.return_to_room() is False


# ---------------------------------------------------------------------------
# #432 追加的三个读数：人数、整页行、到底提示
# ---------------------------------------------------------------------------


async def test_production_read_online_count_parses_the_first_digit_run():
    """「N 人在线」控件里的第一段数字就是房间报的在线人数。

    正则解析属于 Appium 文本细节，止步在适配器：引擎拿到的是 int 或 None，
    不该知道控件文案长什么样。
    """
    driver = _make_soul_adapter(_StubFinder(screen={"user_count": _StubElement(text="6人在线")}))

    assert await driver.read_online_count() == 6


async def test_production_read_online_count_is_none_when_unreadable():
    """控件读不到、或文案里根本没有数字时都是 None —— 没有人数不等于人数为 0。"""
    assert await _make_soul_adapter(_StubFinder(screen={})).read_online_count() is None
    assert (
        await _make_soul_adapter(
            _StubFinder(screen={"user_count": _StubElement(text="在线")})
        ).read_online_count()
        is None
    )


async def test_in_memory_read_online_count_returns_the_screened_count():
    """替身如实报告房间里那个控件写了多少人；控件不存在时是 None。"""
    assert await InMemoryOnlineDrawerDriver(online_count=6).read_online_count() == 6
    assert await InMemoryOnlineDrawerDriver(online_count=None).read_online_count() is None


async def test_production_visible_member_rows_reads_every_rendered_row():
    """整页行一次读回：昵称与关注关系都在适配器里取好，行对象不外泄。"""
    rows = [_StubElement(), _StubElement()]
    alice = _StubElement(text="alice")
    bob = _StubElement(text="bob")
    bob_follow = _StubElement(text="我关注的")
    container = _StubElement()
    finder = _StubFinder(
        screen={"online_users": container},
        children={
            (container, "user_container"): rows,
            (rows[0], "online_user"): alice,
            (rows[0], "follow_state"): _StubElement(text="密友"),
            (rows[1], "online_user"): bob,
            (rows[1], "follow_state"): bob_follow,
        },
    )
    driver = _make_soul_adapter(finder)

    read = await driver.visible_member_rows()

    assert [row.visible_name for row in read] == ["alice", "bob"]
    assert [row.follow_state for row in read] == ["密友", "我关注的"]


async def test_production_visible_member_rows_skips_broken_rows_and_missing_containers():
    """读坏的单行不影响整页（滑动中行会失效是常态）；容器读不到就是空页。"""
    good_row = _StubElement()
    container = _StubElement()
    finder = _StubFinder(
        screen={"online_users": container},
        children={
            (container, "user_container"): [_StubElement(), good_row],
            (good_row, "online_user"): _StubElement(text="小明"),
        },
    )
    driver = _make_soul_adapter(finder)

    read = await driver.visible_member_rows()

    assert [row.visible_name for row in read] == ["小明"]
    assert read[0].follow_state is None
    assert await _make_soul_adapter(_StubFinder(screen={})).visible_member_rows() == []


async def test_in_memory_visible_member_rows_only_returns_the_current_page():
    """替身只给当前窗口的行：翻页是引擎的循环决策，不在读数里偷做。"""
    driver = InMemoryOnlineDrawerDriver(
        members=[("alice", "密友"), ("bob", None), ("cathy", "关注了我")], page_size=2
    )

    assert [row.visible_name for row in await driver.visible_member_rows()] == ["alice", "bob"]
    await driver.scroll_container()
    assert [row.visible_name for row in await driver.visible_member_rows()] == ["cathy"]


async def test_production_is_at_end_requires_the_hint_to_be_displayed():
    """到底提示必须是**已显示**的：元素还留在 dump 里不代表用户看得见它。"""
    shown = _StubElement(text="没有更多了")
    hidden = _StubElement(text="没有更多了", displayed=False)

    assert await _make_soul_adapter(
        _StubFinder(screen={"no_more_data": shown})
    ).is_at_end() is True
    assert await _make_soul_adapter(
        _StubFinder(screen={"no_more_data": hidden})
    ).is_at_end() is False
    assert await _make_soul_adapter(_StubFinder(screen={})).is_at_end() is False


async def test_in_memory_is_at_end_follows_the_end_of_the_list():
    """滑到最后一行之后到底提示才亮；`end_hint=False` 的列表永远不到底。"""
    driver = InMemoryOnlineDrawerDriver(members=["alice", "bob", "cathy"], page_size=2)

    assert await driver.is_at_end() is False
    await driver.scroll_container()
    assert await driver.is_at_end() is True

    never = InMemoryOnlineDrawerDriver(
        members=["alice", "bob", "cathy"], page_size=2, end_hint=False
    )
    await never.scroll_container()
    assert await never.is_at_end() is False



# ---------------------------------------------------------------------------
# #435 追加的资料卡与私聊原语：手势必须与旧 UserManager 的裸调用逐字一致
# ---------------------------------------------------------------------------


def _screen_with_card(card_present=True):
    """一张已经打开的资料卡：抽屉行、卡片昵称、卡片头像与 ivClose 都在屏上。"""
    container = _StubElement()
    row = _StubElement()
    screen = {"online_users": container, "online_users_close": _StubElement()}
    children = {
        (container, "user_container"): [row],
        (row, "online_user"): _StubElement(text="链子"),
    }
    if card_present:
        screen["sender_nickname"] = _StubElement(text="链子")
        screen["sender_avatar"] = _StubElement()
    finder = _StubFinder(screen=screen, children=children)
    return finder, row, container


async def test_production_open_member_profile_clicks_the_row_and_waits_for_the_card():
    """「找行 + 点行」是一次手势：点完必须等到卡片真的出现才算开。

    不等的话，紧接着读到的还是抽屉那一帧，调用方会把「卡片没弹出来」当成正常继续，
    于是后面每一步都点在错误的页面上。
    """
    finder, row, _container = _screen_with_card(card_present=False)
    finder.screen["sender_nickname"] = _StubElement(text="链子")
    driver = _make_soul_adapter(finder)

    assert await driver.open_member_profile("链子") is True
    assert row.clicked is True
    assert "sender_nickname" in finder.looked_up, "点了之后要等卡片出现"


async def test_production_open_member_profile_reports_failure_when_the_card_never_appears():
    """点了却没弹出卡片：如实返回 False，调用方据此走自己的失败路径。"""
    finder, row, _container = _screen_with_card(card_present=False)
    driver = _make_soul_adapter(finder)

    assert await driver.open_member_profile("链子") is False
    assert row.clicked is True


async def test_production_open_member_profile_reports_failure_when_the_row_is_absent():
    """这一行压根没渲染出来：不点任何东西，直接 False（翻页是调用方的循环决策）。"""
    finder, row, _container = _screen_with_card()
    driver = _make_soul_adapter(finder)

    assert await driver.open_member_profile("查无此人") is False
    assert row.clicked is False


async def test_production_profile_card_presence_is_judged_by_its_own_nickname():
    """卡片在不在看它自己的昵称元素：送礼物/管理邀请这类按钮对某些账号不渲染，
    拿一个可能缺席的按钮当标志会把「已经收好」误判成「还悬着」。"""
    shown = _screen_with_card()[0]
    assert await _make_soul_adapter(shown).is_profile_card_open() is True

    hidden = _StubFinder(screen={"sender_nickname": _StubElement(displayed=False)})
    assert await _make_soul_adapter(hidden).is_profile_card_open() is False
    assert await _make_soul_adapter(_StubFinder(screen={})).is_profile_card_open() is False


async def test_production_dismiss_profile_card_clicks_iv_close_and_never_presses_back():
    """收起卡片 = 点它与抽屉共用的 ivClose；`key_actions` 就在旁边也不会被碰。"""
    finder, _row, _container = _screen_with_card()
    close_btn = finder.screen["online_users_close"]
    gesture = _StubGesture()
    driver = _make_soul_adapter(finder, gesture)

    assert await driver.dismiss_profile_card() is True
    assert gesture.clicks == [(close_btn, 0.5)], "点的是 ivClose，不是别的东西"
    assert "sender_nickname" not in finder.screen, "卡片要真的不在了才算收好"


async def test_production_dismiss_profile_card_is_idempotent_when_no_card_is_out():
    """卡片本来就没开着就是幂等的：「已经在房间里」和「收好了」是同一件事。"""
    finder, _row, _container = _screen_with_card(card_present=False)
    gesture = _StubGesture()
    driver = _make_soul_adapter(finder, gesture)

    assert await driver.dismiss_profile_card() is True
    assert gesture.clicks == [], "没有卡片就不该有任何点击"


async def test_production_dismiss_profile_card_reports_false_when_the_card_will_not_go():
    """关闭按钮点得到、点了卡片还在：返回 False，让调用方记警告。

    这里同样没有第二条兜底手势 —— 绝不拿派对房间去赌一次 press_back。
    """
    finder, _row, _container = _screen_with_card()
    finder.screen.pop("online_users_close")
    finder.screen["close_button"] = _StubElement()  # 点得到，但卡片赖着不走
    finder.elements_stay = True
    driver = _make_soul_adapter(finder)

    assert await driver.dismiss_profile_card() is False


async def test_production_dismiss_profile_card_reports_false_when_no_close_button_exists():
    """两个关闭按钮都没渲染出来：如实 False。"""
    finder, _row, _container = _screen_with_card()
    finder.screen.pop("online_users_close")
    driver = _make_soul_adapter(finder)

    assert await driver.dismiss_profile_card() is False


async def test_production_open_member_home_clicks_the_card_avatar_at_the_kept_ratio():
    """点头像进主页，纵向比例仍是旧实现真机调出来的 0.7，不顺手改成正中。"""
    finder, _row, _container = _screen_with_card()
    gesture = _StubGesture()
    avatar = finder.screen["sender_avatar"]
    driver = _make_soul_adapter(finder, gesture)

    assert await driver.open_member_home() is True
    assert gesture.clicks == [(avatar, 0.7)]


async def test_production_open_member_home_reports_failure_when_the_avatar_is_absent():
    """头像读不到：返回 False，调用方负责回房间。"""
    finder, _row, _container = _screen_with_card()
    del finder.screen["sender_avatar"]
    driver = _make_soul_adapter(finder)

    assert await driver.open_member_home() is False


async def test_production_private_chat_steps_use_their_own_element_keys():
    """私聊三步各按各的 key：主页私聊按钮 -> 输入框 -> 发送按钮。"""
    chat_btn = _StubElement()
    input_box = _StubElement()
    send_btn = _StubElement()
    finder = _StubFinder(
        screen={
            "private_chat_button": chat_btn,
            "private_message_input": input_box,
            "private_message_send": send_btn,
        }
    )
    driver = _make_soul_adapter(finder)

    assert await driver.open_private_chat_page() is True
    assert await driver.type_private_message("你好") is True
    assert await driver.submit_private_message() is True

    assert chat_btn.clicked is True
    assert input_box.typed == ["你好"]
    assert send_btn.clicked is True


async def test_production_private_chat_steps_report_false_when_a_key_is_missing():
    """输入框与发送按钮是两件事：少哪一个就各自失败，调用方给它们不同的报错文案。"""
    driver = _make_soul_adapter(_StubFinder(screen={}))

    assert await driver.open_private_chat_page() is False
    assert await driver.type_private_message("你好") is False
    assert await driver.submit_private_message() is False


async def test_production_return_to_room_uses_the_first_entry_that_appears():
    """回房间只点页面上指得出来的入口；私聊页那个动画按钮优先级最高。"""
    entry = _StubElement()
    finder = _StubFinder(any_element=("private_room_entry", entry))
    driver = _make_soul_adapter(finder)

    assert await driver.return_to_room() is True
    assert entry.clicked is True


async def test_production_return_to_room_adds_the_titlebar_back_after_item_left_back():
    """个性主页左上角的返回点完只退掉主页这一层，还要再点一次标题栏返回。"""
    left_back = _StubElement()
    titlebar_back = _StubElement()
    finder = _StubFinder(
        screen={"titlebar_back_ivbtn": titlebar_back},
        any_element=("item_left_back", left_back),
    )
    driver = _make_soul_adapter(finder)

    assert await driver.return_to_room() is True
    assert left_back.clicked is True
    assert titlebar_back.clicked is True


async def test_production_return_to_room_reports_false_when_the_titlebar_back_is_missing():
    """点了主页返回却等不到标题栏返回：如实 False，让调用方记警告。"""
    finder = _StubFinder(any_element=("item_left_back", _StubElement()))
    driver = _make_soul_adapter(finder)

    assert await driver.return_to_room() is False


async def test_production_return_to_room_reports_false_when_no_entry_appears():
    """三个入口都读不到：不换成盲按返回，如实 False。"""
    driver = _make_soul_adapter(_StubFinder(any_element=(None, None)))

    assert await driver.return_to_room() is False


# ---------------------------------------------------------------------------
# 交接（#435）：资料页流程把抽屉连同资料卡交给调用方
# ---------------------------------------------------------------------------


async def test_handover_keeps_the_drawer_open_only_after_release():
    """release() 之后抽屉留在屏上：资料页流程的产物就是那张卡片。

    卡片与抽屉共用 ivClose，这时收尾等于把刚交出去的东西拆掉。
    """
    journal = []
    driver = InMemoryOnlineDrawerDriver(members=["小明"], journal=journal)
    manager = _make_manager(driver)
    handover = Handover()

    async with manager.drawer_session(reason="user:open_profile", handover=handover) as open_error:
        assert open_error is None
        await driver.open_member_profile("小明")
        handover.release()

    assert journal == ["drawer:open", "drawer:settle", "card:open:小明"]
    assert driver.drawer_open is True
    assert driver.card_open is True


async def test_session_still_closes_when_the_body_returns_early_without_releasing():
    """没 release 就中途 return：照常收尾。

    这正是「交接不能用布尔开关」的道理 —— 开关只能整段会话生效，失败路径会被一起
    跳过收尾，把抽屉悬在屏幕上。
    """
    driver = InMemoryOnlineDrawerDriver(members=["小明"])
    manager = _make_manager(driver)
    handover = Handover()

    async with manager.drawer_session(reason="user:open_profile", handover=handover):
        return {"error": "User not found in online users list"}

    assert handover.released is False
    assert driver.drawer_open is False


async def test_session_closes_a_released_drawer_when_the_body_raises():
    """release() 之后正文抛异常：照样收尾。交接只发生在成功路径上。"""
    driver = InMemoryOnlineDrawerDriver(members=["小明"])
    manager = _make_manager(driver)
    handover = Handover()

    with pytest.raises(RuntimeError, match="正文炸了"):
        async with manager.drawer_session(reason="user:open_profile", handover=handover):
            handover.release()
            raise RuntimeError("正文炸了")

    assert driver.drawer_open is False


async def test_handover_is_optional_and_defaults_to_the_original_behaviour():
    """不传 Handover 就是本模块的原始行为：退出即收尾。"""
    driver = InMemoryOnlineDrawerDriver(members=["小明"])
    manager = _make_manager(driver)

    async with manager.drawer_session(reason="user:legacy"):
        pass

    assert driver.drawer_open is False


async def test_settle_failure_can_report_the_callers_own_wording():
    """落定失败与打不开失败在调用方面前是两句话，别被统一入口改成同一句。"""
    driver = InMemoryOnlineDrawerDriver(members=["小明"], settle_fails=True)
    manager = _make_manager(driver)

    async with manager.drawer_session(
        reason="user:open_profile",
        error_message="Failed to open online users list",
        settle_error_message="Failed to find online users container",
    ) as open_error:
        assert open_error == {"error": "Failed to find online users container"}

    assert driver.drawer_open is False


async def test_close_profile_card_dismisses_the_card_that_is_out():
    """交接的另一半：把悬着的卡片收回房间。"""
    journal = []
    driver = InMemoryOnlineDrawerDriver(members=["小明"], journal=journal)
    manager = _make_manager(driver)
    handover = Handover()

    async with manager.drawer_session(reason="user:open_profile", handover=handover) as open_error:
        assert open_error is None
        await driver.open_member_profile("小明")
        handover.release()

    assert driver.card_open is True, "卡片已经交给调用方了"

    await manager.close_profile_card()

    assert driver.card_open is False
    assert driver.drawer_open is False
    assert "card:dismiss" in journal


async def test_close_profile_card_does_nothing_when_no_card_is_out():
    """没有卡片悬着：不夺归属、不去关一个本来就没打开的抽屉。"""
    driver = InMemoryOnlineDrawerDriver(members=["小明"])
    manager = _make_manager(driver)

    await manager.close_profile_card()

    assert driver.close_calls == 0
    assert driver.drawer_open is False


async def test_close_profile_card_logs_and_swallows_a_card_that_will_not_close(caplog):
    """关不掉卡片：记警告、保持原状，绝不把异常抛给调用方，也绝不盲按返回。"""
    driver = InMemoryOnlineDrawerDriver(members=["小明"], dismiss_fails=True)
    manager = _make_manager(driver)
    await driver.open(error_message="打不开")
    await driver.open_member_profile("小明")

    with caplog.at_level(logging.WARNING):
        await manager.close_profile_card()

    assert any("未能通过 ivClose 收起资料卡" in r.message for r in caplog.records)
    assert driver.card_open is True


async def test_profile_and_chat_steps_never_emit_a_back_press():
    """资料卡与私聊的每一步都在事件流里排着队，里面不该出现一次盲按返回。"""
    journal = []
    driver = InMemoryOnlineDrawerDriver(members=["小明"], journal=journal)
    manager = _make_manager(driver)

    async with manager.drawer_session(reason="user:private_message", handover=Handover()) as err:
        assert err is None
        await driver.open_member_profile("小明")
        await driver.open_member_home()
        await driver.open_private_chat_page()
        await driver.type_private_message("你好")
        await driver.submit_private_message()
        await driver.return_to_room()

    assert not any("back" in event for event in journal), journal


# ---------------------------------------------------------------------------
# 生产适配器：送礼那几步（#438）
# ---------------------------------------------------------------------------


async def test_production_open_gift_entry_clicks_the_send_gift_control():
    """进送礼弹窗就一个手势：点资料卡上的「送礼物」。"""
    entry = _StubElement()
    finder = _StubFinder(screen={"send_gift": entry})
    gesture = _StubGesture()
    driver = _make_soul_adapter(finder, gesture)

    assert await driver.open_gift_entry() is True
    assert finder.looked_up == ["send_gift"]
    assert [element for element, _ratio in gesture.clicks] == [entry]


async def test_production_open_gift_entry_reports_false_when_the_entry_is_absent():
    """资料卡没有渲染这个入口：返回 False，调用方给「未找到送礼物入口」。"""
    driver = _make_soul_adapter(_StubFinder(screen={}))

    assert await driver.open_gift_entry() is False


@pytest.mark.parametrize(
    "key, expected",
    [("give_gift", "give_gift"), ("use_item", "use_item")],
)
async def test_production_gift_popup_action_reports_which_button_is_up(key, expected):
    """弹窗是否起来与起来的是哪一个，都由 `wait_for_any_element` 那一对 key 回答。"""
    finder = _StubFinder(any_element=(key, _StubElement()))
    driver = _make_soul_adapter(finder)

    assert await driver.gift_popup_action() == expected


async def test_production_gift_popup_action_is_none_when_the_popup_never_shows():
    """两个动作按钮都没出现 = 弹窗没起来，如实 None，绝不换成盲按返回。"""
    driver = _make_soul_adapter(_StubFinder(any_element=(None, None)))

    assert await driver.gift_popup_action() is None


async def test_production_read_gift_item_name_strips_the_count_suffix():
    """`高级福袋x2` 读回来是 `高级福袋`：件数不该出现在「XX 送你啦」里。"""
    finder = _StubFinder(screen={"luck_item": _StubElement(text="高级福袋x2")})
    driver = _make_soul_adapter(finder)

    assert await driver.read_gift_item_name() == "高级福袋"


async def test_production_read_gift_item_name_keeps_a_name_without_a_count():
    """没有件数后缀的名字原样返回，不为了「拆一下」而改写文案。"""
    finder = _StubFinder(screen={"luck_item": _StubElement(text="小黄鸭")})
    driver = _make_soul_adapter(finder)

    assert await driver.read_gift_item_name() == "小黄鸭"


async def test_production_read_gift_item_name_is_none_when_the_control_is_absent():
    """读不到选中礼物：None，调用方走「Failed to find gift」并负责收尾。"""
    driver = _make_soul_adapter(_StubFinder(screen={}))

    assert await driver.read_gift_item_name() is None


async def test_production_read_gift_soul_power_is_none_but_does_not_raise_when_absent():
    """灵魂力只是日志里的一行读数，读不到不该让一次送礼失败。"""
    driver = _make_soul_adapter(_StubFinder(screen={}))

    assert await driver.read_gift_soul_power() is None

    finder = _StubFinder(screen={"soul_power": _StubElement(text="+12灵魂力")})
    assert await _make_soul_adapter(finder).read_gift_soul_power() == "+12灵魂力"


async def test_production_click_gift_item_and_action_use_their_own_keys():
    """小黄鸭点礼物本身，动作按钮点赠送/使用：三个手势各按各的 key。"""
    item = _StubElement()
    give = _StubElement()
    finder = _StubFinder(
        screen={"luck_item": item, "give_gift": give}, any_element=("give_gift", give)
    )
    gesture = _StubGesture()
    driver = _make_soul_adapter(finder, gesture)

    assert await driver.click_gift_item() is True
    assert await driver.click_gift_action() is True
    assert [element for element, _ratio in gesture.clicks] == [item, give]
    assert [key for key in finder.looked_up if key in ("luck_item", "give_gift")] == [
        "luck_item",
        "give_gift",
    ]


async def test_production_confirm_gift_use_clicks_the_confirm_control():
    """点完「使用」那道确认框要等出来再点：确认按钮是弹出来的，不是常驻的。"""
    confirm = _StubElement()
    finder = _StubFinder(screen={"confirm_use": confirm})
    driver = _make_soul_adapter(finder)

    assert await driver.confirm_gift_use() is True
    assert confirm.clicked is True
    assert finder.looked_up == ["confirm_use"]


async def test_production_confirm_gift_use_reports_false_when_it_never_shows():
    """确认框等不到：False，调用方收干净并给「未找到确认使用按钮」。"""
    driver = _make_soul_adapter(_StubFinder(screen={}))

    assert await driver.confirm_gift_use() is False


async def test_production_dismiss_gift_popup_clicks_an_in_page_close_and_never_presses_back():
    """收弹窗走页内 X，`_ExplodingKeyActions` 会在任何一次盲按返回上当场失败。"""
    close_btn = _StubElement()
    finder = _StubFinder(
        screen={"close_button_1": close_btn, "give_gift": _StubElement()},
    )
    gesture = _StubGesture()
    driver = _make_soul_adapter(finder, gesture)

    assert await driver.dismiss_gift_popup() is True
    assert [element for element, _ratio in gesture.clicks] == [close_btn]


async def test_production_dismiss_gift_popup_falls_back_to_the_second_close_key():
    """第一个 X 点不到就试第二个，按顺序试完为止。"""
    close_btn = _StubElement()
    finder = _StubFinder(
        screen={"close_button": close_btn, "use_item": _StubElement()}
    )
    gesture = _StubGesture()
    driver = _make_soul_adapter(finder, gesture)

    assert await driver.dismiss_gift_popup() is True
    assert [element for element, _ratio in gesture.clicks] == [close_btn]


async def test_production_dismiss_gift_popup_is_idempotent_when_no_popup_is_out():
    """弹窗本来就没开着：幂等 True，调用方不必先问一遍。"""
    driver = _make_soul_adapter(_StubFinder(screen={}))

    assert await driver.dismiss_gift_popup() is True


async def test_production_dismiss_gift_popup_reports_false_when_the_popup_stays_out():
    """两个 X 都点掉、弹窗还在：如实 False 让调用方记警告，保持原状等下一轮恢复。"""
    finder = _StubFinder(screen={"give_gift": _StubElement()}, elements_stay=True)
    driver = _make_soul_adapter(finder)

    assert await driver.dismiss_gift_popup() is False


async def test_gift_steps_never_emit_a_back_press_in_the_production_adapter():
    """生产适配器把整条送礼链路走一遍，`key_actions` 里那个会炸的 press_back 一次都不该被叫。"""
    item = _StubElement()
    give = _StubElement()
    close_btn = _StubElement()
    finder = _StubFinder(
        screen={
            "send_gift": item,
            "luck_item": _StubElement(text="小黄鸭x1"),
            "give_gift": give,
            "close_button_1": close_btn,
        },
        any_element=("give_gift", give),
    )
    driver = _make_soul_adapter(finder)

    await driver.open_gift_entry()
    assert await driver.gift_popup_action() == "give_gift"
    assert await driver.read_gift_item_name() == "小黄鸭"
    await driver.click_gift_item()
    await driver.dismiss_gift_popup()
