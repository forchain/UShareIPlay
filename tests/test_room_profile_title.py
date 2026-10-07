"""房间名（标题 + 主题）这一条纵切片的离线测试。

房名原先由 `RoomNameManager` 独自持有：`{theme}｜{title}` 不变量、10 分钟共享
冷却、抽屉里的标题点击 ritual，以及「改房名会把公告冲掉，改完要补回去」。现在
这些都在 `RoomProfileManager` 里，UI 那一层走抽屉端口，因此这里不需要 Android。

形状与话题（#390）/ 公告（#391）两条纵切一致：**setter 只排队，独立的 tick 才
写 UI**。因此本文件考的是：

- ADR-0001 不变量端到端成立：写进输入框的字符串就是 `{theme}｜{title}`，
  分隔符是全角 `｜`（U+FF5C），拆分只切第一个，标题里的分隔符在入库前就被截断
- 主题不单独占冷却预算 —— 它跟着房名走（共享的 10 分钟）
- 冷却是硬闸门：冷却中 / 没有待写入房名时，一个 UI 动作都不发生，也不打日志
- 他人房间跳过时不记账：草稿留着、预算留着、公屏不播报
- 抽屉由本模块自己开、自己关；关闭走正规 UI 操作而不是盲按返回键

`SoulDrawerDriver` 把同一组原语接到真实 handler 上的映射在
`test_room_profile_manager.py` 里考，本文件不重复。
"""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from ushareiplay.core.message_dispatch import MessageDispatch
from ushareiplay.managers.room_profile import RoomProfileManager
from ushareiplay.state.room_state import RoomState
from tests.fakes.in_memory_room_profile_drawer import InMemoryRoomProfileDrawerDriver

# 全角竖线 U+FF5C —— ADR-0001 的分隔符，写入与拆分两侧都必须是它。
FULLWIDTH_SEPARATOR = "｜"
# 抽屉打开时的屏幕，以及标题编辑层弹出时多出来的东西。
TITLE_DRAWER = (
    'slide_drawer',
    'title_edit_entry',
    'title_edit_input',
    'title_edit_confirm',
)
# 抽屉刚打开、还没有编辑层：编辑入口点得着，输入框还没有。
DRAWER_ONLY = ('slide_drawer', 'title_edit_entry')
# 提交成功之后编辑层消失，抽屉回到带铅笔的那一层。
BACK_TO_DRAWER = ('slide_drawer', 'title_edit_entry')
# 抽屉里的公告那一行（房名写入后要就地恢复被冲掉的公告）。
NOTICE_LAYER = (
    'edit_notice_entry',
    'close_notice',
    'customize_notice_button',
    'edit_notice_input',
    'edit_notice_confirm',
)
DEFAULT_THEME = "听歌"
DEFAULT_TITLE = "听歌"
SYSTEM_DEFAULT_NOTICES = ["弹唱大会", "Souler们在随便聊聊ing", "蹲一个人"]
DEFAULT_NOTICE = "U Share I Play\n分享音乐 享受快乐"

CONFIG = {
    "default_theme": DEFAULT_THEME,
    "default_title": DEFAULT_TITLE,
    "default_notice": DEFAULT_NOTICE,
    "system_default_notices": SYSTEM_DEFAULT_NOTICES,
}


@pytest.fixture(autouse=True)
def reset_room_profile_manager():
    RoomProfileManager.reset_instance()
    yield
    RoomProfileManager.reset_instance()


def _screen_messages(monkeypatch):
    """记录写进公屏的每一条消息 —— 「有没有宣布成功」必须能被断言。"""
    sent = []
    monkeypatch.setattr(
        MessageDispatch.instance(),
        "send_screen_message",
        lambda message, silent=False: sent.append(message),
    )
    return sent


