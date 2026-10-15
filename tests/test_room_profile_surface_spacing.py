"""抽屉是一个物理表面：三个字段的冷却各有各的，但 Soul 只认「这块面板刚没刚写过」。

复现（2026-10-15 运行日志）：

    19:30:27 set_title  Title 山旮旯 queued ... will be updated soon   ← 房名自己的 10 分钟预算是空的
    19:30:38           Topic updated successfully                      ← 话题写成功（同一块抽屉）
    19:30:44→47        Updating room title: 听歌｜山旮旯
                        Update title too frequently -> Update failed - still in cooldown period

我们按字段各记一份预算（话题 5 / 公告 15 / 房名 10 分钟，互不消耗），于是
`set_title` 敢承诺「soon」；可 Soul 侧限制的是**房间信息面板的编辑动作**，
话题刚写 6 秒之后再写房名就是会被拒。更糟的是被拒之后 `mark_attempted` 照样推进
整整 10 分钟 —— 一次本可避免的碰撞，换来 10 分钟的静默。

本票把「能不能**开始一次新的抽屉写入**」与「这个字段自己的预算够不够」分成两个问题：

- `can_start_write(field)` = 字段预算 **且** 抽屉表面安静满 `SURFACE_SPACING_SECONDS`；
- `can_apply_now(field)` 保持不变 = 只看字段预算 —— 抽屉**会话内部**的连带动作
  （房名写入顺手恢复被冲掉的公告，用户故事 #6）绝不能被表面的节奏闸拦回去排队。

间隔取 60 秒：相对 5/10/15 分钟的字段预算是零头，却足以让心跳在下一拍补写，
而不是撞一次被拒、再罚自己 10 分钟。
"""

from datetime import datetime, timedelta

import pytest

from ushareiplay.managers.room_profile import RoomProfileManager
from ushareiplay.managers.room_profile.drafts import (
    SURFACE_SPACING_SECONDS,
    ProfileDraftStore,
)
from unittest.mock import MagicMock

from ushareiplay.state.room_state import RoomState
from tests.fakes.in_memory_room_profile_drawer import InMemoryRoomProfileDrawerDriver

# 抽屉里同时摆着房名那一行与公告那一行：表面节奏闸与「当场补公告」都要能被考到。
DRAWER_SCREEN = (
    'slide_drawer',
    'title_edit_entry',
    'title_edit_input',
    'title_edit_confirm',
    'edit_notice_entry',
    'close_notice',
    'customize_notice_button',
    'edit_notice_input',
    'edit_notice_confirm',
)
DEFAULT_NOTICE = "U Share I Play\n分享音乐 享受快乐"
CONFIG = {
    "default_theme": "听歌",
    "default_title": "听歌",
    "default_notice": DEFAULT_NOTICE,
    "system_default_notices": ["弹唱大会", "Souler们在随便聊聊ing", "蹲一个人"],
}


class _RoomTextFinder:
    """判定读（房名 / 公告），与 `test_room_profile_title.py` 同一个形状。"""

    def __init__(self, room_title_text="听歌｜晚安", notice_text=""):
        self.room_title_text = room_title_text
        self.notice_text = notice_text
        self.room_name_element = object()
        self.notice_element = object()

    def wait_for_element(self, key, timeout=10):
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
    def __init__(self):
        self.logger = MagicMock()
        self.key_actions = MagicMock()
        self.key_actions.switch_to_app.return_value = True
        self.element_finder = _RoomTextFinder()
        self.config = CONFIG

    def log_error(self, _message):
        return None


@pytest.fixture(autouse=True)
def reset_singletons():
    for cls in (RoomProfileManager, RoomState):
        cls.reset_instance()
    yield
    for cls in (RoomProfileManager, RoomState):
        cls.reset_instance()


def _now():
    return datetime.now()


# --------------------------------------------------------------------------
# 草稿库：两个问题分开答
# --------------------------------------------------------------------------


def test_a_field_with_a_free_budget_still_cannot_start_while_the_surface_is_hot():
    """房名预算从没动用过，但话题刚写过 —— 现在**开始**一次房名写入会被 Soul 拒。"""
    store = ProfileDraftStore()
    store.mark_attempted('topic', now=_now())

    assert store.can_apply_now('title') is True, "字段预算是字段自己的事，不变"
    assert store.can_start_write('title') is False
    assert store.minutes_until_write('title') >= 1, "ETA 不能报 0 / 立即可写"


