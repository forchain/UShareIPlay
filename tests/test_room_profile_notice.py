"""房间公告这一条纵切片的离线测试。

公告原先由 `NoticeManager` 独自持有：15 分钟冷却时钟、抽屉里的编辑点击
ritual、房名变更前后那次「公告被系统冲掉就恢复」的保存/恢复。现在这些都在
`RoomProfileManager` 里，UI 那一层走抽屉端口，因此这里不需要 Android。

形状与话题那条纵切（#390）一致：**setter 只排队，独立的 tick 才写 UI**。
因此本文件考的是：

- 冷却是硬闸门：冷却中 / 没有待写入公告时，一个 UI 动作都不发生，也不打日志
- 抽屉的每一次点击与输入都经过端口替身，断言的是「点了哪些 key」而不是 Appium
- **`skipped` 不等于「写成功了」**：他人房间那条跳过分支既不清草稿、也不烧
  冷却、更不往公屏报成功（话题那条路的同名缺陷由 review pass 处理）
- 房名变更把公告冲掉之后，上一条公告的文案确实被写回去了（用户故事 #6）

`SoulDrawerDriver` 把同一组原语接到真实 handler 上的映射在
`test_room_profile_manager.py` 里考，本文件不重复。
"""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from ushareiplay.core.config_loader import ConfigLoader
from ushareiplay.core.message_dispatch import MessageDispatch
from ushareiplay.managers.room_profile import RoomProfileManager
from ushareiplay.state.room_state import RoomState
from tests.fakes.in_memory_room_profile_drawer import InMemoryRoomProfileDrawerDriver

# 公告编辑层打开时抽屉里有的东西（`config.yaml` 的 elements key）。
NOTICE_EDIT_LAYER = (
    'edit_notice_entry',
    'close_notice',
    'customize_notice_button',
    'edit_notice_input',
    'edit_notice_confirm',
)
# 抽屉本体（`with_window_open` 的开关标志）。
DRAWER_LAYER = ('slide_drawer',)


@pytest.fixture(autouse=True)
def reset_room_profile_manager():
    RoomProfileManager.reset_instance()
    yield
    RoomProfileManager.reset_instance()


@pytest.fixture
def screen_messages(monkeypatch):
    """记录写进公屏的每一条消息 —— 「有没有宣布成功」必须能被断言。"""
    sent = []
    monkeypatch.setattr(
        MessageDispatch.instance(),
        "send_screen_message",
        lambda message, silent=False: sent.append(message),
    )
    return sent


class _NoticeTextFinder:
    """`chat_room_notice` 的文本读。

    端口只建模抽屉的物理动作；「读一次当前公告文案好判断它是不是被系统冲掉了」
    是一次探测，本文件因此给 handler 配一个最小替身。
    """

    def __init__(self, text=""):
        self.text = text

    def try_find_element(self, key, log=False):
        return object() if key == 'chat_room_notice' else None

    def get_element_text(self, element):
        return self.text


class _Handler:
    """公告只需要：抽屉（走端口）、配置、以及审计那一次文本读。"""

    def __init__(self, notice_text="", config=None, can_switch=True):
        self.logger = MagicMock()
        self.key_actions = MagicMock()
        self.key_actions.switch_to_app.return_value = can_switch
        self.element_finder = _NoticeTextFinder(notice_text)
        self.config = {} if config is None else config


def _profile(driver=None, handler=None, config=None, notice_text=""):
    profile = RoomProfileManager.initialize(
        handler=handler or _Handler(notice_text, config), drawer_driver=driver
    )
    return profile


def _driver(**kwargs):
    kwargs.setdefault("present", NOTICE_EDIT_LAYER)
    return InMemoryRoomProfileDrawerDriver(**kwargs)


def _levels(profile):
    levels = ("debug", "info", "warning", "error")
    for level in levels:
        getattr(profile.logger, level).reset_mock()
    return levels


# --------------------------------------------------------------------------
# 冷却是硬闸门
# --------------------------------------------------------------------------


def test_the_notice_budget_is_fifteen_minutes():
    profile = _profile()

    assert profile.drafts.cooldown_minutes("notice") == 15


