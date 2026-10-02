"""有人上麦 → 播放静音保护即时开启。

用户在公屏被系统告知「XXX 已上麦」时，机器人也在麦上：此时切歌的底噪会盖住
麦上的人。`PlaybackMuting` 因此不只由配置决定 —— 收到上麦系统消息就即时开启，
直到房间生命周期把它重置。

配置（`soul.playback_mute`）：

| 项 | 作用 |
|---|---|
| `auto_enable_on_mic` | 总开关，默认开启；关掉后上麦不再联动 |
| `ignore_users` | 额外忽略名单（系统账号等） |

自身过滤用配置的 `room_owner` —— 机器人就是以该账号在房间里发言（见
`roles.py`），自己上麦不构成「别人在麦上」。
"""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from ushareiplay.managers.command_manager import CommandManager
from ushareiplay.managers.message_manager import MessageManager
from ushareiplay.managers.playback_muting import PlaybackMuting
from ushareiplay.models.message_info import MessageInfo
from ushareiplay.state.room_state import RoomState


class _StubMusicManager:
    def __init__(self, events):
        self.events = events

    def wait_for_playback_ready(self, expected_song=None, timeout=5.0, settling_delay=0.3):
        self.events.append(f"wait:{expected_song}")
        return True


class _StubMicManager:
    """机器人正在开麦 —— 切歌底噪只有在这种状态下才漏得出去。"""

    def __init__(self, events):
        self.events = events

    def state(self):
        return True

    def set_active(self, enable):
        self.events.append(f"mute:{enable}")
        return {"state": "1" if enable else "0"}

    def ensure_active(self):
        self.events.append("restore")
        return {"state": "1"}


@pytest.fixture
def room(initialized_test_singletons):
    """真实 MessageManager + 真实 PlaybackMuting，共用一个假 handler。

    `events` 记录真正的麦克风动作 —— 上麦联动本身不该产生任何 UI 动作，
    因此「事件列表为空」就是「没有多余的点击」的断言。
    """

    def _build(**playback_mute):
        events = []
        handler = SimpleNamespace(
            logger=MagicMock(),
            config={
                "soul": {
                    "room_owner": "Joyer",
                    "playback_mute": playback_mute,
                }
            },
            controller=None,
        )
        muting = PlaybackMuting.initialize(
            handler, _StubMusicManager(events), _StubMicManager(events)
        )
        manager = MessageManager.instance()
        manager._handler = handler
        manager._chat_logger = MagicMock()
        return SimpleNamespace(events=events, handler=handler, muting=muting, manager=manager)

    return _build


def _dispatch(room, lines, **kwargs):
    return asyncio.run(room.manager.dispatch(lines, **kwargs))


# --------------------------------------------------------------------------
# 识别 → 开启
# --------------------------------------------------------------------------


def test_on_mic_line_arms_muting_without_touching_the_microphone(room):
    """上麦是状态变化，不是动作：此刻不该点闭麦，只该记住「要保护」。"""
    r = room()

    commands = _dispatch(r, ["荒草 已上麦"])

    assert r.muting.dynamically_enabled is True
    assert r.muting.should_engage() is True
    assert r.events == []
    assert commands == []


def test_armed_room_guards_the_next_track_switch(room):
    """用户可见的收益：有人上麦后，:play/:skip 立刻走闭麦-切换-就绪-开麦。"""
    r = room()
    _dispatch(r, ["荒草 已上麦"])

    with r.muting.guard(expected_song="稻香"):
        r.events.append("switch")

    assert r.events == ["mute:False", "switch", "wait:稻香", "restore"]


def test_on_mic_line_is_chat_logged_and_produces_no_command(room):
    r = room()

    _dispatch(r, ["荒草 已上麦"])

    r.manager.chat_logger.info.assert_called_once_with("荒草 已上麦")


def test_arming_is_idempotent_across_repeated_on_mic_lines(room):
    """第二个上麦的人不改变状态，也不重复打「已开启」的行为日志。"""
    r = room()

    _dispatch(r, ["荒草 已上麦"])
    r.handler.logger.info.reset_mock()

    _dispatch(r, ["林小满 已上麦"])

    assert r.muting.arm_on_mic("林小满") is False
    assert r.muting.dynamically_enabled is True
    r.handler.logger.info.assert_not_called()


# --------------------------------------------------------------------------
# 策略：总开关 / 自身 / 指定系统账号
# --------------------------------------------------------------------------


def test_auto_enable_switch_off_keeps_arming_out(room):
    r = room(auto_enable_on_mic=False)

    _dispatch(r, ["荒草 已上麦"])

    assert r.muting.dynamically_enabled is False


def test_own_account_on_mic_is_ignored(room):
    """机器人自己上麦不构成保护理由（否则永远自锁）。"""
    r = room()

    _dispatch(r, ["Joyer 已上麦"])

    assert r.muting.dynamically_enabled is False


def test_configured_system_account_is_ignored(room):
    r = room(ignore_users=["Timer"])

    _dispatch(r, ["Timer 已上麦"])

    assert r.muting.dynamically_enabled is False


def test_arming_overrides_guest_room_only_and_disabled_settings(room):
    """联动要能救场：配置说「客房才保护/根本没开」时也照样生效。"""
    r = room(enabled=False, guest_room_only=True)

    _dispatch(r, ["荒草 已上麦"])

    assert r.muting.should_engage() is True
    with r.muting.guard(expected_song=None):
        r.events.append("switch")
    assert r.events[0] == "mute:False"


