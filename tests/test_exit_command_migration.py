"""`:exit` 迁移到 `UserEventHooks` 后的行为测试（#429）。

覆盖迁移后留在引擎内部的那块「离开专属」判定 —— 同一个人有多个分身（alias），
Soul 在线列表里每个分身各占一行，只有当某个人的**全部分身**都不在线时才触发退出
命令；并且触发时一律用 DB 侧的 canonical 主账号名入队，因为退出命令是按主账号配置
的。同时钉住记忆沉淀调度仍然发生、以及 `:exit` 命令本身退化成了薄适配器。
"""

from types import SimpleNamespace

import pytest
import pytest_asyncio

from ushareiplay.commands.exit import ExitCommand
from ushareiplay.core.db_manager import DatabaseManager
from ushareiplay.core.message_queue import MessageQueue
from ushareiplay.dal.user_dao import UserDAO
from ushareiplay.managers.command_manager import CommandManager
from ushareiplay.managers.info_manager import InfoManager
from ushareiplay.managers.memory_manager import MemoryManager
from ushareiplay.managers.user_event_hooks import ENTER, EXIT, UserEventHooks, spec_for
from ushareiplay.models import User
from ushareiplay.models.message_info import MessageInfo
from ushareiplay.state.presence_tracker import PresenceTracker


@pytest_asyncio.fixture
async def db_init():
    manager = DatabaseManager(db_url="sqlite://:memory:")
    await manager.init()
    yield
    await manager.close()


@pytest_asyncio.fixture
async def hooks():
    """The engine under test. `conftest.py` already resets singletons per test."""
    UserEventHooks.reset_instance()
    UserEventHooks.initialize(handler=None)
    return UserEventHooks.instance()


@pytest_asyncio.fixture
async def avatar_family(db_init):
    """一个主账号 + 两个分身，正是需要聚合判定的那类用户。"""
    canonical = await User.create(username="小明", level=0)
    await User.create(username="明明", level=0, canonical_user_id=canonical.id)
    await User.create(username="小M", level=0, canonical_user_id=canonical.id)
    return canonical


@pytest.fixture
def online_users():
    """Drive the online-user list the gate reads. Returns a setter."""
    PresenceTracker.initialize()
    InfoManager.initialize()

    def _set(names):
        tracker = InfoManager.instance()._presence_tracker
        tracker._online_users = set(names)
        return tracker

    return _set


@pytest.fixture
def scheduled_consolidations(monkeypatch):
    """MemoryManager 的沉淀调度打桩，返回记录到的用户名列表。"""
    if not MemoryManager.is_initialized():
        MemoryManager.initialize()
    mm = MemoryManager.instance()
    scheduled = []
    monkeypatch.setattr(mm, "schedule_consolidation_user", scheduled.append)
    return scheduled


def make_controller():
    """A controller stub good enough for `BaseCommand.__init__`."""
    handler = SimpleNamespace(logger=None, log_error=lambda *a, **k: None)
    return SimpleNamespace(soul_handler=handler, music_handler=handler)


async def drain_messages():
    """Take everything the engine enqueued, in insertion order."""
    queued = await MessageQueue.instance().get_all_messages()
    return list(queued.values())


# --------------------------------------------------------------------------
# 多分身离线判定：全部离线才触发
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exit_fires_when_every_alias_is_offline(
    db_init, hooks, avatar_family, online_users, scheduled_consolidations
):
    """主账号和两个分身都不在在线列表里 → 触发，并且按主账号名入队。"""
    online_users({"张三", "李四"})
    await hooks.execute_crud(EXIT, "小明", ':exit add ":play 稻香"')

    queued_count = await hooks.fire(EXIT, "明明")

    assert queued_count == 1
    queued = await drain_messages()
    assert [(msg.content, msg.nickname) for msg in queued] == [(":play 稻香", "小明")]


@pytest.mark.asyncio
async def test_exit_does_not_fire_while_any_alias_is_still_online(
    db_init, hooks, avatar_family, online_users, scheduled_consolidations
):
    """关键的反向用例：只要还有一个分身在线，这次离开就不能触发退出命令。

    这里在线的是**主账号**自己（`小明`）。判定必须覆盖整个分身集合 —— 若退化成
    「只看离开的那个人在不在线」，`明明` 已经不在列表里，退出命令就会被误触发，
    而主账号其实还在房间里。
    """
    online_users({"小明", "张三"})
    await hooks.execute_crud(EXIT, "小明", ':exit add ":play 稻香"')

    queued_count = await hooks.fire(EXIT, "明明")

    assert queued_count == 0
    assert await drain_messages() == []