class _RoomTextFinder:
    """房名与公告的两次判定读。

    抽屉端口只建模物理动作（探测 / 点 / 等 / 写）。「读一次当前房名看审核有没有
    通过」与「读一次当前公告看它是不是被系统冲掉了」都只是判定，因此走 handler
    的 element_finder，与公告那条纵切同一个形状。
    """

    def __init__(self, room_title_text="听歌｜晚安", notice_text=""):
        self.room_title_text = room_title_text
        self.notice_text = notice_text
        self.room_name_element = object()
        self.notice_element = object()
        self.reads = []

    def wait_for_element(self, key, timeout=10):
        self.reads.append(key)
        return {
            "room_name_in_dialog": self.room_name_element,
            "chat_room_notice": self.notice_element,
        }.get(key)

    def try_find_element(self, key, log=False):
        return self.wait_for_element(key)

    def get_element_text(self, element):
        if element is self.notice_element:
            return self.notice_text
        return self.room_title_text


class _Handler:
    """房名那条路只需要：抽屉（走端口）、配置、以及那两次判定读。"""

    def __init__(self, room_title_text="听歌｜晚安", notice_text="", config=None):
        self.logger = MagicMock()
        self.key_actions = MagicMock()
        self.key_actions.switch_to_app.return_value = True
        self.element_finder = _RoomTextFinder(room_title_text, notice_text)
        self.config = CONFIG if config is None else config

    def log_error(self, _message):
        return None


def _profile(driver=None, handler=None):
    profile = RoomProfileManager.initialize(
        handler=handler or _Handler(), drawer_driver=driver
    )
    # 确认提交后的静默等待是真实 Appium 时序，离线测试直接跳过。
    profile.title_settle_seconds = 0
    return profile


def _driver(**kwargs):
    kwargs.setdefault("present", TITLE_DRAWER)
    kwargs.setdefault(
        "world_after_click", {"title_edit_confirm": BACK_TO_DRAWER}
    )
    return InMemoryRoomProfileDrawerDriver(**kwargs)


def _typed_room_name(driver):
    """写进标题输入框的那一条字符串（房名的完整形态）。"""
    typed = [text for key, text in driver.typed if key == 'title_edit_input']
    assert len(typed) == 1, f"房名输入框应该正好被写一次，实际 {driver.typed}"
    return typed[0]


# --------------------------------------------------------------------------
# ADR-0001 不变量：`{theme}｜{title}` 端到端成立
# --------------------------------------------------------------------------


def test_the_room_name_written_to_the_ui_is_theme_separator_title():
    """ADR-0001：写进 UI 的完整房名就是 `{theme}｜{title}`，分隔符是全角 ｜。"""
    driver = _driver()
    profile = _profile(driver)

    profile.set_title("晚安", theme="三福")
    profile.update_title()

    room_name = _typed_room_name(driver)
    assert room_name == f"三福{FULLWIDTH_SEPARATOR}晚安"
    # 全角竖线 U+FF5C，不是半角 |，也不是 CJK 的 丨(U+4E28)。
    assert FULLWIDTH_SEPARATOR in room_name
    assert "|" not in room_name
    assert "丨" not in room_name


def test_a_title_without_an_explicit_theme_keeps_the_configured_default_theme():
    """没排过主题时，房名仍带配置里的默认主题，不能写成 `None｜标题`。"""
    driver = _driver()
    profile = _profile(driver)

    profile.set_title("晚安")
    profile.update_title()

    assert _typed_room_name(driver) == f"{DEFAULT_THEME}{FULLWIDTH_SEPARATOR}晚安"


def test_the_separator_is_the_fullwidth_vertical_line_and_only_the_first_one_splits():
    """maxsplit=1：第一个分隔符之后全部是标题（与既有实现一致）。"""
    profile = _profile()

    assert profile.parse_room_title("三福｜Lofi Girl") == ("三福", "Lofi Girl")
    assert profile.parse_room_title("三福｜Lofi｜Girl") == ("三福", "Lofi｜Girl")
    assert profile.parse_room_title("没有分隔符") is None


