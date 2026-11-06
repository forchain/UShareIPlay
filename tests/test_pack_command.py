from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from selenium.common.exceptions import StaleElementReferenceException

from ushareiplay.commands import pack as pack_module
from ushareiplay.commands.pack import (
    OPEN_USAGE,
    PACK_USAGE,
    PackCommand,
    _parse_countdown,
    _parse_heat,
    _parse_pack_level,
)
from ushareiplay.models.message_info import MessageInfo


class FakeElement:
    def __init__(self, text="", tag_name="TextView", location=None):
        self.text = text
        self.tag_name = tag_name
        self.location = location or {"x": 0, "y": 0}
        self.clicks = 0

    def click(self):
        self.clicks += 1


class StaleElement(FakeElement):
    """Element that goes stale before its text can be read."""

    def __init__(self, text=""):
        super().__init__(text=text)
        self.text_reads = 0

    @property
    def text(self):
        self.text_reads += 1
        raise StaleElementReferenceException("stale heat value")

    @text.setter
    def text(self, value):
        pass


@pytest.fixture(autouse=True)
def fast_polling(monkeypatch):
    """Keep polling-based tests instant; production timeouts are exercised by hand."""
    monkeypatch.setattr(pack_module, "HEAT_WAIT_SECONDS", 0.01)
    monkeypatch.setattr(pack_module, "HEAT_POLL_SECONDS", 0)
    monkeypatch.setattr(pack_module, "RENDER_WAIT_SECONDS", 0.05)
    monkeypatch.setattr(pack_module, "RENDER_POLL_SECONDS", 0)
    monkeypatch.setattr(pack_module, "COUNTDOWN_WAIT_SECONDS", 0.05)


@pytest.fixture
def mock_controller():
    controller = SimpleNamespace()
    soul_handler = SimpleNamespace()
    soul_handler.logger = SimpleNamespace(
        info=MagicMock(),
        warning=MagicMock(),
        error=MagicMock(),
    )
    soul_handler.log_error = MagicMock()
    soul_handler.element_finder = SimpleNamespace(
        try_find_element=MagicMock(),
        wait_for_element=MagicMock(return_value=None),
        wait_for_element_clickable=MagicMock(),
        find_elements=MagicMock(),
        find_child_elements=MagicMock(return_value=[]),
        wait_for_element_disappear=MagicMock(return_value=True),
        get_element_text=MagicMock(side_effect=lambda element: element.text if element else ""),
    )
    soul_handler.key_actions = SimpleNamespace(
        press_back=MagicMock(),
    )
    soul_handler.gesture_handler = SimpleNamespace(
        click_element_at=MagicMock(return_value=True),
        swipe=MagicMock(return_value=True),
    )
    controller.soul_handler = soul_handler
    controller.music_handler = SimpleNamespace()
    return controller


def _heat_finder(finder, heat_values, tab=True):
    """Mock the finder with a clamped heat sequence and an optional back button."""
    state = {"idx": 0}
    entry_btn = FakeElement(text="步数兑换")
    back_btn = FakeElement(text="返回")
    tab_btn = FakeElement(text="兑换福袋")

    def mock_try_find(key, **kwargs):
        if key == "heat_exchange_entry":
            return entry_btn
        if key == "heat_exchange_back":
            return back_btn
        if key == "heat_remaining_value":
            value = heat_values[min(state["idx"], len(heat_values) - 1)]
            state["idx"] += 1
            return FakeElement(text=value) if value is not None else None
        return None

    def mock_wait(key, **kwargs):
        if key == "heat_exchange_entry":
            return entry_btn
        if key == "heat_exchange_tab":
            return tab_btn if tab else None
        return None

    finder.try_find_element.side_effect = mock_try_find
    finder.wait_for_element.side_effect = mock_wait
    return entry_btn, back_btn, tab_btn


# --- heat text parsing ---


def test_parse_heat_plain_number():
    assert _parse_heat("35999") == 35999


def test_parse_heat_with_wan_unit():
    assert _parse_heat("3.5万") == 35000
    assert _parse_heat("2W") == 20000


def test_parse_heat_keeps_only_first_number():
    assert _parse_heat("35888/60000") == 35888


def test_parse_heat_accepts_thousands_separator():
    assert _parse_heat("35,999") == 35999


def test_parse_heat_returns_none_without_digits():
    assert _parse_heat("暂无热力值") is None
    assert _parse_heat("") is None


# --- :pack ---


@pytest.mark.asyncio
async def test_open_luck_pack_opens_backpack_pack_for_auto_mode(mock_controller):
    """自动触发（在线人数≥5）仍走背包里的幸运礼包，不受 :pack 形态变化影响。"""
    finder = mock_controller.soul_handler.element_finder
    luck_pack_btn = FakeElement(text="幸运礼包 奖励")
    luck_item_btn = FakeElement(text="高级福袋")
    use_pack_btn = FakeElement(text="使用")

    finder.try_find_element.side_effect = lambda key, **kwargs: luck_pack_btn if key == "luck_pack" else None
    finder.wait_for_element_clickable.side_effect = lambda key, **kwargs: (
        luck_item_btn if key == "luck_item" else use_pack_btn if key == "use_pack" else None
    )

    cmd = PackCommand(mock_controller)
    result = cmd.open_luck_pack(user_count=6)

    assert result == {
        "item": "高级福袋",
        "message": "Successfully opened luck pack 高级福袋",
    }
    assert luck_pack_btn.clicks == 1
    assert luck_item_btn.clicks == 1
    assert use_pack_btn.clicks == 1


@pytest.mark.asyncio
async def test_open_luck_pack_reports_no_pack_available(mock_controller):
    finder = mock_controller.soul_handler.element_finder
    finder.try_find_element.return_value = None

    cmd = PackCommand(mock_controller)
    result = cmd.open_luck_pack()

    assert result == {"error": "No luck pack available"}


@pytest.mark.asyncio
async def test_pack_command_invalid_subcommand_is_usage_hint(mock_controller):
    cmd = PackCommand(mock_controller)
    msg_info = MessageInfo(content=":pack invalid", nickname="Tester")
    result = await cmd.do_process(msg_info, ["invalid"])

    assert result == {"message": f"未知子命令，{PACK_USAGE}"}


@pytest.mark.asyncio
async def test_pack_redeem_rejects_extra_parameters(mock_controller):
    finder = mock_controller.soul_handler.element_finder

    cmd = PackCommand(mock_controller)
    msg_info = MessageInfo(content=":pack redeem 99999", nickname="Tester")
    result = await cmd.do_process(msg_info, ["redeem", "99999"])

    assert result == {"message": PACK_USAGE}
    finder.try_find_element.assert_not_called()