def test_set_notice_queues_the_draft_and_answers_with_the_soon_wording():
    driver = _driver()
    profile = _profile(driver)

    result = profile.set_notice("今晚八点开播")

    assert result == {
        "success": True,
        "notice": "今晚八点开播",
        "message": "Notice will be updated soon",
    }
    assert profile.drafts.pending("notice") == "今晚八点开播"
    assert driver.clicks == [], "排队本身不碰 UI"


def test_set_notice_reports_the_remaining_cooldown_and_still_remembers_the_draft():
    profile = _profile(_driver())
    profile.drafts.mark_attempted("notice")

    result = profile.set_notice("今晚八点开播")

    assert result == {
        "cooldown": True,
        "remaining_minutes": 14,
        "pending_notice": "今晚八点开播",
        "message": "Notice will be updated in 14 minutes",
    }
    assert profile.drafts.pending("notice") == "今晚八点开播"


def test_the_notice_budget_is_not_shared_with_the_topic():
    """冷却是「每个字段一份」，写话题不该让公告排队。"""
    profile = _profile(_driver())
    profile.drafts.mark_attempted("topic")

    result = profile.set_notice("今晚八点开播")

    assert "cooldown" not in result
    assert profile.drafts.can_apply_now("notice") is True


def test_set_notice_skips_the_guest_room_without_queueing_anything():
    with _guest_room():
        profile = _profile(_driver())

        result = profile.set_notice("今晚八点开播")

    assert result == {"skipped": True, "reason": "guest_room"}
    assert profile.drafts.pending("notice") is None


def test_update_notice_writes_through_when_the_budget_is_free():
    driver = _driver()
    profile = _profile(driver)
    profile.set_notice("今晚八点开播")

    result = profile.update_notice()

    assert result == {"success": "Notice restored to: 今晚八点开播"}
    assert driver.opened_entries == ["chat_room_title"]
    assert driver.typed == [("edit_notice_input", "今晚八点开播")]


def test_update_notice_refuses_to_touch_the_ui_while_the_cooldown_is_running():
    driver = _driver()
    profile = _profile(driver)
    profile.set_notice("第一版")
    profile.update_notice()  # 第一次写入成功，预算用掉

    driver.clicks.clear()
    driver.typed.clear()
    profile.set_notice("第二版")  # 冷却中：只排队

    result = profile.update_notice()

    assert result == {"skipped": "cooldown"}
    assert driver.clicks == [], "冷却中是硬闸门，一个点击都不该发生"
    assert driver.typed == []
    assert driver.back_presses == 0
    assert profile.drafts.pending("notice") == "第二版", "下一次冷却到期后还要写"


def test_update_notice_becomes_writable_again_once_the_fifteen_minutes_have_passed():
    driver = _driver()
    profile = _profile(driver)
    profile.set_notice("第一版")
    profile.update_notice()
    profile.drafts.set_last_attempt_at(
        "notice", datetime.now() - timedelta(minutes=15)
    )

    profile.set_notice("第二版")
    result = profile.update_notice()

    assert result == {"success": "Notice restored to: 第二版"}


def test_update_notice_does_nothing_when_no_notice_is_queued():
    driver = _driver()
    profile = _profile(driver)

    result = profile.update_notice()

    assert result == {"skipped": "no_pending_notice"}
    assert driver.opened_entries == []
    assert driver.clicks == []


def test_an_idle_notice_tick_never_logs_anything():
    """监控铁律：轮询与冷却未到都不得刷日志。

    「没有待写入公告」和「冷却没到」这两条空转分支由 `:notice` 的定时轮询
    反复走到；只有真的写了东西（成功或失败）才允许打日志。
    """
    driver = _driver()
    profile = _profile(driver)
    profile.set_notice("第一版")
    profile.update_notice()  # 真实写入，把预算用掉
    profile.set_notice("第二版")

    levels = _levels(profile)
    profile.update_notice()  # 冷却中
    profile.update_notice()  # 冷却中
    profile.update_notice()  # 冷却中

    for level in levels:
        assert getattr(profile.logger, level).call_count == 0, f"{level} 在空转时刷屏了"


# --------------------------------------------------------------------------
# 抽屉点击走 UI 端口
# --------------------------------------------------------------------------


