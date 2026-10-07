"""`RoomProfileManager` 的接口测试。

这个模块是房间档案（抽屉会话 + 草稿状态）的唯一所有者。两个接缝被测：

- 组合根创建的受保护单例（ADR-0009）：`.initialize(...)` 创建、`.instance()` 只读查找
- 抽屉 UI 驱动端口：生产适配器与内存替身共用同一组抽屉原语

抽屉的真实实现（Appium 细节）不在这些测试里 —— 那是 `SoulDrawerDriver` 的事。
这里考的是「谁决定打开与关闭」以及「草稿状态归谁记」，因此端口的内存替身
（`InMemoryRoomProfileDrawerDriver`）足够，且离线可跑。
"""

from types import SimpleNamespace

import pytest

from ushareiplay.core.singleton import Singleton, SingletonError
from ushareiplay.managers.room_profile import RoomProfileManager
from ushareiplay.managers.room_profile.drafts import ProfileDraftStore
from ushareiplay.managers.room_profile.soul_drawer import SoulDrawerDriver
from tests.fakes.in_memory_room_profile_drawer import InMemoryRoomProfileDrawerDriver


@pytest.fixture(autouse=True)
def reset_room_profile_manager():
    RoomProfileManager.reset_instance()
    yield
    RoomProfileManager.reset_instance()


# --------------------------------------------------------------------------
# 受保护单例契约（ADR-0009）
# --------------------------------------------------------------------------


def test_direct_constructor_is_not_a_creation_api():
    with pytest.raises(SingletonError, match="Use RoomProfileManager.initialize"):
        RoomProfileManager()


def test_instance_before_initialize_raises_a_clear_error():
    with pytest.raises(SingletonError, match="RoomProfileManager has not been initialized"):
        RoomProfileManager.instance()


def test_initialize_creates_one_instance_and_instance_returns_it():
    created = RoomProfileManager.initialize()
    assert RoomProfileManager.instance() is created
    assert RoomProfileManager.is_initialized() is True


def test_reinitializing_outside_the_composition_root_is_forbidden():
    RoomProfileManager.initialize()
    with pytest.raises(SingletonError, match="already initialized"):
        RoomProfileManager.initialize()


def test_the_composition_root_registers_it_next_to_the_remaining_legacy_manager():
    """组合根必须 `.initialize(...)` 一次，而不是在别处懒创建。"""
    from ushareiplay.managers.room_info_window import RoomInfoWindow

    source = (
        __import__("pathlib").Path(__file__).resolve().parents[1]
        / "src"
        / "ushareiplay"
        / "core"
        / "app_controller.py"
    ).read_text(encoding="utf-8")

    assert "self.room_profile_manager = RoomProfileManager.initialize(" in source
    # 旧单例暂时保留：#394 才删，RoomInfoWindow 现在仍是活调用点。
    assert "RoomInfoWindow.initialize(" in source
    assert RoomInfoWindow is not None and RoomProfileManager is not None


def test_reset_all_instances_also_resets_it():
    RoomProfileManager.initialize()
    Singleton.reset_all_instances()
    assert RoomProfileManager.is_initialized() is False


# --------------------------------------------------------------------------
# 抽屉端口：生产适配器与内存替身共用的一组原语
# --------------------------------------------------------------------------


def _profile(driver=None, handler=object()):
    return RoomProfileManager.initialize(handler=handler, drawer_driver=driver)


class _Handler:
    """只提供 set_topic 需要的切前台动作。抽屉走端口，不走 handler。"""

    def __init__(self, can_switch=True):
        from unittest.mock import MagicMock

        self.logger = MagicMock()
        self.key_actions = MagicMock()
        self.key_actions.switch_to_app.return_value = can_switch