# --- :pack redeem ---


@pytest.mark.asyncio
async def test_pack_redeem_multi_round_picks_highest_affordable_tier(mock_controller):
    finder = mock_controller.soul_handler.element_finder
    entry_btn, back_btn, tab_btn = _heat_finder(finder, ["35999", "6000", "3000", "0"])

    btn_99999 = FakeElement(text="99999")
    btn_29999 = FakeElement(text="29999")
    btn_3000 = FakeElement(text="3000")
    btn_600 = FakeElement(text="600")
    finder.find_elements.side_effect = lambda key: (
        [btn_99999, btn_29999, btn_3000, btn_600] if key == "heat_exchange_buttons" else []
    )

    cmd = PackCommand(mock_controller)
    msg_info = MessageInfo(content=":pack redeem", nickname="Tester")
    result = await cmd.do_process(msg_info, ["redeem"])

    assert result == {
        "message": "成功兑换 3 个福袋，剩余热力值: 0",
    }
    assert entry_btn.clicks == 1
    # Round 1: 35999 -> clicks 29999
    assert btn_29999.clicks == 1
    # Round 2: 6000 -> clicks 3000
    # Round 3: 3000 -> clicks 3000
    assert btn_3000.clicks == 2
    # Round 4: 0 -> stops, 99999 and 600 not clicked
    assert btn_99999.clicks == 0
    assert btn_600.clicks == 0
    assert back_btn.clicks == 1
    mock_controller.soul_handler.key_actions.press_back.assert_not_called()
    mock_controller.soul_handler.logger.info.assert_called_with(
        "Redeemed 3 luck packs, remaining heat 0"
    )


@pytest.mark.asyncio
async def test_pack_redeem_waits_for_window_to_open(mock_controller):
    finder = mock_controller.soul_handler.element_finder
    entry_btn, back_btn, tab_btn = _heat_finder(finder, [None, None, None, "100"])

    cmd = PackCommand(mock_controller)
    msg_info = MessageInfo(content=":pack redeem", nickname="Tester")
    result = await cmd.do_process(msg_info, ["redeem"])

    assert result == {"message": "成功兑换 0 个福袋，剩余热力值: 100"}
    assert entry_btn.clicks == 1
    assert back_btn.clicks == 1


@pytest.mark.asyncio
async def test_pack_redeem_waits_for_balance_to_drop_after_click(mock_controller):
    """Reading the stale balance right after a click must not abort the loop."""
    finder = mock_controller.soul_handler.element_finder
    entry_btn, _, tab_btn = _heat_finder(finder, ["35999", "35999", "6000", "6000", "0"])

    btn_29999 = FakeElement(text="29999")
    btn_3000 = FakeElement(text="3000")
    finder.find_elements.side_effect = lambda key: (
        [btn_29999, btn_3000] if key == "heat_exchange_buttons" else []
    )

    cmd = PackCommand(mock_controller)
    msg_info = MessageInfo(content=":pack redeem", nickname="Tester")
    result = await cmd.do_process(msg_info, ["redeem"])

    assert result == {"message": "成功兑换 2 个福袋，剩余热力值: 0"}
    assert btn_29999.clicks == 1
    assert btn_3000.clicks == 1


@pytest.mark.asyncio
async def test_pack_redeem_case_insensitive_flag(mock_controller):
    finder = mock_controller.soul_handler.element_finder
    entry_btn, back_btn, tab_btn = _heat_finder(finder, ["100"])

    cmd = PackCommand(mock_controller)
    msg_info = MessageInfo(content=":pack REDEEM", nickname="Tester")
    result = await cmd.do_process(msg_info, ["REDEEM"])

    assert result == {"message": "成功兑换 0 个福袋，剩余热力值: 100"}
    assert entry_btn.clicks == 1
    assert back_btn.clicks == 1


@pytest.mark.asyncio
async def test_pack_redeem_entry_not_found(mock_controller):
    finder = mock_controller.soul_handler.element_finder
    finder.wait_for_element.return_value = None

    cmd = PackCommand(mock_controller)
    msg_info = MessageInfo(content=":pack redeem", nickname="Tester")
    result = await cmd.do_process(msg_info, ["redeem"])

    assert result == {"error": "未找到热力兑换入口"}
    mock_controller.soul_handler.key_actions.press_back.assert_not_called()


@pytest.mark.asyncio
async def test_pack_redeem_window_not_opened_does_not_press_back(mock_controller):
    """Without a confirmed open window, BACK could leave the party room."""
    finder = mock_controller.soul_handler.element_finder
    entry_btn, back_btn, tab_btn = _heat_finder(finder, [None], tab=False)

    cmd = PackCommand(mock_controller)
    msg_info = MessageInfo(content=":pack redeem", nickname="Tester")
    result = await cmd.do_process(msg_info, ["redeem"])

    assert result == {"error": "兑换橱窗未打开，未找到兑换福袋标签页"}
    assert entry_btn.clicks == 1
    assert back_btn.clicks == 0
    mock_controller.soul_handler.key_actions.press_back.assert_not_called()


@pytest.mark.asyncio
async def test_pack_redeem_opens_lucky_bag_tab_before_reading_tiers(mock_controller):
    """橱窗默认停在「兑换流量卡」；不切到「兑换福袋」就会把流量卡价格当档位。"""
    finder = mock_controller.soul_handler.element_finder
    entry_btn, back_btn, tab_btn = _heat_finder(finder, ["42998"])

    cmd = PackCommand(mock_controller)
    msg_info = MessageInfo(content=":pack redeem", nickname="Tester")
    await cmd.do_process(msg_info, ["redeem"])

    assert entry_btn.clicks == 1
    assert tab_btn.clicks == 1
    assert finder.wait_for_element.call_args_list[0].args[0] == "heat_exchange_entry"
    assert finder.wait_for_element.call_args_list[1].args[0] == "heat_exchange_tab"


@pytest.mark.asyncio
async def test_pack_redeem_closes_window_when_heat_unreadable_but_tab_found(mock_controller):
    """标签页出现 ⇒ 橱窗确实打开；此时不关窗，后台兜底 back 才会去关它。"""
    finder = mock_controller.soul_handler.element_finder
    entry_btn, back_btn, tab_btn = _heat_finder(finder, [None])

    cmd = PackCommand(mock_controller)
    msg_info = MessageInfo(content=":pack redeem", nickname="Tester")
    result = await cmd.do_process(msg_info, ["redeem"])

    assert result == {"error": "兑换橱窗已打开，未读取到热力值"}
    assert tab_btn.clicks == 1
    assert back_btn.clicks == 1