def test_the_notice_click_sequence_runs_through_the_driver_port():
    driver = _driver()
    profile = _profile(driver)
    profile.set_notice("今晚八点开播")

    profile.update_notice()

    assert driver.clicks == [
        "edit_notice_entry",
        "customize_notice_button",
        "edit_notice_confirm",
        "close_notice",
    ]
    assert driver.typed == [("edit_notice_input", "今晚八点开播")]


def test_the_notice_opens_the_drawer_through_the_default_entries():
    """公告原先用抽屉默认入口（`chat_room_title`），不是话题那个 `room_topic`。"""
    driver = _driver()
    profile = _profile(driver)
    profile.set_notice("今晚八点开播")

    profile.update_notice()

    assert driver.opened_entries == ["chat_room_title"]


def test_the_modify_notice_skin_is_used_when_customize_is_absent():
    driver = _driver(
        present=(
            'edit_notice_entry',
            'close_notice',
            'modify_notice_button',
            'edit_notice_input',
            'edit_notice_confirm',
        )
    )
    profile = _profile(driver)
    profile.set_notice("今晚八点开播")

    result = profile.update_notice()

    assert result == {"success": "Notice restored to: 今晚八点开播"}
    assert driver.clicks[1] == "modify_notice_button"


def test_a_drawer_that_will_not_open_is_reported_without_typing_anything():
    driver = _driver(fail_for=("chat_room_title", "room_topic"))
    profile = _profile(driver)
    profile.set_notice("今晚八点开播")

    result = profile.update_notice()

    assert "error" in result
    assert driver.clicks == []
    assert driver.back_presses == 0


@pytest.mark.parametrize(
    "present, expected_error",
    [
        (('close_notice', 'customize_notice_button'), 'Failed to find edit notice entry'),
        (('edit_notice_entry',), 'Close notice not found'),
        (
            ('edit_notice_entry', 'close_notice'),
            'Failed to find customize notice button',
        ),
        (
            ('edit_notice_entry', 'close_notice', 'customize_notice_button'),
            'Failed to find notice input',
        ),
        (
            (
                'edit_notice_entry',
                'close_notice',
                'customize_notice_button',
                'edit_notice_input',
            ),
            'Failed to find confirm button',
        ),
    ],
)
def test_a_missing_step_reports_its_own_error_and_unwinds_the_drawer(
    present, expected_error
):
    driver = _driver(present=present)
    profile = _profile(driver)
    profile.set_notice("今晚八点开播")

    result = profile.update_notice()

    assert result == {"error": expected_error}
    assert driver.close_attempts == 1, "用自己的正规关窗收回抽屉"
    assert driver.back_presses == 0


def test_a_disabled_customization_hides_the_notice_layer_before_giving_up():
    """底部抽屉挡住了「自定义」时，公告层必须被点掉，不能留在屏幕上。"""
    driver = _driver(present=('edit_notice_entry', 'close_notice'))
    profile = _profile(driver)
    profile.set_notice("今晚八点开播")

    result = profile.update_notice()

    assert result == {"error": "Failed to find customize notice button"}
    assert "close_notice" in driver.clicks
    assert driver.close_attempts == 1


def test_a_ui_layer_that_raises_becomes_an_error_dict_rather_than_an_exception():
    driver = _driver()

    def _boom(*_args, **_kwargs):
        raise RuntimeError("driver crashed")

    driver.click_element = _boom
    profile = _profile(driver)
    profile.set_notice("今晚八点开播")

    result = profile.update_notice()

    assert result == {"error": "Failed to update notice to 今晚八点开播"}


def test_the_notice_path_never_sends_a_blind_back_press():
    """公告这条路上不存在任何「盲按返回」—— 正常路径一次都不按。"""
    outcomes = [
        ("healthy", _driver()),
        ("missing edit entry", _driver(present=('close_notice',))),
        ("missing close button", _driver(present=('edit_notice_entry',))),
        ("missing customize", _driver(present=('edit_notice_entry', 'close_notice'))),
        (
            "missing input",
            _driver(
                present=(
                    'edit_notice_entry',
                    'close_notice',
                    'customize_notice_button',
                )
            ),
        ),
        ("drawer will not open", _driver(fail_for=("chat_room_title",))),
        ("driver explodes", _driver()),
    ]
    outcomes[-1][1].click_element = lambda *_a, **_k: (_ for _ in ()).throw(
        RuntimeError("driver crashed")
    )

    for label, driver in outcomes:
        RoomProfileManager.reset_instance()
        profile = _profile(driver)
        profile.set_notice("今晚八点开播")

        profile.update_notice()

        assert driver.back_presses == 0, f"{label}: 公告路径不允许盲按返回键"


