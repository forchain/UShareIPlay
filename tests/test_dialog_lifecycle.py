"""房间信息抽屉的生命周期契约（#374 / #375 / #376 / #377）。

这些用例断言的是「结束时界面干净、没有误退」这类结果，而不是某一次
`press_back()` 的调用次数 —— 后者只锁死了旧实现里的硬编码退层数，
少退一层照样绿。
"""

import asyncio
from contextlib import contextmanager

import pytest

from tests.fake_ui import FakeElement, FakeScreen, bind_room_info_window, make_handler
from ushareiplay.core.app_controller import AppController
from ushareiplay.managers.command_manager import CommandManager
from ushareiplay.managers.notice_manager import NoticeManager
from ushareiplay.managers.room_info_window import RoomInfoWindow
from ushareiplay.managers.room_name_manager import RoomNameManager
from ushareiplay.managers.user_manager import UserManager


# --------------------------------------------------------------------------
# 房间信息抽屉的层栈模型
# --------------------------------------------------------------------------

# 层名与元素 key 分开：层名只表示「现在开着哪一层」，
# 元素 key 的可见性由 conditional 单独控制。
NOTICE_MODAL = "notice_modal_layer"   # 公告二级模态弹窗
NOTICE_INPUT = "notice_input_layer"   # 公告自定义输入层
TITLE_INPUT = "title_edit_layer"      # 标题编辑层
TYPE_DIALOG = "party_type_dialog_layer"  # 房间类型选项弹窗


def _open_drawer(_entry_key=None):
    """点开房间信息抽屉：抽屉内才看得到编辑入口、公告入口与类型入口。"""
    _CURRENT_SCREEN.open("slide_drawer")


def _room_name_elements():
    """主界面上始终存在的元素。"""
    return {
        "chat_room_title": FakeElement("chat_room_title", text="助眠｜晚安"),
    }


def _visible_only_when(*layers):
    """只有这些层在场时，该元素才存在（原型自己带点击副作用）。"""
    def _predicate(screen):
        return bool(set(layers) & screen.open_keys)

    return _predicate


def _cond(key, predicate, **kwargs):
    return (predicate, FakeElement(key, **kwargs))


_IN_DRAWER = _visible_only_when("slide_drawer")


def _room_name_conditional():
    """抽屉内/编辑层内的元素：对应弹窗没开就不存在。"""
    in_title_input = _visible_only_when(TITLE_INPUT)
    in_type_dialog = _visible_only_when(TYPE_DIALOG)

    return {
        # 抽屉内的编辑入口
        "title_edit_entry": _cond(
            "title_edit_entry", _IN_DRAWER, on_click=lambda: _CURRENT_SCREEN.open(TITLE_INPUT)
        ),
        "edit_notice_entry": _cond(
            "edit_notice_entry", _IN_DRAWER, on_click=lambda: _CURRENT_SCREEN.open(NOTICE_MODAL)
        ),
        "party_room_type_option": _cond(
            "party_room_type_option",
            _IN_DRAWER,
            text="闲聊唠嗑",
            on_click=lambda: _CURRENT_SCREEN.open(TYPE_DIALOG),
        ),
        # 标题编辑层里才有输入框与确认键
        "title_edit_input": _cond("title_edit_input", in_title_input),
        "title_edit_confirm": _cond(
            "title_edit_confirm", in_title_input, on_click=_title_confirm_click
        ),
        # 类型选项弹窗里才有目标类型按钮
        "party_type_singing": _cond("party_type_singing", in_type_dialog),
        "party_type_chat": _cond("party_type_chat", in_type_dialog),
        # 抽屉里的房名（抽屉开着才可见）
        "room_name_in_dialog": _cond(
            "room_name_in_dialog", _IN_DRAWER, text="抽屉里的房名"
        ),
    }


_CURRENT_SCREEN = None


@pytest.fixture
def screen():
    global _CURRENT_SCREEN
    s = FakeScreen()
    _CURRENT_SCREEN = s
    yield s
    _CURRENT_SCREEN = None


def _room_name_handler(screen, **kwargs):
    handler = make_handler(
        screen,
        elements=_room_name_elements(),
        conditional=_room_name_conditional(),
        on_open=_open_drawer,
        **kwargs,
    )
    bind_room_info_window(handler)
    return handler