def _stub_sync_partners(monkeypatch, journal):
    """把审计里的四个协作方换成会记账的替身，好断言批处理顺序。"""
    from ushareiplay.managers.party_manager import PartyManager
    from ushareiplay.managers.recommendation_manager import RecommendationManager
    from ushareiplay.managers.room_name_manager import RoomNameManager

    def _install(cls, **attrs):
        monkeypatch.setattr(cls, "_instance", SimpleNamespace(**attrs), raising=False)
        monkeypatch.setattr(cls, "_singleton_initialized", True, raising=False)

    def _record(key, result):
        journal.append(f"sync:{key}")
        return result

    _install(
        RecommendationManager,
        inspect_current_ui_status=lambda wait=False: _record(
            "recommendation", True
        ) and True,
        room_state=SimpleNamespace(recommendation_enabled=None),
    )
    _install(
        PartyManager,
        handler=object(),
        sync_and_correct_room_type_if_dialog_open=lambda: _record("room_type", {'success': True}),
    )
    _install(
        RoomNameManager,
        handler=object(),
        initialize_from_ui=lambda: _record("room_name", {'success': True}),
    )
    # 公告是本模块自己的字段（#391），核对发生在同一次抽屉会话里，因此这里
    # 直接替换掉那个内部方法，而不是另一个 manager 的单例。
    monkeypatch.setattr(
        RoomProfileManager,
        "_audit_notice_in_open_window",
        lambda self: _record("notice", {'success': True}),
    )


def test_the_drawer_port_is_an_abstract_boundary():
    from ushareiplay.managers.room_profile.driver import RoomProfileDrawerDriverPort

    with pytest.raises(TypeError):
        RoomProfileDrawerDriverPort()

    assert isinstance(
        InMemoryRoomProfileDrawerDriver(), RoomProfileDrawerDriverPort
    ), "内存替身必须走真实端口，否则 ABC 的约束形同虚设"


def test_the_in_memory_adapter_reports_a_closed_drawer_until_something_opens_it():
    driver = InMemoryRoomProfileDrawerDriver()
    assert driver.is_open() is False

    driver.open_drawer("chat_room_title", error_message="boom")
    assert driver.is_open() is True

    driver.close_drawer()
    assert driver.is_open() is False


# --------------------------------------------------------------------------
# 打开与关闭只归 RoomProfileManager 所有
# --------------------------------------------------------------------------


def test_with_window_open_closes_the_drawer_it_opened_itself():
    driver = InMemoryRoomProfileDrawerDriver()
    profile = _profile(driver)

    with profile.with_window_open() as open_error:
        assert open_error is None
        assert driver.is_open() is True

    assert driver.opened_entries == ["chat_room_title"]
    assert driver.is_open() is False, "自己打开的窗口必须由自己关掉"


def test_with_window_open_leaves_a_drawer_the_outer_flow_opened():
    """窗口是外层流程打开的时候，退出后必须保持开着，由外层决定何时关。"""
    driver = InMemoryRoomProfileDrawerDriver(drawer_open=True)
    profile = _profile(driver)

    with profile.with_window_open() as open_error:
        assert open_error is None

    assert driver.opened_entries == [], "已经开着就不该再点一次入口"
    assert driver.close_attempts == 0
    assert driver.back_presses == 0
    assert driver.is_open() is True


def test_with_window_open_yields_the_error_and_closes_nothing_when_it_cannot_open():
    driver = InMemoryRoomProfileDrawerDriver(fail_for=("chat_room_title", "room_topic"))
    profile = _profile(driver)

    with profile.with_window_open() as open_error:
        assert "error" in open_error

    assert driver.opened_entries == ["chat_room_title", "room_topic"]
    assert driver.close_attempts == 0
    assert driver.back_presses == 0


def test_with_window_open_closes_the_drawer_even_when_the_body_raises():
    driver = InMemoryRoomProfileDrawerDriver()
    profile = _profile(driver)

    with pytest.raises(RuntimeError, match="boom"):
        with profile.with_window_open():
            raise RuntimeError("boom")

    assert driver.is_open() is False, "上下文退出路径必须负责关窗"


