"""`UserEventHooks` 深度模块的端到端测试。

覆盖四件事：
- 事件类型注册表对 5 类事件的完整性与文案保真；
- 参数化 DAO 在各事件类型上的 CRUD，以及 single-id 与 alias-group 两种
  用户解析口径的差异（收礼物命令必须能按别名找到主账号下发的命令）；
- `execute_crud` 的 shlex 解析、子动作分发与命令前缀校验；
- `fire()` 把命令以 `MessageInfo` 形态投进运行时队列（`{user_name}` 宏依赖
  这条路径，因此绝不能绕过队列直接执行命令）。
"""

from types import SimpleNamespace

import pytest
import pytest_asyncio

from ushareiplay.commands.enter import EnterCommand
from ushareiplay.core.db_manager import DatabaseManager
from ushareiplay.core.message_queue import MessageQueue
from ushareiplay.dal.user_dao import UserDAO
from ushareiplay.managers.user_event_hooks import (
    ENTER,
    EXIT,
    FOCUS,
    RECEIVE,
    RETURN,
    ALIAS_GROUP,
    SINGLE_ID,
    UserEventHookDAO,
    UserEventHooks,
    spec_for,
)
from ushareiplay.models import User
from ushareiplay.models.message_info import MessageInfo


ALL_EVENT_TYPES = [ENTER, EXIT, RETURN, RECEIVE, FOCUS]


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


def make_controller():
    """A controller stub good enough for `BaseCommand.__init__`."""
    handler = SimpleNamespace(logger=None, log_error=lambda *a, **k: None)
    return SimpleNamespace(soul_handler=handler, music_handler=handler)


async def drain_messages():
    """Take everything the engine enqueued, in insertion order."""
    queued = await MessageQueue.instance().get_all_messages()
    return list(queued.values())


# --------------------------------------------------------------------------
# 注册表：5 类事件的文案必须一字不差
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "event_type,model_name,prefix,noun,error_message,example,hook_method",
    [
        (ENTER, "EnterEvent", ":enter", "进入命令", "处理进入命令时出错", '":play 歌曲名"', "user_enter"),
        (EXIT, "ExitEvent", ":exit", "离开命令", "处理离开命令时出错", '":play 歌曲名"', "user_leave"),
        (RETURN, "ReturnEvent", ":return", "返回命令", "处理返回命令时出错", '":play 歌曲名"', "user_return"),
        (RECEIVE, "ReceiveEvent", ":receive", "收礼物命令", "处理收礼物命令时出错", '":say 谢谢"', "user_gift_receive"),
        (
            FOCUS,
            "FocusEvent",
            ":focus",
            "专注人数联动命令",
            "处理专注人数命令时出错",
            '":play 歌曲名"',
            "focus_count_change",
        ),
    ],
)
def test_registry_is_complete_for_every_event_type(
    event_type, model_name, prefix, noun, error_message, example, hook_method
):
    spec = spec_for(event_type)
    assert spec.model.__name__ == model_name
    assert spec.prefix == prefix
    assert spec.noun == noun
    assert spec.error_message == error_message
    assert spec.prefix_example == example
    assert spec.hook_method == hook_method


def test_registry_rejects_unknown_event_type():
    with pytest.raises(KeyError):
        spec_for("no_such_event")


# --------------------------------------------------------------------------
# 参数化 DAO
# --------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("event_type", ALL_EVENT_TYPES)
async def test_dao_crud_across_event_types(db_init, event_type):
    event = await UserEventHookDAO.create(event_type, "Alice", ":play song")
    assert event.id is not None
    assert event.command == ":play song"

    items = await UserEventHookDAO.get_by_username(event_type, "Alice")
    assert [item.command for item in items] == [":play song"]

    fetched = await UserEventHookDAO.get_by_id(event_type, event.id)
    assert fetched is not None and fetched.id == event.id

    assert await UserEventHookDAO.delete_by_id(event_type, event.id) is True
    assert await UserEventHookDAO.delete_by_id(event_type, event.id) is False
    assert len(await UserEventHookDAO.get_by_username(event_type, "Alice")) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("event_type", ALL_EVENT_TYPES)
