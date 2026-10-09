import pytest
from unittest.mock import MagicMock
from types import SimpleNamespace

from ushareiplay.managers.room_profile import RoomProfileManager
from ushareiplay.managers.room_profile.driver import RoomProfileDrawerDriverPort
from ushareiplay.managers.room_profile.soul_drawer import SoulDrawerDriver
from ushareiplay.commands.recommend import RecommendCommand
from ushareiplay.state.room_state import RoomState
from tests.fakes.in_memory_room_profile_drawer import InMemoryRoomProfileDrawerDriver


@pytest.fixture(autouse=True)
def reset_singletons():
    for cls in (RoomProfileManager, RoomState):
        cls.reset_instance()
    yield
    for cls in (RoomProfileManager, RoomState):
        cls.reset_instance()


def _build_fake_handler(clicks=None, swipes=None, backs=None, current_status_text="所有人", fail_keys=()):
    if clicks is None:
        clicks = []
    if swipes is None:
        swipes = []
    if backs is None:
        backs = []

    class FakeElement:
        def __init__(self, key, text=""):
            self.key = key
            self.text = text

        def click(self):
            clicks.append(self.key)
            return True

    setting_btn = FakeElement("party_setting_btn")
    container = FakeElement("party_setting_container")
    rec_status_elem = FakeElement("party_recommendation_status", text=current_status_text)
    rec_open_elem = FakeElement("party_recommendation_open", text="所有人")
    rec_close_elem = FakeElement("party_recommendation_close", text="关闭推荐分发")

    class FakeElementFinder:
        def wait_for_element_clickable(self, key, timeout=10):
            if key in fail_keys:
                return None
            if key == "party_setting_btn":
                return setting_btn
            if key == "party_recommendation_status":
                return rec_status_elem
            if key == "party_recommendation_open":
                return rec_open_elem
            if key == "party_recommendation_close":
                return rec_close_elem
            return None

        def wait_for_element(self, key, timeout=10):
            if key in fail_keys:
                return None
            if key == "party_setting_container":
                return container
            if key == "party_recommendation_status":
                return rec_status_elem
            return None

        def try_find_element(self, key, log=False):
            if key in fail_keys:
                return None
            if key == "party_setting_btn":
                return setting_btn
            if key == "party_setting_container":
                return container if "party_setting_btn" in clicks else None
            return None

        def get_element_text(self, element):
            return getattr(element, "text", "")

    class FakeGestureHandler:
        def scroll_container_until_element(self, element_key, container_key, direction="up", **kwargs):
            swipes.append((element_key, container_key, direction))
            if "scroll_fail" in fail_keys:
                return None, None, []
            if element_key == "party_recommendation_status" and container_key == "party_setting_container":
                return element_key, rec_status_elem, [current_status_text]
            return None, None, []

    class FakeKeyActions:
        def press_back(self):
            backs.append("press_back")

        def switch_to_app(self):
            return True

    class FakeHandler:
        def __init__(self):
            self.logger = MagicMock()
            self.element_finder = FakeElementFinder()
            self.gesture_handler = FakeGestureHandler()
            self.key_actions = FakeKeyActions()
            self.config = {
                "elements": {
                    "party_setting_btn": "cn.soulapp.android:id/partySettingBtn",
                    "party_setting_container": '//android.widget.FrameLayout[@resource-id="cn.soulapp.android:id/flContainer"]',
                    "party_recommendation_status": '//android.widget.TextView[@resource-id="cn.soulapp.android:id/tvRightHint" and (@text="所有人" or @text="关闭推荐分发")]',
                    "party_recommendation_open": '//android.widget.TextView[@text="所有人"]',
                    "party_recommendation_close": '//android.widget.TextView[@text="关闭推荐分发"]',
                }
            }

    return FakeHandler(), clicks, swipes, backs


def test_set_recommendation_opens_settings_and_swipes_to_change_status():
    """验证通过设置界面关闭/开启派对推荐：
    1. 点击设置按钮 (party_setting_btn / cn.soulapp.android:id/partySettingBtn)
    2. 在设置弹窗 (party_setting_container / cn.soulapp.android:id/flContainer) 中向下翻页滚动
    3. 找到推荐状态按钮 (party_recommendation_status / tvRightHint) 并点击
    4. 在推荐设置弹窗中选择目标选项 (party_recommendation_close / party_recommendation_open)
    5. 关闭设置弹窗并更新 RoomState
    """
    handler, clicks, swipes, backs = _build_fake_handler(current_status_text="所有人")
    profile = RoomProfileManager.initialize(handler=handler)
    room_state = RoomState.initialize()
    room_state.recommendation_enabled = True

    # 尝试关闭推荐
    result = profile.set_recommendation(False)

    assert result == {"success": True, "recommendation_enabled": False}
    assert room_state.recommendation_enabled is False
    assert "party_setting_btn" in clicks
    assert ("party_recommendation_status", "party_setting_container", "up") in swipes
    assert "party_recommendation_close" in clicks
    assert len(backs) >= 1