@pytest.mark.parametrize(
    "user_text",
    ["夜曲｜周杰伦", "夜曲|周杰伦", "夜曲丨周杰伦", "夜曲(周杰伦", "夜曲（周杰伦"],
)
def test_a_title_containing_any_separator_is_truncated_before_it_is_stored(user_text):
    """标题里不可能带分隔符：`clean_banner_text` 在入库前就截断了。

    截断集合 `('|','｜','丨','(','（')` 是既有行为，一个字都不许改。
    """
    profile = _profile()

    profile.set_title(user_text)

    assert profile.drafts.pending("title") == "夜曲"
    assert FULLWIDTH_SEPARATOR not in profile.drafts.pending("title")


def test_the_theme_length_is_checked_before_stripping_like_the_legacy_manager_did():
    """既有的长度判定在 strip 之前，带空格的主题同样超限 —— 逐字保留。"""
    profile = _profile()

    assert profile.set_theme("  听歌  ") == {"error": "主题最多两个字符"}
    assert profile.drafts.pending_theme() is None


def test_initialize_from_ui_splits_theme_and_title_with_the_same_invariant():
    profile = _profile(handler=_Handler(room_title_text="三福｜Lofi Girl"))

    result = profile.initialize_from_ui()

    assert result == {
        'success': True,
        'theme': '三福',
        'title': 'Lofi Girl',
        'initialized': True,
    }
    assert profile.get_current_theme() == "三福"
    assert profile.get_current_title() == "Lofi Girl"


def test_initialize_from_ui_does_not_clobber_a_theme_that_is_waiting_to_be_written():
    """主题变更待生效时，UI 读不得把排队中的主题顶掉。"""
    handler = _Handler(room_title_text="旧主题｜旧标题")
    profile = _profile(handler=handler)
    profile.set_theme("三福")

    profile.initialize_from_ui()

    assert profile.get_current_theme() == "三福", "有主题在排队，UI 读不得覆盖它"
    assert profile.get_current_title() == "旧标题"


# --------------------------------------------------------------------------
# 共享冷却：主题跟着房名走
# --------------------------------------------------------------------------


def test_the_room_name_budget_is_ten_minutes():
    profile = _profile()

    assert profile.drafts.cooldown_minutes("title") == 10


def test_a_theme_change_spends_the_shared_room_name_budget_not_its_own():
    """主题不单独占冷却：它只是房名草稿的前缀（ADR-0001）。"""
    profile = _profile()

    profile.set_theme("三福")
    assert profile.drafts.can_apply_now("title") is True, "排队本身不烧预算"

    profile.drafts.mark_attempted("title")

    assert profile.drafts.can_apply_now("notice") is True
    assert profile.drafts.can_apply_now("topic") is True


def test_set_title_only_queues_and_never_touches_the_ui():
    driver = _driver()
    profile = _profile(driver)

    result = profile.set_title("晚安")

    assert result == {"title": "晚安. Title will update soon"}
    assert profile.drafts.pending("title") == "晚安"
    assert driver.opened_entries == [], "排队本身不碰 UI"
    assert driver.typed == []


def test_set_title_reports_the_remaining_cooldown_of_the_shared_budget():
    profile = _profile(_driver())
    profile.drafts.mark_attempted("title")

    result = profile.set_title("Lofi Girl")

    assert result == {"title": "Lofi Girl. Title will update in 9 minutes"}
    assert profile.drafts.pending("title") == "Lofi Girl", "冷却中也要记住用户要写什么"


def test_set_title_refuses_a_theme_that_set_theme_would_refuse():
    profile = _profile()

    result = profile.set_title("Lofi Girl", theme="三福福")

    assert result == {"error": "主题最多两个字符"}
    assert profile.drafts.pending("title") is None, "主题不合法时标题不该被排队"


# --------------------------------------------------------------------------
# tick 写 UI
# --------------------------------------------------------------------------


def test_update_title_writes_the_room_name_through_the_drawer_port():
    driver = _driver()
    profile = _profile(driver)
    profile.set_title("晚安")

    result = profile.update_title()

    assert result == {"ui_updated": True, "current_title": "晚安"}
    assert driver.opened_entries == ["chat_room_title"]
    assert driver.clicks == ["title_edit_entry", "title_edit_confirm"]
    assert _typed_room_name(driver) == f"{DEFAULT_THEME}{FULLWIDTH_SEPARATOR}晚安"
    assert profile.drafts.pending("title") is None, "写成功后草稿清空"


