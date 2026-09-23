import pytest
import pytest_asyncio
from unittest.mock import MagicMock
from ushareiplay.core.db_manager import DatabaseManager

from ushareiplay.commands.receive import ReceiveCommand
from ushareiplay.models.message_info import MessageInfo
from ushareiplay.core.message_queue import MessageQueue


@pytest_asyncio.fixture
async def db_init():
    manager = DatabaseManager(db_url="sqlite://:memory:")
    await manager.init()
    yield
    await manager.close()


@pytest.mark.asyncio
async def test_receive_command_operations(db_init):
    mock_controller = MagicMock()
    cmd = ReceiveCommand(mock_controller)

    # Add command
    msg = MessageInfo(content=':receive add ":say Thank you!"', nickname="Alice")
    res = await cmd.do_process(msg, ["add", ":say Thank you!"])
    assert "message" in res
    assert "已添加" in res["message"]

    # List command
    msg_list = MessageInfo(content=":receive list", nickname="Alice")
    res_list = await cmd.do_process(msg_list, ["list"])
    assert "message" in res_list
    assert ":say Thank you!" in res_list["message"]

    # Clear command
    msg_clear = MessageInfo(content=":receive clear", nickname="Alice")
    res_clear = await cmd.do_process(msg_clear, ["clear"])
    assert "message" in res_clear
    assert "1" in res_clear["message"]


@pytest.mark.asyncio
async def test_receive_command_trigger(db_init):
    mock_controller = MagicMock()
    cmd = ReceiveCommand(mock_controller)

    msg = MessageInfo(content=':receive add ":say Thanks!"', nickname="Bob")
    await cmd.do_process(msg, ["add", ":say Thanks!"])

    # Clear message queue before trigger
    mq = MessageQueue.instance()
    await mq.clear_queue()

    # Trigger gift receive event for Bob
    await cmd.user_gift_receive("Bob")

    all_msgs = await mq.get_all_messages()
    assert len(all_msgs) == 1
    queued = all_msgs["queue_msg_0"]
    assert queued.nickname == "Bob"
    assert queued.content == ":say Thanks!"

