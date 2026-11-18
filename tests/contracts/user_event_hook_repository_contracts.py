"""`UserEventHookRepository` 的共享契约：内存替身与 Tortoise/SQLite 各跑一遍。"""

from ushareiplay.modules.room.domain import HookCommand
from ushareiplay.modules.room.registry import (
    ALIAS_GROUP,
    ENTER,
    EXIT,
    FOCUS,
    RECEIVE,
    RETURN,
    SINGLE_ID,
    spec_for,
)

ALL_EVENT_TYPES = [ENTER, EXIT, RETURN, RECEIVE, FOCUS]


async def assert_crud_across_event_types(repository, users):
    for event_type in ALL_EVENT_TYPES:
        created = await repository.create(event_type, "Alice", ":play song")
        assert isinstance(created, HookCommand)
        assert created.id is not None
        assert created.command == ":play song"
        assert created.owner == "Alice"

        items = await repository.get_by_username(event_type, "Alice")
        assert [item.command for item in items] == [":play song"]

        fetched = await repository.get_by_id(event_type, created.id)
        assert fetched is not None and fetched.id == created.id

        assert await repository.delete_by_id(event_type, created.id) is True
        assert await repository.delete_by_id(event_type, created.id) is False
        assert await repository.get_by_username(event_type, "Alice") == []


async def assert_delete_all_by_username(repository, users):
    for event_type in ALL_EVENT_TYPES:
        await repository.create(event_type, "Bob", ":say one")
        await repository.create(event_type, "Bob", ":say two")
        await repository.create(event_type, "Carol", ":say other")

        assert await repository.delete_all_by_username(event_type, "Bob") == 2
        assert await repository.get_by_username(event_type, "Bob") == []
        assert len(await repository.get_by_username(event_type, "Carol")) == 1


async def assert_get_all_ordered_returns_every_row(repository, users):
    for event_type in ALL_EVENT_TYPES:
        await repository.create(event_type, "Alice", ":say one")
        await repository.create(event_type, "Bob", ":say two")

        every = await repository.get_all_ordered(event_type)
        assert [row.command for row in every] == [":say one", ":say two"]


async def assert_event_types_do_not_share_rows(repository, users):
    await repository.create(ENTER, "Alice", ":play enter")
    await repository.create(RECEIVE, "Alice", ":say receive")

    assert [row.command for row in await repository.get_by_username(ENTER, "Alice")] == [
        ":play enter"
    ]
    assert [
        row.command for row in await repository.get_by_username(RECEIVE, "Alice")
    ] == [":say receive"]


async def assert_receive_resolves_alias_group(repository, users):
    """收礼物命令按 alias-group 解析：别名能找到主账号下发的命令。"""
    assert spec_for(RECEIVE).resolution is ALIAS_GROUP

    canonical = await users.get_or_create_raw("Outlier")
    alias = await users.get_or_create_raw("Chainer")
    await users.set_canonical(alias.id, canonical.id)

    await repository.create(RECEIVE, "Outlier", ":say Thanks from Outlier")

    items = await repository.get_by_username(RECEIVE, "Chainer")
    assert [item.command for item in items] == [":say Thanks from Outlier"]

    assert await repository.delete_all_by_username(RECEIVE, "Chainer") == 1
    assert await repository.get_by_username(RECEIVE, "Outlier") == []


async def assert_alias_group_covers_rows_bound_to_an_alias_id(repository, users):
    """alias-group 覆盖「挂在分身自己 id 上」的历史命令。"""
    assert spec_for(RECEIVE).resolution is ALIAS_GROUP

    alias = await users.get_or_create_raw("Chainer")
    await repository.create(RECEIVE, "Chainer", ":say 下发于分身名下")

    canonical = await users.get_or_create_raw("Outlier")
    await users.set_canonical(alias.id, canonical.id)

    rows = await repository.get_by_username(RECEIVE, "Outlier")
    assert [row.command for row in rows] == [":say 下发于分身名下"]

    assert await repository.delete_all_by_username(RECEIVE, "Outlier") == 1
    assert await repository.get_by_username(RECEIVE, "Outlier") == []


async def assert_single_id_resolution_stays_on_the_canonical_id(repository, users):
    """其余事件类型是 single-id 口径：只认 canonical 主账号那一个 id。"""
    for event_type in (ENTER, EXIT, RETURN, FOCUS):
        assert spec_for(event_type).resolution is SINGLE_ID

        alias_name = f"Chainer_{event_type}"
        canonical_name = f"Outlier_{event_type}"
        alias = await users.get_or_create_raw(alias_name)
        await repository.create(event_type, alias_name, ":play 下发于分身名下")

        canonical = await users.get_or_create_raw(canonical_name)
        await users.set_canonical(alias.id, canonical.id)

        assert await repository.get_by_username(event_type, canonical_name) == []
        assert await repository.get_by_username(event_type, alias_name) == []

        assert await repository.delete_all_by_username(event_type, canonical_name) == 0
        assert await repository.delete_all_by_username(event_type, alias_name) == 0

        assert len(await repository.get_all_ordered(event_type)) == 1
