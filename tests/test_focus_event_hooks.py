"""`:focus` 迁进 `UserEventHooks` 之后的行为测试（#433）。

覆盖五件事：
- `{username}` / `{seat}` / `{action}` 在 `fire()` 入队前展开，包括「观测键是分身名、
  钩子挂在主账号名上」这条靠身份解析兜底的路；
- 观测缺失时宏落成空串而不是把字面量喊出去，也不炸；
- 触发者三态：`usernames=[...]` 只发这些人的、`[]` 一个都不发、`None` 回退全部；
- `:focus` 四个 CRUD 子动作，以及它作为薄适配器的形状；
- `{user_name}` 不被这一族宏吃掉 —— 它要留到队列 drain 期由 intake 层展开。
"""

import logging
from types import SimpleNamespace

import pytest
import pytest_asyncio

from ushareiplay.commands.focus import FocusCommand
from ushareiplay.core.db_manager import DatabaseManager
from ushareiplay.core.message_queue import MessageQueue
from ushareiplay.core.runtime_services import route_queue_text
from ushareiplay.dal.user_dao import UserDAO
from ushareiplay.managers.user_event_hooks import (
    ENTER,
    FOCUS,
    UserEventHooks,
    spec_for,
)
from ushareiplay.managers.user_event_hooks.dao import UserEventHookDAO
from ushareiplay.managers.user_event_hooks.macros import (
    SEAT_INFO_CTX_KEY,
    expand_seat_macros,
)
from ushareiplay.models import User
from ushareiplay.models.message_info import MessageInfo


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
    queue = MessageQueue.instance()
    await queue.clear_queue()
    yield UserEventHooks.instance()
    await queue.clear_queue()


def make_controller():
    """A controller stub good enough for `BaseCommand.__init__`."""
    handler = SimpleNamespace(logger=None, log_error=lambda *a, **k: None)
    return SimpleNamespace(soul_handler=handler, music_handler=handler)


async def add_focus_hook(hooks, username, command):
    """给某用户配一条专注人数联动命令（`:focus add "<command>"`）。

    这些用例要测的是 `fire()`，所以走配置命令这层只在 `add` 这里出现一次。
    """
    added = await hooks.execute_crud(FOCUS, username, f':focus add "{command}"')
    assert added.get("error") is None, added


async def drain_messages():
    """Take everything the engine enqueued, in insertion order."""
    queued = await MessageQueue.instance().get_all_messages()
    return list(queued.values())


# --------------------------------------------------------------------------
# 宏展开：入队之前完成
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seat_macros_expand_before_enqueue(db_init, hooks):
    await add_focus_hook(hooks, "Alice", ":say {username} 坐到了 {seat} 号座位 ({action})")

    queued_count = await hooks.fire(
        FOCUS,
        usernames=["Alice"],
        ctx={SEAT_INFO_CTX_KEY: {"Alice": {"seat_number": 5, "action": "sit_down"}}},
    )

    queued = await drain_messages()
    assert queued_count == 1
    assert queued[0].content == ":say Alice 坐到了 5 号座位 (sit_down)"
    assert queued[0].nickname == "Alice"


@pytest.mark.asyncio
async def test_seat_macros_resolve_observation_through_identity_fallback(db_init, hooks):
    """观测键是分身名、钩子挂在主账号名上时，宏的数据源靠身份解析找回来。"""
    outlier = await UserDAO.get_or_create_raw("Outlier")
    await User.create(username="Chainer", level=0, canonical_user_id=outlier.id)
    await add_focus_hook(hooks, "Chainer", ":say {username} 坐到了 {seat} 号 ({action})")

    await hooks.fire(
        FOCUS,
        usernames=["Chainer"],
        ctx={SEAT_INFO_CTX_KEY: {"Chainer": {"seat_number": 6, "action": "move_seat"}}},
    )

    queued = await drain_messages()
    # 归属名是主账号（DB canonical），座位与动作来自分身名的观测
    assert queued[0].content == ":say Outlier 坐到了 6 号 (move_seat)"
    assert queued[0].nickname == "Outlier"