def test_set_recommendation_noop_when_already_target_state():
    """若当前已经是目标状态，不执行修改点击，仅关窗并返回成功。"""
    handler, clicks, swipes, backs = _build_fake_handler(current_status_text="所有人")
    profile = RoomProfileManager.initialize(handler=handler)
    room_state = RoomState.initialize()
    room_state.recommendation_enabled = True

    result = profile.set_recommendation(True)

    assert result == {"success": True, "recommendation_enabled": True}
    assert "party_setting_btn" in clicks
    assert ("party_recommendation_status", "party_setting_container", "up") in swipes
    # 未点击选项
    assert "party_recommendation_open" not in clicks
    assert "party_recommendation_close" not in clicks
    assert len(backs) >= 1


def test_set_recommendation_guest_room_refused():
    """在他人客房中不可修改推荐状态。"""
    handler, clicks, swipes, backs = _build_fake_handler()
    profile = RoomProfileManager.initialize(handler=handler)
    room_state = RoomState.initialize()
    room_state.is_guest_room = True

    result = profile.set_recommendation(False)

    assert result == {"error": "他人房间模式下不可修改推荐状态"}
    assert clicks == []


def test_set_recommendation_btn_not_found():
    """未找到设置按钮时返回错误。"""
    handler, clicks, swipes, backs = _build_fake_handler(fail_keys=("party_setting_btn",))
    profile = RoomProfileManager.initialize(handler=handler)

    result = profile.set_recommendation(False)

    assert result == {"error": "Failed to find party setting button"}


def test_set_recommendation_scroll_not_found():
    """滑动后未找到推荐状态按钮时返回错误并按返回键关窗。"""
    handler, clicks, swipes, backs = _build_fake_handler(fail_keys=("scroll_fail",))
    profile = RoomProfileManager.initialize(handler=handler)

    result = profile.set_recommendation(False)

    assert result == {"error": "Failed to find recommendation status entry"}
    assert len(backs) >= 1


def test_set_recommendation_option_click_failed():
    """选项点击失败时返回错误并按返回键关窗。"""
    handler, clicks, swipes, backs = _build_fake_handler(fail_keys=("party_recommendation_close",))
    profile = RoomProfileManager.initialize(handler=handler)

    result = profile.set_recommendation(False)

    assert result == {"error": "Failed to find option for recommendation (party_recommendation_close)"}
    assert len(backs) >= 1


@pytest.mark.asyncio
async def test_recommend_command_with_settings_interface():
    """端到端验证 RecommendCommand 通过设置界面执行关闭推荐。"""
    handler, clicks, swipes, backs = _build_fake_handler(current_status_text="所有人")
    profile = RoomProfileManager.initialize(handler=handler)
    room_state = RoomState.initialize()
    room_state.recommendation_enabled = True

    cmd_runtime = SimpleNamespace(soul_handler=handler, music_handler=SimpleNamespace())
    cmd = RecommendCommand(cmd_runtime)

    result = await cmd.do_process(SimpleNamespace(nickname="Console"), ["off"])

    assert result == {"status": "关闭"}
    assert room_state.recommendation_enabled is False
    assert "party_setting_btn" in clicks
    assert "party_recommendation_close" in clicks


def test_soul_drawer_driver_settings_methods():
    """验证 SoulDrawerDriver 正确桥接 is_settings_open 与 scroll_container_until_element。"""
    handler, _, _, _ = _build_fake_handler()
    driver = SoulDrawerDriver(handler)

    assert driver.is_settings_open() is False
    # 点击打开后
    handler.element_finder.try_find_element = lambda key, log=False: SimpleNamespace(is_displayed=lambda: True) if key == "party_setting_container" else None
    assert driver.is_settings_open() is True

    key, elem, values = driver.scroll_container_until_element(
        "party_recommendation_status", "party_setting_container", direction="up"
    )
    assert key == "party_recommendation_status"
    assert elem is not None
