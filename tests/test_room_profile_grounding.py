"""房间档案必须被真实 UI「接地」（grounding）—— current_title 不能是永远的 None。

复现的用户可见缺陷（2026-10-15 运行日志）：

1. `/radio` 排队房名 -> 心跳写 UI 被 Soul 侧「改得太频繁」拒绝；
2. `/keyword run 旋律` 走歌单播放，`set_title` 把草稿换成新歌单名；
3. `/theme` 于是显示「当前标题: 未设置」，而「即将更新标题」却有值。

`current_title` 只有三个写入口：`initialize_from_ui`、`_parse_title_from_ui`
（仅在**没有**排队草稿时才会被心跳调用，排队中的房名把它饿死）、以及
`_write_title_in_drawer` **写成功**的那一刻。写入失败时唯一能把真实房名读回来的
路径是抽屉全量审计 —— 而它在 PR #413「停用抽屉推荐读写」时被连坐摘掉了：
`PartyManager._refresh_recommendation_state()` 变成空壳，
`ensure_synced_on_return` / `audit_and_repair` / `initialize_from_ui` 自此
零生产调用点，`current_title` 就再也没机会被接地。

本文件钉住三件事：

- 回房/建房时档案必须从 UI 读回真实房名，**不看推荐状态那个已废弃字段的脸色**；
- 房间标识一变，旧的 UI 事实必须作废，否则守卫生不住「已经读过了」这句话；
- PartyManager 的那条触发线必须真的接在模块上（不允许再退回空壳）。
"""

from types import SimpleNamespace

import pytest

from ushareiplay.managers.party_manager import PartyManager
from ushareiplay.managers.room_profile import RoomProfileManager
from ushareiplay.state.room_state import RoomState
from tests.fakes.in_memory_room_profile_drawer import InMemoryRoomProfileDrawerDriver

# 回房时屏幕上真实存在的东西：派对类型那一行（抽屉里）+ 主界面的房名那一行。
# 推荐那一行 #413 之后已经不在 UI 里了。接地走 `chat_room_title` 这条只读回落，
# 所以断言里「一次抽屉动作都不发生」与 #413 的契约是同一件事。
DRAWER_SCREEN = ("slide_drawer", "party_room_type_option")
MAIN_SCREEN = DRAWER_SCREEN + ("chat_room_title",)
ROOM_NAME_ON_MAIN_SCREEN = "听歌｜Lofi Girl"
SINGING_TYPE_TEXT = "唱歌听歌"
CONFIG = {
    "default_theme": "听歌",
    "default_title": "听歌",
    "default_notice": "U Share I Play\n分享音乐 享受快乐",
    "system_default_notices": ["弹唱大会"],
    "target_party_type_element": "party_type_singing",
}


class _Screen:
    def __init__(self, present, texts=None):
        self.present = set(present)
        self.texts = dict(texts or {})
        self.reads = []

    def wait_for_element(self, key, timeout=10):
        self.reads.append(key)
        return key if key in self.present else None

    def try_find_element(self, key, log=False):
        self.reads.append(key)
        return key if key in self.present else None

    def wait_for_element_clickable(self, key, timeout=10):
        self.reads.append(key)
        return key if key in self.present else None

    def wait_for_any_element(self, keys, timeout=10):
        for key in keys:
            if key in self.present:
                return key, self.wait_for_element(key)
        return None, None

    def get_element_text(self, element):
        return self.texts.get(element, "")


class _Logger:
    def _noop(self, *_args, **_kwargs):
        return None

    debug = info = warning = error = critical = _noop


def _handler(screen):
    return SimpleNamespace(
        logger=_Logger(),
        element_finder=screen,
        config=CONFIG,
        key_actions=SimpleNamespace(press_back=lambda: None, switch_to_app=lambda: True),
        ui_actions=SimpleNamespace(switch_and_click=lambda key, **kwargs: {"success": True}),
    )


def _driver():
    return InMemoryRoomProfileDrawerDriver(present=DRAWER_SCREEN)


