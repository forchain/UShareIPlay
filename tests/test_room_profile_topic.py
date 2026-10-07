"""房间话题这一条纵切片的离线测试。

话题原先由 `TopicManager` 独自持有：冷却时钟、`clean_banner_text`、黑板点击
ritual，以及拆窗时连按三次 `press_back()`。现在这些都在 `RoomProfileManager`
里，UI 那一层走抽屉端口，因此这里不需要 Android。

考的东西：

- 冷却是硬闸门：冷却中 / 没有待写入话题时，一个 UI 动作都不发生，也不打日志
- 黑板的每一次点击与输入都经过端口替身，因此断言的是「点了哪些 key」而不是
  某一行 Appium 代码
- **拆窗不再盲按返回键**：正常路径 `back_presses == 0`；正规关窗失效时也只有
  一次保底，而不是原先的三次

`SoulDrawerDriver` 把同一组原语接到真实 handler 上的映射在
`test_room_profile_manager.py` 里考，本文件不重复。
"""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from ushareiplay.managers.room_profile import RoomProfileManager
from ushareiplay.state.room_state import RoomState
from tests.fakes.in_memory_room_profile_drawer import InMemoryRoomProfileDrawerDriver

# 编辑层打开时抽屉里有的东西（`config.yaml` 的 elements key）。
TOPIC_EDIT_LAYER = ('edit_topic_entry', 'edit_topic_input', 'edit_topic_confirm')
# 确认提交之后回到主房间界面：聊天输入框出现。
BACK_TO_ROOM = ('input_box_entry',)


@pytest.fixture(autouse=True)
def reset_room_profile_manager():
    RoomProfileManager.reset_instance()
    yield
    RoomProfileManager.reset_instance()


class _Handler:
    """话题只需要切前台；抽屉与黑板都走端口，不走 handler。"""

    def __init__(self, can_switch=True):
        self.logger = MagicMock()
        self.key_actions = MagicMock()
        self.key_actions.switch_to_app.return_value = can_switch


def _topic_profile(driver=None, can_switch=True):
    profile = RoomProfileManager.initialize(
        handler=_Handler(can_switch), drawer_driver=driver
    )
    # 确认提交后的静默等待是真实 Appium 时序，离线测试直接跳过。
    profile.topic_settle_seconds = 0
    return profile


def _driver(**kwargs):
    kwargs.setdefault("present", TOPIC_EDIT_LAYER)
    kwargs.setdefault("world_after_click", {"edit_topic_confirm": BACK_TO_ROOM})
    return InMemoryRoomProfileDrawerDriver(**kwargs)


# --------------------------------------------------------------------------
# 冷却是硬闸门
# --------------------------------------------------------------------------


def test_the_topic_budget_is_five_minutes():
    profile = _topic_profile()

    assert profile.drafts.cooldown_minutes("topic") == 5


def test_set_topic_stores_the_cleaned_draft_and_the_five_minute_reply():
    driver = _driver()
    profile = _topic_profile(driver)

    result = profile.set_topic("  晚安 | 早点睡  ")

    assert result == {"topic": "晚安. Topic will update soon"}
    assert profile.drafts.pending("topic") == "晚安"
    assert driver.clicks == [], "排队本身不碰 UI"


def test_set_topic_reports_the_remaining_cooldown_and_still_remembers_the_draft():
    profile = _topic_profile(_driver())
    profile.drafts.mark_attempted("topic")

    result = profile.set_topic("夜曲")

    assert result == {"topic": "夜曲. Topic will update in 4 minutes"}
    assert profile.drafts.pending("topic") == "夜曲"


def test_update_topic_writes_through_when_the_budget_is_free():
    driver = _driver()
    profile = _topic_profile(driver)
    profile.set_topic("夜曲")

    result = profile.update_topic()

    assert result == {"success": True, "topic": "夜曲"}
    assert driver.opened_entries == ["room_topic"]
    assert driver.typed == [("edit_topic_input", "夜曲")]


def test_update_topic_refuses_to_touch_the_ui_while_the_cooldown_is_running():
    driver = _driver()
    profile = _topic_profile(driver)
    profile.set_topic("夜曲")
    profile.update_topic()  # 第一次写入成功，预算用掉

    driver.clicks.clear()
    driver.typed.clear()
    profile.set_topic("周曲")  # 冷却中：只排队

    result = profile.update_topic()

    assert "error" not in result
    assert driver.clicks == [], "冷却中是硬闸门，一个点击都不该发生"
    assert driver.typed == []
    assert driver.back_presses == 0
    assert profile.drafts.pending("topic") == "周曲", "下一次冷却到期后还要写"


