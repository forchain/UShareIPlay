"""推荐分发 + 派对类型这一条纵切片的离线测试（#393）。

推荐分发是一个**没有冷却**的一次性开关，因此它与话题（5 分钟）/ 公告（15 分钟）/
房名（10 分钟）三条纵切**形状不同**：`:recommend` 当场就写 UI，回复立刻回去，
不像那三条「先排队、等下一次心跳」。因此本文件考的是：

- 开关走完端口的七个原语，全程一次抽屉会话，选项层收掉之后抽屉确认关好
- 推荐分发**不进草稿库** —— 连续两次 `:recommend` 都必须真的生效
- 派对类型（"闲聊唠嗑" -> "唱歌听歌"）与推荐分发是抽屉里的同两行，
  归同一个所有者，且都是**读文本做判定**：端口只建模物理动作，读判定走 handler
- **批处理（本 ticket 的交付物）**：建房与回房两次生命周期检查必须合并成**一次**
  抽屉会话 —— 断言整个序列里只有一次 `drawer:open` 和一次 `drawer:close`
- 审计结果的四个键（`recommendation` / `room_type` / `room_name` / `notice`）不变

抽屉的内存替身见 `tests/fakes/in_memory_room_profile_drawer.py`；生产适配器
`SoulDrawerDriver` 与真实 handler 的映射在 `test_room_profile_manager.py` 里考。
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from ushareiplay.managers.party_manager import PartyManager
from ushareiplay.managers.room_profile import RoomProfileManager
from ushareiplay.managers.room_profile.soul_drawer import SoulDrawerDriver
from ushareiplay.state.room_state import RoomState
from tests.fakes.in_memory_room_profile_drawer import InMemoryRoomProfileDrawerDriver

# 抽屉刚打开时的屏幕：推荐分发那一行 + 派对类型那一行。
DRAWER_SCREEN = (
    "slide_drawer",
    "party_recommendation_status",
    "party_room_type_option",
)
# 推荐分发的两种目标选项（点开那一行之后才出现的二级列表）。
RECOMMENDATION_OPTIONS = ("party_recommendation_open", "party_recommendation_close")
# 派对类型的二级弹窗目标（key 来自 config 的 target_party_type_element）。
SINGING_TYPE_KEY = "party_type_singing"

OPEN_TEXT = "所有人"
CLOSED_TEXT = "关闭推荐分发"
CHAT_TYPE_TEXT = "闲聊唠嗑"
SINGING_TYPE_TEXT = "唱歌听歌"

CONFIG = {
    "target_party_type_element": SINGING_TYPE_KEY,
    "default_notice": "U Share I Play\n分享音乐 享受快乐",
    "system_default_notices": ["弹唱大会"],
    "default_theme": "听歌",
    "default_title": "听歌",
}


class _Screen:
    """抽屉里当前存在哪些 key，以及每一行显示的文案。

    物理动作走端口（`InMemoryRoomProfileDrawerDriver`），**读文本**走 handler 的
    element_finder —— 端口只建模物理动作，不承载「读文本」，与公告 / 房名两条
    判定读同一个形状。
    """

    def __init__(self, present=(), texts=None):
        self.present = set(present)
        self.texts = dict(texts or {})
        self.clicks = []

    def element(self, key):
        if key not in self.present:
            return None
        screen = self

        class _Element:
            text = screen.texts.get(key, "")

            def click(self):
                screen.present.add(key)
                screen.clicks.append(key)
                return True

        return _Element()

    # --- handler.element_finder 需要的形状 ---

    def try_find_element(self, key, log=False):
        return self.element(key)

    def wait_for_element(self, key, timeout=10):
        return self.element(key)

    def wait_for_element_clickable(self, key, timeout=10):
        return self.element(key)

    def wait_for_any_element(self, keys, timeout=10):
        for key in keys:
            if key in self.present:
                return key, self.element(key)
        return None, None

    def get_element_text(self, element):
        return getattr(element, "text", "")


class _Handler:
    def __init__(self, screen=None, config=None):
        self.logger = MagicMock()
        self.key_actions = SimpleNamespace(switch_to_app=lambda: True, press_back=lambda: None)
        self.element_finder = screen if screen is not None else _Screen()
        self.config = CONFIG if config is None else config


@pytest.fixture(autouse=True)
def reset_singletons():
    for cls in (RoomProfileManager, RoomState, PartyManager):
        cls.reset_instance()
    yield
    for cls in (RoomProfileManager, RoomState, PartyManager):
        cls.reset_instance()


def _profile(driver=None, handler=None):
    return RoomProfileManager.initialize(
        handler=handler or _Handler(), drawer_driver=driver
    )


def _recommendation_driver(**kwargs):
    kwargs.setdefault("present", DRAWER_SCREEN)
    kwargs.setdefault(
        "world_after_click",
        {"party_recommendation_status": DRAWER_SCREEN + RECOMMENDATION_OPTIONS},
    )
    return InMemoryRoomProfileDrawerDriver(**kwargs)


# --------------------------------------------------------------------------
# 推荐分发：开关当场生效，没有冷却
# --------------------------------------------------------------------------


def test_set_recommendation_is_temporarily_disabled():
    """设置派对推荐状态已暂时停用，不执行抽屉动作。"""
    RoomState.initialize()
    driver = _recommendation_driver()
    profile = _profile(driver, _Handler(_Screen(DRAWER_SCREEN, {})))

    result = profile.set_recommendation(True)
    assert result == {"error": "派对推荐设置已暂时停用"}
    assert driver.clicks == []
    assert driver.opened_entries == []


def test_inspecting_the_recommendation_status_returns_none():
    """推荐状态已不在房间信息面板展示。"""
    profile = _profile(_recommendation_driver(), _Handler(_Screen(DRAWER_SCREEN, {"party_recommendation_status": OPEN_TEXT})))

    assert profile.inspect_current_ui_status() is None


def test_sync_while_open_does_not_sync_recommendation():
    """打开抽屉时不再获取/纠偏推荐状态。"""
    room_state = RoomState.initialize()
    room_state.recommendation_enabled = True
    profile = _profile(_recommendation_driver(), _Handler(_Screen(DRAWER_SCREEN, {"party_recommendation_status": CLOSED_TEXT})))

    results = profile.sync_while_open()
    assert "recommendation" not in results
    assert "room_type" in results
    assert room_state.recommendation_enabled is True


def test_ensure_synced_on_return_does_not_touch_the_drawer_when_the_state_is_known():
    """状态已记录就没有「要做」的事：一个抽屉动作都不该发生。"""
    room_state = RoomState.initialize()
    room_state.recommendation_enabled = False
    driver = _recommendation_driver()
    profile = _profile(driver, _Handler(_Screen(DRAWER_SCREEN, {"party_recommendation_status": OPEN_TEXT})))

    assert profile.ensure_synced_on_return() == {"skipped": True, "reason": "already_saved"}
    assert driver.opened_entries == []
    assert room_state.recommendation_enabled is False


def test_ensure_synced_on_return_audits_the_room_when_the_state_is_unknown():
    room_state = RoomState.initialize()
    room_state.recommendation_enabled = None
    driver = _recommendation_driver()
    profile = _profile(driver, _Handler(_Screen(DRAWER_SCREEN, {"party_recommendation_status": OPEN_TEXT})))

    result = profile.ensure_synced_on_return()

    assert result == {"success": True, "recommendation_enabled": None}
    assert driver.opened_entries == ["chat_room_title"]
    # 抽屉全量审计不再读/点推荐分发那一行
    assert "party_recommendation_status" not in driver.clicks
    assert "party_recommendation_open" not in driver.clicks
    assert "party_recommendation_close" not in driver.clicks


def test_ensure_synced_on_return_is_skipped_in_a_guest_room():
    room_state = RoomState.initialize()
    room_state.is_guest_room = True
    driver = _recommendation_driver()
    profile = _profile(driver, _Handler(_Screen(DRAWER_SCREEN, {})))

    assert profile.ensure_synced_on_return() == {"skipped": True, "reason": "guest_room"}
    assert driver.opened_entries == []


# --------------------------------------------------------------------------
# 派对类型：与推荐分发同属抽屉里的两行
# --------------------------------------------------------------------------


def _room_type_driver(**kwargs):
    kwargs.setdefault("present", DRAWER_SCREEN)
    # 点开类型那一行之后，二级弹窗里才出现「唱歌听歌」。
    kwargs.setdefault(
        "world_after_click",
        {"party_room_type_option": DRAWER_SCREEN + (SINGING_TYPE_KEY,)},
    )
    return InMemoryRoomProfileDrawerDriver(**kwargs)


def test_check_and_correct_room_type_switches_a_chat_room_to_singing():
    driver = _room_type_driver()
    screen = _Screen(DRAWER_SCREEN, {"party_room_type_option": CHAT_TYPE_TEXT, SINGING_TYPE_KEY: SINGING_TYPE_TEXT})
    profile = _profile(driver, _Handler(screen))

    result = profile.check_and_correct_room_type(auto_close=True)

    assert result == {"success": True, "switched": True}
    assert driver.clicks == ["party_room_type_option", SINGING_TYPE_KEY]
    assert driver.is_open() is False


def test_check_and_correct_room_type_leaves_a_singing_room_alone():
    driver = _room_type_driver()
    screen = _Screen(DRAWER_SCREEN, {"party_room_type_option": SINGING_TYPE_TEXT, SINGING_TYPE_KEY: SINGING_TYPE_TEXT})
    profile = _profile(driver, _Handler(screen))

    assert profile.check_and_correct_room_type(auto_close=True) == {"success": True, "switched": False}
    assert driver.clicks == [], "类型已经对了就不该点它"


def test_check_and_correct_room_type_opens_the_drawer_when_it_is_not_open():
    driver = _room_type_driver(present=("party_room_type_option", SINGING_TYPE_KEY))
    screen = _Screen(("party_room_type_option", SINGING_TYPE_KEY), {"party_room_type_option": CHAT_TYPE_TEXT})
    profile = _profile(driver, _Handler(screen))

    result = profile.check_and_correct_room_type(auto_close=True)

    assert result == {"success": True, "switched": True}
    assert driver.opened_entries == ["chat_room_title"]
    assert driver.is_open() is False, "自己开的抽屉必须自己关"


def test_the_room_type_is_left_untouched_when_the_drawer_is_not_open():
    """被动纠偏不得自己开窗：窗口是外层开的，外层决定何时关。"""
    driver = _room_type_driver(present=(SINGING_TYPE_KEY,))
    profile = _profile(driver, _Handler(_Screen((SINGING_TYPE_KEY,), {})))

    assert profile.sync_and_correct_room_type_if_dialog_open() == {
        "skipped": True,
        "reason": "dialog_not_open",
    }
    assert driver.opened_entries == []
    assert driver.clicks == []


def test_the_room_type_correction_never_closes_a_drawer_someone_else_opened():
    driver = _room_type_driver(drawer_open=True)
    screen = _Screen(DRAWER_SCREEN, {"party_room_type_option": CHAT_TYPE_TEXT, SINGING_TYPE_KEY: SINGING_TYPE_TEXT})
    profile = _profile(driver, _Handler(screen))

    assert profile.sync_and_correct_room_type_if_dialog_open() == {"success": True, "switched": True}
    assert driver.close_attempts == 0, "抽屉是外层开的，就由外层关"
    assert driver.is_open() is True


def test_a_room_type_target_that_never_appears_is_reported_as_an_error():
    driver = _room_type_driver(world_after_click={})
    screen = _Screen(DRAWER_SCREEN, {"party_room_type_option": CHAT_TYPE_TEXT})
    profile = _profile(driver, _Handler(screen))

    result = profile.check_and_correct_room_type(auto_close=True)

    assert result == {"error": f"Failed to find target party type button ({SINGING_TYPE_KEY})"}
    assert driver.clicks == ["party_room_type_option"]


# --------------------------------------------------------------------------
# 批处理（本 ticket 的交付物）
# --------------------------------------------------------------------------


def _room_lifecycle_handler(screen, profile):
    """PartyManager 在建房 / 回房时看到的那套 handler 依赖。"""
    return SimpleNamespace(
        party_id="FM15321640",
        logger=MagicMock(),
        element_finder=screen,
        key_actions=SimpleNamespace(switch_to_app=lambda: True, press_back=lambda: None),
        ui_actions=SimpleNamespace(
            switch_and_click=lambda key, **kwargs: {"success": True}
        ),
        config=CONFIG,
        controller=SimpleNamespace(
            room_profile_manager=profile,
            seat_manager=SimpleNamespace(
                find_owner_seat=lambda: _async_ok()
            ),
        ),
    )


async def _async_ok():
    return {"success": True}


def _full_drawer_screen():
    return _Screen(
        DRAWER_SCREEN + ("title_edit_entry", "edit_notice_entry", "close_notice"),
        {
            "party_recommendation_status": OPEN_TEXT,
            "party_room_type_option": CHAT_TYPE_TEXT,
            "chat_room_notice": "U Share I Play\n分享音乐 享受快乐",
        },
    )


@pytest.mark.asyncio
async def test_room_creation_does_not_open_drawer_for_recommendation():
    """建房后不再开抽屉刷新推荐（推荐仅在建房时设置）。"""
    journal = []
    screen = _full_drawer_screen()
    driver = InMemoryRoomProfileDrawerDriver(
        journal=journal,
        present=screen.present,
    )
    profile = _profile(driver, _Handler(screen))
    room_state = RoomState.initialize()
    room_state.recommendation_enabled = False  # 建房时的配置假设

    party = PartyManager.initialize()
    party._handler = _room_lifecycle_handler(screen, profile)
    party._logger = MagicMock()

    await party._after_party_created()

    # 建房时设置的推荐状态保留，无需也不再为了推荐开抽屉
    assert room_state.recommendation_enabled is False
    assert journal.count("drawer:open:chat_room_title") == 0


@pytest.mark.asyncio
async def test_re_entering_the_room_does_not_open_drawer_for_recommendation():
    """回房时不再因为推荐状态未知而开抽屉读推荐。"""
    journal = []
    screen = _full_drawer_screen()
    screen.present.add("party_back")
    driver = InMemoryRoomProfileDrawerDriver(journal=journal, present=screen.present)
    profile = _profile(driver, _Handler(screen))
    room_state = RoomState.initialize()
    room_state.recommendation_enabled = None

    party = PartyManager.initialize()
    party._handler = _room_lifecycle_handler(screen, profile)
    party._logger = MagicMock()

    # 点「回到房间」那一支：不应再为了推荐分发开抽屉
    assert await party.join_party() is True

    assert journal.count("drawer:open:chat_room_title") == 0


def test_the_audit_result_keys_are_unchanged():
    """审计结果包含当前在抽屉中的三个字段键。"""
    screen = _full_drawer_screen()
    driver = InMemoryRoomProfileDrawerDriver(present=screen.present)
    profile = _profile(driver, _Handler(screen))

    results = profile.audit_and_repair()

    assert set(results) == {"room_type", "room_name", "notice"}


# --------------------------------------------------------------------------
# 结构约束：循环依赖与「不该存在的原路查询」
# --------------------------------------------------------------------------


def test_the_room_profile_manager_no_longer_defers_to_a_legacy_manager():
    """#393 的循环边收口：`manager.py` 里不再有任何指向 legacy manager 的延迟 import。

    ADR-0009 §4 允许函数体 import，但只允许「真的成环」且注释点名对端。这里
    三条边（RecommendationManager ×2、PartyManager ×1）全部消失，因此文件里
    一条 `ushareiplay.managers.*` 的函数体 import 都不该剩。
    """
    import inspect

    from ushareiplay.managers.room_profile import manager as profile_manager

    body_imports = [
        line.strip()
        for line in inspect.getsource(profile_manager).splitlines()
        if "import" in line
        and "ushareiplay.managers" in line
        and line.startswith(" ")  # 顶部的 import 从行首开始，函数体里的有缩进
    ]
    assert body_imports == [], body_imports


def test_the_room_profile_manager_does_not_import_the_deleted_or_legacy_managers():
    """源码级断言：模块里既不 import 也不提到 `RecommendationManager` / `PartyManager`。"""
    import inspect

    from ushareiplay.managers.room_profile import manager as profile_manager

    source = inspect.getsource(profile_manager)
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith(("from ", "import ")):
            assert "recommendation_manager" not in stripped, stripped
            assert "party_manager" not in stripped, stripped
            assert "room_info_window" not in stripped, stripped


def test_party_manager_has_no_direct_drawer_element_queries_left():
    """AC#3：`party_manager.py` 里不再有任何直接的抽屉元素查询。"""
    import inspect

    source = inspect.getsource(PartyManager)
    for drawer_key in ("party_room_type_option", "party_recommendation_status"):
        assert drawer_key not in source, drawer_key
    assert "def check_and_correct_room_type" not in source
    assert "def sync_and_correct_room_type_if_dialog_open" not in source