@pytest.mark.asyncio
async def test_exit_does_not_fire_while_a_sibling_alias_is_still_online(
    db_init, hooks, avatar_family, online_users, scheduled_consolidations
):
    """换一个分身在线也要拦住：判定看的是整个分身集合，不是「走的那一个」。"""
    online_users({"小M", "张三"})
    await hooks.execute_crud(EXIT, "小明", ':exit add ":play 稻香"')

    assert await hooks.fire(EXIT, "明明") == 0
    assert await drain_messages() == []


@pytest.mark.asyncio
async def test_exit_skips_memory_consolidation_when_the_gate_blocks(
    db_init, hooks, avatar_family, online_users, scheduled_consolidations
):
    """被拦下时既不发命令也不做记忆沉淀 —— 这与迁移前的早退语义一致。"""
    online_users({"小明"})
    await hooks.execute_crud(EXIT, "小明", ':exit add ":play 稻香"')

    await hooks.fire(EXIT, "明明")

    assert scheduled_consolidations == []


@pytest.mark.asyncio
async def test_exit_schedules_memory_consolidation_for_the_canonical_user(
    db_init, hooks, avatar_family, online_users, scheduled_consolidations
):
    """离开的用户仍然要触发记忆沉淀，且用的是主账号名。"""
    online_users({"张三"})
    await hooks.execute_crud(EXIT, "小明", ':exit add ":play 稻香"')

    await hooks.fire(EXIT, "明明")

    assert scheduled_consolidations == ["小明"]


@pytest.mark.asyncio
async def test_exit_consolidation_guard_survives_a_failing_memory_manager(
    db_init, hooks, avatar_family, online_users, monkeypatch
):
    """沉淀调度抛异常不得连带丢掉退出命令（与迁移前的内层 try/except 一致）。"""
    online_users({"张三"})
    if not MemoryManager.is_initialized():
        MemoryManager.initialize()

    def boom(_username):
        raise RuntimeError("consolidation backend down")

    monkeypatch.setattr(MemoryManager.instance(), "schedule_consolidation_user", boom)
    await hooks.execute_crud(EXIT, "小明", ':exit add ":play 稻香"')

    assert await hooks.fire(EXIT, "明明") == 1


@pytest.mark.asyncio
async def test_exit_fires_for_a_user_without_aliases(
    db_init, hooks, online_users, scheduled_consolidations
):
    """没有分身映射的普通用户：只要他自己不在在线列表里就走完整条链路。"""
    await User.create(username="张三", level=0)
    online_users({"李四"})
    await hooks.execute_crud(EXIT, "张三", ':exit add ":play 稻香"')

    assert await hooks.fire(EXIT, "张三") == 1
    queued = await drain_messages()
    assert [(msg.content, msg.nickname) for msg in queued] == [(":play 稻香", "张三")]


@pytest.mark.asyncio
async def test_enter_event_is_not_gated_by_online_users(
    db_init, hooks, avatar_family, online_users, scheduled_consolidations
):
    """离线判定是「离开」专属的：进入事件没有这个条件，在线列表不该拦住它。"""
    online_users({"小明", "明明", "小M"})
    await hooks.execute_crud(ENTER, "小明", ':enter add ":play 稻香"')

    assert await hooks.fire(ENTER, "明明") == 1


@pytest.mark.asyncio
async def test_exit_enqueues_under_canonical_not_the_observed_alias(
    db_init, hooks, online_users, scheduled_consolidations
):
    """队列里的昵称必须是主账号名：`{user_name}` 宏在 drain 时按这个值展开。"""
    canonical = await UserDAO.get_or_create_raw("小明")
    await User.create(username="明明", level=0, canonical_user_id=canonical.id)
    online_users({"张三"})
    await hooks.execute_crud(EXIT, "明明", ':exit add ":say 下线了"')

    await hooks.fire(EXIT, "小明")

    queued = await drain_messages()
    assert [msg.nickname for msg in queued] == ["小明"]


