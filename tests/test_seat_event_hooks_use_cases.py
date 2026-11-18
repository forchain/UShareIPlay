"""Pure domain and use-case tests for Seat Event Hooks (#557).

Uses in-memory fakes only (no DB, no Appium, no singletons) to verify:
- `seat_info_for` & `expand_seat_macros` (`{username}`, `{seat}`, `{action}` + alias resolution)
- `UserEventHooks` gating by seat events (`changed_users` tri-state: list / [] / None)
- Exact CRUD rendering across all five event types (`enter`, `exit`, `return`, `receive`, `focus`)
- `SeatObservationService` -> `on_focus_change` -> `UserEventHooks.fire(FOCUS, ...)` wiring
- `FocusCommand` thin inbound adapter contract
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from tests.fakes.in_memory_user_event_hook_repository import InMemoryUserEventHookRepository
from tests.fakes.in_memory_user_repository import InMemoryUserRepository
from ushareiplay.adapters.inbound.chat.focus import FocusCommand
from ushareiplay.modules.shared.message_info import MessageInfo
from ushareiplay.modules.room.domain import RoomAdmins
from ushareiplay.modules.room.ports import HookCommandSink, PresenceQuery
from ushareiplay.modules.room.registry import (
    ENTER,
    EXIT,
    FOCUS,
    RECEIVE,
    RETURN,
    spec_for,
)
from ushareiplay.modules.room.use_cases import UserEventHooks
from ushareiplay.modules.seat.domain import DeskSnapshot, Reading
from ushareiplay.modules.seat.macros import (
    SEAT_INFO_CTX_KEY,
    expand_seat_macros,
    seat_info_for,
)
from ushareiplay.modules.seat.use_cases import SeatObservationService


class RecordingHookSink(HookCommandSink):
    def __init__(self):
        self.enqueued: list[tuple[str, str]] = []

    async def enqueue(self, command: str, username: str) -> None:
        self.enqueued.append((command, username))


class StaticPresence(PresenceQuery):
    def __init__(self, online: set[str] | None = None):
        self._online = set(online or set())

    def get_online_users(self) -> set[str]:
        return set(self._online)

    def is_user_online(self, username: str) -> bool:
        return username in self._online


def _make_hooks(
    *,
    users: InMemoryUserRepository | None = None,
    repository: InMemoryUserEventHookRepository | None = None,
    sink: RecordingHookSink | None = None,
    presence: StaticPresence | None = None,
):
    users = users or InMemoryUserRepository()
    repository = repository or InMemoryUserEventHookRepository(users=users)
    sink = sink or RecordingHookSink()
    presence = presence or StaticPresence()
    hooks = UserEventHooks(
        repository=repository,
        users=users,
        sink=sink,
        presence=presence,
    )
    return hooks, users, repository, sink


# --------------------------------------------------------------------------
# Pure macro expansion & seat_info_for
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seat_info_for_direct_and_identity_fallback():
    users = InMemoryUserRepository()
    canonical = await users.get_or_create_raw("Outlier")
    alias = await users.get_or_create_raw("Chainer")
    await users.set_canonical(alias.id, canonical.id)

    seat_info = {"Chainer": {"seat_number": 4, "action": "sit_down"}}
    assert await seat_info_for("Chainer", seat_info, users) == {
        "seat_number": 4,
        "action": "sit_down",
    }
    assert await seat_info_for("Outlier", seat_info, users) == {
        "seat_number": 4,
        "action": "sit_down",
    }
    assert await seat_info_for("Stranger", seat_info, users) == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["sit_down", "leave_seat", "move_seat"])
async def test_expand_seat_macros_renders_all_seat_actions(action):
    users = InMemoryUserRepository()
    ctx = {SEAT_INFO_CTX_KEY: {"Alice": {"seat_number": 7, "action": action}}}
    rendered = await expand_seat_macros(
        ":say {username} -> {seat} ({action})",
        "Alice",
        ctx,
        users=users,
    )
    assert rendered == f":say Alice -> 7 ({action})"


@pytest.mark.asyncio
async def test_expand_seat_macros_missing_context_falls_back_to_empty_strings():
    rendered = await expand_seat_macros(":say {username}|{seat}|{action}", "Alice", {})
    assert rendered == ":say Alice||"


# --------------------------------------------------------------------------
# Use-case gating & exact rendering of all 5 event types' commands
# --------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "event_type,prefix,noun",
    [
        (ENTER, ":enter", "进入命令"),
        (EXIT, ":exit", "离开命令"),
        (RETURN, ":return", "返回命令"),
        (RECEIVE, ":receive", "收礼物命令"),
        (FOCUS, ":focus", "专注人数联动命令"),
    ],
)
async def test_crud_rendering_exact_across_all_five_event_types(event_type, prefix, noun):
    hooks, _, _, _ = _make_hooks()
    spec = spec_for(event_type)

    assert await hooks.execute_crud(event_type, "Alice", prefix) == {
        "error": f"缺少参数。使用: {prefix} [add|del|list|clear]"
    }
    assert await hooks.execute_crud(event_type, "Alice", f"{prefix} add") == {
        "error": f'缺少命令内容。使用: {prefix} add "命令内容"'
    }
    assert await hooks.execute_crud(event_type, "Alice", f'{prefix} add "bad"') == {
        "error": f"命令必须以命令前缀(:/：或//／)开头，例如 {spec.prefix_example}"
    }
    assert await hooks.execute_crud(event_type, "Alice", f'{prefix} add ":play 晴天"') == {
        "message": f"已添加{noun}: :play 晴天"
    }
    assert await hooks.execute_crud(event_type, "Alice", f"{prefix} list") == {
        "message": f"您的{noun}列表:\n  [1] :play 晴天"
    }
    assert await hooks.execute_crud(event_type, "Alice", f"{prefix} del 1") == {
        "message": "已删除命令 ID: 1"
    }
    assert await hooks.execute_crud(event_type, "Alice", f"{prefix} del 1") == {
        "error": "未找到命令 ID: 1"
    }
    assert await hooks.execute_crud(event_type, "Alice", f"{prefix} clear") == {
        "message": f"您没有任何{noun}需要清除"
    }
    await hooks.execute_crud(event_type, "Alice", f'{prefix} add ":play 七里香"')
    assert await hooks.execute_crud(event_type, "Alice", f"{prefix} clear") == {
        "message": f"已清除 1 个{noun}"
    }


@pytest.mark.asyncio
async def test_focus_gating_isolates_changed_users_and_expands_macros():
    hooks, _, _, sink = _make_hooks()
    await hooks.execute_crud(FOCUS, "Alice", ':focus add ":say {username} {seat} {action}"')
    await hooks.execute_crud(FOCUS, "Bob", ':focus add ":say Bob"')

    count = await hooks.fire(
        FOCUS,
        usernames=["Alice"],
        ctx={SEAT_INFO_CTX_KEY: {"Alice": {"seat_number": 2, "action": "sit_down"}}},
    )
    assert count == 1
    assert sink.enqueued == [(":say Alice 2 sit_down", "Alice")]

    sink.enqueued.clear()
    assert await hooks.fire(FOCUS, usernames=[]) == 0
    assert sink.enqueued == []

    assert await hooks.fire(FOCUS, usernames=None) == 2
    assert sink.enqueued == [(":say Alice  ", "Alice"), (":say Bob", "Bob")]


# --------------------------------------------------------------------------
# SeatObservationService -> on_focus_change -> UserEventHooks.fire(FOCUS)
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seat_observation_triggers_focus_hook_with_seat_info():
    hooks, _, _, sink = _make_hooks()
    await hooks.execute_crud(FOCUS, "Alice", ':focus add ":say {username}@{seat}:{action}"')

    panel = SimpleNamespace(
        can_probe_ui=True,
        holds_session=True,
        is_handler_ready=True,
        read_focus_count=lambda: 1,
        read_desk_snapshot=lambda w: w,
        read_occupant=AsyncMock(return_value="Alice"),
    )
    room_state = SimpleNamespace(is_host_room=True, is_guest_room=False, focus_count=1)
    room_admins = RoomAdmins()

    async def on_focus_change(before, after, *, changed_users=None, seat_info=None):
        await hooks.fire(
            FOCUS,
            usernames=changed_users,
            ctx={"before": before, "after": after, SEAT_INFO_CTX_KEY: seat_info or {}},
        )

    obs = SeatObservationService(
        panel=panel,
        room_state=room_state,
        room_admins=room_admins,
        on_focus_change=on_focus_change,
    )

    desks = [
        DeskSnapshot(
            desk_id="desk-0",
            bounds={"x": 0, "y": 100, "width": 500, "height": 200},
            displayed=True,
            left=Reading(
                occupied=True,
                is_empty=False,
                label="1",
                has_state=True,
                has_default=False,
                has_rank=False,
                avatar_images=2,
            ),
            right=Reading(
                occupied=False,
                is_empty=True,
                label="",
                has_state=False,
                has_default=True,
                has_rank=False,
                avatar_images=1,
            ),
            left_has_seat=True,
            right_has_seat=True,
            interactable=True,
        )
    ]
    await obs.observe_visible_desks(desks, current_focus_count=1)

    assert sink.enqueued == [(":say Alice@1:sit_down", "Alice")]


@pytest.mark.asyncio
async def test_focus_command_adapter_delegates_crud_and_fire():
    hooks, _, _, sink = _make_hooks()
    handler = SimpleNamespace(logger=None, log_error=lambda *a, **k: None)
    controller = SimpleNamespace(
        soul_handler=handler, music_handler=handler, user_event_hooks=hooks
    )
    cmd = FocusCommand(controller)

    res = await cmd.do_process(MessageInfo(content=':focus add ":say hi {seat}"', nickname="Alice"), [])
    assert res == {"message": "已添加专注人数联动命令: :say hi {seat}"}

    await cmd.focus_count_change(
        0,
        1,
        changed_users=["Alice"],
        seat_info={"Alice": {"seat_number": 9, "action": "sit_down"}},
    )
    assert sink.enqueued == [(":say hi 9", "Alice")]
