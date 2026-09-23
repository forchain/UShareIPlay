import pytest
from types import SimpleNamespace
from ushareiplay.commands.say import SayCommand
from ushareiplay.models.message_info import MessageInfo


@pytest.fixture
def mock_controller():
    controller = SimpleNamespace()
    controller.soul_handler = SimpleNamespace()
    controller.soul_handler.logger = SimpleNamespace(
        info=lambda _msg: None,
        warning=lambda _msg: None,
        error=lambda _msg: None,
    )
    controller.music_handler = SimpleNamespace()
    return controller


@pytest.mark.asyncio
async def test_say_command_console_user_adds_manual_prefix(mock_controller):
    cmd = SayCommand(mock_controller)
    msg_info = MessageInfo(content=":say 欢迎大家", nickname="Console")
    result = await cmd.do_process(msg_info, ["欢迎大家"])
    assert result == {"message": "[人工] 欢迎大家"}


@pytest.mark.asyncio
async def test_say_command_console_preserves_existing_manual_prefix(mock_controller):
    cmd = SayCommand(mock_controller)
    msg_info = MessageInfo(content=":say [人工] 欢迎大家", nickname="Console")
    result = await cmd.do_process(msg_info, ["[人工]", "欢迎大家"])
    assert result == {"message": "[人工] 欢迎大家"}


@pytest.mark.asyncio
async def test_say_command_regular_user_unmodified(mock_controller):
    cmd = SayCommand(mock_controller)
    msg_info = MessageInfo(content=":say 欢迎大家", nickname="Alice")
    result = await cmd.do_process(msg_info, ["欢迎大家"])
    assert result == {"message": "欢迎大家"}


@pytest.mark.asyncio
async def test_say_command_empty_parameters(mock_controller):
    cmd = SayCommand(mock_controller)
    msg_info = MessageInfo(content=":say", nickname="Console")
    result = await cmd.do_process(msg_info, [])
    assert "error" in result
