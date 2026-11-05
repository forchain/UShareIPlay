from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ushareiplay.commands import pack as pack_module
from ushareiplay.commands.pack import PackCommand, _parse_heat
from ushareiplay.models.message_info import MessageInfo


class FakeElement:
    def __init__(self, text="", tag_name="TextView"):
        self.text = text
        self.tag_name = tag_name
        self.clicks = 0

    def click(self):
        self.clicks += 1


@pytest.fixture(autouse=True)
def fast_heat_polling(monkeypatch):
    """Keep polling-based tests instant; production timeouts are exercised by hand."""
    monkeypatch.setattr(pack_module, "HEAT_WAIT_SECONDS", 0.01)
    monkeypatch.setattr(pack_module, "HEAT_POLL_SECONDS", 0)


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
        wait_for_element_clickable=MagicMock(),
        find_elements=MagicMock(),
    )
    soul_handler.key_actions = SimpleNamespace(
        press_back=MagicMock(),
    )
    controller.soul_handler = soul_handler
    controller.music_handler = SimpleNamespace()
    return controller


def _heat_finder(finder, heat_values):
    """Mock the finder with a clamped heat sequence and an optional back button."""
    state = {"idx": 0}
    entry_btn = FakeElement(text="步数兑换")
    back_btn = FakeElement(text="返回")

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

    finder.try_find_element.side_effect = mock_try_find
    return entry_btn, back_btn


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
async def test_pack_command_no_args_opens_luck_pack(mock_controller):
    finder = mock_controller.soul_handler.element_finder
    luck_pack_btn = FakeElement(text="幸运礼包 奖励")
    luck_item_btn = FakeElement(text="高级福袋")
    use_pack_btn = FakeElement(text="使用")

    finder.try_find_element.side_effect = lambda key, **kwargs: luck_pack_btn if key == "luck_pack" else None
    finder.wait_for_element_clickable.side_effect = lambda key, **kwargs: (
        luck_item_btn if key == "luck_item" else use_pack_btn if key == "use_pack" else None
    )

    cmd = PackCommand(mock_controller)
    msg_info = MessageInfo(content=":pack", nickname="Tester")
    result = await cmd.do_process(msg_info, [])

    assert result == {
        "item": "高级福袋",
        "message": "Successfully opened luck pack 高级福袋",
    }
    assert luck_pack_btn.clicks == 1
    assert luck_item_btn.clicks == 1
    assert use_pack_btn.clicks == 1


@pytest.mark.asyncio
async def test_pack_command_no_luck_pack_available(mock_controller):
    finder = mock_controller.soul_handler.element_finder
    finder.try_find_element.return_value = None

    cmd = PackCommand(mock_controller)
    msg_info = MessageInfo(content=":pack", nickname="Tester")
    result = await cmd.do_process(msg_info, [])

    assert result == {"error": "No luck pack available"}


@pytest.mark.asyncio
async def test_pack_command_invalid_subcommand_is_usage_hint(mock_controller):
    cmd = PackCommand(mock_controller)
    msg_info = MessageInfo(content=":pack invalid", nickname="Tester")
    result = await cmd.do_process(msg_info, ["invalid"])

    assert result == {"message": "未知子命令，用法: :pack [redeem]"}


@pytest.mark.asyncio
async def test_pack_redeem_rejects_extra_parameters(mock_controller):
    finder = mock_controller.soul_handler.element_finder

    cmd = PackCommand(mock_controller)
    msg_info = MessageInfo(content=":pack redeem 99999", nickname="Tester")
    result = await cmd.do_process(msg_info, ["redeem", "99999"])

    assert result == {"message": "用法: :pack [redeem]"}
    finder.try_find_element.assert_not_called()


# --- :pack redeem ---