def test_the_notice_path_presses_back_exactly_once_when_the_drawer_will_not_close():
    """正规关窗失效时才退化到保底返回键 —— 一次。"""
    driver = _driver(close_drawer_works=False)
    profile = _profile(driver)
    profile.set_notice("今晚八点开播")

    profile.update_notice()

    assert driver.close_attempts == 1
    assert driver.back_presses == 1


def test_a_drawer_the_outer_flow_opened_is_neither_closed_nor_backed_out_of():
    """只关自己打开的那一次：外层开的抽屉原样留给外层。"""
    driver = _driver(drawer_open=True)
    profile = _profile(driver)
    profile.set_notice("今晚八点开播")

    profile.update_notice()

    assert driver.opened_entries == []
    assert driver.close_attempts == 0
    assert driver.back_presses == 0
    assert driver.drawer_open is True


# --------------------------------------------------------------------------
# 草稿生命周期与公屏播报
# --------------------------------------------------------------------------


def test_a_successful_write_clears_the_draft_and_announces_it_once(screen_messages):
    driver = _driver()
    profile = _profile(driver)
    profile.set_notice("今晚八点开播")

    profile.update_notice()

    assert profile.drafts.pending("notice") is None
    assert screen_messages == ["Notice updated to: 今晚八点开播"]


def test_a_failed_write_keeps_the_draft_so_the_next_cooldown_can_retry(
    screen_messages,
):
    driver = _driver(present=('edit_notice_entry', 'close_notice'))
    profile = _profile(driver)
    profile.set_notice("今晚八点开播")

    result = profile.update_notice()

    assert result == {"error": "Failed to find customize notice button"}
    assert profile.drafts.pending("notice") == "今晚八点开播"
    assert screen_messages == [], "没写成功就不能往公屏报成功"


def test_the_cooldown_clock_advances_even_when_the_write_fails():
    """失败也算一次尝试：否则 `:notice` 会变成紧循环重试。"""
    driver = _driver(present=('edit_notice_entry', 'close_notice'))
    profile = _profile(driver)
    profile.set_notice("今晚八点开播")

    profile.update_notice()

    assert profile.drafts.last_attempt_at("notice") is not None
    assert profile.drafts.remaining_minutes("notice") == 14


# --------------------------------------------------------------------------
# 他人房间：skipped 不是「写成功了」
# --------------------------------------------------------------------------


def _guest_room():
    """把房间状态临时切成「在别人的房间里」。"""
    RoomState.reset_instance()
    room_state = RoomState.initialize()
    room_state.is_guest_room = True

    class _Reset:
        def __enter__(self):
            return room_state

        def __exit__(self, *_exc):
            RoomState.reset_instance()
            return False

    return _Reset()


def test_the_guest_room_tick_writes_nothing_and_keeps_the_draft_and_the_budget(
    screen_messages,
):
    # 先在自家房间排队，再切到别人的房间 —— 排队的公告必须原地等着。
    driver = _driver()
    profile = _profile(driver)
    profile.set_notice("今晚八点开播")

    with _guest_room():
        result = profile.update_notice()

    assert result == {"skipped": True, "reason": "guest_room"}
    assert driver.opened_entries == [], "别人房间不许开抽屉"
    assert driver.clicks == []
    assert profile.drafts.pending("notice") == "今晚八点开播", "跳过不是清空"
    assert profile.drafts.last_attempt_at("notice") is None, "跳过不能烧冷却预算"
    assert profile.drafts.can_apply_now("notice") is True
    assert screen_messages == [], "跳过不能当成写成功了往公屏播报"