def _title_confirm_click():
    _CURRENT_SCREEN.close(TITLE_INPUT)


# --------------------------------------------------------------------------
# #374 房名读取：抽屉没开时不做超时等待
# --------------------------------------------------------------------------

def _room_name_manager(screen):
    manager = RoomNameManager.initialize()
    manager._handler = _room_name_handler(screen)
    manager._logger = manager._handler.logger
    return manager


def test_room_title_read_does_not_wait_on_the_dialog_when_it_is_closed(screen):
    """抽屉没开时直接读主界面房名，绝不去等 room_name_in_dialog。"""
    manager = _room_name_manager(screen)
    finder = manager._handler.element_finder

    assert manager.get_room_title_text_from_ui() == "助眠｜晚安"
    # 超时等待一旦发生，ElementFinder 就会记一条 not found 警告
    assert "room_name_in_dialog" not in finder.waited
    assert finder.waited == []
    assert not manager._handler.logger.mentions("not found")


def test_room_title_read_prefers_the_open_dialog_without_waiting(screen):
    """抽屉开着时非阻塞地读弹窗内房名。"""
    manager = _room_name_manager(screen)
    screen.open("slide_drawer")
    finder = manager._handler.element_finder

    assert manager.get_room_title_text_from_ui() == "抽屉里的房名"
    assert finder.waited == []


# --------------------------------------------------------------------------
# #374 房名更新：任何退出路径都要关抽屉
# --------------------------------------------------------------------------

def _prepare_title_update(screen, **finder_overrides):
    manager = _room_name_manager(screen)
    manager.next_title = "新标题"
    finder = manager._handler.element_finder
    for name, value in finder_overrides.items():
        setattr(finder, name, value)
    return manager, finder


def test_title_update_closes_the_drawer_after_a_successful_write(screen):
    manager, finder = _prepare_title_update(screen)
    finder.wait_for_any_element = lambda keys, timeout=10: ("title_edit_entry", object())

    result = manager.process_pending_update()

    assert result["ui_updated"] is True
    assert screen.is_clean(), f"抽屉没关: {screen.layers}"
    assert screen.stray_backs == 0


def test_title_update_closes_the_drawer_when_the_cooldown_blocks_the_write(screen):
    manager, finder = _prepare_title_update(screen)
    finder.wait_for_any_element = lambda keys, timeout=10: ("title_edit_confirm", object())

    result = manager.process_pending_update()

    assert "error" in result
    assert screen.is_clean(), f"冷却分支残留了抽屉: {screen.layers}"
    assert screen.stray_backs == 0


def test_title_update_closes_the_drawer_when_an_interaction_raises(screen):
    manager, finder = _prepare_title_update(screen)

    def _boom(keys, timeout=10):
        raise RuntimeError("driver died mid-flow")

    finder.wait_for_any_element = _boom

    result = manager.process_pending_update()

    assert "error" in result
    assert screen.is_clean(), f"异常分支残留了抽屉: {screen.layers}"
    assert screen.stray_backs == 0


def test_title_update_closes_the_drawer_when_the_edit_entry_is_missing(screen):
    manager, finder = _prepare_title_update(screen)
    base_try = finder.try_find_element
    finder.try_find_element = lambda key, log=False, clickable=False: (
        None if key == "title_edit_entry" else base_try(key, log=log, clickable=clickable)
    )

    result = manager.process_pending_update()

    assert "error" in result
    assert screen.is_clean(), f"找不到编辑入口时残留了抽屉: {screen.layers}"


# --------------------------------------------------------------------------
# #375 公告：二级模态弹窗按逆序清理
# --------------------------------------------------------------------------

def _notice_manager(screen):
    manager = NoticeManager.initialize()
    manager._handler = _room_name_handler(screen)
    manager._logger = manager._handler.logger
    return manager