def test_the_legacy_recommendation_manager_is_gone():
    with pytest.raises(ModuleNotFoundError):
        __import__("ushareiplay.managers.recommendation_manager")


# --------------------------------------------------------------------------
# 命令层：`:recommend` 只是一层薄适配器
# --------------------------------------------------------------------------


class _CommandRuntime:
    def __init__(self, soul_handler):
        self.soul_handler = soul_handler
        self.music_handler = SimpleNamespace()


@pytest.mark.asyncio
async def test_recommend_command_is_temporarily_disabled():
    from ushareiplay.commands.recommend import RecommendCommand

    driver = _recommendation_driver()
    screen = _Screen(DRAWER_SCREEN, {"party_recommendation_status": OPEN_TEXT})
    handler = _Handler(screen)
    _profile(driver, handler)
    room_state = RoomState.initialize()
    room_state.recommendation_enabled = True

    cmd = RecommendCommand(_CommandRuntime(handler))
    result = await cmd.do_process(SimpleNamespace(nickname="Console"), ["off"])

    assert result == {"error": "派对推荐功能已暂时停用"}
    assert driver.opened_entries == []
    assert driver.clicks == []


@pytest.mark.asyncio
async def test_recommend_command_disabled_when_given_no_argument():
    from ushareiplay.commands.recommend import RecommendCommand

    driver = _recommendation_driver()
    screen = _Screen(DRAWER_SCREEN, {"party_recommendation_status": CLOSED_TEXT})
    handler = _Handler(screen)
    _profile(driver, handler)
    RoomState.initialize().recommendation_enabled = False

    cmd = RecommendCommand(_CommandRuntime(handler))
    result = await cmd.do_process(SimpleNamespace(nickname="Console"), [])

    assert result == {"error": "派对推荐功能已暂时停用"}
    assert driver.opened_entries == []


