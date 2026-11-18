"""User Memory / chat log repositories 的共享契约场景。"""

from datetime import datetime, timedelta


async def assert_memory_is_absent_until_written(memory_repository, user_id):
    assert await memory_repository.get(user_id) is None


async def assert_memory_update_creates_and_overwrites(memory_repository, other_user_id, user_id):
    moment = datetime(2026, 1, 1, 12, 0, 0)

    created = await memory_repository.update(
        user_id,
        directives=["称谓: 浩哥"],
        profile="喜欢华语流行",
        consolidated_at=moment,
    )

    assert created.last_consolidated_at == moment
    assert await memory_repository.get(user_id) == created
    assert await memory_repository.get(other_user_id) is None

    later = moment + timedelta(hours=1)
    updated = await memory_repository.update(
        user_id,
        directives=["称谓: 浩哥", "硬性偏好: 喜好摇滚"],
        profile="喜欢华语流行与摇滚",
        consolidated_at=later,
    )

    assert updated.last_consolidated_at == later
    assert await memory_repository.get(user_id) == updated
    assert (updated.directives, updated.profile) == (
        ["称谓: 浩哥", "硬性偏好: 喜好摇滚"],
        "喜欢华语流行与摇滚",
    )


async def assert_chat_logs_record_in_order_and_count_since(chat_log_repository, user_id):
    first = await chat_log_repository.create(user_id, "  第一条  ")
    second = await chat_log_repository.create(user_id, "第二条")

    assert first.content == "第一条"
    assert first.user_id == user_id
    assert first.created_at is not None
    assert first.created_at < second.created_at

    assert await chat_log_repository.count_unconsolidated(user_id) == 2

    since_first = await chat_log_repository.count_unconsolidated(
        user_id, since=first.created_at
    )
    assert since_first == 1
    logs = await chat_log_repository.unconsolidated_logs(
        user_id, since=first.created_at
    )
    assert [log.content for log in logs] == ["第二条"]


async def assert_chat_logs_are_ordered_and_limited(chat_log_repository, user_id):
    for index in range(3):
        await chat_log_repository.create(user_id, f"消息 {index}")

    logs = await chat_log_repository.unconsolidated_logs(user_id, limit=2)

    assert [log.content for log in logs] == ["消息 0", "消息 1"]


async def assert_global_sweep_respects_min_count_and_cursor(
    chat_log_repository, memory_repository, user_one_id, user_two_id
):
    for index in range(3):
        await chat_log_repository.create(user_one_id, f"user1 {index}")
    await chat_log_repository.create(user_two_id, "user2 0")

    assert await chat_log_repository.active_user_ids_with_unconsolidated_logs(2) == [
        (user_one_id, 3)
    ]
    assert sorted(
        await chat_log_repository.active_user_ids_with_unconsolidated_logs(1)
    ) == [(user_one_id, 3), (user_two_id, 1)]

    logs = await chat_log_repository.unconsolidated_logs(user_one_id)
    await memory_repository.update(
        user_one_id,
        directives=[],
        profile="",
        consolidated_at=logs[1].created_at,
    )

    assert await chat_log_repository.active_user_ids_with_unconsolidated_logs(2) == []
    assert sorted(
        await chat_log_repository.active_user_ids_with_unconsolidated_logs(1)
    ) == [(user_one_id, 1), (user_two_id, 1)]