def _notice_conditional():
    base = _room_name_conditional()
    in_modal = _visible_only_when(NOTICE_MODAL)
    in_input = _visible_only_when(NOTICE_INPUT)
    base.update({
        # 公告二级模态弹窗里才有「关闭公告」与自定义入口
        "close_notice": _cond("close_notice", in_modal, on_click=lambda: _CURRENT_SCREEN.close(NOTICE_MODAL)),
        "customize_notice_button": _cond(
            "customize_notice_button", in_modal, on_click=lambda: _CURRENT_SCREEN.open(NOTICE_INPUT)
        ),
        "modify_notice_button": _cond(
            "modify_notice_button", in_modal, on_click=lambda: _CURRENT_SCREEN.open(NOTICE_INPUT)
        ),
        # 自定义入口点了之后才有输入层
        "edit_notice_input": _cond("edit_notice_input", in_input),
        "edit_notice_confirm": _cond(
            "edit_notice_confirm", in_input, on_click=lambda: _CURRENT_SCREEN.close(NOTICE_INPUT)
        ),
    })
    return base


def _notice_manager_ready(screen):
    manager = NoticeManager.initialize()
    handler = make_handler(
        screen,
        elements=_room_name_elements(),
        conditional=_notice_conditional(),
        on_open=_open_drawer,
    )
    bind_room_info_window(handler)
    manager._handler = handler
    manager._logger = handler.logger
    return manager


def test_notice_write_closes_the_modal_and_the_drawer_on_success(screen):
    manager = _notice_manager_ready(screen)

    result = manager._set_notice_immediate("新公告")

    assert "success" in result
    assert screen.is_clean(), f"公告流程残留了弹窗: {screen.layers}"
    assert screen.stray_backs == 0


@pytest.mark.parametrize(
    "missing_keys, expected",
    [
        # 自定义/修改两个入口是同一个按钮的两种文案，缺一个不算缺
        (("customize_notice_button", "modify_notice_button"), "Failed to find customize notice button"),
        (("edit_notice_input",), "Failed to find notice input"),
        (("edit_notice_confirm",), "Failed to find confirm button"),
    ],
)
def test_notice_write_unwinds_every_layer_when_a_step_is_missing(screen, missing_keys, expected):
    """找不到自定义按钮/输入框/确认按钮时，公告模态与抽屉都要退干净。"""
    manager = _notice_manager_ready(screen)
    base_try = manager._handler.element_finder.try_find_element
    manager._handler.element_finder.try_find_element = lambda key, log=False, clickable=False: (
        None if key in missing_keys else base_try(key, log=log, clickable=clickable)
    )

    result = manager._set_notice_immediate("新公告")

    assert result == {"error": expected}
    assert screen.is_clean(), f"{missing_keys} 缺失时残留了弹窗: {screen.layers}"
    assert screen.stray_backs == 0


def test_notice_write_unwinds_when_an_interaction_raises(screen):
    manager = _notice_manager_ready(screen)

    def _boom(keys, timeout=10):
        raise RuntimeError("driver died mid-flow")

    manager._handler.element_finder.wait_for_any_element = _boom

    result = manager._set_notice_immediate("新公告")

    assert "error" in result
    assert screen.is_clean(), f"异常分支残留了弹窗: {screen.layers}"


def test_passive_notice_correction_closes_the_modal_but_leaves_the_drawer_to_its_caller(screen):
    """被动纠偏只收自己拉起的模态弹窗；外层抽屉归 audit_and_repair 关。"""
    manager = _notice_manager_ready(screen)
    screen.open("slide_drawer")
    manager._handler.config = {"soul": {"system_default_notices": ["蹲一个人"]}}
    notice_text = FakeElement("chat_room_notice", screen, text="蹲一个人")

    base_try = manager._handler.element_finder.try_find_element
    manager._handler.element_finder.try_find_element = lambda key, log=False, clickable=False: (
        notice_text if key == "chat_room_notice" else base_try(key, log=log, clickable=clickable)
    )
    base_try_el = manager._handler.element_finder.wait_for_any_element
    manager._handler.element_finder.wait_for_any_element = lambda keys, timeout=10: (
        ("customize_notice_button", FakeElement("customize_notice_button"))
        if any(k in keys for k in ("customize_notice_button", "modify_notice_button"))
        else base_try_el(keys, timeout=timeout)
    )

    result = manager.sync_and_correct_notice_if_dialog_open()

    # 输入层缺失 -> 报错；模态弹窗与输入层都必须退掉
    assert "error" in result
    assert NOTICE_MODAL not in screen.open_keys, "公告二级模态弹窗没退掉"
    assert NOTICE_INPUT not in screen.open_keys
    assert "slide_drawer" in screen.open_keys, "外层抽屉不该由被动纠偏关闭"


