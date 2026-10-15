"""#424：`:return` / `:receive` 迁移到 UserEventHooks 之后的适配器与事件侧行为。

这里锁三件容易回归的事：

1. 四个子动作（add/del/list/clear）仍能经命令适配器端到端跑通，且用户看到的文案
   一字不变 —— 文案的事实源在 `registry`，命令层只是转发。
2. 收礼物命令的 alias-group 解析在新路径上仍然成立：主账号配的命令，用分身名既
   查得到也触发得到。返回命令走 single-id，两者不共用口径。
3. 事件侧只入队一次 —— 既不能漏发，也不能因为属性名分发还在就重复发；`:seat`
   原本挂在 `user_return` 上的座位复核不能被顺手干掉（#436 把它收成 `notify_*` 里的
   显式调用，这里跟着验新缝）。
"""

import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from ushareiplay.commands.receive import ReceiveCommand

# `return` 是 Python 关键字，`from ushareiplay.commands.return import ...` 语法非法
# （CommandManager 正是因为这个才用 `_find_command_class` 动态发现命令类）。
ReturnCommand = importlib.import_module("ushareiplay.commands.return").ReturnCommand

from ushareiplay.core.db_manager import DatabaseManager
from ushareiplay.core.message_queue import MessageQueue
from ushareiplay.dal.receive_dao import ReceiveDao
from ushareiplay.dal.return_dao import ReturnDao
from ushareiplay.dal.user_dao import UserDAO
from ushareiplay.managers.command_manager import CommandManager
from ushareiplay.managers.memory_manager import MemoryManager
from ushareiplay.managers.seat_manager import SeatManager
from ushareiplay.managers.user_event_hooks import RECEIVE, RETURN, UserEventHooks
from ushareiplay.models import User
from ushareiplay.models.message_info import MessageInfo


@pytest_asyncio.fixture
async def db_init():
    manager = DatabaseManager(db_url="sqlite://:memory:")
    await manager.init()
    yield
    await manager.close()


def _logger_stub():
    return SimpleNamespace(
        info=MagicMock(), warning=MagicMock(), error=MagicMock(), debug=MagicMock()
    )


async def _drain():
    """取出队列里全部消息（`get_all_messages` 本身会清空队列），保持入队顺序。"""
    return list((await MessageQueue.instance().get_all_messages()).values())


# --------------------------------------------------------------------------
# 命令适配器：四个子动作端到端
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_return_command_crud_end_to_end(db_init):
    cmd = ReturnCommand(MagicMock())

    added = await cmd.do_process(
        MessageInfo(content=':return add ":play 稻香"', nickname="Alice"), []
    )
    assert added == {"message": "已添加返回命令: :play 稻香"}

    await cmd.do_process(
        MessageInfo(content=':return add ":say 我回来啦"', nickname="Alice"), []
    )

    # 适配器写的就是旧表，legacy DAO 读得到（#436 才收掉旧 DAO）
    stored = await ReturnDao.get_by_username("Alice")
    assert [row.command for row in stored] == [":play 稻香", ":say 我回来啦"]

    listed = await cmd.do_process(MessageInfo(content=":return list", nickname="Alice"), [])
    assert listed["message"].startswith("您的返回命令列表:")
    assert ":play 稻香" in listed["message"]

    deleted = await cmd.do_process(
        MessageInfo(content=f":return del {stored[0].id}", nickname="Alice"), []
    )
    assert deleted == {"message": f"已删除命令 ID: {stored[0].id}"}

    cleared = await cmd.do_process(MessageInfo(content=":return clear", nickname="Alice"), [])
    assert cleared == {"message": "已清除 1 个返回命令"}
    assert await ReturnDao.get_by_username("Alice") == []


@pytest.mark.asyncio
async def test_return_command_keeps_prefix_example_text(db_init):
    cmd = ReturnCommand(MagicMock())

    res = await cmd.do_process(MessageInfo(content=':return add "稻香"', nickname="Alice"), [])
    assert res == {"error": '命令必须以命令前缀(:/：或//／)开头，例如 ":play 歌曲名"'}

    usage = await cmd.do_process(MessageInfo(content=":return", nickname="Alice"), [])
    assert usage == {"error": "缺少参数。使用: :return [add|del|list|clear]"}