# --------------------------------------------------------------------------
# 生产适配器：原语在真实 handler 上的映射
# --------------------------------------------------------------------------


def test_the_production_adapter_reports_a_successful_click_as_true():
    """`click_element` 等不到元素才返回 False；点到了就必须返回 True。

    Selenium 的 `WebElement.click()` 返回 None —— 适配器若把它的返回值当布尔
    报告，「点成功」与「点失败」在生产里会无法区分，调用方会把每一次成功的
    点击当成失败。
    """
    clicked = []
    finder = SimpleNamespace(
        wait_for_element_clickable=lambda key, timeout=10: SimpleNamespace(
            click=lambda: clicked.append(key)
        ),
        try_find_element=lambda key, log=False: None,
    )
    driver = SoulDrawerDriver(
        SimpleNamespace(element_finder=finder, ui_actions=None, key_actions=None)
    )

    assert driver.click_element("party_recommendation_status") is True
    assert clicked == ["party_recommendation_status"]


def test_the_production_adapter_reports_a_missing_element_as_false():
    finder = SimpleNamespace(
        wait_for_element_clickable=lambda key, timeout=10: None,
        try_find_element=lambda key, log=False: None,
    )
    driver = SoulDrawerDriver(
        SimpleNamespace(element_finder=finder, ui_actions=None, key_actions=None)
    )

    assert driver.click_element("party_recommendation_status") is False