def test_backfilled_on_mic_line_does_not_arm(room):
    """回溯到的是历史行：那人可能早已下麦，不能据此认定「现在有人在麦上」。"""
    r = room()

    _dispatch(r, ["荒草 已上麦"], from_backfill=True)

    assert r.muting.dynamically_enabled is False


def test_dispatch_survives_an_uninitialized_playback_muting():
    """单例未装配时聊天流照常跑完，只是没人接联动（不许把公屏带崩）。"""
    manager = MessageManager.instance()
    manager._handler = SimpleNamespace(logger=MagicMock(), config={}, controller=None)
    manager._chat_logger = MagicMock()

    commands = asyncio.run(manager.dispatch(["荒草 已上麦"]))

    assert commands == []
    manager.chat_logger.info.assert_called_once_with("荒草 已上麦")


# --------------------------------------------------------------------------
# 房间生命周期收敛
# --------------------------------------------------------------------------


def test_room_change_resets_dynamic_arming(room, initialized_test_singletons):
    """退房 / 切房 / 派对重启都走 RoomState.clear()，动态开启不得跨场次。"""
    RoomState.initialize()
    r = room(enabled=False)
    _dispatch(r, ["荒草 已上麦"])
    assert r.muting.dynamically_enabled is True

    RoomState.instance().clear()

    assert r.muting.dynamically_enabled is False
    assert r.muting.should_engage() is False


# --------------------------------------------------------------------------
# 端到端：上麦 -> 真实命令路径 -> 静音保护生命周期
# --------------------------------------------------------------------------


class _Runtime:
    def emit(self, *_args, **_kwargs):
        pass

    @asynccontextmanager
    async def ui_session(self, _reason):
        yield


class _Recorder:
    """MessageDispatch 的替身：记录公屏通知。"""

    def __init__(self, events):
        self.events = events

    def configure_runtime(self, _runtime):
        pass

    def bind_handler(self, _handler):
        return self

    def send_screen_message(self, _message, silent=False):
        self.events.append("screen")

    def send_for_message_info(self, _message_info, response, silent=False):
        self.events.append(f"notify:{response}")


class _DispatchStub:
    recorder = None

    @classmethod
    def instance(cls):
        return cls.recorder


class _PlaybackCommand:
    """`:play` 的替身：静音保护的参与由命令自己声明。"""

    playback_muting = True

    def __init__(self, events):
        self.events = events

    async def process(self, message_info, parameters):
        self.events.append("playback")
        return {"song": "稻香", "singer": "周杰伦", "album": "叶惠美"}

    def playback_expected_song(self, parameters):
        return " ".join(parameters)


def _run_play_command(monkeypatch, r) -> None:
    """让真实 CommandManager 跑一条 `:play`，事件记进 r.events。"""
    monkeypatch.setattr("ushareiplay.managers.command_manager.MessageDispatch", _DispatchStub)
    _DispatchStub.recorder = _Recorder(r.events)
    manager = CommandManager.instance()
    manager.configure_runtime(_Runtime())
    manager._logger = MagicMock()
    manager._handler = SimpleNamespace(
        logger=MagicMock(), config={"soul": {"system_users": ["Console"]}}
    )
    monkeypatch.setattr(manager, "is_valid_command", lambda _content: True)
    monkeypatch.setattr(
        manager,
        "parse_command",
        lambda _content: {
            "prefix": "play",
            "level": 0,
            "parameters": ["稻香"],
            "response_template": "{song} - {singer}",
            "error_template": "Failed to play music, because {error}",
        },
    )
    monkeypatch.setattr(manager, "get_command", lambda _prefix: _PlaybackCommand(r.events))

    asyncio.run(
        manager.execute_command_messages(
            [MessageInfo(content=":play 稻香", nickname="Console")]
        )
    )


# 配置成「本不该保护」的样子：静音保护整体关掉、且只限客房（此刻是主房）。
# 于是下面两条测试里唯一的变量就是那条上麦通知。
MUTING_OFF = {"enabled": False, "guest_room_only": True}


def test_playback_command_after_an_on_mic_line_follows_the_muting_lifecycle(monkeypatch, room):
    """端到端验收：收到「XXX 已上麦」后，`:play` 立刻走闭麦-切换-就绪-开麦。

    走的是真实命令路径（`CommandManager.execute_command_messages` ->
    `playback_muting_guard` -> 真实 PlaybackMuting），不是直接调 `guard()`。
    """
    r = room(**MUTING_OFF)
    _dispatch(r, ["荒草 已上麦"])
    r.events.clear()

    _run_play_command(monkeypatch, r)

    assert r.events == [
        "screen",
        "mute:False",
        "playback",
        "notify:稻香 - 周杰伦 @Console",
        "wait:稻香",
        "restore",
    ]


def test_without_an_on_mic_line_the_same_room_keeps_its_configuration(monkeypatch, room):
    """对照组：同样的配置、同样的 `:play`，没有上麦通知就不该有多余的麦克风动作。"""
    r = room(**MUTING_OFF)
    assert r.muting.should_engage() is False

    _run_play_command(monkeypatch, r)

    assert r.events == ["screen", "playback", "notify:稻香 - 周杰伦 @Console"]