def test_the_surface_gate_lifts_once_the_drawer_has_been_quiet():
    store = ProfileDraftStore()
    store.mark_attempted('topic', now=_now() - timedelta(seconds=SURFACE_SPACING_SECONDS + 1))

    assert store.can_start_write('title') is True
    assert store.minutes_until_write('title') == 0


def test_the_field_budget_still_governs_after_the_surface_cools():
    """表面安静了，但字段自己的 10 分钟没到：仍然不能写。"""
    store = ProfileDraftStore()
    store.mark_attempted('title', now=_now())
    store.mark_attempted('topic', now=_now() - timedelta(seconds=SURFACE_SPACING_SECONDS + 1))

    assert store.can_start_write('title') is False
    assert store.minutes_until_write('title') == 9


def test_a_field_never_touched_needs_no_surface_history():
    store = ProfileDraftStore()

    assert store.can_start_write('title') is True


# --------------------------------------------------------------------------
# 端到端：不再承诺一个会被告拒的「soon」，也不烧掉一次预算
# --------------------------------------------------------------------------


def _profile(driver=None, handler=None):
    profile = RoomProfileManager.initialize(
        handler=handler or _Handler(), drawer_driver=driver
    )
    profile.title_settle_seconds = 0
    return profile


def _driver():
    return InMemoryRoomProfileDrawerDriver(
        present=DRAWER_SCREEN,
        world_after_click={"title_edit_confirm": ("slide_drawer", "title_edit_entry")},
    )


def test_set_title_after_a_topic_write_does_not_promise_soon():
    """用户看到的第一个谎：`queued ... will be updated soon`，6 秒后却被服务端拒绝。"""
    RoomState.initialize()
    profile = _profile(_driver())
    profile.drafts.mark_attempted('topic', now=_now())  # 话题刚刚写成功

    result = profile.set_title('山旮旯')

    assert 'soon' not in result['title'], f"表面正热时不许承诺 soon：{result}"


def test_the_heartbeat_does_not_spend_the_room_name_budget_on_a_hot_surface():
    """表面正热时心跳**不去点编辑层**，也就不会被拒、不会被罚一整个 10 分钟周期。"""
    RoomState.initialize()
    driver = _driver()
    profile = _profile(driver)

    profile.set_title('山旮旯')
    profile.drafts.mark_attempted('topic', now=_now())  # 话题写入落地，表面变热

    result = profile.update_title()

    assert result.get('cooldown') is True
    assert driver.clicks == [], "一次点击都不该发生"
    assert profile.drafts.last_attempt_at('title') is None, "没尝试过就不许记账"


def test_the_same_title_is_written_once_the_surface_has_quieted():
    """下一拍：表面安静了，房名照常写出去（预算没被误烧，所以不用等 10 分钟）。"""
    RoomState.initialize()
    driver = _driver()
    profile = _profile(driver)

    profile.set_title('山旮旯')
    profile.drafts.mark_attempted('topic', now=_now())
    assert profile.update_title().get('cooldown') is True

    profile.drafts.set_last_attempt_at('topic', _now() - timedelta(seconds=SURFACE_SPACING_SECONDS + 1))
    result = profile.update_title()

    assert result.get('ui_updated') is True, result
    assert profile.get_current_title() == '山旮旯'


def test_the_notice_restore_inside_an_open_drawer_is_never_deferred_by_spacing():
    """用户故事 #6：抽屉是房名流程开的，公告必须**当场**补回去。

    表面节奏闸只管「开始一次新的写入」，绝不能把会话内部的连带动作推去排队 ——
    那正是 `can_apply_now` 与 `can_start_write` 必须分开的理由。
    """
    RoomState.initialize()
    profile = _profile(_driver())
    profile.drafts.mark_attempted('title', now=_now())  # 房名刚写过（表面与预算都热）

    assert profile.drafts.can_apply_now('notice') is True
    result = profile.restore_notice(DEFAULT_NOTICE)

    assert 'skipped' not in result and 'cooldown' not in result, (
        f"会话内部的公告恢复被表面节奏闸推去排队：{result}"
    )
