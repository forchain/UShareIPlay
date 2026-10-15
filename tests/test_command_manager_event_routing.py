"""#436：`CommandManager` 事件分发改成直接路由之后的行为钉子。

反射分发（遍历已加载命令模块找同名钩子方法）收掉后，`notify_*` 直接调
`UserEventHooks.fire`，座位复核变成显式调用。这里钉三件容易静默回归的事：

1. **专注人数联动的三态选人不能被归一**。`changed_users=None`（触发者未知）回退为
   所有已配置用户，`[]`（本次没有用户变更）一条都不发，`[...]` 只发名单里这些。
   注意这条以前是经 `FocusCommand.focus_count_change` 覆盖的，而 #436 之后
   `notify_focus_count_change` 直接调 `fire`，不再经过命令对象 —— 三态必须在
   `CommandManager` 这一层重新钉一遍。

2. **座位观测要进事件上下文**。`{username}` / `{seat}` / `{action}` 宏的数据源是
   `ctx["seat_info"]`；转发时丢了，宏就展开成空串而不是报错。

3. **进入/返回的座位复核**属于显式副作用调用，不是用户事件钩子，删掉就静默没了。
   客房守卫那半边在 `test_guest_room_guard.py`，这里钉本房确实会复核。
"""

import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from ushareiplay.core.db_manager import DatabaseManager
from ushareiplay.core.message_queue import MessageQueue
from ushareiplay.managers.command_manager import CommandManager
from ushareiplay.managers.seat_manager import SeatManager
from ushareiplay.managers.user_event_hooks import UserEventHooks

from ushareiplay.commands.enter import EnterCommand

ReturnCommand = importlib.import_module("ushareiplay.commands.return").ReturnCommand

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
    return list((await MessageQueue.instance().get_all_messages()).values())


def make_controller():
    handler = SimpleNamespace(logger=None, log_error=lambda *a, **k: None)
    return SimpleNamespace(soul_handler=handler, music_handler=handler)


# --------------------------------------------------------------------------
# 专注人数联动：三态选人
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_focus_change_with_changed_users_none_fires_every_configured_user(db_init):
    """`changed_users=None` = 触发者未知 → 所有人已配的联动命令都发。"""
    for who, cmd in (("Alice", ":say Alice"), ("Bob", ":say Bob")):
        await UserEventHooks.instance().execute_crud(
            "focus", who, f':focus add "{cmd}"'
        )

    cm = CommandManager.instance()
    cm._logger = _logger_stub()
    await MessageQueue.instance().clear_queue()

    await cm.notify_focus_count_change(1, 2, changed_users=None)

    assert sorted(m.content for m in await _drain()) == [":say Alice", ":say Bob"]


@pytest.mark.asyncio
async def test_focus_change_with_empty_changed_users_fires_nobody(db_init):
    """`changed_users=[]` = 本次没有用户变更 → 一条都不发（与 None 语义相反）。"""
    await UserEventHooks.instance().execute_crud(
        "focus", "Alice", ':focus add ":say Alice"'
    )

    cm = CommandManager.instance()
    cm._logger = _logger_stub()
    await MessageQueue.instance().clear_queue()

    await cm.notify_focus_count_change(1, 2, changed_users=[])

    assert await _drain() == []


@pytest.mark.asyncio
async def test_focus_change_isolates_to_the_named_users(db_init):
    """给了名单就只发名单里这些人的。"""
    for who in ("Alice", "Bob", "Carol"):
        await UserEventHooks.instance().execute_crud(
            "focus", who, f':focus add ":say {who}"'
        )

    cm = CommandManager.instance()
    cm._logger = _logger_stub()
    await MessageQueue.instance().clear_queue()

    await cm.notify_focus_count_change(1, 2, changed_users=["Alice", "Carol"])

    assert sorted(m.content for m in await _drain()) == [":say Alice", ":say Carol"]


@pytest.mark.asyncio
async def test_focus_change_carries_seat_info_into_the_macro_context(db_init):
    """座位观测必须进 `ctx`，否则 `{seat}` / `{action}` 展开成空串。"""
    await UserEventHooks.instance().execute_crud(
        "focus", "Alice", ':focus add ":say {username} 坐到了 {seat} 号座位 ({action})"'
    )

    cm = CommandManager.instance()
    cm._logger = _logger_stub()
    await MessageQueue.instance().clear_queue()

    await cm.notify_focus_count_change(
        1,
        2,
        changed_users=["Alice"],
        seat_info={"Alice": {"seat_number": 3, "action": "坐下"}},
    )

    assert [m.content for m in await _drain()] == [":say Alice 坐到了 3 号座位 (坐下)"]


# --------------------------------------------------------------------------
# 进入 / 返回：座位复核是显式调用
# --------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "notify_name,command_cls,raw",
    [
        ("notify_user_enter", EnterCommand, ':enter add ":play 稻香"'),
        ("notify_user_return", ReturnCommand, ':return add ":play 稻香"'),
    ],
)
async def test_enter_and_return_fire_hooks_and_check_seats_once(
    db_init, notify_name, command_cls, raw
):
    """一次事件 = 钩子入队一次 + 座位复核一次，不多不少。"""
    await command_cls(make_controller()).do_process(
        MessageInfo(content=raw, nickname="Bob"), []
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
        await getattr(cm, notify_name)("Bob")

    assert [m.content for m in await _drain()] == [":play 稻香"]
    seat_check.assert_awaited_once_with("Bob")