def test_ensure_open_falls_back_to_the_next_entry_and_keeps_the_callers_error_text():
    driver = InMemoryRoomProfileDrawerDriver(fail_for=("chat_room_title",))
    profile = _profile(driver)

    assert profile.ensure_open() is None
    assert driver.opened_entries == ["chat_room_title", "room_topic"]


def test_ensure_open_hands_the_callers_error_text_to_the_entry_it_tries():
    driver = InMemoryRoomProfileDrawerDriver(fail_for=("chat_room_title", "room_topic"))
    profile = _profile(driver)

    error = profile.ensure_open(error_message="Failed to find room title")

    assert error == {"error": "Failed to find room title"}


def test_ensure_closed_prefers_the_ui_close_over_a_back_press():
    driver = InMemoryRoomProfileDrawerDriver(drawer_open=True)
    profile = _profile(driver)

    profile.ensure_closed()

    assert driver.close_attempts == 1
    assert driver.back_presses == 0, "抽屉能被正规关窗操作关掉时不得盲按返回"


def test_ensure_closed_presses_back_exactly_once_when_the_ui_close_fails():
    driver = InMemoryRoomProfileDrawerDriver(drawer_open=True, close_drawer_works=False)
    profile = _profile(driver)

    profile.ensure_closed()

    assert driver.close_attempts == 1
    assert driver.back_presses == 1


def test_ensure_closed_never_presses_back_when_no_drawer_marker_is_present():
    """防盲按返回的第一道闸：没有弹窗标志就一个返回键都不按。"""
    driver = InMemoryRoomProfileDrawerDriver()
    profile = _profile(driver)

    profile.ensure_closed()

    assert driver.close_attempts == 0
    assert driver.back_presses == 0


def test_is_open_is_false_before_anything_is_configured():
    profile = RoomProfileManager.initialize()
    assert profile.is_open() is False


def test_ensure_open_reports_the_missing_app_instead_of_touching_the_ui():
    profile = RoomProfileManager.initialize()

    assert profile.ensure_open() == {"error": "Soul handler is not available"}


def test_a_handler_without_a_configured_port_is_a_wiring_error_not_a_domain_failure():
    profile = _profile(driver=None, handler=object())

    with pytest.raises(RuntimeError, match="RoomProfileDrawerDriverPort"):
        profile.ensure_open()


# --------------------------------------------------------------------------
# 草稿库：三个字段的冷却与待写入文案由同一个对象拥有
# --------------------------------------------------------------------------


def test_the_draft_store_keeps_the_established_cooldowns():
    drafts = ProfileDraftStore()

    assert drafts.cooldown_minutes("topic") == 5
    assert drafts.cooldown_minutes("notice") == 15
    assert drafts.cooldown_minutes("title") == 10


def test_each_field_has_its_own_cooldown_budget():
    """房间名/标题与话题、公告互不消耗预算 —— 三个 PendingWrite 各自一份。"""
    drafts = ProfileDraftStore()
    drafts.mark_attempted("title")

    assert drafts.can_apply_now("title") is False
    assert drafts.can_apply_now("topic") is True
    assert drafts.can_apply_now("notice") is True


def test_remaining_minutes_truncates_the_same_way_the_three_legacy_managers_did():
    """刚推进时钟就报 9 分钟 —— int() 向下截断，与原先三份实现一致。"""
    drafts = ProfileDraftStore()
    drafts.mark_attempted("title")

    assert drafts.remaining_minutes("title") == 9


def test_remaining_minutes_is_zero_before_any_attempt():
    assert ProfileDraftStore().remaining_minutes("notice") == 0


def test_a_submitted_draft_survives_a_failed_attempt_and_is_cleared_on_success():
    drafts = ProfileDraftStore()
    drafts.submit("topic", "测试话题")

    assert drafts.has_pending("topic") is True
    assert drafts.pending("topic") == "测试话题"

    drafts.mark_attempted("topic")
    # 失败：文案留着，下个冷却周期再试。
    assert drafts.has_pending("topic") is True

    drafts.clear("topic")
    assert drafts.has_pending("topic") is False