@pytest.mark.asyncio
async def test_pack_redeem_dead_loop_defense_when_heat_not_decreasing(mock_controller):
    finder = mock_controller.soul_handler.element_finder
    entry_btn, back_btn, tab_btn = _heat_finder(finder, ["1000"])

    btn_600 = FakeElement(text="600")
    finder.find_elements.side_effect = lambda key: [btn_600] if key == "heat_exchange_buttons" else []

    cmd = PackCommand(mock_controller)
    msg_info = MessageInfo(content=":pack redeem", nickname="Tester")
    result = await cmd.do_process(msg_info, ["redeem"])

    assert result == {"message": "成功兑换 1 个福袋，剩余热力值: 1000"}
    assert btn_600.clicks == 1
    assert back_btn.clicks == 1
    mock_controller.soul_handler.logger.warning.assert_called()


@pytest.mark.asyncio
async def test_pack_redeem_stops_when_no_affordable_tier(mock_controller):
    finder = mock_controller.soul_handler.element_finder
    entry_btn, back_btn, tab_btn = _heat_finder(finder, ["100"])

    btn_600 = FakeElement(text="600")
    finder.find_elements.side_effect = lambda key: [btn_600] if key == "heat_exchange_buttons" else []

    cmd = PackCommand(mock_controller)
    msg_info = MessageInfo(content=":pack redeem", nickname="Tester")
    result = await cmd.do_process(msg_info, ["redeem"])

    assert result == {"message": "成功兑换 0 个福袋，剩余热力值: 100"}
    assert btn_600.clicks == 0
    assert back_btn.clicks == 1


@pytest.mark.asyncio
async def test_pack_redeem_stops_at_max_redemptions(mock_controller, monkeypatch):
    monkeypatch.setattr(pack_module, "MAX_REDEMPTIONS", 3)

    finder = mock_controller.soul_handler.element_finder
    state = {"heat": 1800}
    entry_btn = FakeElement(text="步数兑换")
    back_btn = FakeElement(text="返回")

    class Balance(FakeElement):
        def click(self):
            super().click()
            state["heat"] -= 600

    btn_600 = Balance(text="600")
    finder.try_find_element.side_effect = lambda key, **kwargs: (
        entry_btn if key == "heat_exchange_entry" else
        back_btn if key == "heat_exchange_back" else
        FakeElement(text=str(state["heat"])) if key == "heat_remaining_value" else None
    )
    finder.wait_for_element.side_effect = lambda key, **kwargs: (
        entry_btn if key == "heat_exchange_entry" else
        FakeElement(text="兑换福袋") if key == "heat_exchange_tab" else None
    )
    finder.find_elements.side_effect = lambda key: [btn_600] if key == "heat_exchange_buttons" else []

    cmd = PackCommand(mock_controller)
    msg_info = MessageInfo(content=":pack redeem", nickname="Tester")
    result = await cmd.do_process(msg_info, ["redeem"])

    assert result == {
        "message": "成功兑换 3 个福袋，剩余热力值: 0（已达单次上限 3）",
    }
    assert btn_600.clicks == 3
    assert back_btn.clicks == 1
    mock_controller.soul_handler.logger.warning.assert_called()


@pytest.mark.asyncio
async def test_pack_redeem_navigation_safety_press_back_fallback(mock_controller):
    finder = mock_controller.soul_handler.element_finder
    entry_btn = FakeElement(text="步数兑换")

    # No back button on screen
    finder.try_find_element.side_effect = lambda key, **kwargs: (
        entry_btn if key == "heat_exchange_entry" else
        FakeElement(text="50") if key == "heat_remaining_value" else None
    )
    finder.wait_for_element.side_effect = lambda key, **kwargs: (
        entry_btn if key == "heat_exchange_entry" else
        FakeElement(text="兑换福袋") if key == "heat_exchange_tab" else None
    )

    cmd = PackCommand(mock_controller)
    msg_info = MessageInfo(content=":pack redeem", nickname="Tester")
    result = await cmd.do_process(msg_info, ["redeem"])

    assert result == {"message": "成功兑换 0 个福袋，剩余热力值: 50"}
    assert entry_btn.clicks == 1
    mock_controller.soul_handler.key_actions.press_back.assert_called_once()


@pytest.mark.asyncio
async def test_pack_redeem_exception_handling_safely_exits(mock_controller):
    finder = mock_controller.soul_handler.element_finder
    entry_btn, back_btn, tab_btn = _heat_finder(finder, ["1000"])

    def failing_click():
        raise RuntimeError("Click failed")

    btn_600 = FakeElement(text="600")
    btn_600.click = failing_click
    finder.find_elements.side_effect = lambda key: [btn_600] if key == "heat_exchange_buttons" else []

    cmd = PackCommand(mock_controller)
    msg_info = MessageInfo(content=":pack redeem", nickname="Tester")
    result = await cmd.do_process(msg_info, ["redeem"])

    assert result == {"error": "Failed to redeem heat"}
    # Even after error, exchange window is exited
    assert back_btn.clicks == 1
    mock_controller.soul_handler.log_error.assert_called_once()


@pytest.mark.asyncio
async def test_pack_redeem_exit_paths_failing_does_not_raise(mock_controller):
    finder = mock_controller.soul_handler.element_finder
    entry_btn = FakeElement(text="步数兑换")

    def failing_click():
        raise RuntimeError("Back click failed")

    back_btn = FakeElement(text="返回")
    back_btn.click = failing_click
    finder.try_find_element.side_effect = lambda key, **kwargs: (
        entry_btn if key == "heat_exchange_entry" else
        back_btn if key == "heat_exchange_back" else
        FakeElement(text="50") if key == "heat_remaining_value" else None
    )
    finder.wait_for_element.side_effect = lambda key, **kwargs: (
        entry_btn if key == "heat_exchange_entry" else
        FakeElement(text="兑换福袋") if key == "heat_exchange_tab" else None
    )
    mock_controller.soul_handler.key_actions.press_back.side_effect = RuntimeError("back key failed")

    cmd = PackCommand(mock_controller)
    msg_info = MessageInfo(content=":pack redeem", nickname="Tester")
    result = await cmd.do_process(msg_info, ["redeem"])

    assert result == {"message": "成功兑换 0 个福袋，剩余热力值: 50"}
    assert back_btn.clicks == 0