# --------------------------------------------------------------------------
# #376 送礼：三层蒙层在所有错误分支都要收掉
# --------------------------------------------------------------------------

ONLINE_DRAWER = "online_drawer"     # 在线用户抽屉
USER_PROFILE = "user_profile"       # 用户资料页
GIFT_PANEL = "gift_panel"           # 礼物面板
CONFIRM_USE = "confirm_use_layer"   # 「确认使用」二次确认


def _gift_manager(screen, *, missing=(), raise_on=False):
    """在线抽屉 -> 资料页 -> 礼物面板三层栈。"""
    def _open_profile():
        screen.open(ONLINE_DRAWER)
        screen.open(USER_PROFILE)

    elements = {
        # 在线列表：点人数进入抽屉
        "user_count": FakeElement("user_count", on_click=_open_profile),
        "online_users": FakeElement("online_users"),
    }
    conditional = {
        # 资料页里才有「送礼物」入口与关注状态；点了送礼物才弹出礼物面板
        "send_gift": _cond(
            "send_gift", _visible_only_when(USER_PROFILE), on_click=lambda: screen.open(GIFT_PANEL)
        ),
        "follow_status": _cond("follow_status", _visible_only_when(USER_PROFILE)),
        # 礼物面板里才有赠送/使用按钮、背包与礼物
        "give_gift": _cond("give_gift", _visible_only_when(GIFT_PANEL)),
        "use_item": _cond(
            "use_item", _visible_only_when(GIFT_PANEL),
            on_click=lambda: screen.open(CONFIRM_USE),
        ),
        "luck_item": _cond("luck_item", _visible_only_when(GIFT_PANEL), text="初级福袋x1"),
        "soul_power": _cond("soul_power", _visible_only_when(GIFT_PANEL), text="+12灵魂力"),
        "confirm_use": _cond("confirm_use", _visible_only_when(CONFIRM_USE)),
    }
    if missing:
        for key in missing:
            elements.pop(key, None)
            conditional.pop(key, None)

    class _Gestures:
        @staticmethod
        def click_element_at(element, *a, **k):
            # 坐标点击同样会把目标弹窗点出来
            element.click()
            return True

        @staticmethod
        def scroll_container_until_element(key, *_a, **_k):
            return key, FakeElement(key), FakeElement(key)

    handler = make_handler(screen, elements=elements, conditional=conditional)
    handler.gesture_handler = _Gestures()

    closed = []

    class _Recovery:
        @staticmethod
        def close_drawer(drawer_key, **_kw):
            closed.append(drawer_key)
            screen.close(ONLINE_DRAWER)
            return True

    handler.controller = type("C", (), {"recovery_manager": _Recovery()})()
    handler.closed_drawers = closed

    if raise_on:
        def _boom(*_a, **_k):
            raise RuntimeError("driver died mid-flow")
        handler.element_finder.wait_for_element_clickable = _boom

    manager = UserManager.initialize()
    manager._handler = handler
    manager._logger = handler.logger
    return manager, handler


@pytest.mark.parametrize(
    "missing_keys",
    [
        ("send_gift",),
        # 赠送/使用是礼物面板的两个按钮，缺一个不算面板没出现
        ("give_gift", "use_item"),
        ("luck_item",),
        # 走「使用」分支但确认按钮没渲染
        ("give_gift", "confirm_use"),
    ],
)
def test_gift_flow_closes_every_overlay_on_error_branches(screen, missing_keys):
    manager, handler = _gift_manager(screen, missing=missing_keys)

    result = manager.send_gift("Alice")

    assert "error" in result
    assert screen.is_clean(), f"{missing_keys} 缺失时残留了蒙层: {screen.layers}"
    assert handler.closed_drawers == ["online_drawer"], "在线抽屉必须被显式关掉"


def test_gift_flow_closes_every_overlay_when_the_flow_raises(screen):
    manager, handler = _gift_manager(screen, raise_on=True)

    result = manager.send_gift("Alice")

    assert "error" in result
    assert screen.is_clean(), f"异常分支残留了蒙层: {screen.layers}"
    assert handler.closed_drawers == ["online_drawer"]


