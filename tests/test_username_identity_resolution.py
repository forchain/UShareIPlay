"""分身（别名）与主账号（canonical）两套命名域的一致性规则测试。

Soul UI 只暴露当前在房间里可见的名字（分身名），而 DB 侧 `UserDAO.get_or_create`
会把任何名字解析成主账号名。以用户名作参数的命令（:seat / :admin / :gift / :level /
:focus 钩子等）必须遵守同一条规则：

  - DB 侧读写：一律走 canonical（现状已满足，测试作为回归保护）。
  - 面向 Soul UI 的查找与比对：必须用 UI 当前可见的名字；跨命名域比对必须按
    身份（canonical + 全部分身），不能按字符串相等。

复现的真实故障（2026-09-30 01:58 日志）：专注事件把主账号名交给 `:seat 3`，
麦位弹窗里读到的是分身名，字符串永不相等 → "User 不约儿童~𝓨o🐏🐏 not found on any seat"。
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from ushareiplay.commands.gift import GiftCommand
from ushareiplay.commands.seat import SeatCommand
from ushareiplay.core.db_manager import DatabaseManager
from ushareiplay.core.message_queue import MessageQueue
from ushareiplay.dal.focus_event_dao import FocusEventDao
from ushareiplay.dal.user_dao import UserDAO
from ushareiplay.managers.admin_manager import AdminManager
from ushareiplay.managers.info_manager import InfoManager
from ushareiplay.managers.seat_manager import SeatManager
from ushareiplay.managers.seat_manager.subsystem import SeatSubsystem
from ushareiplay.models.message_info import MessageInfo
from ushareiplay.models.user import User
from ushareiplay.state.presence_tracker import PresenceTracker

CANONICAL = "不约儿童~𝓨o🐏🐏"  # 主账号：DB 里 canonical 记录的 username
AVATAR = "不约儿童🐏🐏"  # 分身：Soul UI / 麦位上真正显示的名字
STRANGER = "路人甲"


@pytest.fixture
async def db():
    manager = DatabaseManager(db_url="sqlite://:memory:")
    await manager.init()
    yield manager
    await manager.close()


@pytest.fixture
async def alias_pair(db):
    """建立 分身 → 主账号 的映射，等价于运行过 `:alias "<分身>" "<主账号>"`。"""
    canonical = await UserDAO.get_or_create_raw(CANONICAL)
    avatar = await UserDAO.get_or_create_raw(AVATAR)
    avatar.canonical_user_id = canonical.id
    await avatar.save(update_fields=["canonical_user_id"])
    return SimpleNamespace(canonical=canonical, avatar=avatar)


@pytest.fixture(autouse=True)
def presence_env():
    """在线集合由 Soul UI 读回，因此里面只有分身名。"""
    for cls in (PresenceTracker, InfoManager, AdminManager):
        cls.reset_instance()
    presence = PresenceTracker.initialize()
    presence._logger = SimpleNamespace(
        info=lambda _m: None, warning=lambda _m: None, error=lambda _m: None, critical=lambda _m: None
    )
    info_manager = InfoManager.initialize()
    info_manager._logger = SimpleNamespace(info=lambda _m: None)
    yield presence
    for cls in (PresenceTracker, InfoManager, AdminManager):
        cls.reset_instance()


# ---------------------------------------------------------------------------
# UI 替身：与生产同形的麦位（参考 tests/test_seat_off_command.py）
# ---------------------------------------------------------------------------
class DummyElement:
    def __init__(self, text=""):
        self.text = text
        self.clicked = False

    def click(self):
        self.clicked = True


class DummyLogger:
    def __init__(self):
        self.messages = []

    def _record(self, level, message):
        self.messages.append((level, message))

    def info(self, message):
        self._record("info", message)

    def warning(self, message):
        self._record("warning", message)

    def error(self, message):
        self._record("error", message)


class DummySeatHandler:
    """麦位 DOM 替身：弹窗里读到的名字就是 UI 可见名字（分身名）。

    昵称节点与 back 的关系按真机建模：back 关掉弹窗后，昵称节点就离开 dump ——
    所以 SeatPanelDriver 的二次取证（此刻还读得到昵称才按 back）在这里也成立。
    """

    def __init__(self, desks, popup_name):
        self.desks = desks
        self.popup_name = popup_name
        self.popup_open = popup_name is not None
        self.logger = DummyLogger()
        self.confirm = DummyElement("确认")
        self.back_pressed = False

    def find_child_element(self, desk, key, log_failure=True):
        return desk.get(key)

    def try_find_element(self, element_key, log=False, clickable=False):
        if self.popup_open and element_key in ("souler_name", "user_name"):
            return DummyElement(self.popup_name or "")
        return None

    def wait_for_element_clickable(self, key, *args, **kwargs):
        return self.confirm if key == "confirm_seat" else None

    def wait_for_any_element(self, keys, timeout=10):
        if not self.popup_name:
            return None, None
        return keys[0], DummyElement(self.popup_name)

    def press_back(self):
        self.back_pressed = True
        self.popup_open = False

    def log_error(self, message):
        self.logger.error(message)

    @property
    def element_finder(self):
        return self

    @property
    def key_actions(self):
        return self

    @property
    def gesture_handler(self):
        return SimpleNamespace(click_element_at=lambda *args, **kwargs: None)


class DummySeatUI:
    def __init__(self, handler):
        self.handler = handler

    async def expand_and_find_desks(self):
        return self.handler.desks

    def scroll_to_row(self, desk_index, seat_desks, duration=100):
        pass


def _desk(left_label="", left_occupied=False, right_label="", right_occupied=False):
    return {
        "left_seat": DummyElement(),
        "right_seat": DummyElement(),
        "left_state": DummyElement() if left_occupied else None,
        "right_state": DummyElement() if right_occupied else None,
        "left_label": DummyElement(left_label) if left_label else None,
        "right_label": DummyElement(right_label) if right_label else None,
    }


class DummyController:
    """命令构造需要的最小 controller（BaseCommand 会取 soul/music handler 与 config）。"""

    def __init__(self, handler=None):
        self.soul_handler = handler or SimpleNamespace(logger=DummyLogger(), config={})
        self.music_handler = None
        self.config = {}


def _seating_manager(desks, popup_name):
    handler = DummySeatHandler(desks, popup_name)
    manager = SeatSubsystem(handler, seat_ui=DummySeatUI(handler))
    return handler, manager


# ---------------------------------------------------------------------------
# 身份集合原语
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_identity_usernames_covers_canonical_and_all_avatars(alias_pair):
    assert await UserDAO.get_identity_usernames(CANONICAL) == {CANONICAL, AVATAR}
    assert await UserDAO.get_identity_usernames(AVATAR) == {CANONICAL, AVATAR}


@pytest.mark.asyncio
async def test_identity_usernames_does_not_create_unknown_users(db):
    assert await UserDAO.get_identity_usernames(STRANGER) == {STRANGER}
    assert await User.get_or_none(username=STRANGER) is None


@pytest.mark.asyncio
async def test_is_same_identity_matches_across_naming_domains(alias_pair):
    assert await UserDAO.is_same_identity(CANONICAL, AVATAR) is True
    assert await UserDAO.is_same_identity(AVATAR, CANONICAL) is True
    assert await UserDAO.is_same_identity(CANONICAL, STRANGER) is False


# ---------------------------------------------------------------------------
# :seat 3 —— 专注事件传入主账号名，麦位上是分身名
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_accompany_user_matches_avatar_shown_on_seat(alias_pair):
    desks = [_desk(right_label=AVATAR, right_occupied=True)]
    handler, manager = _seating_manager(desks, popup_name=AVATAR)

    result = await manager.accompany_user(CANONICAL, sender_username=CANONICAL)

    assert result == {"success": "Successfully took a seat"}, result
    assert desks[0]["left_seat"].clicked is True


@pytest.mark.asyncio
async def test_accompany_user_does_not_sit_next_to_stranger(alias_pair):
    desks = [_desk(right_label=STRANGER, right_occupied=True)]
    handler, manager = _seating_manager(desks, popup_name=STRANGER)

    result = await manager.accompany_user(CANONICAL, sender_username=CANONICAL)

    assert result == {"error": f"User {CANONICAL} not found on any seat"}
    assert desks[0]["left_seat"].clicked is False


@pytest.mark.asyncio
async def test_seat_3_without_parameter_targets_the_avatar_name_on_seat(alias_pair):
    """`:seat 3` 不接参数时，交给座位层的靶子必须是麦位上可见的分身名。"""
    desks = [_desk(right_label=AVATAR, right_occupied=True)]
    handler = DummySeatHandler(desks, popup_name=AVATAR)
    seating = SeatSubsystem(handler, seat_ui=DummySeatUI(handler))
    presence_env = PresenceTracker.instance()
    presence_env._online_users = {AVATAR}

    accompanying = {}

    async def spy(target_username, sender_username=None):
        accompanying["target"] = target_username
        return await seating.accompany_user(target_username, sender_username=sender_username)

    SeatManager.reset_instance()
    seat_manager = SeatManager.initialize()
    seat_manager.accompany_user = spy
    command = SeatCommand(DummyController(handler))
    result = await command.do_process(
        MessageInfo(content=":seat 3", nickname=CANONICAL), ["3"]
    )

    assert accompanying["target"] == AVATAR
    assert result == {"success": "Successfully took a seat"}


# ---------------------------------------------------------------------------
# :focus 钩子 —— 观测到分身名，钩子挂在主账号上
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_focus_hook_seat_macro_resolves_from_avatar_observation(alias_pair):
    await FocusEventDao.create(AVATAR, ":say {username} 坐到了 {seat} 号 ({action})")
    queue = MessageQueue.instance()
    await queue.clear_queue()

    from ushareiplay.commands.focus import FocusCommand

    handler = SimpleNamespace(logger=DummyLogger())
    command = FocusCommand(SimpleNamespace(soul_handler=handler, music_handler=None))
    command.handler = handler

    await command.focus_count_change(
        before=2,
        after=3,
        changed_users=[AVATAR],
        seat_info={AVATAR: {"seat_number": 6, "action": "move_seat"}},
    )

    msgs = await queue.get_all_messages()
    assert len(msgs) == 1
    # 主账号名用于 DB 归属，{seat}/{action} 必须来自分身名的观测
    assert list(msgs.values())[0].content == f":say {CANONICAL} 坐到了 6 号 (move_seat)"
    await queue.clear_queue()


# ---------------------------------------------------------------------------
# 在线列表 —— :admin / :gift 必须在 UI 上找得到人
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_resolve_visible_username_returns_the_name_soul_shows(alias_pair):
    PresenceTracker.instance()._online_users = {AVATAR, STRANGER}
    info_manager = InfoManager.instance()

    assert await info_manager.resolve_visible_username(CANONICAL) == AVATAR
    assert await info_manager.resolve_visible_username(AVATAR) == AVATAR

    PresenceTracker.instance()._online_users = {STRANGER}
    assert await info_manager.resolve_visible_username(CANONICAL) == CANONICAL


@pytest.mark.asyncio
async def test_admin_opens_the_avatar_profile_and_tracks_the_visible_name(alias_pair):
    PresenceTracker.instance()._online_users = {AVATAR}
    manager = AdminManager.initialize()
    manager._handler = MagicMock()
    manager._logger = MagicMock()

    invite = MagicMock()
    invite.text = "管理邀请"
    confirm = MagicMock()
    manager._handler.element_finder.wait_for_element_clickable.side_effect = lambda key: (
        invite if key == "manager_invite" else (confirm if key == "confirm_invite" else None)
    )

    opened = []

    class FakeUserManager:
        def open_user_profile_from_online_list(self, nickname):
            opened.append(nickname)
            return {"user": nickname} if nickname == AVATAR else {
                "error": "User not found in online users list", "user": nickname
            }

    with patch("ushareiplay.managers.user_manager.UserManager.instance", return_value=FakeUserManager()), \
         patch("ushareiplay.managers.recovery_manager.RecoveryManager.instance", return_value=MagicMock()):
        result = await manager.manage_admin(enable=True, target_nickname=CANONICAL)

    assert opened == [AVATAR]
    assert result == {"user": AVATAR, "action": "Invited"}
    # 麦位观测用 UI 名字标注管理员，因此登记也必须是分身名
    assert manager.is_room_admin(AVATAR)


@pytest.mark.asyncio
async def test_gift_targets_the_avatar_visible_in_the_room(alias_pair):
    PresenceTracker.instance()._online_users = {AVATAR}
    sent = []

    class FakeUserManager:
        def send_gift(self, nickname):
            sent.append(nickname)
            return {"success": f"已送给 {nickname}"}

    controller = DummyController()
    command = GiftCommand(controller)

    with patch("ushareiplay.commands.gift.UserManager.instance", return_value=FakeUserManager()):
        result = await command.do_process(
            MessageInfo(content=f":gift {CANONICAL}", nickname="群主"), [CANONICAL]
        )

    assert sent == [AVATAR]
    assert result == {"success": f"已送给 {AVATAR}"}


# ---------------------------------------------------------------------------
# DB 侧（:level）：已经是 canonical 解析，规则回归保护
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_level_writes_through_the_alias_to_canonical(alias_pair):
    from ushareiplay.commands.level import LevelCommand

    controller = DummyController()
    command = LevelCommand(controller)

    # Joyer 是默认房主（人工操作者），才有权设置他人等级
    result = await command.do_process(
        MessageInfo(content=f':level "{AVATAR}" 7', nickname="Joyer"), [AVATAR, "7"]
    )

    assert "error" not in result, result
    canonical = await User.get_or_none(username=CANONICAL)
    assert canonical.level == 7
    assert await User.get_or_none(username=AVATAR) is not None  # 分身记录仍在


@pytest.mark.asyncio
async def test_accompany_user_collapses_seats_and_avoids_duplicate_row_scrolls(alias_pair):
    """accompany_user 结束时收起麦位，且同一排的桌子不重复触发滚屏。"""
    desks = [
        _desk(left_label="U1", left_occupied=True, right_label="U2", right_occupied=True),
        _desk(left_label="U3", left_occupied=True, right_label="U4", right_occupied=True),
    ]
    handler = DummySeatHandler(desks, popup_name="U1")
    scrolled_desks = []
    collapsed = []

    class MockUI(DummySeatUI):
        def scroll_to_row(self, desk_index, seat_desks, duration=100):
            scrolled_desks.append(desk_index)

        async def collapse_seats(self):
            collapsed.append(True)

    manager = SeatSubsystem(handler, seat_ui=MockUI(handler))

    result = await manager.accompany_user(CANONICAL, sender_username=CANONICAL)
    assert "error" in result
    # 两个桌子都在 row 0，只滚屏一次（desk 0），不会重复为 desk 1 滚屏
    assert scrolled_desks == [0]
    # 最终收起面板
    assert collapsed == [True]