def test_setting_a_draft_to_none_clears_it():
    drafts = ProfileDraftStore()
    drafts.submit("notice", "公告")
    drafts.set_pending("notice", None)

    assert drafts.has_pending("notice") is False


def test_an_unknown_field_is_rejected_rather_than_silently_created():
    drafts = ProfileDraftStore()

    with pytest.raises(KeyError):
        drafts.submit("playlist", "歌单")


def test_set_topic_queues_the_cleaned_text_against_the_topic_budget():
    profile = RoomProfileManager.initialize()
    profile.adopt_handler(_Handler())

    result = profile.set_topic("  晚安 | 早点睡  ")

    assert result == {"topic": "晚安. Topic will update soon"}
    assert profile.drafts.pending("topic") == "晚安"


def test_set_topic_reports_the_remaining_cooldown_once_the_budget_is_spent():
    profile = RoomProfileManager.initialize()
    profile.adopt_handler(_Handler())
    profile.drafts.mark_attempted("topic")

    result = profile.set_topic("夜曲")

    assert result == {"topic": "夜曲. Topic will update in 4 minutes"}
    assert profile.drafts.pending("topic") == "夜曲", "冷却中也要记住用户要写什么"


def test_set_notice_queues_against_its_own_slower_budget():
    profile = RoomProfileManager.initialize()
    profile.drafts.mark_attempted("title")

    result = profile.set_notice("今晚八点开播")

    assert result == {
        "success": True,
        "notice": "今晚八点开播",
        "message": "Notice will be updated soon",
    }
    assert profile.drafts.pending("notice") == "今晚八点开播"


def test_set_notice_reports_the_remaining_cooldown():
    profile = RoomProfileManager.initialize()
    profile.drafts.mark_attempted("notice")

    result = profile.set_notice("今晚八点开播")

    assert result["cooldown"] is True
    assert result["remaining_minutes"] == 14
    assert result["pending_notice"] == "今晚八点开播"


def test_set_title_cleans_the_banner_text_to_the_first_separator():
    profile = RoomProfileManager.initialize()

    result = profile.set_title("  夜曲｜周杰伦  ")

    assert result == {"title": "夜曲. Title will update soon"}
    assert profile.drafts.pending("title") == "夜曲"


def test_set_title_reports_the_remaining_cooldown_of_the_shared_title_budget():
    profile = RoomProfileManager.initialize()
    profile.drafts.mark_attempted("title")

    result = profile.set_title("Lofi Girl")

    assert result == {"title": "Lofi Girl. Title will update in 9 minutes"}


def test_set_title_also_accepts_a_theme_and_composes_the_room_name_invariant():
    """ADR-0001：房间名是 `{theme}｜{title}`，主题与标题共用一份冷却。"""
    profile = RoomProfileManager.initialize()
    profile.set_title("Lofi Girl", theme="三福")

    assert profile.drafts.pending("title") == "Lofi Girl"
    assert profile.drafts.pending_theme() == "三福"
    assert profile.compose_room_title() == "三福｜Lofi Girl"


def test_set_title_refuses_a_theme_that_set_theme_would_refuse():
    profile = RoomProfileManager.initialize()

    result = profile.set_title("Lofi Girl", theme="三福福")

    assert result == {"error": "主题最多两个字符"}
    assert profile.drafts.pending("title") is None, "主题不合法时标题不该被排队"


def test_set_theme_validates_and_records_a_pending_theme():
    profile = RoomProfileManager.initialize()

    assert profile.set_theme("听歌") == {"success": True, "theme": "听歌", "old_theme": None}
    assert profile.drafts.pending_theme() == "听歌"
    assert profile.set_theme("") == {"error": "主题不能为空"}
    assert profile.set_theme("三福福") == {"error": "主题最多两个字符"}


