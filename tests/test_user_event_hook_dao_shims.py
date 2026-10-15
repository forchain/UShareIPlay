"""#436：遗留 DAO 垫片的兼容性，以及 `:xxx clear` 修复的回归哨。

两件事：

1. **兼容**。`EnterDao` / `ExitDao` / `ReturnDao` / `ReceiveDao` / `FocusEventDao`
   现在只是 `UserEventHookDAO` 的门面，但外部调用方与既有测试仍在按旧类名与旧签名
   调用。两条非对称行为必须原样活着：收礼物命令的 **alias-group** 解析口径（主账号
   配的规则，用分身名查得到也删得掉），以及 `FocusEventDao.get_all_ordered()` 的
   全量按 id 升序。其余四个走 **single-id**，只认 canonical 主账号。

2. **修复**。迁移前这 4 个 single-id DAO 的 `delete_all_by_username` 写的是
   `filter(user__id=…)` 接 `.delete()` —— `user__id` 是 join 写法，Tortoise 会拼出
   `sqlite3.OperationalError: near "LEFT": syntax error`（已实测复现）。

   两条用户命令 `:enter clear` / `:exit clear` / `:return clear` / `:focus clear`
   跟着 #422~#433 就已经改走 `UserEventHookDAO`（外键列过滤），因此**在 #436 之前就
   已经好了**；这里端到端钉住它们，防的是回退。

   真正被这个 ticket 修掉的是**垫片本身**：`EnterDao.delete_all_by_username` 等 4 个
   方法仍然带着 `near "LEFT"` 的缺陷，外部调用方调它们照样炸。
   `test_shim_delete_all_by_username_returns_count` 就是这条的回归哨 —— 把
   `enter_dao.py` 换回迁移前的实现，它会失败。
"""

import importlib
from types import SimpleNamespace

import pytest
import pytest_asyncio

from ushareiplay.commands.enter import EnterCommand
from ushareiplay.commands.exit import ExitCommand
from ushareiplay.commands.focus import FocusCommand
from ushareiplay.commands.receive import ReceiveCommand

# `return` 是 Python 关键字，只能动态 import
ReturnCommand = importlib.import_module("ushareiplay.commands.return").ReturnCommand

from ushareiplay.core.db_manager import DatabaseManager
from ushareiplay.dal.enter_dao import EnterDao
from ushareiplay.dal.exit_dao import ExitDao
from ushareiplay.dal.focus_event_dao import FocusEventDao
from ushareiplay.dal.receive_dao import ReceiveDao
from ushareiplay.dal.return_dao import ReturnDao
from ushareiplay.managers.user_event_hooks import (
    ENTER,
    EXIT,
    FOCUS,
    RECEIVE,
    RETURN,
    spec_for,
)
from ushareiplay.models import User
from ushareiplay.models.enter_event import EnterEvent
from ushareiplay.models.exit_event import ExitEvent
from ushareiplay.models.focus_event import FocusEvent
from ushareiplay.models.message_info import MessageInfo
from ushareiplay.models.receive_event import ReceiveEvent
from ushareiplay.models.return_event import ReturnEvent


@pytest_asyncio.fixture
async def db_init():
    manager = DatabaseManager(db_url="sqlite://:memory:")
    await manager.init()
    yield
    await manager.close()


#: (事件类型, 垫片类, 命令适配器, 命令前缀)
SHIMS = [
    (ENTER, EnterDao, EnterCommand, ":enter"),
    (EXIT, ExitDao, ExitCommand, ":exit"),
    (RETURN, ReturnDao, ReturnCommand, ":return"),
    (RECEIVE, ReceiveDao, ReceiveCommand, ":receive"),
    (FOCUS, FocusEventDao, FocusCommand, ":focus"),
]


def make_controller():
    """A controller stub good enough for `BaseCommand.__init__`."""
    handler = SimpleNamespace(logger=None, log_error=lambda *a, **k: None)
    return SimpleNamespace(soul_handler=handler, music_handler=handler)


async def make_identity(canonical_name="Outlier", alias_name="Chainer"):
    """造一个主账号 + 一个分身：两者字符串不同，DB 分身指向主账号。

    返回 `(主账号 User, 分身 User)` —— 分身对象用于直接往分身 id 上挂一行，用来暴露
    alias-group 与 single-id 的差别（走 DAO 写永远落在主账号上，看不出差别）。
    """
    canonical = await User.create(username=canonical_name, level=1)
    alias = await User.create(username=alias_name, level=0, canonical_user=canonical)
    return canonical, alias


# --------------------------------------------------------------------------
# clear 回归哨：以前这四条命令一直抛 `near "LEFT"`
# --------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("event_type,dao,command_cls,prefix", SHIMS)
async def test_clear_command_actually_deletes(db_init, event_type, dao, command_cls, prefix):
    """`:enter clear` / `:exit clear` / … 用户可见路径端到端可用。"""
    await dao.create("Alice", ":play 起风了")
    await dao.create("Alice", ":say 来了")

    assert await dao.get_by_username("Alice") != []

    result = await command_cls(make_controller()).do_process(
        MessageInfo(content=f"{prefix} clear", nickname="Alice"), []
    )

    # 计数要真的报出来，而不是被 LEFT JOIN 语法错误吞掉
    noun = spec_for(event_type).noun
    assert result == {"message": f"已清除 2 个{noun}"}, result
    assert await dao.get_by_username("Alice") == []