def test_gift_flow_closes_the_gift_panel_after_a_successful_send(screen):
    manager, handler = _gift_manager(screen)

    result = manager.send_gift("Alice")

    assert "success" in result
    assert screen.is_clean(), f"送礼成功后残留了蒙层: {screen.layers}"


# --------------------------------------------------------------------------
# #376 房间类型切换：选项弹窗必须关掉
# --------------------------------------------------------------------------

def _party_manager(screen):
    from ushareiplay.managers.party_manager import PartyManager

    handler = _room_name_handler(
        screen,
        config={"target_party_type_element": "party_type_singing"},
    )

    manager = PartyManager.instance()
    manager._handler = handler
    manager._logger = handler.logger
    return manager, handler


def test_room_type_switch_closes_the_option_dialog_when_the_target_is_missing(screen):
    manager, handler = _party_manager(screen)
    screen.open("slide_drawer")
    handler.config["target_party_type_element"] = "party_type_missing"

    result = manager.check_and_correct_room_type(auto_close=False)

    assert "error" in result
    assert "party_type_singing" not in screen.open_keys, "类型选项弹窗没退掉"
    assert "slide_drawer" in screen.open_keys, "auto_close=False 时抽屉归外层"


def test_room_type_switch_closes_the_option_dialog_on_success(screen):
    manager, handler = _party_manager(screen)
    screen.open("slide_drawer")

    result = manager.check_and_correct_room_type(auto_close=False)

    assert result == {"success": True, "switched": True}
    assert "party_type_singing" not in screen.open_keys, "类型选项弹窗没退掉"


# --------------------------------------------------------------------------
# #377 前置自愈 + UI 独占会话
# --------------------------------------------------------------------------

def _window_on(screen):
    handler = _room_name_handler(screen)
    return RoomInfoWindow.instance(), handler


def test_self_heal_clears_a_drawer_left_behind_by_the_previous_round(screen):
    window, _handler = _window_on(screen)
    screen.open("slide_drawer")

    result = window.heal_stale_overlays()

    assert screen.is_clean(), f"残留抽屉没被自愈: {screen.layers}"
    assert "room_info_window" in result["healed"]
    assert result["remaining"] == []


def test_self_heal_clears_a_stale_overlay_layer(screen):
    window, _handler = _window_on(screen)
    screen.open("online_drawer")
    screen.open("input_drawer")

    result = window.heal_stale_overlays()

    assert screen.is_clean(), f"残留蒙层没被自愈: {screen.layers}"
    assert set(result["healed"]) == {"online_drawer", "input_drawer"}


def test_self_heal_is_a_noop_on_a_clean_screen(screen):
    """干净界面上自愈必须是零动作 —— 否则会盲按返回把派对房间退掉。"""
    window, _handler = _window_on(screen)

    result = window.heal_stale_overlays()

    assert result == {"healed": [], "remaining": []}
    assert screen.backs == 0
    assert screen.stray_backs == 0


def test_opening_the_window_self_heals_before_touching_the_entry(screen):
    window, handler = _window_on(screen)
    screen.open("input_drawer")  # 上一轮残留

    assert window.ensure_open() is None

    assert "input_drawer" not in screen.open_keys
    assert "slide_drawer" in screen.open_keys, "自愈之后应当真的把抽屉打开"
    assert handler.ui_actions.clicks == ["chat_room_title"]


# --------------------------------------------------------------------------
# #377 周期性后台任务持有 UI 独占会话
# --------------------------------------------------------------------------

class _FakeController:
    """记录 ui_session 的进出，并在会话内报告 ui_lock 忙。"""

    def __init__(self):
        self.entered = []
        self.depth = 0
        self.locked_flag = False

    def locked(self):
        """对照 asyncio.Lock.locked()：供 EventRuntimeContext.is_ui_busy 使用。"""
        return self.locked_flag

    def ui_session(self, reason=""):
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _session():
            self.entered.append(reason)
            self.depth += 1
            self.locked_flag = True
            try:
                yield
            finally:
                self.depth -= 1
                self.locked_flag = self.depth > 0

        return _session()