def test_the_theme_length_is_checked_before_stripping_like_the_legacy_manager_did():
    """既有的长度判定在 strip 之前，带空格的主题同样超限 —— 逐字保留。"""
    profile = RoomProfileManager.initialize()

    assert profile.set_theme("  听歌  ") == {"error": "主题最多两个字符"}
    assert profile.drafts.pending_theme() is None


def test_the_separator_is_the_fullwidth_vertical_line_and_only_the_first_one_splits():
    profile = RoomProfileManager.initialize()

    assert profile.parse_room_title("三福｜Lofi Girl") == ("三福", "Lofi Girl")
    # maxsplit=1：第一个分隔符之后全部是标题（与既有实现一致）。
    assert profile.parse_room_title("三福｜Lofi｜Girl") == ("三福", "Lofi｜Girl")
    assert profile.parse_room_title("没有分隔符") is None


def test_the_batched_audit_syncs_before_editing_and_closes_the_drawer_last(monkeypatch):
    """全量审计的顺序：开窗 -> 纠偏(推荐/类型) -> 编辑(房名/公告) -> 统一关窗。"""
    journal = []
    driver = InMemoryRoomProfileDrawerDriver(journal=journal)
    profile = _profile(driver, handler=_Handler())
    _stub_sync_partners(monkeypatch, journal)

    results = profile.audit_and_repair()

    assert journal == [
        "drawer:open:chat_room_title",
        "sync:recommendation",
        "sync:room_type",
        "sync:room_name",
        "sync:notice",
        "drawer:close",
    ]
    assert set(results) == {"recommendation", "room_type", "room_name", "notice"}
    assert profile.pending_audit_retry is False
    assert driver.is_open() is False


# --------------------------------------------------------------------------
# 过渡门面对既有调用点保持透明
# --------------------------------------------------------------------------


def test_room_info_window_forwards_the_drawer_session_including_the_callers_error_text():
    """既有的调用点一行不改地继续工作：文案与「只关自己打开的那一次」都不变。"""
    from ushareiplay.managers.room_info_window import RoomInfoWindow
    profile = RoomProfileManager.initialize()
    window = RoomInfoWindow.instance()
    driver = InMemoryRoomProfileDrawerDriver()
    profile.adopt_handler(_Handler(), driver)

    # 调用点自己开的窗，后面的上下文不负责关 —— 归属权规则原样穿过门面。
    assert window.ensure_open(error_message="Failed to find room title") is None
    assert window.is_open() is True
    assert driver.opened_entries == ["chat_room_title"]

    with window.with_window_open() as open_error:
        assert open_error is None
    assert driver.close_attempts == 0
    assert driver.is_open() is True

    # 关掉之后，下一个调用点再开就归它自己关。
    window.ensure_closed()
    with window.with_window_open():
        pass
    assert driver.close_attempts == 2
    assert driver.is_open() is False


def test_room_info_window_survives_before_the_profile_manager_is_registered():
    """组合根还没注册真实实现时，门面必须安静地回答「关着」，而不是炸掉。"""
    from ushareiplay.managers.room_info_window import RoomInfoWindow
    RoomProfileManager.reset_instance()
    window = RoomInfoWindow.instance()
    window._handler = _Handler()

    assert window.is_open() is False
    assert window.ensure_open() == {"error": "Soul handler is not available"}
    assert window.pending_audit_retry is False
    assert window.last_audit_results == {}


# --------------------------------------------------------------------------
# 推荐分发：开关不进草稿库
# --------------------------------------------------------------------------


def test_set_recommendation_owns_the_drawer_session_and_leaves_no_draft_behind(monkeypatch):
    journal = []
    driver = InMemoryRoomProfileDrawerDriver(journal=journal)
    profile = _profile(driver, handler=_Handler())

    from ushareiplay.managers.recommendation_manager import RecommendationManager

    clicked = []
    monkeypatch.setattr(
        RecommendationManager,
        "_instance",
        SimpleNamespace(
            update_recommendation_ui=lambda enabled: clicked.append(enabled) or {"success": True}
        ),
        raising=False,
    )
    monkeypatch.setattr(RecommendationManager, "_singleton_initialized", True, raising=False)

    assert profile.set_recommendation(True) == {"success": True}

    # 开一次窗、收一次选项层；抽屉随即确认关好，不再多按返回。
    assert journal == ["drawer:open:chat_room_title", "drawer:back"]
    assert driver.back_presses == 1
    assert clicked == [True]
    # 推荐分发没有冷却：草稿库里不该多出任何待写入值。
    assert [profile.drafts.pending(f) for f in profile.drafts.fields()] == [None, None, None]
    assert driver.is_open() is False