def test_update_title_closes_the_drawer_it_opened_without_a_blind_back_press():
    """拆窗不再盲按返回键：先点遮罩关，只有遮罩关不掉才退化为一次保底。"""
    driver = _driver()
    profile = _profile(driver)
    profile.set_title("晚安")

    profile.update_title()

    assert driver.close_attempts == 1
    assert driver.back_presses == 0, "抽屉能被正规关窗操作关掉时不得盲按返回"
    assert driver.is_open() is False


def test_update_title_leaves_a_drawer_the_outer_flow_opened():
    """窗口是外层流程打开的时候，房名流程不负责关它。"""
    driver = _driver(drawer_open=True)
    profile = _profile(driver)
    profile.set_title("晚安")

    profile.update_title()

    assert driver.opened_entries == [], "已经开着就不该再点一次入口"
    assert driver.close_attempts == 0
    assert driver.back_presses == 0
    assert driver.is_open() is True


def test_a_theme_only_change_rewrites_the_whole_room_name():
    """只改主题也要重写完整房名 —— 否则 Soul 侧的主题不会变。"""
    driver = _driver()
    profile = _profile(driver, handler=_Handler(room_title_text="听歌｜Lofi Girl"))
    profile.initialize_from_ui()  # current_title = "Lofi Girl", theme = "听歌"
    profile.set_theme("三福")

    result = profile.update_title()

    assert result == {"ui_updated": True, "current_title": "Lofi Girl"}
    assert _typed_room_name(driver) == f"三福{FULLWIDTH_SEPARATOR}Lofi Girl"


def test_update_title_refuses_to_touch_the_ui_while_the_cooldown_is_running():
    driver = _driver()
    profile = _profile(driver)
    profile.set_title("晚安")
    profile.update_title()  # 第一次写入成功，预算用掉

    driver.clicks.clear()
    driver.typed.clear()
    profile.set_title("早安")  # 冷却中：只排队

    result = profile.update_title()

    assert result == {"cooldown": True, "remaining_minutes": 9}
    assert driver.clicks == [], "冷却中一个点击都不该有"
    assert driver.typed == []
    assert profile.drafts.pending("title") == "早安"


def test_update_title_skips_silently_when_nothing_is_queued():
    driver = _driver()
    profile = _profile(driver)

    result = profile.update_title()

    assert result == {"skipped": True, "reason": "no pending update"}
    assert driver.is_open_calls == 0, "没有活可干就不要去探测抽屉"
    for level in ("info", "warning", "error"):
        getattr(profile.logger, level).assert_not_called(), "空闲分支不许刷日志"


def test_a_failed_write_keeps_the_title_queued_for_the_next_cooldown():
    driver = _driver(present=('slide_drawer', 'title_edit_entry'))  # 没有输入框
    profile = _profile(driver)
    profile.set_title("晚安")

    result = profile.update_title()

    assert result == {"error": "Failed to find title input"}
    assert profile.drafts.pending("title") == "晚安", "失败必须留着草稿等下个周期重试"
    assert profile.drafts.can_apply_now("title") is False, "失败也占用本轮预算"


def test_a_rejected_submit_closes_the_edit_layer_and_reports_the_cooldown():
    """提交被拒时编辑层还开着：先把它收起，别留在屏幕上。"""
    driver = InMemoryRoomProfileDrawerDriver(
        present=('slide_drawer', 'title_edit_entry', 'title_edit_input',
                 'title_edit_confirm', 'go_back'),
        # 编辑层没消失：抽屉里那行铅笔被编辑层盖住，等不到它，只等得到确认键。
        world_after_click={
            "title_edit_confirm": (
                'slide_drawer',
                'title_edit_input',
                'title_edit_confirm',
                'go_back',
            )
        },
    )
    profile = _profile(driver)
    profile.set_title("晚安")

    result = profile.update_title()

    assert result == {"error": "Update failed - still in cooldown period"}
    assert "go_back" in driver.clicks, "编辑层没收起来"
    assert driver.close_attempts == 1
    assert profile.drafts.pending("title") == "晚安"