def test_update_topic_becomes_writable_again_once_the_five_minutes_have_passed():
    driver = _driver()
    profile = _topic_profile(driver)
    profile.set_topic("夜曲")
    profile.update_topic()
    profile.drafts.set_last_attempt_at("topic", datetime.now() - timedelta(minutes=5))

    # 第一次写入之后屏幕真的回到了主房间，第二次要重新打开抽屉编辑层。
    driver.present = set(TOPIC_EDIT_LAYER)
    profile.set_topic("周曲")
    result = profile.update_topic()

    assert result == {"success": True, "topic": "周曲"}


def test_update_topic_does_nothing_when_no_topic_is_queued():
    driver = _driver()
    profile = _topic_profile(driver)

    result = profile.update_topic()

    assert result == {"skipped": "no_pending_topic"}
    assert driver.opened_entries == []
    assert driver.clicks == []


def test_an_idle_tick_never_logs_anything():
    """监控铁律：轮询与冷却未到都不得刷日志。

    只有「没有待写入话题」和「冷却没到」这两条空转分支必须完全安静；用户真的
    下过指令、真的写成功了，那是有行为触发，该打就打。
    """
    driver = _driver()
    profile = _topic_profile(driver)
    profile.set_topic("夜曲")
    profile.update_topic()  # 真实写入，把预算用掉
    profile.set_topic("周曲")

    levels = ("debug", "info", "warning", "error")
    for level in levels:
        getattr(profile.logger, level).reset_mock()

    profile.update_topic()  # 没有待写入
    profile.update_topic()  # 冷却中

    for level in levels:
        assert getattr(profile.logger, level).call_count == 0, f"{level} 在空转时刷屏了"


# --------------------------------------------------------------------------
# 黑板点击走 UI 端口
# --------------------------------------------------------------------------


def test_the_blackboard_click_sequence_runs_through_the_driver_port():
    driver = _driver()
    profile = _topic_profile(driver)
    profile.set_topic("夜曲")

    profile.update_topic()

    assert driver.clicks == ["edit_topic_entry", "edit_topic_confirm"]
    assert driver.typed == [("edit_topic_input", "夜曲")]


def test_the_topic_opens_the_drawer_through_the_room_topic_entry_only():
    """话题原先点的是 `room_topic`，不是默认的 `chat_room_title`。"""
    driver = _driver()
    profile = _topic_profile(driver)
    profile.set_topic("夜曲")

    profile.update_topic()

    assert driver.opened_entries == ["room_topic"]


def test_the_background_skin_edit_entry_is_used_when_the_primary_one_is_absent():
    driver = _driver(
        present=("edit_topic_bg_entry", "edit_topic_input", "edit_topic_confirm")
    )
    profile = _topic_profile(driver)
    profile.set_topic("夜曲")

    result = profile.update_topic()

    assert result == {"success": True, "topic": "夜曲"}
    assert driver.clicks[0] == "edit_topic_bg_entry"


def test_a_drawer_that_will_not_open_is_reported_without_touching_the_blackboard():
    driver = _driver(fail_for=("room_topic",))
    profile = _topic_profile(driver)
    profile.set_topic("夜曲")

    result = profile.update_topic()

    assert result == {"error": "Failed to find room topic"}
    assert driver.clicks == []
    assert driver.back_presses == 0


@pytest.mark.parametrize(
    "present, expected_error",
    [
        (("edit_topic_input", "edit_topic_confirm"), "Failed to find edit topic entry"),
        (("edit_topic_entry", "edit_topic_confirm"), "Failed to find topic input"),
        (("edit_topic_entry", "edit_topic_input"), "Failed to find confirm button"),
    ],
)
def test_a_missing_step_reports_its_own_error_and_unwinds_the_drawer(
    present, expected_error
):
    driver = _driver(present=present)
    profile = _topic_profile(driver)
    profile.set_topic("夜曲")

    result = profile.update_topic()

    assert result == {"error": expected_error}
    assert driver.close_attempts == 1, "用自己的正规关窗收回抽屉"
    assert driver.back_presses == 0