async def test_dao_delete_all_by_username(db_init, event_type):
    await UserEventHookDAO.create(event_type, "Bob", ":say one")
    await UserEventHookDAO.create(event_type, "Bob", ":say two")
    await UserEventHookDAO.create(event_type, "Carol", ":say other")

    assert await UserEventHookDAO.delete_all_by_username(event_type, "Bob") == 2
    remaining = await UserEventHookDAO.get_by_username(event_type, "Bob")
    assert len(remaining) == 0
    assert len(await UserEventHookDAO.get_by_username(event_type, "Carol")) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("event_type", ALL_EVENT_TYPES)
async def test_dao_get_all_ordered_returns_every_row(db_init, event_type):
    await UserEventHookDAO.create(event_type, "Alice", ":say one")
    await UserEventHookDAO.create(event_type, "Bob", ":say two")

    every = await UserEventHookDAO.get_all_ordered(event_type)
    assert [row.command for row in every] == [":say one", ":say two"]


@pytest.mark.asyncio
async def test_dao_receive_resolves_alias_group(db_init):
    """收礼物命令按 alias-group 解析：别名能找到主账号下发的命令。"""
    assert spec_for(RECEIVE).resolution is ALIAS_GROUP

    outlier = await UserDAO.get_or_create_raw("Outlier")
    await User.create(username="Chainer", level=0, canonical_user_id=outlier.id)

    await UserEventHookDAO.create(RECEIVE, "Outlier", ":say Thanks from Outlier")

    items = await UserEventHookDAO.get_by_username(RECEIVE, "Chainer")
    assert [item.command for item in items] == [":say Thanks from Outlier"]

    # alias-group 的 clear 同样要覆盖主账号下发的命令
    assert await UserEventHookDAO.delete_all_by_username(RECEIVE, "Chainer") == 1
    assert len(await UserEventHookDAO.get_by_username(RECEIVE, "Outlier")) == 0


@pytest.mark.asyncio
async def test_dao_alias_group_also_covers_rows_bound_to_an_alias_id(db_init):
    """alias-group 覆盖「挂在分身自己 id 上」的历史命令。

    命令先在分身还不是任何人的分身时创建（此时它绑定分身自己的 id），之后再补上
    主账号关联。此时按主账号查询，alias-group 要能把这条命令捞出来。
    """
    assert spec_for(RECEIVE).resolution is ALIAS_GROUP

    chainer = await UserDAO.get_or_create_raw("Chainer")
    await UserEventHookDAO.create(RECEIVE, "Chainer", ":say 下发于分身名下")

    outlier = await UserDAO.get_or_create_raw("Outlier")
    await User.filter(id=chainer.id).update(canonical_user_id=outlier.id)

    rows = await UserEventHookDAO.get_by_username(RECEIVE, "Outlier")
    assert [row.command for row in rows] == [":say 下发于分身名下"]

    assert await UserEventHookDAO.delete_all_by_username(RECEIVE, "Outlier") == 1
    assert len(await UserEventHookDAO.get_by_username(RECEIVE, "Outlier")) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("event_type", [ENTER, EXIT, RETURN, FOCUS])
async def test_dao_single_id_resolution_stays_on_the_canonical_id(db_init, event_type):
    """其余事件类型是 single-id 口径：只认 canonical 主账号那一个 id。

    注意这不等于「分身查不到主账号的命令」—— `UserDAO.get_or_create` 会把分身解析
    回主账号，所以那条路两边一致。真正的差别在于挂在分身自己 id 上的命令：single-id
    一旦分身关联建立，从任何名字都够不着它，alias-group 则仍能捞到。

    这个「够不着」是遗留语义，本 ticket 只做收拢、不改口径，因此在这里钉住。
    """
    assert spec_for(event_type).resolution is SINGLE_ID

    chainer = await UserDAO.get_or_create_raw("Chainer")
    await UserEventHookDAO.create(event_type, "Chainer", ":play 下发于分身名下")

    outlier = await UserDAO.get_or_create_raw("Outlier")
    await User.filter(id=chainer.id).update(canonical_user_id=outlier.id)

    # single-id：无论按主账号还是按分身查，都只看 canonical 那一个 id
    assert len(await UserEventHookDAO.get_by_username(event_type, "Outlier")) == 0
    assert len(await UserEventHookDAO.get_by_username(event_type, "Chainer")) == 0

    # clear 同样只覆盖 canonical 口径
    assert await UserEventHookDAO.delete_all_by_username(event_type, "Outlier") == 0
    assert await UserEventHookDAO.delete_all_by_username(event_type, "Chainer") == 0

    # 而同一行数据在 alias-group 的收礼物命令下始终可达（见上一个测试）
    assert len(await UserEventHookDAO.get_all_ordered(event_type)) == 1