def test_an_unreachable_drawer_reports_the_callers_own_error_text():
    driver = _driver(fail_for=('chat_room_title', 'room_topic'))
    profile = _profile(driver)
    profile.set_title("晚安")

    result = profile.update_title()

    assert result == {"error": "Failed to find room title"}
    assert driver.opened_entries == ["chat_room_title", "room_topic"]


# --------------------------------------------------------------------------
# 他人房间：跳过一次写入不等于写成功了
# --------------------------------------------------------------------------


def test_a_guest_room_skip_does_not_bookkeep_the_room_name_write(monkeypatch):
    """别人房间里一个点击都没发生：草稿留着、预算留着、公屏也不播报。"""
    sent = _screen_messages(monkeypatch)
    driver = _driver()
    profile = _profile(driver)
    profile.set_title("晚安")  # 自己的房间里排队
    assert profile.drafts.last_attempt_at("title") is None

    # 排队之后房间变成了别人的 —— 这是这条闸门真正要防的竞态。
    RoomState.reset_instance()
    room_state = RoomState.initialize()
    room_state.is_guest_room = True
    try:
        result = profile.update_title()
    finally:
        RoomState.reset_instance()

    assert result == {"skipped": True, "reason": "guest_room"}
    assert profile.drafts.pending("title") == "晚安"
    assert profile.drafts.last_attempt_at("title") is None, "没写成就别烧冷却预算"
    assert profile.drafts.can_apply_now("title") is True
    assert sent == [], "没有发生的变更不得播报到公屏"
    assert driver.opened_entries == [], "别人房间里一次点击都不该有"


def test_a_guest_room_refuses_the_theme_before_the_length_check():
    """既有次序：他人房间的拒绝先于主题长度校验。"""
    RoomState.reset_instance()
    room_state = RoomState.initialize()
    room_state.is_guest_room = True
    try:
        profile = _profile()
        assert profile.set_theme("三福福") == {"error": "他人房间模式下不可修改房间主题"}
    finally:
        RoomState.reset_instance()


# --------------------------------------------------------------------------
# 审核未通过的自愈
# --------------------------------------------------------------------------


def test_a_room_name_the_moderation_stripped_queues_the_default_title():
    """写完之后房名里没有分隔符 = 审核没通过：排一次默认标题重设。"""
    handler = _Handler(room_title_text="晚安")  # 被系统吃得只剩标题
    profile = _profile(handler=handler, driver=_driver())
    profile.set_title("晚安")

    profile.update_title()

    assert profile.drafts.pending("title") == DEFAULT_TITLE
    assert profile.drafts.can_apply_now("title") is False


def test_a_kept_room_name_does_not_queue_anything_extra():
    driver = _driver()
    profile = _profile(handler=_Handler(room_title_text="听歌｜晚安"), driver=driver)
    profile.set_title("晚安")

    profile.update_title()

    assert profile.drafts.pending("title") is None


# --------------------------------------------------------------------------
# 公告恢复：判定留在房名流程，写入归公告那条纵切
# --------------------------------------------------------------------------


def _title_change_with_notice(notice_text):
    """跑一次真实的房名写入（抽屉里公告那一行也在屏幕上），返回 `(driver, profile)`。"""
    present = TITLE_DRAWER + (
        'edit_notice_entry',
        'close_notice',
        'customize_notice_button',
        'edit_notice_input',
        'edit_notice_confirm',
    )
    driver = InMemoryRoomProfileDrawerDriver(
        present=present,
        world_after_click={
            # 提交之后抽屉还在，公告那一行照旧可点。
            "title_edit_confirm": BACK_TO_DRAWER + NOTICE_LAYER,
            "edit_notice_confirm": ('edit_notice_entry',),
        },
    )
    handler = _Handler(room_title_text="听歌｜晚安", notice_text=notice_text)
    profile = _profile(handler=handler, driver=driver)
    profile.set_title("晚安")
    profile.update_title()
    return driver, profile