def test_the_guest_room_restore_keeps_the_draft_and_the_budget_too(screen_messages):
    with _guest_room():
        driver = _driver()
        profile = _profile(driver)
        profile.drafts.set_pending("notice", "旧公告")

        result = profile.restore_notice("新公告")

    assert result == {"skipped": True, "reason": "guest_room"}
    assert driver.opened_entries == []
    assert profile.drafts.pending("notice") == "旧公告"
    assert profile.drafts.last_attempt_at("notice") is None
    assert screen_messages == []


# --------------------------------------------------------------------------
# 房名变更把公告冲掉之后的保存/恢复（用户故事 #6）
# --------------------------------------------------------------------------


DEFAULT_NOTICE = "U Share I Play\n分享音乐 享受快乐"
SYSTEM_DEFAULT_NOTICES = ["弹唱大会", "Souler们在随便聊聊ing", "蹲一个人"]
# `handler.config` 就是 config.yaml 的 `soul` 段（组合根用 `config["soul"]` 构造 handler）。
CONFIG = {
    "default_notice": DEFAULT_NOTICE,
    "system_default_notices": SYSTEM_DEFAULT_NOTICES,
}
# 房名流程的公告判重走 `ConfigLoader.load_config()`，因此它读整份配置里的 `soul` 段。
FULL_CONFIG = {"soul": CONFIG}


def test_restore_notice_writes_immediately_when_the_budget_is_free():
    driver = _driver()
    profile = _profile(driver)

    result = profile.restore_notice(DEFAULT_NOTICE)

    assert result == {"success": f"Notice restored to: {DEFAULT_NOTICE}"}
    assert driver.typed == [("edit_notice_input", DEFAULT_NOTICE)]
    assert profile.drafts.pending("notice") is None
    assert profile.drafts.can_apply_now("notice") is False, "恢复也占用公告预算"


def test_restore_notice_queues_the_text_while_the_cooldown_is_running():
    driver = _driver()
    profile = _profile(driver)
    profile.drafts.mark_attempted("notice")

    result = profile.restore_notice(DEFAULT_NOTICE)

    assert result["cooldown"] is True
    assert result["remaining_minutes"] == 14
    assert result["pending_notice"] == DEFAULT_NOTICE
    assert driver.clicks == [], "冷却中不碰 UI，只排队"
    assert profile.drafts.pending("notice") == DEFAULT_NOTICE

    # 冷却到期后同一条草稿由 tick 写出去
    profile.drafts.set_last_attempt_at(
        "notice", datetime.now() - timedelta(minutes=15)
    )
    assert profile.update_notice() == {"success": f"Notice restored to: {DEFAULT_NOTICE}"}


def test_a_failed_restore_keeps_the_previous_text_queued():
    driver = _driver(present=('edit_notice_entry', 'close_notice'))
    profile = _profile(driver)

    result = profile.restore_notice(DEFAULT_NOTICE)

    assert result == {"error": "Failed to find customize notice button"}
    assert profile.drafts.pending("notice") == DEFAULT_NOTICE


class _TitleFlowFinder:
    """房名写入流程要用的元素查找器。

    房名的物理动作已经走抽屉端口（#392），端口不承载「读文本」，因此本替身只
    负责那两次**判定**读：抽屉里的房名元素（审核有没有把房名吃掉）与被改房名
    冲掉的那条公告文案。
    """

    def __init__(self, notice_text):
        self.notice_text = notice_text
        self.title_element = MagicMock(name="title_element")
        self.notice_element = MagicMock(name="notice_element")

    def wait_for_element(self, key, timeout=10):
        return {
            "room_name_in_dialog": self.title_element,
            "chat_room_notice": self.notice_element,
        }.get(key)

    def try_find_element(self, key, log=False):
        return self.wait_for_element(key)

    def get_element_text(self, element):
        if element is self.notice_element:
            return self.notice_text
        return "听歌｜新标题"


#: 抽屉里标题那一行 + 公告那一行 —— 一次房名写入要在同一个会话里动到它们。
TITLE_FLOW_DRAWER = (
    "slide_drawer",
    "title_edit_entry",
    "title_edit_input",
    "title_edit_confirm",
) + NOTICE_EDIT_LAYER