@pytest.mark.asyncio
async def test_dao_event_types_do_not_share_rows(db_init):
    """同一用户名在不同事件类型下各自独立，不串表。"""
    await UserEventHookDAO.create(ENTER, "Alice", ":play enter")
    await UserEventHookDAO.create(RECEIVE, "Alice", ":say receive")

    enter_rows = await UserEventHookDAO.get_by_username(ENTER, "Alice")
    receive_rows = await UserEventHookDAO.get_by_username(RECEIVE, "Alice")
    assert [row.command for row in enter_rows] == [":play enter"]
    assert [row.command for row in receive_rows] == [":say receive"]


# --------------------------------------------------------------------------
# execute_crud：解析、子动作与前缀校验
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_crud_add_list_del_clear(db_init, hooks):
    added = await hooks.execute_crud(ENTER, "Alice", ':enter add ":play 起风了"')
    assert added == {"message": '已添加进入命令: :play 起风了'}

    listed = await hooks.execute_crud(ENTER, "Alice", ":enter list")
    lines = listed["message"].splitlines()
    assert lines[0] == "您的进入命令列表:"
    assert lines[1].endswith(':play 起风了')

    command_id = int(lines[1].strip().split("]")[0].lstrip("["))
    deleted = await hooks.execute_crud(ENTER, "Alice", f":enter del {command_id}")
    assert deleted == {"message": f"已删除命令 ID: {command_id}"}

    assert await hooks.execute_crud(ENTER, "Alice", ":enter clear") == {
        "message": "您没有任何进入命令需要清除"
    }


@pytest.mark.asyncio
async def test_execute_crud_clear_counts(db_init, hooks):
    await hooks.execute_crud(ENTER, "Alice", ':enter add ":play one"')
    await hooks.execute_crud(ENTER, "Alice", ':enter add ":play two"')

    assert await hooks.execute_crud(ENTER, "Alice", ":enter clear") == {"message": "已清除 2 个进入命令"}


@pytest.mark.asyncio
async def test_execute_crud_list_when_empty(db_init, hooks):
    assert await hooks.execute_crud(ENTER, "Alice", ":enter list") == {
        "message": "您还没有设置任何进入命令"
    }


@pytest.mark.asyncio
async def test_execute_crud_missing_and_unknown_arguments(db_init, hooks):
    assert await hooks.execute_crud(ENTER, "Alice", ":enter") == {
        "error": "缺少参数。使用: :enter [add|del|list|clear]"
    }
    assert await hooks.execute_crud(ENTER, "Alice", ":enter add") == {
        "error": '缺少命令内容。使用: :enter add "命令内容"'
    }
    assert await hooks.execute_crud(ENTER, "Alice", ":enter del") == {
        "error": "缺少命令ID。使用: :enter del <id>"
    }
    assert await hooks.execute_crud(ENTER, "Alice", ":enter del abc") == {
        "error": "命令ID必须是数字"
    }
    assert await hooks.execute_crud(ENTER, "Alice", ":enter del 4242") == {
        "error": "未找到命令 ID: 4242"
    }
    assert await hooks.execute_crud(ENTER, "Alice", ":enter wat") == {
        "error": "未知操作: wat。使用: :enter [add|del|list|clear]"
    }