def test_a_title_change_that_wiped_the_notice_restores_the_previous_text():
    """改房名会把公告冲成系统默认文案；改完要把上一条公告写回去。"""
    driver, profile = _title_change_with_notice("蹲一个人 蹲了那么久，终于等到你！")

    assert driver.typed == [
        ('title_edit_input', f"{DEFAULT_THEME}{FULLWIDTH_SEPARATOR}晚安"),
        ('edit_notice_input', DEFAULT_NOTICE),
    ]
    assert profile.pending_notice_restore is False, "恢复标记用完即清"
    assert profile.restore_notice_content is None


def test_the_restore_after_a_title_change_reuses_the_same_drawer_session():
    """恢复公告发生在房名流程已经打开的那个抽屉会话里，不再开第二次。"""
    driver, _profile = _title_change_with_notice("弹唱大会")

    assert driver.opened_entries == ["chat_room_title"], "整个标题+恢复只开一次抽屉"


def test_a_normal_notice_is_left_alone_by_the_title_change():
    """公告没被冲掉时，房名变更不该多写一次公告。"""
    driver, profile = _title_change_with_notice("今晚八点开播，记得来听")

    assert driver.typed == [
        ('title_edit_input', f"{DEFAULT_THEME}{FULLWIDTH_SEPARATOR}晚安")
    ]
    assert profile.pending_notice_restore is False


def test_a_broken_notice_restore_does_not_undo_the_room_name_write():
    """恢复公告失败只记日志 —— 已经写成功的房名不能因此变成一次失败。"""
    present = TITLE_DRAWER + NOTICE_LAYER
    driver = InMemoryRoomProfileDrawerDriver(
        present=present,
        world_after_click={"title_edit_confirm": present},
    )
    handler = _Handler(room_title_text="听歌｜晚安", notice_text="弹唱大会")
    profile = _profile(handler=handler, driver=driver)

    def _boom(_notice):
        raise RuntimeError("drawer exploded")

    profile.restore_notice = _boom
    profile.set_title("晚安")

    result = profile.update_title()

    assert result == {"ui_updated": True, "current_title": "晚安"}
    assert _typed_room_name(driver) == f"{DEFAULT_THEME}{FULLWIDTH_SEPARATOR}晚安"
    assert profile.pending_notice_restore is False, "恢复标记用完即清"


# --------------------------------------------------------------------------
# `:title` / `:theme` 两个命令只是接缝上的薄适配器
# --------------------------------------------------------------------------


def _command_with_profile(profile):
    from ushareiplay.commands.theme import ThemeCommand
    from ushareiplay.commands.title import TitleCommand

    handler = _Handler()
    controller = SimpleNamespace(soul_handler=handler, music_handler=None)
    return {
        'title': TitleCommand(controller),
        'theme': ThemeCommand(controller),
        'handler': handler,
    }


def test_the_title_and_theme_commands_keep_the_handler_attr_and_error_text_they_always_had():
    """config.yaml 的 `{title}` / `{theme}` 模板靠这些类属性与返回 dict 的键对上。"""
    from ushareiplay.commands.theme import ThemeCommand
    from ushareiplay.commands.title import TitleCommand

    assert TitleCommand.handler_attr == "soul_handler"
    assert TitleCommand.error_message == "Failed to process title command: {error}"
    assert ThemeCommand.handler_attr == "soul_handler"
    assert ThemeCommand.error_message == "处理主题命令失败: {error}"


async def test_the_title_command_delegates_to_the_room_profile_manager():
    profile = _profile(_driver())
    seen = {}
    profile.set_title = lambda title, theme=None: seen.update(
        title=title, theme=theme
    ) or {"title": "晚安. Title will update soon"}
    command = _command_with_profile(profile)['title']
    command._room_profile_manager = profile

    result = await command.process({}, ["晚安"])

    assert seen == {"title": "晚安", "theme": None}
    assert result == {"title": "晚安. Title will update soon"}