@pytest.mark.asyncio
@pytest.mark.parametrize("event_type,dao,command_cls,prefix", SHIMS)
async def test_clear_command_on_empty_user_is_quiet(
    db_init, event_type, dao, command_cls, prefix
):
    """什么都没有时 `clear` 不报错、不删别人的命令。"""
    await dao.create("Bob", ":play 一首")

    result = await command_cls(make_controller()).do_process(
        MessageInfo(content=f"{prefix} clear", nickname="Alice"), []
    )

    noun = spec_for(event_type).noun
    assert result == {"message": f"您没有任何{noun}需要清除"}, result
    assert len(await dao.get_by_username("Bob")) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("event_type,dao,command_cls,prefix", SHIMS)
async def test_shim_delete_all_by_username_returns_count(
    db_init, event_type, dao, command_cls, prefix
):
    """垫片层的 `delete_all_by_username` 同样返回条数（旧的这条直接抛异常）。"""
    await dao.create("Alice", ":play 一")
    await dao.create("Alice", ":play 二")
    await dao.create("Bob", ":play 别人的")

    assert await dao.delete_all_by_username("Alice") == 2
    assert await dao.get_by_username("Alice") == []
    assert len(await dao.get_by_username("Bob")) == 1


# --------------------------------------------------------------------------
# shim CRUD 逐个方法仍然可用（外部调用方按旧签名调）
# --------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("event_type,dao,command_cls,prefix", SHIMS)
async def test_shim_crud_round_trip(db_init, event_type, dao, command_cls, prefix):
    created = await dao.create("Alice", ":play 一首")
    assert created.id is not None

    fetched = await dao.get_by_id(created.id)
    assert fetched is not None
    assert fetched.command == ":play 一首"
    # user 关系是 prefetch 出来的 —— 外部调用方读 `.user.username`
    assert fetched.user.username == "Alice"

    assert [c.command for c in await dao.get_by_username("Alice")] == [":play 一首"]

    assert await dao.delete_by_id(created.id) is True
    assert await dao.delete_by_id(created.id) is False
    assert await dao.get_by_username("Alice") == []


# --------------------------------------------------------------------------
# 非对称：收礼物 alias-group，其余 single-id
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_receive_shim_keeps_alias_group_resolution(db_init):
    """收礼物走 alias-group：挂在分身 id 上的旧行也查得到、也删得掉。

    走 DAO 写永远落在主账号上（`get_or_create` 会 resolve canonical），所以那一档
    看不出差别；真正的分叉是历史上直接挂在分身 id 上的行 —— alias-group 能看见，
    single-id 看不见（下面那条测试钉的就是这个反面）。
    """
    _canonical, alias = await make_identity()

    await ReceiveDao.create("Outlier", ":say 主账号配的")
    await ReceiveEvent.create(user=alias, command=":say 挂在分身上的")

    commands = [c.command for c in await ReceiveDao.get_by_username("Chainer")]
    assert commands == [":say 主账号配的", ":say 挂在分身上的"]

    assert await ReceiveDao.delete_all_by_username("Chainer") == 2
    assert await ReceiveDao.get_by_username("Outlier") == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "event_type,dao,model", [
        (ENTER, EnterDao, EnterEvent),
        (EXIT, ExitDao, ExitEvent),
        (RETURN, ReturnDao, ReturnEvent),
        (FOCUS, FocusEventDao, FocusEvent),
    ]
)
async def test_single_id_shims_resolve_to_canonical_only(db_init, event_type, dao, model):
    """其余四个走 single-id：只认主账号那一个 id，分身 id 上的行既查不到也删不掉。

    刻意与上面那条对着写 —— 两种口径不是「默认值 + 例外」，混用会让 `clear` 误删。
    """
    _canonical, alias = await make_identity()

    await dao.create("Outlier", ":play 主账号配的")
    await model.create(user=alias, command=":play 挂在分身上的")

    assert [c.command for c in await dao.get_by_username("Chainer")] == [":play 主账号配的"]
    assert await dao.delete_all_by_username("Chainer") == 1

    # 分身那行原封不动还在
    assert await model.filter(user_id=alias.id).count() == 1


@pytest.mark.asyncio
async def test_focus_shim_get_all_ordered_spans_every_user(db_init):
    """`get_all_ordered()` 是专注人数联动「触发者未知」时的回退路径，必须保留。"""
    await FocusEventDao.create("Bob", ":say Bob")
    await FocusEventDao.create("Alice", ":say Alice")
    await FocusEventDao.create("Bob", ":say Bob 两条")

    ordered = await FocusEventDao.get_all_ordered()

    assert [c.command for c in ordered] == [":say Bob", ":say Alice", ":say Bob 两条"]
    assert [c.id for c in ordered] == sorted(c.id for c in ordered)
    assert [c.user.username for c in ordered] == ["Bob", "Alice", "Bob"]
