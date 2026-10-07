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


def test_set_recommendation_closes_recommendation_in_one_drawer_session():
    """一次开关 = 一次抽屉会话：开窗 -> 点状态行 -> 点选项 -> 收选项层 -> 关窗。"""
    journal = []
    driver = _recommendation_driver(journal=journal)
    screen = _Screen(DRAWER_SCREEN, {"party_recommendation_status": OPEN_TEXT})
    profile = _profile(driver, _Handler(screen))
    room_state = RoomState.initialize()

    result = profile.set_recommendation(False)

    assert result == {"success": True, "recommendation_enabled": False}
    assert room_state.recommendation_enabled is False
    assert driver.clicks == ["party_recommendation_status", "party_recommendation_close"]
    # 开一次窗 -> 点状态行 -> 点选项 -> 收一次选项层；抽屉随即确认关好，不再多按返回。
    assert journal == [
        "drawer:open:chat_room_title",
        "element:click:party_recommendation_status",
        "element:click:party_recommendation_close",
        "drawer:back",
    ]
    assert driver.is_open() is False


def test_set_recommendation_opens_recommendation_when_the_room_shows_it_closed():
    RoomState.initialize()
    driver = _recommendation_driver()
    screen = _Screen(DRAWER_SCREEN, {"party_recommendation_status": CLOSED_TEXT})
    profile = _profile(driver, _Handler(screen))

    assert profile.set_recommendation(True) == {"success": True, "recommendation_enabled": True}
    assert driver.clicks == ["party_recommendation_status", "party_recommendation_open"]


def test_set_recommendation_applies_immediately_every_time_and_never_queues_a_draft():
    """推荐分发没有预算：连着两次都当场生效，草稿库里不多出一个待写入值。"""
    RoomState.initialize()
    profile = _profile(_recommendation_driver(), _Handler(_Screen(DRAWER_SCREEN, {})))

    for enabled in (False, True, False):
        assert "error" not in profile.set_recommendation(enabled)

    # 草稿库只有话题 / 公告 / 房名三个字段 —— 推荐分发根本没有自己的预算。
    assert list(profile.drafts.fields()) == ["topic", "notice", "title"]
    assert [profile.drafts.pending(f) for f in profile.drafts.fields()] == [None, None, None]
    # 冷却闸门对它不存在：can_apply_now 恒为真，没有任何字段被 mark_attempted。
    assert all(profile.drafts.can_apply_now(f) for f in profile.drafts.fields())


def test_set_recommendation_does_nothing_when_the_room_is_already_in_that_state():
    """已经在目标状态：一个点击都不该发生。"""
    RoomState.initialize()
    driver = _recommendation_driver()
    screen = _Screen(DRAWER_SCREEN, {"party_recommendation_status": OPEN_TEXT})
    profile = _profile(driver, _Handler(screen))

    assert profile.set_recommendation(True) == {"success": True, "recommendation_enabled": True}
    assert driver.clicks == []


def test_set_recommendation_keeps_the_legacy_open_failure_text():
    """开不了窗时 `:recommend` 的报错文案一个字都不许变。

    这条文案原先由 `commands/recommend.py` 传进 `ensure_open`，回复模板是
    `设置派对推荐失败: {error}`，因此必须由本方法原样交出。
    """
    driver = InMemoryRoomProfileDrawerDriver(fail_for=("chat_room_title", "room_topic"))
    profile = _profile(driver, _Handler(_Screen(DRAWER_SCREEN, {})))

    assert profile.set_recommendation(False) == {"error": "Failed to find room title"}
    assert driver.clicks == [], "开不了窗就不该去点选项"


def test_set_recommendation_is_refused_in_a_guest_room():
    room_state = RoomState.initialize()
    room_state.is_guest_room = True
    driver = _recommendation_driver()
    profile = _profile(driver, _Handler(_Screen(DRAWER_SCREEN, {})))

    assert profile.set_recommendation(True) == {"error": "他人房间模式下不可修改推荐状态"}
    assert driver.clicks == []


# --------------------------------------------------------------------------
# 推荐分发的状态读取与被动纠偏
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        (OPEN_TEXT, True),
        (CLOSED_TEXT, False),
        ("", None),
        ("看不懂的文案", None),
    ],
)
def test_inspecting_the_recommendation_status_reads_the_drawer_row(text, expected):
    profile = _profile(_recommendation_driver(), _Handler(_Screen(DRAWER_SCREEN, {"party_recommendation_status": text})))

    assert profile.inspect_current_ui_status() is expected