def test_the_app_reporting_the_topic_as_too_frequent_is_surfaced_to_the_caller():
    """确认后编辑层还在（风险提示盖住主界面）= 改得太频繁。"""
    driver = _driver(world_after_click={"edit_topic_confirm": ("edit_topic_confirm",)})
    profile = _topic_profile(driver)
    profile.set_topic("夜曲")

    result = profile.update_topic()

    assert result == {"error": "update topic too frequently"}
    assert profile.drafts.pending("topic") == "夜曲", "失败要保留草稿等下次冷却"


def test_an_unrecognised_post_submit_screen_is_still_reported_as_success():
    driver = _driver(world_after_click={"edit_topic_confirm": ()})
    profile = _topic_profile(driver)
    profile.set_topic("夜曲")

    result = profile.update_topic()

    assert result == {"success": True, "topic": "夜曲"}


def test_a_ui_layer_that_raises_becomes_an_error_dict_rather_than_an_exception():
    driver = _driver()

    def _boom(*_args, **_kwargs):
        raise RuntimeError("driver crashed")

    driver.wait_for_any = _boom
    profile = _topic_profile(driver)
    profile.set_topic("夜曲")

    result = profile.update_topic()

    assert result == {"error": "Failed to update topic: 夜曲"}


# --------------------------------------------------------------------------
# 拆窗不再盲按返回键（本票的核心行为变更）
# --------------------------------------------------------------------------


def test_the_topic_path_never_sends_a_blind_back_press():
    """话题这条路上不存在任何「盲按返回」—— 正常路径一次都不按。

    `TopicManager._update_topic_ui` 在收尾时连按三次 `press_back()`，那是
    spec 用户故事 #12 点名的风险：按多了会直接退出派对房间。现在拆窗走
    `with_window_open` → `ensure_closed()` 的阶梯（无弹窗标志则零次、正规
    关窗、再退化为一次保底），因此这里断言 `back_presses == 0`。
    """
    outcomes = [
        ("healthy", _driver()),
        ("missing edit entry", _driver(present=("edit_topic_input",))),
        ("missing input", _driver(present=("edit_topic_entry",))),
        ("missing confirm", _driver(present=("edit_topic_entry", "edit_topic_input"))),
        (
            "too frequent",
            _driver(world_after_click={"edit_topic_confirm": ("edit_topic_confirm",)}),
        ),
        ("drawer will not open", _driver(fail_for=("room_topic",))),
        ("driver explodes", _driver()),
    ]
    # 「driver explodes」单独接线：让点击本身抛异常。
    outcomes[-1][1].wait_for_any = lambda *_a, **_k: (_ for _ in ()).throw(
        RuntimeError("driver crashed")
    )

    for label, driver in outcomes:
        RoomProfileManager.reset_instance()
        profile = _topic_profile(driver)
        profile.set_topic("夜曲")

        profile.update_topic()

        assert driver.back_presses == 0, f"{label}: 话题路径不允许盲按返回键"


def test_the_topic_path_presses_back_exactly_once_when_the_drawer_will_not_close():
    """正规关窗失效时才退化到保底返回键 —— 一次，不是原先的三次。"""
    driver = _driver(close_drawer_works=False)
    profile = _topic_profile(driver)
    profile.set_topic("夜曲")

    profile.update_topic()

    assert driver.close_attempts == 1
    assert driver.back_presses == 1


def test_a_drawer_the_outer_flow_opened_is_neither_closed_nor_backed_out_of():
    """只关自己打开的那一次：外层开的抽屉原样留给外层。"""
    driver = _driver(drawer_open=True)
    profile = _topic_profile(driver)
    profile.set_topic("夜曲")

    profile.update_topic()

    assert driver.opened_entries == []
    assert driver.close_attempts == 0
    assert driver.back_presses == 0
    assert driver.drawer_open is True


# --------------------------------------------------------------------------
# 草稿生命周期
# --------------------------------------------------------------------------


def test_a_successful_write_clears_the_draft_and_records_the_current_topic():
    driver = _driver()
    profile = _topic_profile(driver)
    profile.set_topic("夜曲")

    profile.update_topic()

    assert profile.get_topic_status()["current_topic"] == "夜曲"
    assert profile.drafts.pending("topic") is None