@pytest.mark.asyncio
async def test_pack_redeem_stale_balance_is_retried_not_fatal(mock_controller):
    """余额节点被 App 重建时 .text 会抛 Stale；必须重试而不是整条命令失败。"""
    finder = mock_controller.soul_handler.element_finder
    entry_btn, back_btn, tab_btn = _heat_finder(finder, ["42998"])

    stale = StaleElement()
    calls = {"n": 0}
    heat_after = ["42998", "42998", "9999"]

    def mock_try_find(key, **kwargs):
        if key == "heat_remaining_value":
            calls["n"] += 1
            if calls["n"] == 1:
                return stale
            return FakeElement(text=heat_after[min(calls["n"] - 2, len(heat_after) - 1)])
        if key == "heat_exchange_entry":
            return entry_btn
        if key == "heat_exchange_back":
            return back_btn
        return None

    def mock_get_text(element):
        try:
            return element.text
        except StaleElementReferenceException:
            return ""

    finder.try_find_element.side_effect = mock_try_find
    finder.get_element_text.side_effect = mock_get_text

    btn_12000 = FakeElement(text="12000")
    finder.find_elements.side_effect = lambda key: (
        [btn_12000] if key == "heat_exchange_buttons" else []
    )

    cmd = PackCommand(mock_controller)
    msg_info = MessageInfo(content=":pack redeem", nickname="Tester")
    result = await cmd.do_process(msg_info, ["redeem"])

    assert result == {"message": "成功兑换 1 个福袋，剩余热力值: 9999"}
    assert btn_12000.clicks == 1
    mock_controller.soul_handler.log_error.assert_not_called()


@pytest.mark.asyncio
async def test_pack_redeem_skips_locked_tier_without_numeric_price(mock_controller):
    """锁定档位没有具体数值，只能跳过；兑换后继续检测下一轮。"""
    finder = mock_controller.soul_handler.element_finder
    entry_btn, back_btn, tab_btn = _heat_finder(finder, ["42998", "42998", "9999"])

    btn_locked = FakeElement(text="锁定")
    btn_10000 = FakeElement(text="10000")
    btn_100000 = FakeElement(text="100000")
    finder.find_elements.side_effect = lambda key: (
        [btn_locked, btn_10000, btn_100000] if key == "heat_exchange_buttons" else []
    )

    cmd = PackCommand(mock_controller)
    msg_info = MessageInfo(content=":pack redeem", nickname="Tester")
    result = await cmd.do_process(msg_info, ["redeem"])

    assert result == {"message": "成功兑换 1 个福袋，剩余热力值: 9999"}
    assert btn_locked.clicks == 0
    assert btn_100000.clicks == 0
    assert btn_10000.clicks == 1


@pytest.mark.asyncio
async def test_pack_redeem_closes_window_when_tab_click_fails(mock_controller):
    """标签页存在 ⇒ 橱窗已打开；切页失败也要关窗，否则错误消息发不出去。"""
    finder = mock_controller.soul_handler.element_finder
    entry_btn, back_btn, tab_btn = _heat_finder(finder, ["42998"])

    def failing_click():
        raise RuntimeError("Tab click failed")

    tab_btn.click = failing_click

    cmd = PackCommand(mock_controller)
    msg_info = MessageInfo(content=":pack redeem", nickname="Tester")
    result = await cmd.do_process(msg_info, ["redeem"])

    assert result == {"error": "切换到兑换福袋标签页失败"}
    assert back_btn.clicks == 1


# --- config wiring ---