@pytest.mark.asyncio
async def test_missing_seat_info_substitutes_empty_strings(db_init, hooks):
    """没观测到这个人时宏落成空串：既不喊出 `{seat}`，也不让整批入队炸掉。"""
    await add_focus_hook(hooks, "Alice", ":say {username}|{seat}|{action}")

    assert await hooks.fire(FOCUS, usernames=["Alice"]) == 1
    assert await hooks.fire(FOCUS, usernames=["Alice"], ctx={SEAT_INFO_CTX_KEY: {}}) == 1

    queued = await drain_messages()
    assert [msg.content for msg in queued] == [":say Alice||", ":say Alice||"]


@pytest.mark.asyncio
async def test_seat_number_is_coerced_to_string(db_init, hooks):
    await add_focus_hook(hooks, "Alice", ":seat {seat}")

    await hooks.fire(
        FOCUS,
        usernames=["Alice"],
        ctx={SEAT_INFO_CTX_KEY: {"Alice": {"seat_number": 3, "action": "sit_down"}}},
    )

    assert (await drain_messages())[0].content == ":seat 3"


@pytest.mark.asyncio
async def test_macros_are_declared_per_event_type_not_by_event_type_branch(db_init, hooks):
    """宏策略挂在注册表上：没声明宏的事件类型原样入队。"""
    assert spec_for(ENTER).macros is None
    assert spec_for(FOCUS).macros is expand_seat_macros

    await hooks.execute_crud(ENTER, "Alice", ':enter add ":seat {seat}"')
    await hooks.fire(ENTER, "Alice")

    assert (await drain_messages())[0].content == ":seat {seat}"


# --------------------------------------------------------------------------
# 触发者三态：None / [] / 名单，三者语义不可合并
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_usernames_isolates_to_the_affected_users(db_init, hooks):
    await add_focus_hook(hooks, "Alice", ":say Alice changed seat")
    await add_focus_hook(hooks, "Bob", ":say Bob changed seat")

    queued_count = await hooks.fire(FOCUS, usernames=["Alice"])

    queued = await drain_messages()
    assert queued_count == 1
    assert [(msg.nickname, msg.content) for msg in queued] == [
        ("Alice", ":say Alice changed seat")
    ]


@pytest.mark.asyncio
async def test_empty_usernames_fires_nobody(db_init, hooks):
    """`[]` 是「没有用户变更」——一条都不发，不是「触发者未知」。"""
    await add_focus_hook(hooks, "Alice", ":seat {seat}")
    await add_focus_hook(hooks, "Bob", ":seat {seat}")

    assert await hooks.fire(FOCUS, usernames=[]) == 0
    assert await drain_messages() == []


@pytest.mark.asyncio
async def test_missing_usernames_falls_back_to_every_configured_user(db_init, hooks):
    await add_focus_hook(hooks, "Alice", ":say A")
    await add_focus_hook(hooks, "Bob", ":say B")

    assert await hooks.fire(FOCUS) == 2
    assert [msg.nickname for msg in await drain_messages()] == ["Alice", "Bob"]


@pytest.mark.asyncio
async def test_usernames_deduplicates_aliases_of_one_canonical_user(db_init, hooks):
    """名单里同一主账号的多个分身只入队一次。"""
    canonical = await UserDAO.get_or_create_raw("David")
    for avatar in ("David_Avatar1", "David_Avatar2"):
        row = await UserDAO.get_or_create_raw(avatar)
        row.canonical_user_id = canonical.id
        await row.save(update_fields=["canonical_user_id"])

    await add_focus_hook(hooks, "David", ":say David changed seat")

    assert (
        await hooks.fire(
            FOCUS,
            usernames=["David_Avatar1", "David_Avatar2"],
            ctx={
                SEAT_INFO_CTX_KEY: {
                    "David_Avatar1": {"seat_number": 1, "action": "sit_down"}
                }
            },
        )
        == 1
    )
    assert (await drain_messages())[0].nickname == "David"


def test_list_passed_as_the_single_username_argument_is_rejected(db_init):
    """`fire(FOCUS, [])` 曾会掉进「查一个叫这个的用户」；名单必须走 `usernames=`。"""
    with pytest.raises(TypeError):
        UserEventHooks._resolve_targets(["Alice"], None)
    with pytest.raises(ValueError):
        UserEventHooks._resolve_targets("Alice", ["Bob"])


@pytest.mark.asyncio
async def test_misused_fire_argument_queues_nothing(db_init, hooks):
    await add_focus_hook(hooks, "Alice", ":seat {seat}")

    assert await hooks.fire(FOCUS, ["Alice"]) == 0
    assert await drain_messages() == []