async def test_the_title_command_composes_the_two_parameter_reply_unchanged():
    profile = _profile(_driver())
    profile.set_title = lambda title, theme=None: {"title": "晚安. Title will update soon"}
    command = _command_with_profile(profile)['title']
    command._room_profile_manager = profile

    result = await command.process({}, ["晚安", "三福"])

    assert result == {"title": "主题: 三福\n晚安. Title will update soon"}


async def test_the_title_command_tick_delegates_to_the_room_profile_manager():
    calls = []
    profile = _profile(_driver())
    profile.current_title = '晚安'
    profile.update_title = lambda: calls.append("update_title") or {
        'ui_updated': True,
        'current_title': profile.get_current_title(),
    }
    command = _command_with_profile(profile)['title']
    command._room_profile_manager = profile
    command._message_dispatch = SimpleNamespace(
        send_screen_message=lambda message: calls.append(message)
    )

    command.update()

    assert calls == ["update_title", "标题已更新为: 晚安"]


async def test_the_theme_command_reports_status_from_the_room_profile_manager():
    profile = _profile(_driver())
    profile.drafts.set_pending("title", "晚安")
    profile.drafts.mark_attempted("title")
    command = _command_with_profile(profile)['theme']
    command._room_profile_manager = profile

    result = await command.process({}, [])

    assert result["theme"] == (
        f"当前主题: {DEFAULT_THEME}\n"
        "当前标题: 未设置\n"
        "即将更新标题: 晚安\n"
        "剩余更新时间: 9分钟"
    )


async def test_the_theme_command_keeps_its_cooldown_wording():
    profile = _profile(_driver())
    profile.set_theme = lambda theme: {"success": True, "theme": theme, "old_theme": None}
    profile.verify_theme = lambda theme: {"success": True, "theme": theme}
    profile.update_title = lambda: {"cooldown": True, "remaining_minutes": 9}
    command = _command_with_profile(profile)['theme']
    command._room_profile_manager = profile

    result = await command.process({}, ["三福"])

    assert result == {
        'theme': "主题已更新为: 三福",
        'ui_update': "房间标题更新被冷却时间阻止，还需等待9分钟",
    }


def test_the_title_and_theme_commands_never_reach_for_the_legacy_room_name_manager():
    """:title / :theme 的每一次调用都必须落在房间档案这一个模块上。"""
    import pathlib

    import ushareiplay.commands.theme as theme_module
    import ushareiplay.commands.title as title_module

    for module in (title_module, theme_module):
        source = pathlib.Path(module.__file__).read_text(encoding="utf-8")
        assert "RoomNameManager" not in source
        assert "room_name_manager" not in source


def test_the_room_name_manager_module_is_gone():
    """旧的房名模块随这条纵切下线 —— 房名只有 RoomProfileManager 一个所有者。"""
    import pathlib

    source_root = pathlib.Path(__file__).resolve().parents[1] / "src" / "ushareiplay"
    assert not (source_root / "managers" / "room_name_manager.py").exists()


# --------------------------------------------------------------------------
# 标题编辑入口的点击坐标
# --------------------------------------------------------------------------
#
# 旧 `room_name_manager` 点 `title_edit_entry` 用的是
# `gesture_handler.click_element_at(edit_entry, y_ratio=0.25)` —— 点在元素上缘而
# 不是中心。这是随主题功能一起上线的既有行为，抽屉端口必须能表达它。


def test_the_title_entry_is_tapped_at_the_quarter_height_the_legacy_manager_used():
    driver = _driver()
    profile = _profile(driver)
    profile.set_title("晚安")

    profile.update_title()

    assert driver.coordinate_clicks == [("title_edit_entry", 0.25)], (
        "标题编辑入口必须沿用 0.25 高度那次点击，不得退化成中心点击"
    )


def test_only_the_title_entry_uses_the_coordinate_tap():
    driver = _driver()
    profile = _profile(driver)
    profile.set_title("晚安")

    profile.update_title()

    assert [key for key, _ratio in driver.coordinate_clicks] == ["title_edit_entry"]