def test_pack_config_declarations():
    """Verify that config.yaml declares pack subcommands, elements, and templates."""
    from pathlib import Path
    import yaml
    from ushareiplay.core.roles import resolve_command_level

    repo_root = Path(__file__).resolve().parents[1]
    with open(repo_root / "config.yaml", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    elements = config["soul"]["elements"]
    assert elements["heat_exchange_entry"] == "cn.soulapp.android:id/tvStepInfo"
    assert elements["heat_exchange_tab"] == '//android.view.View[@text="兑换福袋"]'
    assert "每日0点清零" in elements["heat_remaining_value"]
    assert "600" in elements["heat_exchange_buttons"]
    assert "兑换橱窗" in elements["heat_exchange_back"]

    # 福袋抽屉与倒计时的元素定位器
    assert elements["pack_entry"] == "cn.soulapp.android:id/tvLbLabelPackNormal"
    assert elements["pack_list"] == "cn.soulapp.android:id/listUser"
    assert elements["pack_content"] == "cn.soulapp.android:id/tvContent"
    assert elements["pack_drawer_handle"] == "cn.soulapp.android:id/touch_close"
    assert elements["pack_countdown_text"] == "cn.soulapp.android:id/tvSettingContent"
    assert elements["pack_countdown_entry"] == "cn.soulapp.android:id/tvSetting"
    assert elements["pack_countdown_item"] == "cn.soulapp.android:id/settingCountDown"
    assert elements["pack_countdown_option"] == "cn.soulapp.android:id/tvLabel"
    assert elements["pack_countdown_confirm"] == "cn.soulapp.android:id/tvConfirm"

    pack_cmd = next(c for c in config["commands"] if c["prefix"] == "pack")
    assert pack_cmd["level"] == 3
    assert pack_cmd["subcommands"] == {
        "list": {"level": 3},
        "open": {"level": 3},
        "redeem": {"level": 2},
    }
    assert pack_cmd["response_template"] == "{message}"
    assert pack_cmd["error_template"] == "{error}"
    assert resolve_command_level(pack_cmd, []) == 3
    assert resolve_command_level(pack_cmd, ["list"]) == 3
    assert resolve_command_level(pack_cmd, ["LIST"]) == 3
    assert resolve_command_level(pack_cmd, ["open"]) == 3
    assert resolve_command_level(pack_cmd, ["open", "3", "5"]) == 3
    assert resolve_command_level(pack_cmd, ["redeem"]) == 2
    assert resolve_command_level(pack_cmd, ["REDEEM"]) == 2


@pytest.mark.asyncio
async def test_pack_redeem_error_renders_without_generic_prefix():
    """`:pack redeem` failures must reach the user self-descriptive, not wrapped."""
    from contextlib import asynccontextmanager
    from pathlib import Path

    import yaml

    from ushareiplay.managers.command_manager import CommandManager

    class RuntimeStub:
        def emit(self, *args, **kwargs):
            return None

        @asynccontextmanager
        async def ui_session(self, *_args, **_kwargs):
            yield

    class HandlerStub:
        config = {"system_users": ["Timer"]}
        logger = SimpleNamespace(
            info=lambda *_a, **_k: None,
            warning=lambda *_a, **_k: None,
            debug=lambda *_a, **_k: None,
            error=lambda *_a, **_k: None,
        )
        controller = None

    class FakePackCommand:
        async def process(self, *_args, **_kwargs):
            return {"error": "未找到热力兑换入口"}

    config = yaml.safe_load((Path(__file__).resolve().parents[1] / "config.yaml").read_text(encoding="utf-8"))
    pack_cmd = next(c for c in config["commands"] if c["prefix"] == "pack")
    command_info = {
        **pack_cmd,
        "parameters": ["redeem"],
        "response_template": pack_cmd["response_template"],
        "error_template": pack_cmd["error_template"],
    }

    manager = CommandManager.instance()
    manager.configure_runtime(RuntimeStub())
    manager._handler = HandlerStub()
    msg = MessageInfo(content=":pack redeem", nickname="Alice")

    with patch("ushareiplay.dal.user_dao.UserDAO.get_or_create", new_callable=AsyncMock) as mock_user:
        mock_user.return_value = SimpleNamespace(level=2)
        response = await manager.process_command(FakePackCommand(), msg, command_info)

    assert response == "未找到热力兑换入口"


# --- 福袋阶段文案与倒计时解析 ---


def test_parse_pack_level_reads_phase_text():
    assert _parse_pack_level("第一阶段奖励") == 1
    assert _parse_pack_level("第二阶段奖励") == 2
    assert _parse_pack_level("第三阶段奖励") == 3
    assert _parse_pack_level("第四阶段奖励") == 4
    assert _parse_pack_level("第五阶段奖励") == 5


def test_parse_pack_level_ignores_other_text():
    assert _parse_pack_level("初级福袋") is None
    assert _parse_pack_level("") is None
    assert _parse_pack_level(None) is None


def test_parse_countdown_reads_option_text():
    assert _parse_countdown("即刻抢 | 所有人") == 0
    assert _parse_countdown("1分钟 | 所有人") == 1
    assert _parse_countdown("3分钟 | 所有人") == 3
    assert _parse_countdown("10分钟 | 所有人") == 10


def test_parse_countdown_rejects_unknown_text():
    assert _parse_countdown("") is None
    assert _parse_countdown("随时") is None
    assert _parse_countdown(None) is None


# --- 福袋抽屉场景 ---

#: 福袋等级 → 阶段文案里的汉字
_PHASE_CN = {1: "一", 2: "二", 3: "三", 4: "四", 5: "五"}


#: 一屏正好两件福袋；滑一屏位移 0.7 个抽屉高度。
_PACK_ITEM_HEIGHT = 400


class FakeDrawer:
    """福袋列表容器。"""

    def __init__(self):
        self.location = {"x": 0, "y": 600}
        self.size = {"width": 720, "height": 700}


def _pack_setup(mock_controller, packs, countdown="即刻抢 | 所有人", start=0):
    """摆一个会滚动的福袋抽屉场景。

    packs 是列表自上而下的全部福袋，每项为 (等级, 名称)；start 是抽屉打开时
    第一个可见条目的下标。卡片按固定间距排布，滑动时整体位移。
    """
    finder = mock_controller.soul_handler.element_finder
    gesture = mock_controller.soul_handler.gesture_handler
    drawer = FakeDrawer()
    top = drawer.location["y"]
    max_offset = max(0, len(packs) * _PACK_ITEM_HEIGHT - drawer.size["height"])
    state = {"offset": min(start * _PACK_ITEM_HEIGHT, max_offset)}
    contents = []

    entry = FakeElement(text="福袋")
    handle = FakeElement(text="")
    use = FakeElement(text="使用")
    setting = FakeElement(text="去设置")
    countdown_item = FakeElement(text="倒计时")
    confirm = FakeElement(text="确认")
    countdown_text = FakeElement(text=countdown)
    options = [
        FakeElement(text=text)
        for text in ("即刻抢", "1分钟", "3分钟", "5分钟", "10分钟")
    ]

    def visible():
        for index, (level, name) in enumerate(packs):
            item_top = top + index * _PACK_ITEM_HEIGHT - state["offset"]
            if item_top + _PACK_ITEM_HEIGHT <= top or item_top >= top + drawer.size["height"]:
                continue
            yield level, name, item_top

    def find_children(_parent, key, **_kwargs):
        visible_items = list(visible())
        if key == "pack_content":
            elements = [
                FakeElement(text=f"第{_PHASE_CN[level]}阶段奖励", location={"x": 0, "y": item_top})
                for level, _name, item_top in visible_items
            ]
            contents.extend(elements)
            return elements
        if key == "luck_item":
            return [FakeElement(text=name) for _level, name, _top in visible_items]
        return []

    def swipe(_x1, start_y, _x2, end_y, **_kwargs):
        # 手指上滑（start_y > end_y）露出更靠后的条目；下滑露出更靠前的条目
        distance = int(drawer.size["height"] * 0.7)
        if start_y > end_y:
            state["offset"] = min(state["offset"] + distance, max_offset)
        else:
            state["offset"] = max(state["offset"] - distance, 0)
        return True

    gesture.swipe.side_effect = swipe
    finder.find_child_elements.side_effect = find_children
    finder.wait_for_element_clickable.side_effect = lambda key, **_kwargs: (
        use if key == "use_pack" else None
    )
    finder.wait_for_element.side_effect = lambda key, **_kwargs: {
        "pack_entry": entry,
        "pack_list": drawer,
        "pack_drawer_handle": handle,
        "pack_countdown_text": countdown_text,
        "pack_countdown_entry": setting,
        "pack_countdown_item": countdown_item,
        "pack_countdown_confirm": confirm,
    }.get(key)
    finder.try_find_element.side_effect = lambda key, **_kwargs: (
        drawer if key == "pack_list" else None
    )
    finder.find_elements.side_effect = lambda key: (
        options if key == "pack_countdown_option" else []
    )

    return SimpleNamespace(
        entry=entry,
        handle=handle,
        use=use,
        setting=setting,
        countdown_item=countdown_item,
        confirm=confirm,
        countdown_text=countdown_text,
        options=options,
        contents=contents,
        state=state,
    )


# --- :pack / :pack list ---


@pytest.mark.asyncio
async def test_pack_no_args_lists_packs_and_closes_drawer(mock_controller):
    parts = _pack_setup(
        mock_controller, [(3, "高级福袋"), (2, "中级福袋"), (1, "初级福袋")]
    )

    cmd = PackCommand(mock_controller)
    result = await cmd.do_process(MessageInfo(content=":pack", nickname="Tester"), [])

    assert result == {
        "message": "福袋列表（共3个）：高级福袋（3级）、中级福袋（2级）、初级福袋（1级）"
    }
    assert parts.entry.clicks == 1
    mock_controller.soul_handler.gesture_handler.click_element_at.assert_called_once_with(
        parts.handle, x_ratio=0.5, y_ratio=0, y_offset=-200
    )


@pytest.mark.asyncio
async def test_pack_list_alias_matches_no_arg_form(mock_controller):
    _pack_setup(mock_controller, [(1, "初级福袋")])

    cmd = PackCommand(mock_controller)
    result = await cmd.do_process(MessageInfo(content=":pack list", nickname="Tester"), ["list"])

    assert result == {"message": "福袋列表（共1个）：初级福袋（1级）"}


@pytest.mark.asyncio
async def test_pack_list_scrolls_until_bottom_and_merges_screens(mock_controller):
    parts = _pack_setup(
        mock_controller,
        [(3, "高级福袋"), (2, "中级福袋"), (1, "初级福袋")],
    )

    cmd = PackCommand(mock_controller)
    result = await cmd.do_process(MessageInfo(content=":pack list", nickname="Tester"), ["list"])

    assert result == {
        "message": "福袋列表（共3个）：高级福袋（3级）、中级福袋（2级）、初级福袋（1级）"
    }
    assert parts.state["offset"] > 0


@pytest.mark.asyncio
async def test_pack_list_without_packs_returns_friendly_hint(mock_controller):
    _pack_setup(mock_controller, [])

    cmd = PackCommand(mock_controller)
    result = await cmd.do_process(MessageInfo(content=":pack", nickname="Tester"), [])

    assert result == {"message": "当前没有福袋"}


@pytest.mark.asyncio
async def test_pack_list_reports_missing_entry(mock_controller):
    finder = mock_controller.soul_handler.element_finder
    finder.wait_for_element.side_effect = lambda key, **_kwargs: (
        None if key == "pack_entry" else FakeElement(text=key)
    )

    cmd = PackCommand(mock_controller)
    result = await cmd.do_process(MessageInfo(content=":pack", nickname="Tester"), [])

    assert result == {"error": "未找到福袋入口"}
    mock_controller.soul_handler.gesture_handler.click_element_at.assert_not_called()


@pytest.mark.asyncio
async def test_pack_list_closes_drawer_when_scan_fails(mock_controller):
    parts = _pack_setup(mock_controller, [(1, "初级福袋")])
    finder = mock_controller.soul_handler.element_finder
    finder.find_child_elements.side_effect = RuntimeError("列表读取失败")

    cmd = PackCommand(mock_controller)
    result = await cmd.do_process(MessageInfo(content=":pack", nickname="Tester"), [])

    assert result == {"error": "Failed to list luck packs"}
    mock_controller.soul_handler.gesture_handler.click_element_at.assert_called_once_with(
        parts.handle, x_ratio=0.5, y_ratio=0, y_offset=-200
    )


@pytest.mark.asyncio
async def test_pack_list_scans_packs_above_the_initial_viewport(mock_controller):
    """抽屉停在列表中间时，更高等级的福袋在视口上方，必须往回扫到。"""
    _pack_setup(
        mock_controller,
        [(5, "至尊福袋"), (4, "钻石福袋"), (3, "高级福袋"), (2, "中级福袋"), (1, "初级福袋")],
        start=2,
    )

    cmd = PackCommand(mock_controller)
    result = await cmd.do_process(MessageInfo(content=":pack list", nickname="Tester"), ["list"])

    assert result == {
        "message": "福袋列表（共5个）：至尊福袋（5级）、钻石福袋（4级）、高级福袋（3级）、"
                   "中级福袋（2级）、初级福袋（1级）"
    }


@pytest.mark.asyncio
async def test_pack_open_finds_level_above_the_initial_viewport(mock_controller):
    parts = _pack_setup(
        mock_controller,
        [(5, "至尊福袋"), (4, "钻石福袋"), (3, "高级福袋"), (2, "中级福袋")],
        start=2,
    )

    cmd = PackCommand(mock_controller)
    result = await cmd.do_process(
        MessageInfo(content=":pack open 5", nickname="Tester"), ["open", "5"]
    )

    assert result == {"message": "已开启5级福袋"}
    assert [element.text for element in parts.contents if element.clicks] == ["第五阶段奖励"]
    assert parts.use.clicks == 1


# --- :pack open ---


@pytest.mark.asyncio
async def test_pack_open_defaults_to_smallest_pack_with_instant_countdown(mock_controller):
    parts = _pack_setup(
        mock_controller,
        [(3, "高级福袋"), (2, "中级福袋"), (1, "初级福袋")],
    )

    cmd = PackCommand(mock_controller)
    result = await cmd.do_process(MessageInfo(content=":pack open", nickname="Tester"), ["open"])

    assert result == {"message": "已开启1级福袋"}
    # 倒计时已经是即刻抢，不必改设置
    assert parts.setting.clicks == 0
    assert parts.confirm.clicks == 0
    # 点中的是等级最小的那一个
    assert [element.text for element in parts.contents if element.clicks] == ["第一阶段奖励"]
    assert parts.use.clicks == 1


@pytest.mark.asyncio
async def test_pack_open_switches_countdown_when_mismatch(mock_controller):
    parts = _pack_setup(
        mock_controller, [(1, "初级福袋")], countdown="1分钟 | 所有人"
    )

    cmd = PackCommand(mock_controller)
    result = await cmd.do_process(
        MessageInfo(content=":pack open 1 5", nickname="Tester"), ["open", "1", "5"]
    )

    assert result == {"message": "已开启1级福袋"}
    assert parts.setting.clicks == 1
    assert parts.countdown_item.clicks == 1
    assert parts.options[3].clicks == 1  # 5分钟
    assert parts.options[1].clicks == 0  # 1分钟
    assert parts.confirm.clicks == 1


@pytest.mark.asyncio
async def test_pack_open_keeps_countdown_when_already_matching(mock_controller):
    parts = _pack_setup(
        mock_controller, [(2, "中级福袋")], countdown="3分钟 | 所有人"
    )

    cmd = PackCommand(mock_controller)
    result = await cmd.do_process(
        MessageInfo(content=":pack open 2 3", nickname="Tester"), ["open", "2", "3"]
    )

    assert result == {"message": "已开启2级福袋"}
    assert parts.setting.clicks == 0
    assert parts.confirm.clicks == 0


@pytest.mark.asyncio
async def test_pack_open_selects_requested_level(mock_controller):
    parts = _pack_setup(
        mock_controller,
        [(3, "高级福袋"), (2, "中级福袋"), (1, "初级福袋")],
    )

    cmd = PackCommand(mock_controller)
    result = await cmd.do_process(
        MessageInfo(content=":pack open 3", nickname="Tester"), ["open", "3"]
    )

    assert result == {"message": "已开启3级福袋"}
    assert [element.text for element in parts.contents if element.clicks] == ["第三阶段奖励"]
    assert parts.use.clicks == 1


@pytest.mark.asyncio
async def test_pack_open_success_leaves_drawer_to_settle_itself(mock_controller):
    _pack_setup(mock_controller, [(1, "初级福袋")])

    cmd = PackCommand(mock_controller)
    await cmd.do_process(MessageInfo(content=":pack open 1", nickname="Tester"), ["open", "1"])

    # 开启成功后抽屉会自己落定，不再手动点抓手
    mock_controller.soul_handler.gesture_handler.click_element_at.assert_not_called()


@pytest.mark.asyncio
async def test_pack_open_missing_pack_closes_drawer_manually(mock_controller):
    parts = _pack_setup(mock_controller, [(1, "初级福袋")])

    cmd = PackCommand(mock_controller)
    result = await cmd.do_process(
        MessageInfo(content=":pack open 5", nickname="Tester"), ["open", "5"]
    )

    assert result == {"error": "未找到5级福袋"}
    assert parts.use.clicks == 0
    mock_controller.soul_handler.gesture_handler.click_element_at.assert_called_once_with(
        parts.handle, x_ratio=0.5, y_ratio=0, y_offset=-200
    )


@pytest.mark.asyncio
async def test_pack_open_without_use_button_closes_drawer(mock_controller):
    parts = _pack_setup(mock_controller, [(1, "初级福袋")])
    finder = mock_controller.soul_handler.element_finder
    finder.wait_for_element_clickable.side_effect = lambda key, **_kwargs: (
        None if key == "use_pack" else FakeElement(text=key)
    )

    cmd = PackCommand(mock_controller)
    result = await cmd.do_process(
        MessageInfo(content=":pack open 1", nickname="Tester"), ["open", "1"]
    )

    assert result == {"error": "福袋未选中，使用按钮不可用"}
    mock_controller.soul_handler.gesture_handler.click_element_at.assert_called_once_with(
        parts.handle, x_ratio=0.5, y_ratio=0, y_offset=-200
    )


@pytest.mark.asyncio
async def test_pack_open_rejects_invalid_level(mock_controller):
    cmd = PackCommand(mock_controller)
    result = await cmd.do_process(
        MessageInfo(content=":pack open 9", nickname="Tester"), ["open", "9"]
    )

    assert result == {"message": OPEN_USAGE}
    mock_controller.soul_handler.element_finder.wait_for_element_clickable.assert_not_called()


@pytest.mark.asyncio
async def test_pack_open_rejects_invalid_countdown(mock_controller):
    cmd = PackCommand(mock_controller)
    result = await cmd.do_process(
        MessageInfo(content=":pack open 1 2", nickname="Tester"), ["open", "1", "2"]
    )

    assert result == {"message": OPEN_USAGE}
    mock_controller.soul_handler.element_finder.wait_for_element_clickable.assert_not_called()


@pytest.mark.asyncio
async def test_pack_open_rejects_too_many_parameters(mock_controller):
    cmd = PackCommand(mock_controller)
    result = await cmd.do_process(
        MessageInfo(content=":pack open 1 5 9", nickname="Tester"), ["open", "1", "5", "9"]
    )

    assert result == {"message": OPEN_USAGE}
    mock_controller.soul_handler.element_finder.wait_for_element_clickable.assert_not_called()


@pytest.mark.asyncio
async def test_pack_open_reports_missing_entry(mock_controller):
    finder = mock_controller.soul_handler.element_finder
    finder.wait_for_element.side_effect = lambda key, **_kwargs: (
        None if key == "pack_entry" else FakeElement(text=key)
    )

    cmd = PackCommand(mock_controller)
    result = await cmd.do_process(MessageInfo(content=":pack open", nickname="Tester"), ["open"])

    assert result == {"error": "未找到福袋入口"}
    mock_controller.soul_handler.gesture_handler.click_element_at.assert_not_called()


@pytest.mark.asyncio
async def test_pack_list_falls_back_to_level_label_without_names(mock_controller):
    """福袋卡片没有名称时退化成「N级福袋」，不至于整条命令失败。"""
    finder = mock_controller.soul_handler.element_finder
    _pack_setup(mock_controller, [(1, "初级福袋")])
    finder.find_child_elements.side_effect = lambda _parent, key, **_kwargs: (
        [FakeElement(text="第一阶段奖励")] if key == "pack_content" else []
    )

    cmd = PackCommand(mock_controller)
    result = await cmd.do_process(MessageInfo(content=":pack", nickname="Tester"), [])

    assert result == {"message": "福袋列表（共1个）：1级福袋"}


@pytest.mark.asyncio
async def test_pack_list_tolerates_missing_names(mock_controller):
    """名称与阶段对不上时（名称更少），后面的福袋退化成「N级福袋」，不报错。"""
    finder = mock_controller.soul_handler.element_finder
    _pack_setup(mock_controller, [(2, "中级福袋"), (1, "初级福袋")])
    finder.find_child_elements.side_effect = lambda _parent, key, **_kwargs: (
        [FakeElement(text="第二阶段奖励"), FakeElement(text="第一阶段奖励")]
        if key == "pack_content" else
        [FakeElement(text="中级福袋")]
        if key == "luck_item" else
        []
    )

    cmd = PackCommand(mock_controller)
    result = await cmd.do_process(MessageInfo(content=":pack", nickname="Tester"), [])

    assert result == {
        "message": "福袋列表（共2个）：中级福袋（2级）、1级福袋"
    }


@pytest.mark.asyncio
async def test_pack_list_counts_same_level_packs_on_one_screen(mock_controller):
    """同屏两个中级福袋是两件，不能按 (等级, 名称) 合并成一件。"""
    _pack_setup(mock_controller, [(2, "中级福袋"), (2, "中级福袋"), (1, "初级福袋")])

    cmd = PackCommand(mock_controller)
    result = await cmd.do_process(MessageInfo(content=":pack list", nickname="Tester"), ["list"])

    assert result == {
        "message": "福袋列表（共3个）：中级福袋（2级）×2、初级福袋（1级）"
    }


@pytest.mark.asyncio
async def test_pack_list_scans_past_identical_screens(mock_controller):
    """连续两屏同档位福袋文案一致，但确实滑动了；不能把文案当成「到底」。"""
    _pack_setup(
        mock_controller,
        [(2, "中级福袋"), (2, "中级福袋"), (2, "中级福袋"), (2, "中级福袋"), (1, "初级福袋")],
    )

    cmd = PackCommand(mock_controller)
    result = await cmd.do_process(MessageInfo(content=":pack list", nickname="Tester"), ["list"])

    assert result == {
        "message": "福袋列表（共5个）：中级福袋（2级）×4、初级福袋（1级）"
    }


@pytest.mark.asyncio
async def test_pack_open_without_level_finds_lowest_below_identical_screens(mock_controller):
    """省略 level 时选等级最小的；不能因为前两屏文案相同就停在半截。"""
    parts = _pack_setup(
        mock_controller,
        [(2, "中级福袋"), (2, "中级福袋"), (2, "中级福袋"), (2, "中级福袋"), (1, "初级福袋")],
    )

    cmd = PackCommand(mock_controller)
    result = await cmd.do_process(MessageInfo(content=":pack open", nickname="Tester"), ["open"])

    assert result == {"message": "已开启1级福袋"}
    assert [element.text for element in parts.contents if element.clicks] == ["第一阶段奖励"]


@pytest.mark.asyncio
async def test_pack_open_missing_pack_leaves_countdown_untouched(mock_controller):
    """找不到目标档位时不能先改房间倒计时——那是房间级的持久设置。"""
    parts = _pack_setup(
        mock_controller, [(1, "初级福袋")], countdown="1分钟 | 所有人"
    )

    cmd = PackCommand(mock_controller)
    result = await cmd.do_process(
        MessageInfo(content=":pack open 5", nickname="Tester"), ["open", "5"]
    )

    assert result == {"error": "未找到5级福袋"}
    assert parts.setting.clicks == 0
    assert parts.countdown_item.clicks == 0
    assert parts.confirm.clicks == 0


@pytest.mark.asyncio
async def test_close_pack_drawer_falls_back_to_back(mock_controller):
    """抓手没点掉抽屉时按返回兜底，确认列表消失才算关掉。"""
    finder = mock_controller.soul_handler.element_finder
    _pack_setup(mock_controller, [(1, "初级福袋")])
    finder.wait_for_element_disappear.return_value = False
    finder.try_find_element.side_effect = lambda key, **_kwargs: None

    cmd = PackCommand(mock_controller)

    assert cmd._close_pack_drawer() is True
    mock_controller.soul_handler.key_actions.press_back.assert_called_once()


@pytest.mark.asyncio
async def test_close_pack_drawer_reports_failure_when_still_visible(mock_controller):
    finder = mock_controller.soul_handler.element_finder
    _pack_setup(mock_controller, [(1, "初级福袋")])
    finder.wait_for_element_disappear.return_value = False

    cmd = PackCommand(mock_controller)

    assert cmd._close_pack_drawer() is False
    mock_controller.soul_handler.key_actions.press_back.assert_called_once()


@pytest.mark.asyncio
async def test_pack_list_waits_for_cards_to_render(mock_controller):
    """抽屉容器出现时子卡片可能还没渲染，读空一次不能就当「没有福袋」。"""
    _pack_setup(mock_controller, [(1, "初级福袋")])
    finder = mock_controller.soul_handler.element_finder
    render = finder.find_child_elements.side_effect
    calls = {"count": 0}

    def late(parent, key, **kwargs):
        if key == "pack_content" and calls["count"] == 0:
            calls["count"] += 1
            return []
        return render(parent, key, **kwargs)

    finder.find_child_elements.side_effect = late

    cmd = PackCommand(mock_controller)
    result = await cmd.do_process(MessageInfo(content=":pack list", nickname="Tester"), ["list"])

    assert result == {"message": "福袋列表（共1个）：初级福袋（1级）"}


@pytest.mark.asyncio
async def test_pack_open_waits_for_countdown_options_to_render(mock_controller):
    """设置弹层刚起时选项列表可能是空的，要等它渲染。"""
    parts = _pack_setup(
        mock_controller, [(1, "初级福袋")], countdown="1分钟 | 所有人"
    )
    finder = mock_controller.soul_handler.element_finder
    options = parts.options
    calls = {"count": 0}

    def late(key):
        if key != "pack_countdown_option":
            return []
        calls["count"] += 1
        return [] if calls["count"] == 1 else options

    finder.find_elements.side_effect = late

    cmd = PackCommand(mock_controller)
    result = await cmd.do_process(
        MessageInfo(content=":pack open 1 5", nickname="Tester"), ["open", "1", "5"]
    )

    assert result == {"message": "已开启1级福袋"}
    assert parts.options[3].clicks == 1  # 5分钟


# --- 权限 ---


@pytest.mark.asyncio
async def test_pack_requires_level_three_for_normal_users():
    """普通用户等级不足 3 时，`:pack` 必须被权限门禁拦下。"""
    from contextlib import asynccontextmanager
    from pathlib import Path

    import yaml

    from ushareiplay.managers.command_manager import CommandManager

    class RuntimeStub:
        def emit(self, *args, **kwargs):
            return None

        @asynccontextmanager
        async def ui_session(self, *_args, **_kwargs):
            yield

    class HandlerStub:
        config = {"system_users": ["Timer"]}
        logger = SimpleNamespace(
            info=lambda *_a, **_k: None,
            warning=lambda *_a, **_k: None,
            debug=lambda *_a, **_k: None,
            error=lambda *_a, **_k: None,
        )
        controller = None

    class FakePackCommand:
        async def process(self, *_args, **_kwargs):
            return {"message": "不该执行到这里"}

    config = yaml.safe_load(
        (Path(__file__).resolve().parents[1] / "config.yaml").read_text(encoding="utf-8")
    )
    pack_cmd = next(c for c in config["commands"] if c["prefix"] == "pack")
    command_info = {
        **pack_cmd,
        "parameters": [],
        "response_template": pack_cmd["response_template"],
        "error_template": pack_cmd["error_template"],
    }

    manager = CommandManager.instance()
    manager.configure_runtime(RuntimeStub())
    manager._handler = HandlerStub()
    msg = MessageInfo(content=":pack", nickname="Alice")

    with patch("ushareiplay.dal.user_dao.UserDAO.get_or_create", new_callable=AsyncMock) as mock_user:
        mock_user.return_value = SimpleNamespace(level=2)
        response = await manager.process_command(FakePackCommand(), msg, command_info)

    assert response == "需要等级 3 才能使用此命令，您当前等级为 2"