# --------------------------------------------------------------------------
# 日志铁律：只探测、没发生行为的一律留在 DEBUG
# --------------------------------------------------------------------------


def _info_lines(handler):
    return [call.args[0] for call in handler.logger.info.call_args_list]


def _debug_lines(handler):
    return [call.args[0] for call in handler.logger.debug.call_args_list]


def test_probing_an_already_correct_party_type_logs_nothing_at_info():
    """没有行为触发的探测，按日志铁律不得 INFO。

    这条路径每次回房 / 建房都会走到（`audit_and_repair` 里的派对类型纠偏），
    一次回房刷一条 INFO 就是刷屏。
    """
    driver = _room_type_driver()
    handler = _Handler(
        _Screen(
            DRAWER_SCREEN,
            {"party_room_type_option": SINGING_TYPE_TEXT, SINGING_TYPE_KEY: SINGING_TYPE_TEXT},
        )
    )
    profile = _profile(driver, handler)

    assert profile.check_and_correct_room_type(auto_close=True) == {
        "success": True,
        "switched": False,
    }

    # 只盯着**探测**那两句：`ensure_closed()` 里的 INFO 是另一回事 ——
    # 那里真的关掉了一个抽屉，是有行为触发的，合规。
    probe_lines = [
        line
        for line in _info_lines(handler)
        if "party type" in line or "Inspected" in line
    ]
    assert probe_lines == [], f"只探测就换了状态，不得有 INFO：{probe_lines}"