# --------------------------------------------------------------------------
# CommandManager.notify_user_leave：保留公开名与签名，改为委托给 fire()
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_notify_user_leave_delegates_to_fire(
    db_init, hooks, avatar_family, online_users, scheduled_consolidations
):
    online_users({"张三"})
    await hooks.execute_crud(EXIT, "小明", ':exit add ":play 稻香"')
    cm = CommandManager.instance()

    await cm.notify_user_leave("明明")

    queued = await drain_messages()
    assert [(msg.content, msg.nickname) for msg in queued] == [(":play 稻香", "小明")]
    assert scheduled_consolidations == ["小明"]


@pytest.mark.asyncio
async def test_notify_user_leave_skips_when_an_alias_is_still_online(
    db_init, hooks, avatar_family, online_users, scheduled_consolidations
):
    online_users({"小明"})
    await hooks.execute_crud(EXIT, "小明", ':exit add ":play 稻香"')
    cm = CommandManager.instance()

    await cm.notify_user_leave("明明")

    assert await drain_messages() == []
    assert scheduled_consolidations == []


# --------------------------------------------------------------------------
# :exit 薄适配器
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exit_command_is_a_thin_adapter(db_init, hooks):
    command = ExitCommand(make_controller())

    assert command.handler_attr == "soul_handler"
    assert command.error_message == spec_for(EXIT).error_message == "处理离开命令时出错"

    added = await command.do_process(
        MessageInfo(content=':exit add ":play 起风了"', nickname="Alice"), []
    )
    assert added == {"message": "已添加离开命令: :play 起风了"}

    listed = await command.do_process(MessageInfo(content=":exit list", nickname="Alice"), [])
    assert listed["message"].splitlines()[0] == "您的离开命令列表:"


@pytest.mark.asyncio
async def test_exit_command_crud_sub_verbs(db_init, hooks):
    """四个子动作都走引擎，文案与 `:exit` 自己的名词一致。"""
    command = ExitCommand(make_controller())

    def run(content, nickname="Alice"):
        return command.do_process(MessageInfo(content=content, nickname=nickname), [])

    assert await run(":exit") == {"error": "缺少参数。使用: :exit [add|del|list|clear]"}
    assert await run(':exit add "play 歌曲名"') == {
        "error": '命令必须以命令前缀(:/：或//／)开头，例如 ":play 歌曲名"'
    }

    await run(':exit add ":play one"')
    await run(':exit add ":play two"')
    listed = await run(":exit list")
    lines = listed["message"].splitlines()
    assert lines[0] == "您的离开命令列表:"
    assert lines[1].endswith(":play one")

    command_id = int(lines[1].strip().split("]")[0].lstrip("["))
    assert await run(f":exit del {command_id}") == {"message": f"已删除命令 ID: {command_id}"}
    assert await run(":exit del 4242") == {"error": "未找到命令 ID: 4242"}
    assert await run(":exit del abc") == {"error": "命令ID必须是数字"}
    assert await run(":exit clear") == {"message": "已清除 1 个离开命令"}
    assert await run(":exit wat") == {"error": "未知操作: wat。使用: :exit [add|del|list|clear]"}


@pytest.mark.asyncio
async def test_exit_command_user_leave_delegates_to_fire(db_init, hooks, online_users):
    """`user_leave` 仍是命令上的可调用钩子。

    它委托的 `fire(EXIT, ...)` 会先过离线判定，因此这里要先摆好在线列表：正在离开
    的用户不在列表里，判定自然放行。
    """
    online_users({"Bob"})
    await hooks.execute_crud(EXIT, "Alice", ':exit add ":play 起风了"')

    command = ExitCommand(make_controller())
    await command.user_leave("Alice")

    queued = await drain_messages()
    assert [(msg.content, msg.nickname) for msg in queued] == [(":play 起风了", "Alice")]


@pytest.mark.asyncio
async def test_exit_command_still_goes_through_the_message_queue(
    db_init, hooks, online_users
):
    """`{user_name}` 宏依赖入队路径，因此命令必须以 `MessageInfo` 形态进队列。"""
    online_users({"Bob"})
    await hooks.execute_crud(EXIT, "Alice", ':exit add ":say 下线了 {user_name}"')

    command = ExitCommand(make_controller())
    await command.user_leave("Alice")

    queued = await drain_messages()
    assert len(queued) == 1
    assert isinstance(queued[0], MessageInfo)
    assert queued[0].content == ":say 下线了 {user_name}"