# --------------------------------------------------------------------------
# 队列契约：`{user_name}` 是另一族宏，必须活到 drain 期
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_user_name_macro_survives_enqueue_and_expands_at_drain(db_init, hooks):
    await add_focus_hook(hooks, "Alice", ":say {user_name} 在 {seat} 号")

    await hooks.fire(
        FOCUS,
        usernames=["Alice"],
        ctx={SEAT_INFO_CTX_KEY: {"Alice": {"seat_number": 2, "action": "sit_down"}}},
    )

    queued = (await drain_messages())[0]
    # 入队时座位宏已替换，intake 层的 {user_name} 原样留着
    assert queued.content == ":say {user_name} 在 2 号"

    routing = route_queue_text(queued.content, queued.nickname)
    assert [cmd.content for cmd in routing.commands] == [":say Alice 在 2 号"]


# --------------------------------------------------------------------------
# 日志：座位观测不进运行时日志（监控路径不刷屏）
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fire_log_keeps_seat_observation_out(db_init, hooks, caplog):
    await add_focus_hook(hooks, "Alice", ":seat {seat}")

    with caplog.at_level(logging.INFO, logger="user_event_hooks"):
        await hooks.fire(
            FOCUS,
            usernames=["Alice"],
            ctx={
                "before": 1,
                "after": 2,
                SEAT_INFO_CTX_KEY: {"Alice": {"seat_number": 3, "action": "sit_down"}},
            },
        )

    assert "seat_info" not in caplog.text
    assert "'before': 1" in caplog.text and "'after': 2" in caplog.text


# --------------------------------------------------------------------------
# `:focus` 薄适配器
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_focus_command_is_a_thin_adapter(db_init, hooks):
    command = FocusCommand(make_controller())

    assert command.handler_attr == "soul_handler"
    assert command.error_message == "处理专注人数命令时出错"

    message = MessageInfo(content=':focus add ":play 起风了"', nickname="Alice")
    assert await command.do_process(message, []) == {
        "message": "已添加专注人数联动命令: :play 起风了"
    }


@pytest.mark.asyncio
async def test_focus_command_crud_subverbs(db_init, hooks):
    command = FocusCommand(make_controller())

    added = await command.do_process(
        MessageInfo(content=':focus add ":play 起风了"', nickname="Alice"), []
    )
    assert added == {"message": "已添加专注人数联动命令: :play 起风了"}

    listed = await command.do_process(MessageInfo(content=":focus list", nickname="Alice"), [])
    assert listed["message"].splitlines() == [
        "您的专注人数联动命令列表:",
        "  [1] :play 起风了",
    ]

    command_id = (await UserEventHookDAO.get_by_username(FOCUS, "Alice"))[0].id
    deleted = await command.do_process(
        MessageInfo(content=f":focus del {command_id}", nickname="Alice"), []
    )
    assert deleted == {"message": f"已删除命令 ID: {command_id}"}

    cleared = await command.do_process(MessageInfo(content=":focus clear", nickname="Alice"), [])
    assert cleared == {"message": "您没有任何专注人数联动命令需要清除"}


@pytest.mark.asyncio
async def test_focus_command_changed_users_keeps_its_three_states(db_init, hooks):
    command = FocusCommand(make_controller())
    await add_focus_hook(hooks, "Alice", ":say {username} 到了 {seat} 号 ({action})")
    await add_focus_hook(hooks, "Bob", ":say Bob 到了")
    seat_info = {"Alice": {"seat_number": 4, "action": "sit_down"}}

    # 名单：只发被点名的用户，座位宏在入队前就替换好
    await command.focus_count_change(0, 1, changed_users=["Alice"], seat_info=seat_info)
    queued = await drain_messages()
    assert [(msg.nickname, msg.content) for msg in queued] == [
        ("Alice", ":say Alice 到了 4 号 (sit_down)")
    ]

    # 空名单：没有用户变更，一条都不发
    await command.focus_count_change(1, 2, changed_users=[], seat_info=seat_info)
    assert await drain_messages() == []

    # 触发者未知：回退为所有已配置用户
    await command.focus_count_change(1, 2, changed_users=None)
    queued = await drain_messages()
    assert sorted(msg.nickname for msg in queued) == ["Alice", "Bob"]