def _title_change(monkeypatch, notice_text):
    """跑一次真实的房名写入，返回 `(driver, RoomProfileManager, 结果)`。

    端到端地走真实调用链：`RoomProfileManager._write_title_in_drawer` 自己开抽屉、
    先读公告有没有被系统冲掉，标题写成功后调同模块的 `restore_notice`，那一写
    必须落到同一个抽屉端口的输入框上。
    """
    monkeypatch.setattr(ConfigLoader, "load_config", lambda *a, **k: FULL_CONFIG)

    handler = _Handler(notice_text=notice_text, config=CONFIG)
    handler.element_finder = _TitleFlowFinder(notice_text)

    driver = InMemoryRoomProfileDrawerDriver(
        present=TITLE_FLOW_DRAWER,
        world_after_click={
            # 提交之后抽屉还在，公告那一行照旧可点。
            "title_edit_confirm": TITLE_FLOW_DRAWER,
            "edit_notice_confirm": ("edit_notice_entry",),
        },
    )
    RoomProfileManager.reset_instance()
    profile = RoomProfileManager.initialize(handler=handler, drawer_driver=driver)
    profile.title_settle_seconds = 0

    return driver, profile, profile._write_title_in_drawer("新标题")


def test_a_title_change_that_wiped_the_notice_restores_the_previous_text(monkeypatch):
    """改房名会把公告冲成系统默认文案；改完要把上一条公告写回去。"""
    driver, profile, result = _title_change(
        monkeypatch, "蹲一个人 蹲了那么久，终于等到你！"
    )

    assert result == {"success": True}
    assert driver.typed == [
        ("title_edit_input", "听歌｜新标题"),
        ("edit_notice_input", DEFAULT_NOTICE),
    ]
    assert profile.pending_notice_restore is False, "恢复标记用完即清"
    assert profile.restore_notice_content is None


def test_the_restore_after_a_title_change_reuses_the_open_window(monkeypatch):
    """恢复公告发生在房名流程已经打开的那个抽屉会话里，不再开第二次。"""
    driver, _profile, _result = _title_change(monkeypatch, "弹唱大会")

    assert driver.typed == [
        ("title_edit_input", "听歌｜新标题"),
        ("edit_notice_input", DEFAULT_NOTICE),
    ]
    assert driver.opened_entries == ["chat_room_title"], "整个标题+恢复只开一次抽屉"
    assert driver.close_attempts == 1, "这次抽屉是房名流程自己开的，由它自己关"
    assert driver.back_presses == 0, "关窗走正规 UI 操作，不盲按返回"


def test_a_normal_notice_is_left_alone_by_the_title_change(monkeypatch):
    """公告没被冲掉时，房名变更不该多写一次公告。"""
    driver, profile, _result = _title_change(monkeypatch, "今晚八点开播，记得来听")

    assert driver.typed == [("title_edit_input", "听歌｜新标题")]
    assert profile.pending_notice_restore is False
    assert profile.restore_notice_content is None


# --------------------------------------------------------------------------
# 窗口内的公告核对（全量审计那一步）
# --------------------------------------------------------------------------


def test_the_audit_restores_a_notice_the_system_wiped():
    driver = _driver(drawer_open=True)
    profile = _profile(
        driver,
        handler=_Handler("蹲一个人 蹲了那么久", config=CONFIG),
    )

    result = profile._audit_notice_in_open_window()

    assert result == {"success": True, "restored_notice": DEFAULT_NOTICE}
    assert driver.typed == [("edit_notice_input", DEFAULT_NOTICE)]
    assert profile.drafts.pending("notice") is None
    assert profile.drafts.can_apply_now("notice") is False


def test_the_audit_leaves_a_normal_notice_alone():
    driver = _driver(drawer_open=True)
    profile = _profile(driver, handler=_Handler("今晚八点开播", config=CONFIG))

    result = profile._audit_notice_in_open_window()

    assert result == {"status": "notice_normal", "current_text": "今晚八点开播"}
    assert driver.clicks == [], "公告正常就一个点击都不该有"


def test_the_audit_skips_when_the_edit_entry_is_not_visible():
    driver = _driver(drawer_open=True, present=('slide_drawer',))
    profile = _profile(driver, handler=_Handler("蹲一个人", config=CONFIG))

    result = profile._audit_notice_in_open_window()

    assert result == {"skipped": "edit_notice_entry not visible"}
    assert driver.clicks == []