def test_set_recommendation_reports_the_open_failure_without_touching_the_options(monkeypatch):
    from ushareiplay.managers.recommendation_manager import RecommendationManager
    driver = InMemoryRoomProfileDrawerDriver(fail_for=("chat_room_title", "room_topic"))
    profile = _profile(driver, handler=_Handler())

    clicked = []
    monkeypatch.setattr(
        RecommendationManager,
        "_instance",
        SimpleNamespace(update_recommendation_ui=lambda enabled: clicked.append(enabled)),
        raising=False,
    )
    monkeypatch.setattr(RecommendationManager, "_singleton_initialized", True, raising=False)

    assert "error" in profile.set_recommendation(False)
    assert clicked == [], "开不了窗就不该去点选项"


# --------------------------------------------------------------------------
# 生产适配器：把同一组端口原语接到真实的 Soul handler 上
# --------------------------------------------------------------------------


def test_the_production_adapter_maps_the_port_onto_the_real_handler():
    from ushareiplay.managers.recovery_manager import RecoveryManager
    class _Finder:
        def __init__(self, present):
            self.present = present
            self.queries = []

        def try_find_element(self, key, log=False):
            self.queries.append(key)
            return object() if key in self.present else None

    class _Actions:
        def __init__(self):
            self.clicks = []

        def switch_and_click(self, key, **kwargs):
            self.clicks.append((key, kwargs.get("error_message")))
            return {"success": True}

    class _Keys:
        def __init__(self):
            self.back_presses = 0

        def press_back(self):
            self.back_presses += 1

    finder = _Finder({"slide_drawer"})
    actions = _Actions()
    keys = _Keys()
    driver = SoulDrawerDriver(
        SimpleNamespace(element_finder=finder, ui_actions=actions, key_actions=keys)
    )

    # 任一弹窗标志命中即算开着 —— 与被搬走的那段判定逐字一致。
    assert driver.is_open() is True
    assert "slide_drawer" in finder.queries

    assert driver.open_drawer("chat_room_title", error_message="Failed to find room title") == {
        "success": True
    }
    assert actions.clicks == [("chat_room_title", "Failed to find room title")]

    closed = []
    RecoveryManager._instance = SimpleNamespace(
        close_drawer=lambda drawer_key, **_kw: closed.append(drawer_key) or True
    )
    RecoveryManager._singleton_initialized = True
    try:
        assert driver.close_drawer() is True
    finally:
        RecoveryManager.reset_instance()
    assert closed == ["slide_drawer"]

    driver.press_back()
    assert keys.back_presses == 1


def test_the_production_adapter_reports_a_missing_app_instead_of_an_attribute_error():
    driver = SoulDrawerDriver(None)

    assert driver.is_open() is False
    assert driver.close_drawer() is False
    with pytest.raises(RuntimeError, match="Soul handler is not available"):
        driver.press_back()


def test_close_with_back_presses_again_only_when_the_nested_layer_is_still_there():
    """选项层盖在抽屉之上：返回一次还不够时才按第二次，绝不多按。"""
    driver = InMemoryRoomProfileDrawerDriver(drawer_open=True, back_closes=False)
    profile = _profile(driver)

    profile.close_with_back()
    assert driver.back_presses == 2

    driver.back_presses = 0
    driver.drawer_open = False
    profile.close_with_back()
    assert driver.back_presses == 1, "抽屉已经关掉时只按一次，不再叠第三次"