def test_an_actual_party_type_switch_still_logs_at_info():
    """反过来钉住：真的点了就是触发了行为，INFO 合规，不能被一起降级。"""
    driver = _room_type_driver()
    handler = _Handler(
        _Screen(
            DRAWER_SCREEN,
            {"party_room_type_option": CHAT_TYPE_TEXT, SINGING_TYPE_KEY: SINGING_TYPE_TEXT},
        )
    )
    profile = _profile(driver, handler)

    assert profile.check_and_correct_room_type(auto_close=True)["switched"] is True
    assert _info_lines(handler), "真的执行了类型切换，必须留下 INFO"


def test_the_party_type_probe_is_still_observable_at_debug():
    """降级不是丢信息：DEBUG 里要能查清楚当时读到了什么。"""
    driver = _room_type_driver()
    handler = _Handler(
        _Screen(
            DRAWER_SCREEN,
            {"party_room_type_option": SINGING_TYPE_TEXT, SINGING_TYPE_KEY: SINGING_TYPE_TEXT},
        )
    )
    profile = _profile(driver, handler)

    profile.check_and_correct_room_type(auto_close=True)

    assert _debug_lines(handler), "探测结果必须仍然留在 DEBUG 以便排查"


# --------------------------------------------------------------------------
# 「已关窗」这句话只在该真关掉的时候说
# --------------------------------------------------------------------------