@pytest.fixture(autouse=True)
def _reset_singletons(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # isolate data/room_state.json persistence
    for cls in (RoomState, RoomProfileManager, PartyManager):
        cls.reset_instance()
    yield
    for cls in (RoomState, RoomProfileManager, PartyManager):
        cls.reset_instance()


# --------------------------------------------------------------------------
# 守卫：「要不要去读 UI」问的是档案自己知不知道，不是推荐字段记没记过
# --------------------------------------------------------------------------


def test_entering_the_room_grounds_the_real_room_name_even_when_the_recommendation_state_is_known():
    """建房流程早已记下推荐状态，也不能挡住房名接地。

    #413 之后推荐那一行根本不在抽屉里了：`recommendation_enabled` 恒为 True/False，
    拿它当「档案已知」的守卫，等于把全量审计永久短路，`current_title` 就停在 None。
    """
    room_state = RoomState.initialize()
    room_state.recommendation_enabled = True
    screen = _Screen(MAIN_SCREEN, {"chat_room_title": ROOM_NAME_ON_MAIN_SCREEN})
    driver = _driver()
    profile = RoomProfileManager.initialize(handler=_handler(screen), drawer_driver=driver)

    profile.ensure_synced_on_return()

    assert profile.get_current_title() == "Lofi Girl", (
        "回房必须把真实房名读回来，否则 /theme 只能报「当前标题: 未设置」"
    )
    assert profile.get_current_theme() == "听歌"
    assert profile.is_initialized is True
    # #413 的契约：接地不花一次抽屉会话 —— 零打开、零点击。
    assert driver.opened_entries == []
    assert driver.clicks == []


def test_the_audit_is_skipped_once_the_profile_already_knows_the_room_name():
    """反过来钉住：真的读过了就不为「发现读过了」再开一次抽屉（日志铁律）。"""
    room_state = RoomState.initialize()
    screen = _Screen(MAIN_SCREEN, {"chat_room_title": ROOM_NAME_ON_MAIN_SCREEN})
    driver = _driver()
    profile = RoomProfileManager.initialize(handler=_handler(screen), drawer_driver=driver)

    assert profile.ensure_synced_on_return().get("initialized") is True

    second = profile.ensure_synced_on_return()
    assert second.get("skipped") is True
    assert second.get("reason") == "already_initialized"
    assert driver.opened_entries == []


def test_a_title_that_failed_to_write_still_leaves_the_current_title_grounded():
    """用户日志里的原始场景：写房名被 Soul 拒绝后，`/theme` 不得报「未设置」。"""
    room_state = RoomState.initialize()
    room_state.recommendation_enabled = True
    screen = _Screen(MAIN_SCREEN, {"chat_room_title": ROOM_NAME_ON_MAIN_SCREEN})
    profile = RoomProfileManager.initialize(handler=_handler(screen), drawer_driver=_driver())

    profile.ensure_synced_on_return()  # 回房接地

    # /radio 排队房名 -> 心跳写入被拒（Soul 侧「改得太频繁」）
    profile.set_title("山旮旯")
    profile.drafts.mark_attempted("title")

    assert profile.get_current_title() == "Lofi Girl"
    assert profile.get_next_title() == "山旮旯"


# --------------------------------------------------------------------------
# 换房：旧的 UI 事实必须作废，否则守卫守不住
# --------------------------------------------------------------------------


def test_changing_room_invalidates_the_room_facts_read_from_the_ui():
    """房间标识一变，上一间房的房名/主题就不能再被当成「当前值」。"""
    room_state = RoomState.initialize()
    room_state.room_id = "FM15321640"
    screen = _Screen(MAIN_SCREEN, {"chat_room_title": ROOM_NAME_ON_MAIN_SCREEN})
    profile = RoomProfileManager.initialize(handler=_handler(screen), drawer_driver=_driver())
    profile.ensure_synced_on_return()
    assert profile.get_current_title() == "Lofi Girl"

    room_state.room_id = "FM9999999"

    assert profile.get_current_title() is None, "换房后不得沿用上一间房的房名"
    assert profile.is_initialized is False, "换房后必须重新接地"


# --------------------------------------------------------------------------
# 接线：PartyManager 那条触发线必须真的接在模块上
# --------------------------------------------------------------------------


def test_party_manager_routes_the_return_and_create_paths_through_the_module():
    """#413 把推荐读写停掉时，顺手把整条抽屉审计接线做成了空壳。

    这里用源码断言钉住：回房/进房/建房三条路径必须经由
    `RoomProfileManager.ensure_synced_on_return()`，不允许留一个 `return None` 的
    同名函数继续冒充触发点。
    """
    import inspect

    from ushareiplay.managers import party_manager as pm

    source = inspect.getsource(pm)
    assert "ensure_synced_on_return()" in source, (
        "PartyManager 必须把房间档案的 UI 接地点回来 —— "
        "它是 audit_and_repair/initialize_from_ui 唯一的生产触发点"
    )


def test_a_room_name_that_cannot_be_read_leaves_the_profile_ungrounded():
    """主界面那一行读不到就不许声称接地：下一次回房必须再读一次。"""
    room_state = RoomState.initialize()
    screen = _Screen(DRAWER_SCREEN, {})  # 没有 chat_room_title，也没有抽屉里的房名
    profile = RoomProfileManager.initialize(handler=_handler(screen), drawer_driver=_driver())

    result = profile.ensure_synced_on_return()

    assert "error" in result
    assert profile.is_initialized is False
    assert profile.ensure_synced_on_return() is not None  # 还会再试


# --------------------------------------------------------------------------
# 兜底：进程重启时人已经在房里，join_party 那条线一次都没走过
# --------------------------------------------------------------------------


def _title_command(profile):
    from ushareiplay.commands.title import TitleCommand

    handler = _handler(_Screen(MAIN_SCREEN, {"chat_room_title": ROOM_NAME_ON_MAIN_SCREEN}))
    command = TitleCommand(SimpleNamespace(soul_handler=handler, music_handler=None))
    command._room_profile_manager = profile
    command._message_dispatch = SimpleNamespace(send_screen_message=lambda _m: None)
    return command


def test_the_heartbeat_grounds_the_profile_the_entry_path_missed():
    """`update_commands()` 每拍都会走 `:title` 的心跳：档案没接地就顺手读一次。

    只读、有守卫、接地之后一个 UI 调用都不发生 —— 所以挂在心跳上是安全的。
    """
    room_state = RoomState.initialize()
    screen = _Screen(MAIN_SCREEN, {"chat_room_title": ROOM_NAME_ON_MAIN_SCREEN})
    profile = RoomProfileManager.initialize(handler=_handler(screen), drawer_driver=_driver())
    assert profile.get_current_title() is None

    _title_command(profile).update()

    assert profile.get_current_title() == "Lofi Girl", "心跳必须把没接上的地补回来"

    reads = len(screen.reads)
    _title_command(profile).update()  # 已经接地：不许再为「发现已经接地」去读 UI
    assert len(screen.reads) == reads
    assert profile.is_initialized is True


def test_a_failed_grounding_backs_off_instead_of_reading_the_ui_every_tick():
    """读不到真实房名时退避，而不是每拍都吃一次 2 秒的元素等待。"""
    RoomState.initialize()
    screen = _Screen(DRAWER_SCREEN, {})  # 房名那一行还没渲染出来
    profile = RoomProfileManager.initialize(handler=_handler(screen), drawer_driver=_driver())

    _title_command(profile).update()
    assert profile.is_initialized is False
    reads_after_first_attempt = len(screen.reads)
    assert reads_after_first_attempt >= 1, "第一拍必须真的尝试过一次读，否则退避无从谈起"

    _title_command(profile).update()  # 下一拍：退避中，一次读都不该发生
    assert len(screen.reads) == reads_after_first_attempt


def test_changing_room_clears_the_grounding_backoff():
    """换房 = 重新欠一次接地：退避计时器不得把新房间也一起挡住。"""
    room_state = RoomState.initialize()
    screen = _Screen(DRAWER_SCREEN, {})
    profile = RoomProfileManager.initialize(handler=_handler(screen), drawer_driver=_driver())

    _title_command(profile).update()
    reads_after_first_attempt = len(screen.reads)
    _title_command(profile).update()
    assert len(screen.reads) == reads_after_first_attempt

    room_state.room_id = "FM9999999"

    _title_command(profile).update()
    assert len(screen.reads) > reads_after_first_attempt, "换房后必须立刻重新尝试接地"