@contextmanager
def _patched_command_manager(commands):
    """临时把 CommandManager.instance 换成一个只提供 update_commands 的替身。"""
    original = CommandManager.instance
    CommandManager.instance = classmethod(lambda cls: commands)
    try:
        yield
    finally:
        CommandManager.instance = original


class _RealLockController:
    """借用真实的 AppController.ui_session，只把 logger 换成无声的替身。

    锁本身、owner/depth 记录、可重入判定全部是真的 —— 这正是要验证的部分。
    """

    ui_session = AppController.ui_session

    def __init__(self):
        self.ui_lock = asyncio.Lock()
        self._ui_lock_depth = 0
        self._ui_lock_owner = None
        self.logger = None


async def _observe_lock(controller, sink):
    """EventManager 的兜底 back 判断：UI 忙时不得按下返回键。"""
    from ushareiplay.core.runtime_context import EventRuntimeContext

    sink.append(EventRuntimeContext(ui_lock=controller.ui_lock).is_ui_busy())


def test_background_updates_run_inside_an_exclusive_ui_session(screen):
    """周期性房名/公告/话题更新会真实点击，必须整段持 UI 独占锁。"""
    from ushareiplay.core.runtime_context import EventRuntimeContext
    from ushareiplay.events.message_content import MessageContentEvent
    from ushareiplay.managers.command_manager import CommandManager

    controller = _FakeController()
    handler = _room_name_handler(screen)
    handler.controller = controller

    event = MessageContentEvent(handler)
    busy_seen = []

    class _Commands:
        @staticmethod
        def update_commands():
            busy_seen.append(EventRuntimeContext(ui_lock=controller).is_ui_busy())

    with _patched_command_manager(_Commands):
        asyncio.run(event._process_update_logic())

    assert controller.entered == ["periodic:background-updates"]
    # 更新跑到的时候锁是持有的：未知页兜底 back 因此不会掐断弹窗流程
    assert busy_seen == [True]
    assert controller.locked_flag is False, "退出后必须释放锁"


def test_background_updates_hold_the_real_ui_lock_against_a_fallback_back_listener(screen):
    """跑真实的 AppController.ui_session：并发监听期间兜底 back 必须被抑制。

    这是 #377 AC3 点名的协调关系，之前的用例只验证了自己的假锁，没有把真实的
    asyncio.Lock 与 EventManager 的兜底 back 判断接到一起。
    """
    import asyncio as aio

    from ushareiplay.core.app_controller import AppController
    from ushareiplay.core.runtime_context import EventRuntimeContext
    from ushareiplay.events.message_content import MessageContentEvent

    controller = _RealLockController()
    handler = _room_name_handler(screen)
    handler.controller = controller

    lock_states = []

    class _Commands:
        @staticmethod
        def update_commands():
            lock_states.append(controller.ui_lock.locked())
            screen.open("slide_drawer")

    async def _main():
        # 后台任务持锁期间，另一个 task（EventManager 的兜底 back 判断）必须看到忙
        async with controller.ui_session("periodic:background-updates"):
            listener = aio.create_task(_observe_lock(controller, lock_states))
            await listener

        with _patched_command_manager(_Commands):
            await MessageContentEvent(handler)._process_update_logic()

    aio.run(_main())

    # 兜底 back 的抑制条件成立：持锁期间 is_ui_busy() 恒为 True
    assert lock_states[0] is True, "后台更新期间 UI 锁必须是真实持有的"
    assert all(lock_states[1:]), f"并发监听期间锁不应显示为空闲: {lock_states[1:]}"
    assert controller.ui_lock.locked() is False, "退出后必须释放锁"


def test_background_updates_still_run_without_a_controller(screen):
    """拿不到锁接口时退化为不加锁，绝不因为拿不到锁就把后台任务跳过。"""
    from ushareiplay.events.message_content import MessageContentEvent

    ran = []

    class _Commands:
        @staticmethod
        def update_commands():
            ran.append(True)

    handler = _room_name_handler(screen)
    handler.controller = None

    with _patched_command_manager(_Commands):
        asyncio.run(MessageContentEvent(handler)._process_update_logic())

    assert ran == [True]