@pytest.mark.asyncio
async def test_pack_redeem_multi_round_picks_highest_affordable_tier(mock_controller):
    finder = mock_controller.soul_handler.element_finder
    entry_btn, back_btn = _heat_finder(finder, ["35999", "6000", "3000", "0"])

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
    entry_btn, back_btn = _heat_finder(finder, [None, None, None, "100"])

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
    entry_btn, _ = _heat_finder(finder, ["35999", "35999", "6000", "6000", "0"])

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
    entry_btn, back_btn = _heat_finder(finder, ["100"])

    cmd = PackCommand(mock_controller)
    msg_info = MessageInfo(content=":pack REDEEM", nickname="Tester")
    result = await cmd.do_process(msg_info, ["REDEEM"])

    assert result == {"message": "成功兑换 0 个福袋，剩余热力值: 100"}
    assert entry_btn.clicks == 1
    assert back_btn.clicks == 1


@pytest.mark.asyncio
async def test_pack_redeem_entry_not_found(mock_controller):
    finder = mock_controller.soul_handler.element_finder
    finder.try_find_element.return_value = None

    cmd = PackCommand(mock_controller)
    msg_info = MessageInfo(content=":pack redeem", nickname="Tester")
    result = await cmd.do_process(msg_info, ["redeem"])

    assert result == {"error": "未找到热力兑换入口"}
    mock_controller.soul_handler.key_actions.press_back.assert_not_called()


@pytest.mark.asyncio
async def test_pack_redeem_window_not_opened_does_not_press_back(mock_controller):
    """Without a confirmed open window, BACK could leave the party room."""
    finder = mock_controller.soul_handler.element_finder
    entry_btn, back_btn = _heat_finder(finder, [None])

    cmd = PackCommand(mock_controller)
    msg_info = MessageInfo(content=":pack redeem", nickname="Tester")
    result = await cmd.do_process(msg_info, ["redeem"])

    assert result == {"error": "兑换橱窗未打开，未读取到热力值"}
    assert entry_btn.clicks == 1
    assert back_btn.clicks == 0
    mock_controller.soul_handler.key_actions.press_back.assert_not_called()


@pytest.mark.asyncio
async def test_pack_redeem_dead_loop_defense_when_heat_not_decreasing(mock_controller):
    finder = mock_controller.soul_handler.element_finder
    entry_btn, back_btn = _heat_finder(finder, ["1000"])

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
    entry_btn, back_btn = _heat_finder(finder, ["100"])

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

    cmd = PackCommand(mock_controller)
    msg_info = MessageInfo(content=":pack redeem", nickname="Tester")
    result = await cmd.do_process(msg_info, ["redeem"])

    assert result == {"message": "成功兑换 0 个福袋，剩余热力值: 50"}
    assert entry_btn.clicks == 1
    mock_controller.soul_handler.key_actions.press_back.assert_called_once()


@pytest.mark.asyncio
async def test_pack_redeem_exception_handling_safely_exits(mock_controller):
    finder = mock_controller.soul_handler.element_finder
    entry_btn, back_btn = _heat_finder(finder, ["1000"])

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
    mock_controller.soul_handler.key_actions.press_back.side_effect = RuntimeError("back key failed")

    cmd = PackCommand(mock_controller)
    msg_info = MessageInfo(content=":pack redeem", nickname="Tester")
    result = await cmd.do_process(msg_info, ["redeem"])

    assert result == {"message": "成功兑换 0 个福袋，剩余热力值: 50"}
    assert back_btn.clicks == 0


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
    assert "每日0点清零" in elements["heat_remaining_value"]
    assert "600" in elements["heat_exchange_buttons"]
    assert "兑换橱窗" in elements["heat_exchange_back"]

    pack_cmd = next(c for c in config["commands"] if c["prefix"] == "pack")
    assert pack_cmd["level"] == 1
    assert pack_cmd["subcommands"] == {"redeem": {"level": 2}}
    assert pack_cmd["response_template"] == "{message}"
    assert pack_cmd["error_template"] == "{error}"
    assert resolve_command_level(pack_cmd, []) == 1
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