def test_the_audit_writes_inside_the_window_the_audit_already_opened():
    """「核对并修正」必须发生在同一次抽屉会话里，不额外开窗。"""
    journal = []
    driver = _driver(journal=journal)
    profile = _profile(driver, handler=_Handler("蹲一个人", config=CONFIG))

    results = profile.audit_and_repair()

    assert results["notice"] == {"success": True, "restored_notice": DEFAULT_NOTICE}
    assert driver.opened_entries == ["chat_room_title"]
    assert journal.count("drawer:open:chat_room_title") == 1


# --------------------------------------------------------------------------
# 默认公告（开房之后设置一次）
# --------------------------------------------------------------------------


async def test_set_default_notice_queues_the_configured_default():
    profile = _profile(_driver(), handler=_Handler(config=CONFIG))

    result = await profile.set_default_notice()

    assert result["success"] is True
    assert profile.drafts.pending("notice") == DEFAULT_NOTICE


async def test_set_default_notice_without_configuration_reports_it():
    profile = _profile(_driver(), handler=_Handler(config={}))

    result = await profile.set_default_notice()

    assert result == {"error": "No default_notice configuration found"}


# --------------------------------------------------------------------------
# :notice 命令退化成薄适配器
# --------------------------------------------------------------------------


def _command_with_profile(profile):
    from ushareiplay.commands.notice import NoticeCommand

    handler = _Handler()
    controller = SimpleNamespace(soul_handler=handler, music_handler=None)
    command = NoticeCommand(controller)
    command._room_profile_manager = profile
    return command


def test_the_notice_command_keeps_the_reply_templates_it_always_had():
    from ushareiplay.commands.notice import NoticeCommand

    assert NoticeCommand.handler_attr == "soul_handler"
    assert NoticeCommand.error_message == "Failed to process notice command: {error}"


async def test_the_notice_command_delegates_the_change_to_the_room_profile_manager():
    seen = {}

    def _set_notice(text):
        seen["set_notice"] = text
        return {"success": True, "notice": text, "message": "Notice will be updated soon"}

    profile = _profile(_driver())
    profile.set_notice = _set_notice
    command = _command_with_profile(profile)

    result = await command.process({}, ["今晚", "八点开播"])

    assert seen["set_notice"] == "今晚 八点开播"
    assert result == {"notice": "今晚 八点开播"}


async def test_the_notice_command_still_reports_the_cooldown_wording():
    profile = _profile(_driver())
    profile.set_notice = lambda text: {
        "cooldown": True,
        "remaining_minutes": 14,
        "pending_notice": text,
        "message": "Notice will be updated in 14 minutes",
    }
    command = _command_with_profile(profile)

    result = await command.process({}, ["今晚八点开播"])

    assert result == {"notice": "今晚八点开播. Notice will update in 14 minutes"}


async def test_the_notice_command_reports_an_error_with_its_own_wording():
    profile = _profile(_driver())
    profile.set_notice = lambda text: {"error": "Failed to find edit notice entry"}
    command = _command_with_profile(profile)

    result = await command.process({}, ["今晚八点开播"])

    assert result == {"error": "Failed to update notice: Failed to find edit notice entry"}


async def test_the_notice_command_without_parameters_asks_for_the_text():
    profile = _profile(_driver())
    command = _command_with_profile(profile)

    result = await command.process({}, [])

    assert result == {"error": "Missing notice parameter"}


async def test_the_notice_command_tick_delegates_to_the_room_profile_manager():
    calls = []
    profile = _profile(_driver())
    profile.update_notice = lambda: calls.append("update_notice") or {
        "skipped": "no_pending_notice"
    }
    command = _command_with_profile(profile)

    command.update()

    assert calls == ["update_notice"]


async def test_the_notice_command_never_reaches_for_the_legacy_notice_manager():
    """`:notice` 的每一次调用都必须落在房间档案这一个模块上。"""
    import ushareiplay.commands.notice as notice_module

    source = open(notice_module.__file__, encoding="utf-8").read()

    assert "NoticeManager" not in source
    assert "notice_manager" not in source