@pytest.mark.asyncio
async def test_execute_crud_rejects_unquoted_quotes(db_init, hooks):
    assert await hooks.execute_crud(ENTER, "Alice", ':enter add "unterminated') == {
        "error": "参数格式错误，带空格的参数请使用引号包裹"
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("event_type", ALL_EVENT_TYPES)
@pytest.mark.parametrize("command", [":play 歌曲名", "：play 歌曲名", "/play 歌曲名", "／play 歌曲名"])
async def test_execute_crud_accepts_all_four_prefixes(db_init, hooks, event_type, command):
    result = await hooks.execute_crud(event_type, "Alice", f'{spec_for(event_type).prefix} add "{command}"')
    assert result == {"message": f"已添加{spec_for(event_type).noun}: {command}"}


@pytest.mark.asyncio
@pytest.mark.parametrize("event_type", ALL_EVENT_TYPES)
async def test_execute_crud_rejects_missing_prefix(db_init, hooks, event_type):
    spec = spec_for(event_type)
    result = await hooks.execute_crud(event_type, "Alice", f'{spec.prefix} add "play 歌曲名"')
    assert result == {"error": f'命令必须以命令前缀(:/：或//／)开头，例如 {spec.prefix_example}'}


@pytest.mark.asyncio
async def test_execute_crud_keeps_quoted_commands_with_spaces(db_init, hooks):
    """`fire` 之外的解析细节：命令原文按 shlex 取第二段，带空格的命令要完整。"""
    await hooks.execute_crud(ENTER, "Alice", ':enter add ":play 周杰伦 - 稻香"')
    rows = await UserEventHookDAO.get_by_username(ENTER, "Alice")
    assert [row.command for row in rows] == [":play 周杰伦 - 稻香"]


@pytest.mark.asyncio
async def test_execute_crud_renders_per_event_type_wording(db_init, hooks):
    """5 类事件各自的名词文案必须不同，不能串味。"""
    assert await hooks.execute_crud(EXIT, "Alice", ":exit list") == {"message": "您还没有设置任何离开命令"}
    assert await hooks.execute_crud(RETURN, "Alice", ":return list") == {"message": "您还没有设置任何返回命令"}
    assert await hooks.execute_crud(RECEIVE, "Alice", ":receive list") == {"message": "您还没有设置任何收礼物命令"}
    assert await hooks.execute_crud(FOCUS, "Alice", ":focus list") == {
        "message": "您还没有设置任何专注人数联动命令"
    }


# --------------------------------------------------------------------------
# fire：入队而不是直接执行
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fire_enqueues_message_info(db_init, hooks):
    await hooks.execute_crud(ENTER, "Alice", ':enter add ":play 起风了"')

    await hooks.fire(ENTER, "Alice")

    queued = await drain_messages()
    assert len(queued) == 1
    assert isinstance(queued[0], MessageInfo)
    assert queued[0].content == ":play 起风了"
    assert queued[0].nickname == "Alice"


@pytest.mark.asyncio
async def test_fire_without_configuration_enqueues_nothing(db_init, hooks):
    await hooks.fire(ENTER, "Nobody")
    assert await drain_messages() == []


@pytest.mark.asyncio
async def test_fire_accepts_realtime_context(db_init, hooks):
    """`ctx` 是可选的实时上下文（人数前后值等），不参与命令内容。"""
    await hooks.execute_crud(ENTER, "Alice", ':enter add ":play one"')
    await hooks.fire(ENTER, "Alice", {"before": 1, "after": 2})

    queued = await drain_messages()
    assert [msg.content for msg in queued] == [":play one"]


@pytest.mark.asyncio
async def test_fire_with_none_username_uses_all_configured_users(db_init, hooks):
    """`username=None` 是专注人数联动的向后兼容回退：执行所有已配置用户。"""
    await hooks.execute_crud(FOCUS, "Alice", ':focus add ":seat {seat}"')
    await hooks.execute_crud(FOCUS, "Bob", ':focus add ":wave {username}"')

    await hooks.fire(FOCUS, None, {})

    queued = await drain_messages()
    assert sorted(msg.content for msg in queued) == [":seat {seat}", ":wave {username}"]
    assert sorted(msg.nickname for msg in queued) == ["Alice", "Bob"]


# --------------------------------------------------------------------------
# :enter 薄适配器
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enter_command_is_a_thin_adapter(db_init, hooks):
    controller = make_controller()
    command = EnterCommand(controller)

    assert command.handler_attr == "soul_handler"
    assert command.error_message == "处理进入命令时出错"

    message = MessageInfo(content=':enter add ":play 起风了"', nickname="Alice")
    result = await command.do_process(message, [])
    assert result == {"message": "已添加进入命令: :play 起风了"}

    listed = await command.do_process(MessageInfo(content=":enter list", nickname="Alice"), [])
    assert listed["message"].splitlines()[0] == "您的进入命令列表:"


@pytest.mark.asyncio
async def test_enter_command_user_enter_delegates_to_fire(db_init, hooks):
    """`user_enter` 仍是命令上的可调用钩子（CommandManager 直接按属性名分发）。"""
    await hooks.execute_crud(ENTER, "Alice", ':enter add ":play 起风了"')

    command = EnterCommand(make_controller())
    await command.user_enter("Alice")

    queued = await drain_messages()
    assert [(msg.content, msg.nickname) for msg in queued] == [(":play 起风了", "Alice")]