def test_a_failed_open_never_claims_the_room_info_window_was_closed():
    """抽屉根本没打开成功，说「已关窗」就是一句假话。"""
    room_state = RoomState.initialize()
    room_state.recommendation_enabled = None
    driver = _recommendation_driver(fail_for=("chat_room_title", "room_topic"))
    handler = _Handler(_Screen(DRAWER_SCREEN, {"party_room_type_option": SINGING_TYPE_TEXT}))
    profile = _profile(driver, handler)

    profile.ensure_synced_on_return()

    assert not any("Closed room info window" in line for line in _info_lines(handler)), (
        f"打开失败时不得声称关过窗：{_info_lines(handler)}"
    )


def test_a_real_audit_still_claims_the_window_was_closed():
    """反过来钉住：真的走完一次审计并关窗时，这句 INFO 不得被一起删掉。"""
    room_state = RoomState.initialize()
    room_state.recommendation_enabled = None
    driver = _recommendation_driver()
    handler = _Handler(_Screen(DRAWER_SCREEN, {"party_recommendation_status": OPEN_TEXT}))
    profile = _profile(driver, handler)

    profile.ensure_synced_on_return()

    assert any("Closed room info window" in line for line in _info_lines(handler))
    assert driver.is_open() is False


# --------------------------------------------------------------------------
# 推荐分发状态：命令层不该穿过模块去摸 RoomState
# --------------------------------------------------------------------------


def test_the_manager_answers_the_recommendation_state_directly():
    room_state = RoomState.initialize()
    room_state.recommendation_enabled = True
    profile = _profile()

    assert profile.recommendation_enabled is True

    room_state.recommendation_enabled = None
    assert profile.recommendation_enabled is None, "还没读到过时是 None，不是 False"


def test_the_recommend_command_reads_the_state_through_the_module():
    """`:recommend` 不得 `profile.room_state` 往里摸 —— RoomState 留在模块背后。"""
    import pathlib

    source = (
        pathlib.Path(__file__).resolve().parents[1]
        / "src"
        / "ushareiplay"
        / "commands"
        / "recommend.py"
    ).read_text(encoding="utf-8")

    assert "room_state" not in source, "命令层仍在穿过模块边界读 RoomState"
    assert "recommendation_enabled" in source, "命令层应改问模块的直接答案"