def test_a_failed_write_keeps_the_draft_so_the_next_cooldown_can_retry():
    driver = _driver(present=("edit_topic_entry", "edit_topic_input"))
    profile = _topic_profile(driver)
    profile.set_topic("夜曲")

    profile.update_topic()

    assert profile.drafts.pending("topic") == "夜曲"
    assert profile.get_topic_status()["current_topic"] == "None"


def test_the_cooldown_clock_advances_before_the_ui_write_even_when_it_throws():
    """`mark_attempted` 在 UI 调用之前：抛异常也算一次尝试，不该反复重试。"""
    driver = _driver()
    driver.wait_for_any = lambda *_a, **_k: (_ for _ in ()).throw(
        RuntimeError("driver crashed")
    )
    profile = _topic_profile(driver)
    profile.set_topic("夜曲")

    profile.update_topic()

    assert profile.drafts.last_attempt_at("topic") is not None
    assert profile.drafts.remaining_minutes("topic") == 4


def test_a_guest_room_never_opens_the_drawer():
    RoomState.reset_instance()
    room_state = RoomState.initialize()
    room_state.is_guest_room = True
    try:
        driver = _driver()
        profile = _topic_profile(driver)
        profile.set_topic("夜曲")

        result = profile.update_topic()
    finally:
        RoomState.reset_instance()

    assert result == {"skipped": "guest_room"}
    assert driver.opened_entries == []
    assert driver.back_presses == 0


# --------------------------------------------------------------------------
# 状态查询面（`:topic` 无参数那一支）
# --------------------------------------------------------------------------


def test_the_status_reports_none_before_anything_has_been_written():
    profile = _topic_profile(_driver())

    assert profile.get_topic_status() == {
        "current_topic": "None",
        "next_topic": "None",
        "remaining_time": None,
    }


def test_the_status_reports_the_queued_topic_and_the_minutes_left():
    driver = _driver()
    profile = _topic_profile(driver)
    profile.set_topic("夜曲")
    profile.update_topic()
    profile.set_topic("周曲")

    status = profile.get_topic_status()

    assert status == {
        "current_topic": "夜曲",
        "next_topic": "周曲",
        "remaining_time": 4,
    }


# --------------------------------------------------------------------------
# :topic 命令退化成薄适配器
# --------------------------------------------------------------------------


def _command_with_profile(profile):
    from ushareiplay.commands.topic import TopicCommand

    handler = _Handler()
    controller = SimpleNamespace(soul_handler=handler, music_handler=None)
    command = TopicCommand(controller)
    command._room_profile_manager = profile
    return command


def test_the_topic_command_keeps_the_reply_templates_it_always_had():
    from ushareiplay.commands.topic import TopicCommand

    assert TopicCommand.handler_attr == "soul_handler"
    assert TopicCommand.error_message == "Failed to process topic command"


async def test_the_topic_command_delegates_a_change_to_the_room_profile_manager():
    seen = {}

    def _set_topic(text):
        seen["set_topic"] = text
        return {"topic": f"{text}. Topic will update soon"}

    profile = _topic_profile(_driver())
    profile.set_topic = _set_topic
    command = _command_with_profile(profile)

    result = await command.process({}, ["听歌", "自习中"])

    assert seen["set_topic"] == "听歌 自习中"
    assert result == {"topic": "听歌 自习中. Topic will update soon"}


async def test_the_topic_command_status_reply_still_matches_the_response_template():
    profile = _topic_profile(_driver())
    profile.get_topic_status = lambda: {
        "current_topic": "None",
        "next_topic": "夜曲",
        "remaining_time": 3,
    }
    command = _command_with_profile(profile)

    result = await command.process({}, [])

    assert result == {
        "topic": "Current topic: None\nNext topic: 夜曲\nWill update in 3 minute(s)"
    }


async def test_the_topic_command_tick_delegates_to_the_room_profile_manager():
    calls = []
    profile = _topic_profile(_driver())
    profile.update_topic = lambda: calls.append("update_topic") or {"skipped": "no_pending_topic"}
    command = _command_with_profile(profile)

    command.update()

    assert calls == ["update_topic"]


async def test_the_topic_command_never_reaches_for_the_legacy_topic_manager():
    """`:topic` 的每一次调用都必须落在房间档案这一个模块上。"""
    import ushareiplay.commands.topic as topic_module

    source = open(topic_module.__file__, encoding="utf-8").read()

    assert "TopicManager" not in source
    assert "topic_manager" not in source