@pytest.mark.asyncio
async def test_receive_command_crud_end_to_end(db_init):
    cmd = ReceiveCommand(MagicMock())

    added = await cmd.do_process(
        MessageInfo(content=':receive add ":say 谢谢"', nickname="Alice"), []
    )
    assert added == {"message": "已添加收礼物命令: :say 谢谢"}

    await cmd.do_process(
        MessageInfo(content=':receive add ":say 老板大气"', nickname="Alice"), []
    )

    stored = await ReceiveDao.get_by_username("Alice")
    assert [row.command for row in stored] == [":say 谢谢", ":say 老板大气"]

    listed = await cmd.do_process(MessageInfo(content=":receive list", nickname="Alice"), [])
    assert listed["message"].startswith("您的收礼物命令列表:")
    assert ":say 谢谢" in listed["message"]

    deleted = await cmd.do_process(
        MessageInfo(content=f":receive del {stored[0].id}", nickname="Alice"), []
    )
    assert deleted == {"message": f"已删除命令 ID: {stored[0].id}"}

    cleared = await cmd.do_process(MessageInfo(content=":receive clear", nickname="Alice"), [])
    assert cleared == {"message": "已清除 1 个收礼物命令"}
    assert await ReceiveDao.get_by_username("Alice") == []


@pytest.mark.asyncio
async def test_receive_command_keeps_prefix_example_text(db_init):
    cmd = ReceiveCommand(MagicMock())

    res = await cmd.do_process(MessageInfo(content=':receive add "谢谢"', nickname="Alice"), [])
    assert res == {"error": '命令必须以命令前缀(:/：或//／)开头，例如 ":say 谢谢"'}

    usage = await cmd.do_process(MessageInfo(content=":receive", nickname="Alice"), [])
    assert usage == {"error": "缺少参数。使用: :receive [add|del|list|clear]"}


# --------------------------------------------------------------------------
# 收礼物命令的 alias-group 解析（返回命令是 single-id，两者不统一）
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_receive_command_alias_resolution_through_adapter(db_init):
    outlier = await UserDAO.get_or_create_raw("Outlier")
    await User.create(username="Chainer", level=0, canonical_user_id=outlier.id)

    cmd = ReceiveCommand(MagicMock())
    await cmd.do_process(
        MessageInfo(content=':receive add ":say 谢谢"', nickname="Outlier"), []
    )

    # 分身名查得到主账号配的命令
    listed = await cmd.do_process(MessageInfo(content=":receive list", nickname="Chainer"), [])
    assert ":say 谢谢" in listed["message"]

    # 分身名触发也要入队
    await MessageQueue.instance().clear_queue()
    await cmd.user_gift_receive("Chainer")

    queued = await _drain()
    assert [(m.nickname, m.content) for m in queued] == [("Chainer", ":say 谢谢")]


@pytest.mark.asyncio
async def test_return_and_receive_keep_different_user_resolution(db_init):
    """收礼物按 alias-group、返回按 single-id，两者不统一 —— 别"顺手对齐"。

    差别只在**直接挂在分身 id 名下**的历史数据：alias-group 认，返回命令不认。
    主账号挂的数据两边都能查到，因为 `UserDAO.get_or_create` 本就解析 canonical。
    """
    from ushareiplay.models.receive_event import ReceiveEvent
    from ushareiplay.models.return_event import ReturnEvent

    outlier = await UserDAO.get_or_create_raw("Outlier")
    chainer = await User.create(username="Chainer", level=0, canonical_user_id=outlier.id)

    # 历史数据：直接挂在分身 id 名下
    await ReceiveEvent.create(user=chainer, command=":say 分身专属")
    await ReturnEvent.create(user=chainer, command=":play 分身专属")

    receive_cmd = ReceiveCommand(MagicMock())
    return_cmd = ReturnCommand(MagicMock())

    receive_listed = await receive_cmd.do_process(
        MessageInfo(content=":receive list", nickname="Chainer"), []
    )
    assert ":say 分身专属" in receive_listed["message"]

    return_listed = await return_cmd.do_process(
        MessageInfo(content=":return list", nickname="Chainer"), []
    )
    assert return_listed == {"message": "您还没有设置任何返回命令"}


# --------------------------------------------------------------------------
# fire() 入队
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fire_enqueues_message_info_for_return_and_receive(db_init):
    hooks = UserEventHooks.instance()
    await hooks.execute_crud(RETURN, "Bob", ':return add ":play 稻香"')
    await hooks.execute_crud(RECEIVE, "Bob", ':receive add ":say 谢谢"')

    queue = MessageQueue.instance()
    await queue.clear_queue()

    assert await hooks.fire(RETURN, "Bob") == 1
    assert await hooks.fire(RECEIVE, "Bob") == 1

    queued = await _drain()
    assert [(m.nickname, m.content) for m in queued] == [
        ("Bob", ":play 稻香"),
        ("Bob", ":say 谢谢"),
    ]