def test_syncing_the_recommendation_writes_the_real_ui_state_back_to_room_state():
    """纠偏：UI 上是"关闭"就往 RoomState 回写 False，而不是保留建房时的假设。"""
    room_state = RoomState.initialize()
    room_state.recommendation_enabled = True
    profile = _profile(_recommendation_driver(), _Handler(_Screen(DRAWER_SCREEN, {"party_recommendation_status": CLOSED_TEXT})))

    assert profile.sync_while_open()["recommendation"] == {"success": True, "status": False}
    assert room_state.recommendation_enabled is False


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

    assert result == {"success": True, "recommendation_enabled": True}
    assert room_state.recommendation_enabled is True
    assert driver.opened_entries == ["chat_room_title"]
    # 全量纠偏只**读**推荐分发那一行：审计不该顺手把开关点一遍。
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
async def test_room_creation_batches_every_correction_into_one_drawer_session():
    """建房后的全量纠偏**只开一次抽屉**：推荐、类型、房名、公告在同一次会话里。

    这就是 spec 用户故事 #10 / #11 要的批处理：`PartyManager._after_party_created`
    原本自己去开窗做推荐刷新，随后每个字段各自开一次；现在整条链路只有一次
    `drawer:open` 和一次 `drawer:close`。
    """
    journal = []
    screen = _full_drawer_screen()
    driver = InMemoryRoomProfileDrawerDriver(
        journal=journal,
        present=screen.present,
        world_after_click={
            "party_room_type_option": screen.present | {SINGING_TYPE_KEY},
            "edit_notice_entry": screen.present
            | {"close_notice", "customize_notice_button", "edit_notice_input", "edit_notice_confirm"},
        },
    )
    profile = _profile(driver, _Handler(screen))
    room_state = RoomState.initialize()
    room_state.recommendation_enabled = False  # 建房时的配置假设

    party = PartyManager.initialize()
    party._handler = _room_lifecycle_handler(screen, profile)
    party._logger = MagicMock()

    await party._after_party_created()

    # 批处理的证据：整个建房序列里只有一次打开、一次关闭。
    assert journal.count("drawer:open:chat_room_title") == 1, journal
    assert [e for e in journal if e.startswith("drawer:close")] == ["drawer:close"], journal
    # 顺序：开窗 -> 纠偏 -> 编辑 -> 统一关窗；没有任何一次重复开窗。
    assert journal == [
        "drawer:open:chat_room_title",
        "element:click:party_room_type_option",
        "element:click:party_type_singing",
        "element:click:edit_notice_entry",
        "element:click:customize_notice_button",
        "element:type:edit_notice_input",
        "element:click:edit_notice_confirm",
        "element:click:close_notice",
        "drawer:close",
    ], journal
    # 真实状态从 UI 读回来了（不是建房时的假设）。
    assert room_state.recommendation_enabled is True
    assert profile.last_audit_results["recommendation"] == {"success": True, "status": True}
    assert profile.last_audit_results["room_type"] == {"success": True, "switched": True}
    assert driver.is_open() is False


@pytest.mark.asyncio
async def test_re_entering_the_room_audits_in_one_drawer_session_too():
    """回房（`join_party` 里的 `ensure_synced_on_return`）同样只开一次抽屉。"""
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

    # 点「回到房间」那一支：它必须自己去把推荐分发的真实状态读回来。
    assert await party.join_party() is True

    assert journal.count("drawer:open:chat_room_title") == 1, journal
    assert [e for e in journal if e.startswith("drawer:close")] == ["drawer:close"], journal
    assert room_state.recommendation_enabled is True


def test_the_audit_result_keys_are_unchanged():
    """审计结果的四个键是既有接口，#393 之后仍然是这四个。"""
    screen = _full_drawer_screen()
    driver = InMemoryRoomProfileDrawerDriver(present=screen.present)
    profile = _profile(driver, _Handler(screen))

    results = profile.audit_and_repair()

    assert set(results) == {"recommendation", "room_type", "room_name", "notice"}


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
async def test_recommend_command_delegates_the_toggle_to_the_room_profile_manager():
    from ushareiplay.commands.recommend import RecommendCommand

    driver = _recommendation_driver()
    screen = _Screen(DRAWER_SCREEN, {"party_recommendation_status": OPEN_TEXT})
    handler = _Handler(screen)
    _profile(driver, handler)
    room_state = RoomState.initialize()
    room_state.recommendation_enabled = True

    cmd = RecommendCommand(_CommandRuntime(handler))
    result = await cmd.do_process(SimpleNamespace(nickname="Console"), ["off"])

    assert result == {"status": "关闭"}
    assert room_state.recommendation_enabled is False
    assert driver.clicks == ["party_recommendation_status", "party_recommendation_close"]


@pytest.mark.asyncio
async def test_recommend_command_toggles_when_given_no_argument():
    from ushareiplay.commands.recommend import RecommendCommand

    driver = _recommendation_driver()
    screen = _Screen(DRAWER_SCREEN, {"party_recommendation_status": CLOSED_TEXT})
    handler = _Handler(screen)
    _profile(driver, handler)
    RoomState.initialize().recommendation_enabled = False

    cmd = RecommendCommand(_CommandRuntime(handler))
    result = await cmd.do_process(SimpleNamespace(nickname="Console"), [])

    assert result == {"status": "开放"}


@pytest.mark.asyncio
async def test_recommend_command_keeps_its_argument_error_and_never_opens_the_drawer():
    from ushareiplay.commands.recommend import RecommendCommand

    driver = _recommendation_driver()
    handler = _Handler(_Screen(DRAWER_SCREEN, {}))
    _profile(driver, handler)
    RoomState.initialize()

    cmd = RecommendCommand(_CommandRuntime(handler))
    result = await cmd.do_process(SimpleNamespace(nickname="Console"), ["也许"])

    assert result == {"error": '未知参数 "也许", 请使用 on/off 或 开启/关闭'}
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