@pytest.mark.asyncio
async def test_fire_returns_zero_when_no_commands_configured(db_init):
    assert await UserEventHooks.instance().fire(RETURN, "Nobody") == 0
    assert await UserEventHooks.instance().fire(RECEIVE, "Nobody") == 0


@pytest.mark.asyncio
async def test_hook_methods_enqueue_through_message_queue(db_init):
    """钩子方法必须经 MessageQueue 入队：drain 时才展开 `{user_name}` 宏。"""
    return_cmd = ReturnCommand(MagicMock())
    receive_cmd = ReceiveCommand(MagicMock())
    await return_cmd.do_process(
        MessageInfo(content=':return add ":say 回来啦 {user_name}"', nickname="Bob"), []
    )
    await receive_cmd.do_process(
        MessageInfo(content=':receive add ":say 谢谢 {user_name}"', nickname="Bob"), []
    )

    queue = MessageQueue.instance()
    await queue.clear_queue()

    await return_cmd.user_return("Bob")
    await receive_cmd.user_gift_receive("Bob")

    queued = await _drain()
    assert [(m.nickname, m.content) for m in queued] == [
        ("Bob", ":say 回来啦 {user_name}"),
        ("Bob", ":say 谢谢 {user_name}"),
    ]


# --------------------------------------------------------------------------
# CommandManager 事件侧：只入队一次，且不误伤 seat 的座位复核
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_notify_user_return_enqueues_once_and_checks_seats(db_init):
    cmd = ReturnCommand(MagicMock())
    await cmd.do_process(
        MessageInfo(content=':return add ":play 稻香"', nickname="Bob"), []
    )

    cm = CommandManager.instance()
    cm._logger = _logger_stub()

    SeatManager.reset_instance()
    SeatManager.initialize()

    await MessageQueue.instance().clear_queue()
    with patch(
        "ushareiplay.managers.seat_manager.SeatManager.check_seats_on_entry",
        new_callable=AsyncMock,
    ) as seat_check:
        await cm.notify_user_return("Bob")

    queued = await _drain()
    assert [m.content for m in queued] == [":play 稻香"]

    # 返回命令只入队一次；座位复核仍会发生 —— #436 起它是 notify_* 里的显式调用，
    # 不再靠遍历命令模块按属性名找到 `:seat` 的 user_return 钩子。
    seat_check.assert_awaited_once_with("Bob")


@pytest.mark.asyncio
async def test_notify_gift_receive_enqueues_receive_command(db_init):
    cmd = ReceiveCommand(MagicMock())
    await cmd.do_process(
        MessageInfo(content=':receive add ":say 谢谢"', nickname="Bob"), []
    )

    cm = CommandManager.instance()
    cm._logger = _logger_stub()

    await MessageQueue.instance().clear_queue()
    await cm.notify_gift_receive("Bob")

    queued = await _drain()
    assert [(m.nickname, m.content) for m in queued] == [("Bob", ":say 谢谢")]


@pytest.mark.asyncio
async def test_notify_gift_receive_with_nothing_configured_enqueues_nothing(db_init):
    cm = CommandManager.instance()
    cm._logger = _logger_stub()

    await MessageQueue.instance().clear_queue()
    await cm.notify_gift_receive("Bob")

    assert await _drain() == []


# --------------------------------------------------------------------------
# 记忆整合的非对称：返回要调度，送礼不调度
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_return_schedules_memory_consolidation_but_gift_does_not(db_init, monkeypatch):
    if not MemoryManager.is_initialized():
        MemoryManager.initialize()
    mm = MemoryManager.instance()
    mm.configure({"llm": {"memory": {"enabled": True}}})

    scheduled = []
    monkeypatch.setattr(
        mm, "schedule_consolidation_user", lambda username: scheduled.append(username)
    )

    cm = CommandManager.instance()
    cm._logger = _logger_stub()

    await cm.notify_user_return("bob")
    assert scheduled == ["bob"]

    # 送礼刻意不调度记忆整合 —— 与 notify_user_return 的差异是历史有意为之
    await cm.notify_gift_receive("alice")
    assert scheduled == ["bob"]
